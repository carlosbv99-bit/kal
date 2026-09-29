"""
Tests de versionado de herramientas dinámicas:
  - kernel/registry/versioning.py::ToolVersionStore (persistencia en disco)
  - kernel/registry/registry.py::ToolRegistry (activación versionada,
    rollback_tool, verify_tool_integrity), integrando firma real vía
    ToolSigner sobre un key_dir aislado (tmp_path) — no el key_dir real
    del proyecto.
"""
from __future__ import annotations

import pytest

from kernel.lifecycle.docker_runner import SandboxResult
from kernel.registry.registry import ToolRegistry
from kernel.registry.signing import ToolSigner
from kernel.registry.versioning import ToolVersionStore
from sdk.skill import ToolManifest


class FakeSandboxExecutor:
    def __init__(self, result: SandboxResult | None = None):
        self.result = result or SandboxResult(status="success", stdout="ok", stderr="", exit_code=0)
        self.calls: list[dict] = []

    def execute(self, source_code, context=None, network_mode=None, image=None, granted_permissions=None):
        self.calls.append({"source_code": source_code, "granted_permissions": granted_permissions})
        return self.result


def _manifest(**overrides) -> ToolManifest:
    defaults = {"name": "herramienta_de_prueba", "description": "una herramienta de prueba", "created_by": "agent"}
    defaults.update(overrides)
    return ToolManifest(**defaults)


# --- ToolVersionStore, sin registry ---


def test_first_version_is_1_and_increments(tmp_path):
    store = ToolVersionStore(base_dir=tmp_path)
    store.save_version("t", 1, "print(1)", {"name": "t"}, "sig1")
    assert store.next_version("t") == 2

    store.save_version("t", 2, "print(2)", {"name": "t"}, "sig2")
    assert store.list_versions("t") == [1, 2]


def test_read_version_roundtrips_source_and_signature(tmp_path):
    store = ToolVersionStore(base_dir=tmp_path)
    store.save_version("t", 1, "print('hola')", {"name": "t"}, "unafirma")

    source, sidecar = store.read_version("t", 1)

    assert source == "print('hola')"
    assert sidecar["signature"] == "unafirma"
    assert sidecar["manifest"] == {"name": "t"}


