"""
Tests de agent_core/context_service.py — decide qué entra al próximo
mensaje al LLM (ventana de turnos + fusión de artefacto activo y
contexto del editor en un único mensaje de sistema).
"""
from __future__ import annotations

from agent_core.context_service import ContextService, EditorContextSignals
from agent_core.sessions import SessionManager
from sdk.artifacts import Artifact


def _session_with_turns(n: int):
    manager = SessionManager()
    session = manager.get_or_create(None)
    for i in range(n):
        manager.record_turn(session, goal=f"pedido {i}", final_answer=f"respuesta {i}")
    return session


def test_history_includes_all_turns_when_under_the_limit():
    service = ContextService(max_recent_turns=8)
    session = _session_with_turns(3)

    bundle = service.build(session)

    assert len(bundle.history) == 6  # 3 turnos * (user + assistant)
    assert bundle.history[0] == {"role": "user", "content": "pedido 0"}


def test_history_window_keeps_only_the_last_n_turns():
    service = ContextService(max_recent_turns=2)
    session = _session_with_turns(5)

    bundle = service.build(session)

    assert len(bundle.history) == 4  # solo los últimos 2 turnos
    assert bundle.history[0] == {"role": "user", "content": "pedido 3"}
    assert bundle.history[-1] == {"role": "assistant", "content": "respuesta 4"}


def test_default_max_recent_turns_comes_from_settings():
    from utils.config import settings

    service = ContextService()
    assert service.max_recent_turns == settings.context.max_recent_turns


def test_session_context_is_none_without_artifact_or_editor_context():
    service = ContextService()
    session = _session_with_turns(0)

    bundle = service.build(session)

    assert bundle.session_context is None


def test_session_context_describes_the_active_artifact():
    service = ContextService()
    manager = SessionManager()
    session = manager.get_or_create(None)
    manager.update_active_artifact(session, Artifact(modality="image", uri="data/artifacts/images/logo.png"))

    bundle = service.build(session)

    assert bundle.session_context["role"] == "system"
    assert "image" in bundle.session_context["content"]
    assert "data/artifacts/images/logo.png" in bundle.session_context["content"]


def test_session_context_tells_the_model_to_call_analyze_image_for_an_active_image():
    """
    BUG REAL ENCONTRADO EN USO: pedido "describe esta imagen" sobre una
    imagen recién generada (ya anunciada como artefacto activo) devolvió
    "no puedo ver o analizar imágenes en este entorno" — el modelo tenía
    disponibles el path del artefacto activo y la herramienta
    analyze_image, pero nunca conectó una cosa con la otra.
    """
    service = ContextService()
    manager = SessionManager()
    session = manager.get_or_create(None)
    manager.update_active_artifact(session, Artifact(modality="image", uri="data/artifacts/images/leon.png"))

    bundle = service.build(session)

    assert "analyze_image" in bundle.session_context["content"]
    assert "data/artifacts/images/leon.png" in bundle.session_context["content"]
    assert "no podés ver imágenes" in bundle.session_context["content"]


def test_session_context_does_not_mention_analyze_image_for_non_image_artifacts():
    service = ContextService()
    manager = SessionManager()
    session = manager.get_or_create(None)
    manager.update_active_artifact(session, Artifact(modality="audio", uri="data/artifacts/audio/voz.wav"))

    bundle = service.build(session)

    assert "analyze_image" not in bundle.session_context["content"]


def test_session_context_describes_editor_context():
    service = ContextService()
    session = _session_with_turns(0)
    editor_context = EditorContextSignals(
        relative_path="src/foo.py", language_id="python", text="def foo():\n    pass\n", is_selection=True,
    )

    bundle = service.build(session, editor_context)

    assert bundle.session_context["role"] == "system"
    assert "selección de src/foo.py" in bundle.session_context["content"]
    assert "lenguaje python" in bundle.session_context["content"]
    assert "```python\ndef foo" in bundle.session_context["content"]


def test_editor_context_labels_full_file_when_not_a_selection():
    service = ContextService()
    session = _session_with_turns(0)
    editor_context = EditorContextSignals(
        relative_path="src/bar.ts", language_id="typescript", text="export const x = 1;", is_selection=False,
    )

    bundle = service.build(session, editor_context)

    assert "archivo completo de src/bar.ts" in bundle.session_context["content"]


