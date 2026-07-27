"""Tests de agent_core/sessions.py — continuidad conversacional por sesión."""
from __future__ import annotations

from agent_core.sessions import SessionManager
from sdk.artifacts import Artifact
from sdk.permissions import Permission


def test_get_or_create_with_none_creates_a_new_session_with_random_id():
    manager = SessionManager()

    session = manager.get_or_create(None)

    assert session.id
    assert session.turns == []
    assert session.active_artifact is None


def test_get_or_create_with_known_id_returns_the_same_session():
    manager = SessionManager()
    first = manager.get_or_create(None)

    second = manager.get_or_create(first.id)

    assert second is first


def test_get_or_create_with_unknown_id_degrades_gracefully_instead_of_failing():
    # Simula un backend reiniciado: el cliente manda un session_id que el
    # SessionManager (nuevo, en memoria) nunca vio — no debe fallar, debe
    # arrancar una sesión nueva bajo ese mismo id.
    manager = SessionManager()

    session = manager.get_or_create("id-de-una-sesion-que-ya-no-existe")

    assert session.id == "id-de-una-sesion-que-ya-no-existe"
    assert session.turns == []


def test_record_turn_appends_to_turns():
    manager = SessionManager()
    session = manager.get_or_create(None)

    manager.record_turn(session, goal="hazme un logo", final_answer="Listo, generé el logo.")
    manager.record_turn(session, goal="hazle el fondo azul", final_answer="Fondo cambiado a azul.")

    assert [t.goal for t in session.turns] == ["hazme un logo", "hazle el fondo azul"]
    assert [t.final_answer for t in session.turns] == ["Listo, generé el logo.", "Fondo cambiado a azul."]


def test_update_active_artifact_replaces_the_previous_one():
    manager = SessionManager()
    session = manager.get_or_create(None)
    manager.update_active_artifact(session, Artifact(modality="image", uri="uno.png"))

    manager.update_active_artifact(session, Artifact(modality="image", uri="dos.png"))

    assert session.active_artifact.uri == "dos.png"


def test_new_session_has_no_artifact_history_by_default():
    manager = SessionManager()
    session = manager.get_or_create(None)

    assert session.artifacts == []


def test_record_artifact_accumulates_unlike_active_artifact_which_only_keeps_the_last_one():
    """
    Gap real que motivó esto: `active_artifact` solo recuerda el ÚLTIMO
    artefacto (uri="dos.png" pisa a "uno.png") — sin esto no había forma
    de responder "qué generé en esta sesión" más allá de eso.
    """
    manager = SessionManager()
    session = manager.get_or_create(None)

    manager.record_artifact(session, Artifact(modality="image", uri="uno.png"), tool_name="image_generation")
    manager.record_artifact(session, Artifact(modality="image", uri="dos.png"), tool_name="image_editing")

    assert [r.artifact.uri for r in session.artifacts] == ["uno.png", "dos.png"]
    assert [r.tool_name for r in session.artifacts] == ["image_generation", "image_editing"]


def test_record_artifact_never_touches_active_artifact():
    manager = SessionManager()
    session = manager.get_or_create(None)

    manager.record_artifact(session, Artifact(modality="image", uri="uno.png"), tool_name="image_generation")

    assert session.active_artifact is None


def test_different_sessions_are_isolated_from_each_other():
    manager = SessionManager()
    session_a = manager.get_or_create("sesion-a")
    session_b = manager.get_or_create("sesion-b")

    manager.record_turn(session_a, goal="a", final_answer="respuesta a")
    manager.record_artifact(session_a, Artifact(modality="image", uri="a.png"), tool_name="image_generation")

    assert session_a.turns != []
    assert session_b.turns == []
    assert session_a.artifacts != []
    assert session_b.artifacts == []


def test_new_session_has_no_denied_permissions_by_default():
    manager = SessionManager()
    session = manager.get_or_create(None)

    assert session.denied_permissions == frozenset()


def test_update_denied_permissions_sets_the_override():
    manager = SessionManager()
    session = manager.get_or_create(None)

    manager.update_denied_permissions(session, frozenset({Permission.NETWORK}))

    assert session.denied_permissions == frozenset({Permission.NETWORK})


def test_update_denied_permissions_replaces_not_accumulates():
    manager = SessionManager()
    session = manager.get_or_create(None)
    manager.update_denied_permissions(session, frozenset({Permission.NETWORK}))

    manager.update_denied_permissions(session, frozenset({Permission.BROWSER}))

    assert session.denied_permissions == frozenset({Permission.BROWSER})


def test_new_session_has_no_progress_by_default():
    manager = SessionManager()
    session = manager.get_or_create(None)

    assert session.progress == []


def test_append_progress_accumulates_in_order():
    manager = SessionManager()
    session = manager.get_or_create(None)

    manager.append_progress(session, {"stage": "conversation_engine", "model": "qwen2.5:3b"})
    manager.append_progress(session, {"stage": "main_model", "model": "qwen2.5-coder:14b"})

    assert session.progress == [
        {"stage": "conversation_engine", "model": "qwen2.5:3b"},
        {"stage": "main_model", "model": "qwen2.5-coder:14b"},
    ]


def test_clear_progress_empties_it():
    manager = SessionManager()
    session = manager.get_or_create(None)
    manager.append_progress(session, {"stage": "main_model", "model": "x"})

    manager.clear_progress(session)

    assert session.progress == []
