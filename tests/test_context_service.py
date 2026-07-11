"""
Tests de agent_core/context_service.py — decide qué entra al próximo
mensaje al LLM (ventana de turnos + fusión de artefacto activo y
contexto del editor en un único mensaje de sistema).
"""
from __future__ import annotations

from agent_core.context_service import ContextService, EditorContextSignals
from agent_core.sessions import SessionManager
from tool_integration.base_tool import Artifact


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