def test_editor_context_code_block_is_closed():
    service = ContextService()
    session = _session_with_turns(0)
    editor_context = EditorContextSignals(
        relative_path="a.js", language_id="javascript", text="console.log(1);", is_selection=False,
    )

    bundle = service.build(session, editor_context)

    assert bundle.session_context["content"].rstrip().endswith("```")


def test_vscode_client_adds_the_code_only_instruction():
    """
    Distinción real entre facetas (2026-07-11): la interfaz web sigue
    generando imagen/audio/video por default; la extensión de VS Code
    (client="vscode") necesita la instrucción explícita de responder
    con código, no con imágenes, para pedidos de "página web"/app/etc.
    """
    service = ContextService()
    session = _session_with_turns(0)

    bundle = service.build(session, client="vscode")

    assert bundle.session_context["role"] == "system"
    assert "agente de programación dentro de VS Code" in bundle.session_context["content"]


def test_vscode_client_instruction_tells_the_model_to_use_propose_project_files():
    """
    BUG REAL ENCONTRADO EN USO: con propose_project_files ya disponible
    en el toolset, el modelo seguía mostrando el código en texto y
    pidiéndole al usuario que lo copie a mano — tener la herramienta
    ofrecida no bastó, hizo falta instruirlo explícitamente a preferirla
    sobre responder solo en texto.
    """
    service = ContextService()
    session = _session_with_turns(0)

    bundle = service.build(session, client="vscode")

    assert "propose_project_files" in bundle.session_context["content"]


def test_vscode_client_instruction_tells_the_model_to_use_a_subfolder_per_distinct_project():
    """
    BUG REAL ENCONTRADO EN USO: dos pedidos de proyectos distintos en la
    misma conversación (una página para una barbería, después otra para
    una panadería) proponían archivos sueltos en la raíz del proyecto
    (index.html/estilos.css/script.js para ambos) — se mezclaban entre
    sí, sin ninguna separación.
    """
    service = ContextService()
    session = _session_with_turns(0)

    bundle = service.build(session, client="vscode")

    assert "subcarpeta" in bundle.session_context["content"]


def test_vscode_client_instruction_tells_the_model_to_browse_before_importing_a_real_photo():
    """
    Artifact Service (import_resource): el modelo no debe inventar una
    URL de Unsplash/Pexels a ciegas — tiene que confirmarla navegando
    primero (browser, action='images').
    """
    service = ContextService()
    session = _session_with_turns(0)

    bundle = service.build(session, client="vscode")

    assert "import_resource" in bundle.session_context["content"]
    assert "action='images'" in bundle.session_context["content"]


def test_web_client_never_gets_the_vscode_instruction():
    service = ContextService()
    session = _session_with_turns(0)

    bundle = service.build(session, client=None)

    assert bundle.session_context is None  # sin artefacto/editor context, nada que agregar


def test_vscode_instruction_is_fused_with_artifact_and_editor_context_in_one_message():
    service = ContextService()
    manager = SessionManager()
    session = manager.get_or_create(None)
    manager.update_active_artifact(session, Artifact(modality="image", uri="logo.png"))
    editor_context = EditorContextSignals(
        relative_path="src/foo.py", language_id="python", text="x = 1", is_selection=False,
    )

    bundle = service.build(session, editor_context, client="vscode")

    assert bundle.session_context["role"] == "system"
    assert "agente de programación dentro de VS Code" in bundle.session_context["content"]
    assert "logo.png" in bundle.session_context["content"]
    assert "src/foo.py" in bundle.session_context["content"]


def test_artifact_and_editor_context_are_fused_into_a_single_system_message():
    """
    BUG REAL ya documentado en agent_core/llm/agent_loop.py::run(): un
    segundo mensaje role=system hacía que qwen3-coder:30b lo ignorara
    por completo. El Context Service debe fusionar todo en UNO solo.
    """
    service = ContextService()
    manager = SessionManager()
    session = manager.get_or_create(None)
    manager.update_active_artifact(session, Artifact(modality="image", uri="logo.png"))
    editor_context = EditorContextSignals(
        relative_path="src/foo.py", language_id="python", text="x = 1", is_selection=False,
    )

    bundle = service.build(session, editor_context)

    assert bundle.session_context["role"] == "system"
    assert "logo.png" in bundle.session_context["content"]
    assert "src/foo.py" in bundle.session_context["content"]
