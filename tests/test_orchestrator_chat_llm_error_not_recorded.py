"""
Tests de agent_core/routers/chat.py::chat() — un turno con
status="llm_error" (ver agent_core/llm/agent_loop.py: ProviderError
atrapado por paso, nunca propaga como excepción) NO debe grabarse en
session.turns.

BUG REAL ENCONTRADO EN USO (2026-08-23): un 500 real de Ollama dejaba
result.final_answer como el texto crudo del error HTTP, y record_turn()
lo grababa igual como si fuera una respuesta real — el próximo pedido
en la MISMA sesión mandaba ese error de vuelta al modelo como su propio
mensaje "assistant" anterior (ver context_service.py::_windowed_history),
causando una respuesta rara ("Entendido, usaré propose_project_files...")
en vez de reintentar la herramienta de una. session.turns solo se usa
para construir ese historial — no grabar un turno de error no pierde
nada que el usuario necesite (ya ve el error en esa misma respuesta).

`orchestrator.planning_agent.run` mockeado con un PlanRunResult
guionado — mismo patrón que test_orchestrator_chat_workspace_file_request.py.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from agent_core import orchestrator as orchestrator_module
from agent_core.llm.planner import Plan, PlanRunResult
from agent_core.orchestrator import app

client = TestClient(app, base_url="http://localhost")


def _scripted_result(status: str, final_answer: str) -> PlanRunResult:
    return PlanRunResult(
        goal="crea un proyecto de agenda para android",
        plan=Plan(goal="crea un proyecto de agenda para android", steps=[]),
        step_results=[],
        final_answer=final_answer,
        status=status,
    )


def test_an_llm_error_turn_is_not_recorded_in_session_history(monkeypatch):
    error_text = "Ollama devolvió un error HTTP: 500 Server Error: Internal Server Error"
    monkeypatch.setattr(
        orchestrator_module.orchestrator,
        "planning_agent",
        type("_", (), {"run": staticmethod(lambda *a, **kw: _scripted_result("llm_error", error_text))})(),
    )

    response = client.post(
        "/chat", json={"goal": "crea un proyecto de agenda para android", "session_id": "s-llm-error-test"}
    )

    assert response.status_code == 200
    session = orchestrator_module.orchestrator.sessions.get_or_create("s-llm-error-test")
    assert session.turns == []


def test_a_successful_turn_is_still_recorded_in_session_history(monkeypatch):
    """No regresión: el fix de arriba no debe romper el caso normal."""
    monkeypatch.setattr(
        orchestrator_module.orchestrator,
        "planning_agent",
        type("_", (), {"run": staticmethod(lambda *a, **kw: _scripted_result("success", "listo"))})(),
    )

    response = client.post(
        "/chat", json={"goal": "crea un proyecto de agenda para android", "session_id": "s-success-test"}
    )

    assert response.status_code == 200
    session = orchestrator_module.orchestrator.sessions.get_or_create("s-success-test")
    assert len(session.turns) == 1
    assert session.turns[0].final_answer == "listo"
