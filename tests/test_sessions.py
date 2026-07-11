"""Tests de agent_core/sessions.py — continuidad conversacional por sesión."""
from __future__ import annotations

from agent_core.sessions import SessionManager
from tool_integration.base_tool import Artifact
from tool_integration.permissions import Permission


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


def test_record_turn_appends_to_history():
    manager = SessionManager()
    session = manager.get_or_create(None)

    manager.record_turn(session, goal="hazme un logo", final_answer="Listo, generé el logo.")
    manager.record_turn(session, goal="hazle el fondo azul", final_answer="Fondo cambiado a azul.")

    assert session.history_messages() == [
        {"role": "user", "content": "hazme un logo"},
        {"role": "assistant", "content": "Listo, generé el logo."},
        {"role": "user", "content": "hazle el fondo azul"},
        {"role": "assistant", "content": "Fondo cambiado a azul."},
    ]


def test_context_message_is_none_without_an_active_artifact():
    manager = SessionManager()
    session = manager.get_or_create(None)

    assert session.context_message() is None


def test_context_message_describes_the_active_artifact():
    manager = SessionManager()
    session = manager.get_or_create(None)
    artifact = Artifact(modality="image", uri="data/artifacts/images/logo.png")

    manager.update_active_artifact(session, artifact)

    message = session.context_message()
    assert message["role"] == "system"
    assert "image" in message["content"]
    assert "data/artifacts/images/logo.png" in message["content"]


def test_update_active_artifact_replaces_the_previous_one():
    manager = SessionManager()
    session = manager.get_or_create(None)
    manager.update_active_artifact(session, Artifact(modality="image", uri="uno.png"))

    manager.update_active_artifact(session, Artifact(modality="image", uri="dos.png"))

    assert session.active_artifact.uri == "dos.png"


def test_different_sessions_are_isolated_from_each_other():
    manager = SessionManager()
    session_a = manager.get_or_create("sesion-a")
    session_b = manager.get_or_create("sesion-b")

    manager.record_turn(session_a, goal="a", final_answer="respuesta a")

    assert session_a.history_messages() != []
    assert session_b.history_messages() == []


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