def test_read_missing_version_raises(tmp_path):
    store = ToolVersionStore(base_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        store.read_version("no_existe", 1)


def test_list_versions_empty_for_unknown_tool(tmp_path):
    store = ToolVersionStore(base_dir=tmp_path)
    assert store.list_versions("no_existe") == []


# --- K-6 (auditoría externa Likay-OS, 2026-09-26): path traversal en el
# name de una herramienta dinámica ---


def test_save_version_rejects_path_traversal_in_name(tmp_path):
    """
    `name` (elegido por el LLM vía propose_dynamic_tool, ver
    test_registry_rejects_path_traversal_in_dynamic_tool_name de abajo
    para la primera capa) se usaba sin sanitizar para armar
    self.base_dir / name, seguido de mkdir(parents=True,
    exist_ok=True) — mismo patrón que K-1. Esta es la segunda capa,
    directo sobre ToolVersionStore, para cualquier llamador que no
    pase por propose_dynamic_tool().
    """
    store = ToolVersionStore(base_dir=tmp_path / "versions")

    with pytest.raises(ValueError, match="inválido"):
        store.save_version("../../../../tmp/pwned", 1, "print(1)", {}, "sig")

    assert not (tmp_path / "tmp" / "pwned").exists()


def test_list_versions_rejects_path_traversal_in_name(tmp_path):
    store = ToolVersionStore(base_dir=tmp_path / "versions")
    with pytest.raises(ValueError, match="inválido"):
        store.list_versions("../../../../etc")


# --- Integración con ToolRegistry (firma real, versionado real) ---


@pytest.fixture
def signer(tmp_path):
    return ToolSigner(key_dir=tmp_path / "keys")


@pytest.fixture
def version_store(tmp_path):
    return ToolVersionStore(base_dir=tmp_path / "versions")


@pytest.fixture
def registry(signer, version_store):
    return ToolRegistry(sandbox=FakeSandboxExecutor(), signer=signer, version_store=version_store)


def test_activating_tool_persists_and_signs_version_1(registry, version_store, signer):
    registry.propose_dynamic_tool(_manifest(), "print('v1')")

    assert version_store.list_versions("herramienta_de_prueba") == [1]
    source, sidecar = version_store.read_version("herramienta_de_prueba", 1)
    assert source == "print('v1')"
    assert signer.verify("herramienta_de_prueba", 1, source, sidecar["signature"]) is True

    tool = registry.get("herramienta_de_prueba")
    assert tool.version == 1


def test_reproposing_tool_creates_version_2(registry, version_store):
    registry.propose_dynamic_tool(_manifest(), "print('v1')")
    registry.propose_dynamic_tool(_manifest(), "print('v2')")

    assert version_store.list_versions("herramienta_de_prueba") == [1, 2]
    tool = registry.get("herramienta_de_prueba")
    assert tool.version == 2
    assert tool.source_code == "print('v2')"


def test_rollback_tool_reactivates_previous_version(registry):
    registry.propose_dynamic_tool(_manifest(), "print('v1')")
    registry.propose_dynamic_tool(_manifest(), "print('v2')")

    registry.rollback_tool("herramienta_de_prueba", to_version=1, approved_by="kalin")

    tool = registry.get("herramienta_de_prueba")
    assert tool.version == 1
    assert tool.source_code == "print('v1')"


def test_rollback_unknown_version_raises(registry):
    registry.propose_dynamic_tool(_manifest(), "print('v1')")
    with pytest.raises(FileNotFoundError):
        registry.rollback_tool("herramienta_de_prueba", to_version=99, approved_by="kalin")


def test_rollback_rejects_a_version_file_tampered_on_disk(registry, version_store):
    registry.propose_dynamic_tool(_manifest(), "print('v1')")
    registry.propose_dynamic_tool(_manifest(), "print('v2')")

    # Simula edición fuera de banda del archivo de la versión 1, después
    # de que ya fue firmada y persistida por el pipeline.
    tampered_path = version_store.base_dir / "herramienta_de_prueba" / "herramienta_de_prueba_v1.py"
    tampered_path.write_text("print('codigo malicioso inyectado')", encoding="utf-8")

    with pytest.raises(ValueError, match="firma"):
        registry.rollback_tool("herramienta_de_prueba", to_version=1, approved_by="kalin")

    # La herramienta activa (v2, no tocada) sigue intacta.
    tool = registry.get("herramienta_de_prueba")
    assert tool.version == 2


def test_verify_tool_integrity_detects_tampering_of_active_version(registry, version_store):
    registry.propose_dynamic_tool(_manifest(), "print('v1')")
    assert registry.verify_tool_integrity("herramienta_de_prueba") is True

    active_path = version_store.base_dir / "herramienta_de_prueba" / "herramienta_de_prueba_v1.py"
    active_path.write_text("print('alguien lo edito a mano')", encoding="utf-8")

    assert registry.verify_tool_integrity("herramienta_de_prueba") is False


def test_registry_rejects_path_traversal_in_dynamic_tool_name(registry, version_store):
    """
    K-6 (auditoría externa Likay-OS, 2026-09-26): primera capa de
    defensa — rechazado ACÁ, antes de validar código o correr el
    sandbox de prueba, nunca llega a tocar disco vía
    ToolVersionStore (ver test_save_version_rejects_path_traversal_in_name
    para la segunda capa).
    """
    pending = registry.propose_dynamic_tool(_manifest(name="../../../../tmp/pwned"), "print(1)")

    assert pending.status == "rejected"
    assert registry.get("../../../../tmp/pwned") is None
    # Nunca llegó a tocar disco: ni siquiera se creó version_store.base_dir.
    assert not version_store.base_dir.exists()


def test_verify_tool_integrity_is_true_for_static_tools(registry):
    from sdk.artifacts import Artifact
    from sdk.skill import Tool

    class DummyStaticTool(Tool):
        manifest = _manifest(name="estatica", created_by="system")

        def execute(self, **kwargs):
            return Artifact(modality="text", uri="", metadata={})

    registry.register_static_tool(DummyStaticTool())
    assert registry.verify_tool_integrity("estatica") is True


# --- deny_pending_tool / deactivate_tool / auditoría de verify_tool_integrity
# (hallazgo real en kal-in, 2026-09-29, portado acá vía
# scripts/check_kernel_drift.py) ---------------------------------------------


def test_verify_tool_integrity_audits_tampering_it_detects(registry, version_store, monkeypatch):
    """
    Antes, una manipulación detectada volvía True/False en silencio — la única
    detección de manipulación del sistema que no dejaba rastro, contra un fondo
    donde todas las demás (rollback_tool, install_from_market.py) sí auditan.
    """
    import kernel.registry.registry as modulo_registry

    eventos = []
    monkeypatch.setattr(modulo_registry.audit_log, "record", lambda evento: eventos.append(evento))

    registry.propose_dynamic_tool(_manifest(), "print('v1')")
    active_path = version_store.base_dir / "herramienta_de_prueba" / "herramienta_de_prueba_v1.py"
    active_path.write_text("print('alguien lo edito a mano')", encoding="utf-8")

    assert registry.verify_tool_integrity("herramienta_de_prueba") is False

    evento = next(e for e in eventos if e.event_type == "tool_tamper_detected")
    assert evento.context["tool_name"] == "herramienta_de_prueba"
    assert evento.context["detected_by"] == "verify_tool_integrity"
    assert evento.outcome == "failure"


def test_verify_tool_integrity_does_not_audit_the_happy_path(registry, monkeypatch):
    """Camino feliz sin ruido: nada que reportar cuando la firma verifica."""
    import kernel.registry.registry as modulo_registry

    registry.propose_dynamic_tool(_manifest(), "print('v1')")

    eventos = []
    monkeypatch.setattr(modulo_registry.audit_log, "record", lambda evento: eventos.append(evento))

    assert registry.verify_tool_integrity("herramienta_de_prueba") is True
    assert eventos == []


def test_deny_pending_tool_removes_it_and_audits(registry, monkeypatch):
    """
    El espejo de approve_pending_tool(): antes la interfaz era asimétrica (solo
    "sí"), y un pendiente rechazado se quedaba en _pending para siempre, sin
    que la decisión quedara registrada.
    """
    import kernel.registry.registry as modulo_registry
    from kernel.registry.registry import PendingTool

    eventos = []
    monkeypatch.setattr(modulo_registry.audit_log, "record", lambda evento: eventos.append(evento))
    manifest = _manifest(name="pendiente_de_prueba")
    registry._pending["pendiente_de_prueba"] = PendingTool(
        manifest=manifest, source_code="x = 1", status="pending_approval"
    )

    registry.deny_pending_tool("pendiente_de_prueba", denied_by="kalin")

    assert "pendiente_de_prueba" not in registry._pending
    assert not any(p["name"] == "pendiente_de_prueba" for p in registry.list_pending())
    evento = next(e for e in eventos if e.event_type == "tool_denied")
    assert evento.context["tool_name"] == "pendiente_de_prueba"
    assert "kalin" in evento.summary


def test_deny_pending_tool_raises_for_unknown_name(registry):
    with pytest.raises(ValueError, match="No hay herramienta pendiente"):
        registry.deny_pending_tool("no-existe")


def test_deny_pending_tool_rejects_something_not_actually_pending(registry):
    """Mismo guarda que approve_pending_tool(): no se "rechaza" algo que ya no espera decisión."""
    from kernel.registry.registry import PendingTool

    manifest = _manifest(name="ya_activa")
    registry._pending["ya_activa"] = PendingTool(
        manifest=manifest, source_code="x = 1", status="active"
    )

    with pytest.raises(ValueError, match="no está pendiente"):
        registry.deny_pending_tool("ya_activa")


def test_deactivate_tool_removes_it_from_active_and_audits(registry, monkeypatch):
    """
    Antes no había forma de APAGAR una herramienta dinámica, solo de
    reemplazarla vía rollback_tool() por otra versión. get()/active_tools()
    resuelven contra _active_tools, así que borrar la entrada es lo que la
    apaga de verdad: deja de ofrecerse y de poder invocarse.
    """
    import kernel.registry.registry as modulo_registry

    eventos = []
    monkeypatch.setattr(modulo_registry.audit_log, "record", lambda evento: eventos.append(evento))
    registry.propose_dynamic_tool(_manifest(), "print('v1')")
    assert registry.get("herramienta_de_prueba") is not None

    registry.deactivate_tool("herramienta_de_prueba", deactivated_by="kalin", reason="comprometida")

    assert registry.get("herramienta_de_prueba") is None
    evento = next(e for e in eventos if e.event_type == "tool_deactivated")
    assert evento.context["tool_name"] == "herramienta_de_prueba"
    assert evento.context["reason"] == "comprometida"
    assert "kalin" in evento.summary


def test_deactivate_tool_raises_for_unknown_name(registry):
    with pytest.raises(ValueError, match="No hay herramienta activa"):
        registry.deactivate_tool("no-existe")


def test_deactivate_tool_rejects_static_tools(registry):
    """Las estáticas son del sistema: no se retiran por acá."""
    from sdk.artifacts import Artifact
    from sdk.skill import Tool

    class DummyStaticTool(Tool):
        manifest = _manifest(name="estatica", created_by="system")

        def execute(self, **kwargs):
            return Artifact(modality="text", uri="", metadata={})

    registry.register_static_tool(DummyStaticTool())

    with pytest.raises(ValueError, match="herramienta estática"):
        registry.deactivate_tool("estatica")


def test_deactivated_tool_cannot_be_rolled_back(registry):
    """
    Consecuencia deliberada: rollback_tool() exige que la herramienta esté
    activa, así que una desactivada no se reactiva con un rollback — hay que
    volver a proponerla y aprobarla.
    """
    registry.propose_dynamic_tool(_manifest(), "print('v1')")
    registry.deactivate_tool("herramienta_de_prueba")

    with pytest.raises(ValueError, match="No hay herramienta activa"):
        registry.rollback_tool("herramienta_de_prueba", to_version=1, approved_by="kalin")
