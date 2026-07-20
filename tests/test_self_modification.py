"""
Tests de agent_core/self_modification.py.

Usan un proyecto SINTÉTICO minúsculo (fixture `fake_project`), no el
propio kal/ — de lo contrario cada test tendría que copiar el proyecto
completo y correr su test suite real (con Docker, modelos de ML, etc.)
DOS veces (baseline + candidato), lo cual sería lentísimo y frágil.
Aquí se prueba la LÓGICA del pipeline (bloqueo de núcleo, detección de
regresión, aplicación, rollback), no el contenido real de kal/.

Nota: los tests que llegan a _run_tests() invocan un pytest real como
subproceso — requieren que pytest esté instalado en el intérprete
activo. Los que no llegan ahí (bloqueo de núcleo, código inseguro,
path traversal) son más rápidos y no dependen de eso.
"""
from __future__ import annotations

import pytest

from agent_core.self_modification import SelfModificationManager
from utils.config import settings


@pytest.fixture
def fake_project(tmp_path):
    """
    Proyecto sintético mínimo:
        mymodule.py       — una función simple
        tests/test_mymodule.py — un test que la ejerce
    """
    (tmp_path / "mymodule.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "test_mymodule.py").write_text(
        "from mymodule import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def manager(fake_project):
    return SelfModificationManager(project_root=fake_project)


@pytest.fixture(autouse=True)
def _enabled_by_default(monkeypatch):
    """
    Todo el resto de este archivo prueba la lógica del pipeline
    asumiendo que la funcionalidad está habilitada — el gate de
    enabled=false (ver más abajo) es un caso aparte, que lo desactiva
    explícitamente donde corresponde.
    """
    monkeypatch.setattr(settings.self_modification, "enabled", True)


# --- self_modification.enabled: false (bug real corregido 2026-07-11:
# este flag existía en el esquema pero nada lo leía, quedaba siempre
# activo sin importar su valor) ---


def test_propose_is_rejected_when_disabled_in_config(manager, monkeypatch):
    monkeypatch.setattr(settings.self_modification, "enabled", False)

    proposal = manager.propose(
        target_path="mymodule.py", proposed_source="def add(a, b):\n    return a + b\n", justification="x",
    )

    assert proposal.status == "disabled"
    assert proposal.baseline_tests is None  # nunca llegó a correr tests


def test_disabled_check_short_circuits_before_core_path_check(manager, monkeypatch):
    """
    El gate de enabled=false es el PRIMER chequeo de propose(), antes
    incluso del bloqueo de rutas núcleo — si no fuera así, este target
    (núcleo) devolvería 'blocked_core', no 'disabled'.
    """
    monkeypatch.setattr(settings.self_modification, "enabled", False)

    proposal = manager.propose(
        target_path="agent_core/orchestrator.py", proposed_source="# cualquier cosa", justification="x",
    )

    assert proposal.status == "disabled"


# --- Casos rápidos: no llegan a _run_tests() ---

def test_core_path_is_blocked_immediately(manager):
    proposal = manager.propose(
        target_path="agent_core/orchestrator.py",
        proposed_source="# cualquier cosa",
        justification="intento de modificar el núcleo",
    )
    assert proposal.status == "blocked_core"
    assert proposal.baseline_tests is None  # nunca llegó a correr tests


def test_error_handling_path_is_also_blocked(manager):
    proposal = manager.propose(
        target_path="error_handling/strategies.py",
        proposed_source="# cualquier cosa",
        justification="intento",
    )
    assert proposal.status == "blocked_core"


def test_sandbox_path_is_also_blocked(manager):
    proposal = manager.propose(
        target_path="kernel/lifecycle/docker_runner.py",
        proposed_source="# cualquier cosa",
        justification="intento",
    )
    assert proposal.status == "blocked_core"


def test_unsafe_code_is_rejected_without_running_tests(manager):
    proposal = manager.propose(
        target_path="mymodule.py",
        proposed_source="import os\nos.system('ls')\ndef add(a, b):\n    return a + b\n",
        justification="código inseguro",
    )
    assert proposal.status == "rejected_unsafe"
    assert proposal.baseline_tests is None


def test_path_traversal_relative_is_rejected(manager):
    proposal = manager.propose(
        target_path="../../etc/cron.d/evil",
        proposed_source="algo",
        justification="intento de escape",
    )
    assert proposal.status == "rejected_unsafe"
    assert "traversal" in proposal.detail.lower() or "sale del directorio" in proposal.detail.lower()


def test_path_traversal_absolute_is_rejected(manager):
    proposal = manager.propose(
        target_path="/etc/passwd",
        proposed_source="algo",
        justification="intento de escape absoluto",
    )
    assert proposal.status == "rejected_unsafe"


def test_nonexistent_target_is_rejected(manager):
    proposal = manager.propose(
        target_path="no_existe.py",
        proposed_source="print('hola')",
        justification="archivo que no existe",
    )
    assert proposal.status == "rejected_unsafe"
    assert "no existe" in proposal.detail.lower()


def test_get_unknown_proposal_returns_none(manager):
    assert manager.get("id-inventado") is None


def test_cannot_apply_a_blocked_proposal(manager):
    proposal = manager.propose(
        target_path="agent_core/orchestrator.py", proposed_source="x", justification="x"
    )
    with pytest.raises(ValueError):
        manager.apply(proposal.id, approved_by="kalin")


def test_cannot_rollback_a_proposal_never_applied(manager):
    proposal = manager.propose(
        target_path="agent_core/orchestrator.py", proposed_source="x", justification="x"
    )
    with pytest.raises(ValueError):
        manager.rollback(proposal.id, reason="no aplica")


# --- Casos que sí corren pytest real como subproceso (más lentos) ---

def test_safe_change_without_regression_is_pending_approval(manager):
    new_source = (
        "def add(a, b):\n"
        "    \"\"\"Suma dos números.\"\"\"\n"
        "    return a + b\n"
    )
    proposal = manager.propose(
        target_path="mymodule.py", proposed_source=new_source, justification="agregar docstring"
    )

    assert proposal.status == "pending_human_approval"
    assert proposal.baseline_tests is not None
    assert proposal.candidate_tests is not None
    assert proposal.candidate_tests.is_clean


def test_change_that_breaks_existing_test_is_detected_as_regression(manager):
    broken_source = "def add(a, b):\n    return a - b\n"  # rompe test_add
    proposal = manager.propose(
        target_path="mymodule.py", proposed_source=broken_source, justification="cambio que rompe todo"
    )

    assert proposal.status == "regression_detected"
    assert proposal.candidate_tests.failed > proposal.baseline_tests.failed


def test_apply_writes_change_and_creates_backup(manager, fake_project):
    new_source = "def add(a, b):\n    \"\"\"Suma.\"\"\"\n    return a + b\n"
    proposal = manager.propose(target_path="mymodule.py", proposed_source=new_source, justification="doc")
    assert proposal.status == "pending_human_approval"

    manager.apply(proposal.id, approved_by="kalin")

    real_file = fake_project / "mymodule.py"
    assert real_file.read_text(encoding="utf-8") == new_source
    assert proposal.backup_path is not None
    from pathlib import Path
    assert Path(proposal.backup_path).exists()


def test_rollback_restores_original_content(manager, fake_project):
    original_content = (fake_project / "mymodule.py").read_text(encoding="utf-8")
    new_source = "def add(a, b):\n    \"\"\"Suma.\"\"\"\n    return a + b\n"

    proposal = manager.propose(target_path="mymodule.py", proposed_source=new_source, justification="doc")
    manager.apply(proposal.id, approved_by="kalin")
    manager.rollback(proposal.id, reason="prueba de rollback")

    real_file = fake_project / "mymodule.py"
    assert real_file.read_text(encoding="utf-8") == original_content
    assert proposal.status == "rolled_back"


def test_cannot_apply_same_proposal_twice(manager):
    new_source = "def add(a, b):\n    \"\"\"Suma.\"\"\"\n    return a + b\n"
    proposal = manager.propose(target_path="mymodule.py", proposed_source=new_source, justification="doc")
    manager.apply(proposal.id, approved_by="kalin")

    with pytest.raises(ValueError):
        manager.apply(proposal.id, approved_by="otro")
