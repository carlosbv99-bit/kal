"""
Tests de agent_core/routers/chat.py — integración del Conversation
Engine (ver agent_core/conversation_engine.py) en /chat: si detecta
baja confianza, responde de inmediato con la aclaración SIN correr
planning_agent.run() (ahorro real de cómputo). Si la confianza alcanza
(o el clasificador devuelve None, "fail-open"), el flujo sigue
exactamente como antes de este cambio.

`orchestrator.conversation_engine`/`orchestrator.planning_agent`
mockeados — no se ejercita ningún LLM real.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from agent_core import orchestrator as orchestrator_module
from agent_core.conversation_engine import ConversationEngineResult
from agent_core.llm.agent_loop import AgentRunResult, AgentStep
from agent_core.llm.planner import Plan, PlanRunResult, PlanStep, PlanStepResult
from agent_core.orchestrator import app
from utils.config import settings

client = TestClient(app)


def _scripted_planning_result() -> PlanRunResult:
    step = AgentStep(tool_name="run_code", arguments={}, observation="listo", artifact=None)
    agent_result = AgentRunResult(goal="hola", final_answer="Respuesta real del agente.", steps=[step])
    return PlanRunResult(
        goal="hola",
        plan=Plan(goal="hola", steps=[PlanStep(description="hola")]),
        step_results=[PlanStepResult(step="hola", result=agent_result)],
        final_answer="Respuesta real del agente.",
    )


class _FakeConversationEngine:
    def __init__(self, result: ConversationEngineResult | None):
        self._result = result
        self.calls: list[str] = []

    def classify(self, goal: str):
        self.calls.append(goal)
        return self._result


class _NeverCallMePlanningAgent:
    """Si planning_agent.run() se llama cuando NO debería, el test falla ruidosamente."""

    def run(self, *args, **kwargs):
        raise AssertionError("planning_agent.run() no debería llamarse con baja confianza")


def test_low_confidence_responds_immediately_without_running_the_agent(monkeypatch):
    fake_ce = _FakeConversationEngine(
        ConversationEngineResult(
            intent="ambiguo", confidence=0.2, required_capabilities=[], user_reply="¿Podrías dar más detalles?"
        )
    )
    monkeypatch.setattr(orchestrator_module.orchestrator, "conversation_engine", fake_ce)
    monkeypatch.setattr(orchestrator_module.orchestrator, "planning_agent", _NeverCallMePlanningAgent())

    response = client.post("/chat", json={"goal": "eh"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_clarification"
    assert body["final_answer"] == "¿Podrías dar más detalles?"
    assert body["plan"] == []
    assert body["steps"] == []
    assert fake_ce.calls == ["eh"]
    # "Último modelo utilizado" (ver frontend/app.js): en el camino de
    # aclaración, el que resolvió el turno es el del Conversation
    # Engine, nunca el modelo principal.
    assert body["model_used"] == settings.conversation_engine.model


def test_high_confidence_runs_the_agent_normally(monkeypatch):
    fake_ce = _FakeConversationEngine(
        ConversationEngineResult(
            intent="saludo", confidence=0.95, required_capabilities=["conversation"], user_reply="listo"
        )
    )
    monkeypatch.setattr(orchestrator_module.orchestrator, "conversation_engine", fake_ce)
    monkeypatch.setattr(
        orchestrator_module.orchestrator, "planning_agent",
        type("_", (), {"run": staticmethod(lambda *a, **kw: _scripted_planning_result())})(),
    )

    response = client.post("/chat", json={"goal": "hola"})

    assert response.status_code == 200
    body = response.json()
    assert body["final_answer"] == "Respuesta real del agente."
    assert body["status"] != "needs_clarification"
    # Sin req.model explícito, el que de verdad resolvió el turno es
    # settings.llm.default_model (misma resolución que OllamaClient.chat()).
    assert body["model_used"] == settings.llm.default_model


def test_model_used_reflects_an_explicit_model_override(monkeypatch):
    fake_ce = _FakeConversationEngine(
        ConversationEngineResult(
            intent="saludo", confidence=0.95, required_capabilities=["conversation"], user_reply="listo"
        )
    )
    monkeypatch.setattr(orchestrator_module.orchestrator, "conversation_engine", fake_ce)
    monkeypatch.setattr(
        orchestrator_module.orchestrator, "planning_agent",
        type("_", (), {"run": staticmethod(lambda *a, **kw: _scripted_planning_result())})(),
    )

    response = client.post("/chat", json={"goal": "hola", "model": "otro-modelo:1b"})

    assert response.json()["model_used"] == "otro-modelo:1b"


def test_conversation_engine_returning_none_falls_through_to_the_agent_normally(monkeypatch):
    # "Fail-open": clasificador deshabilitado o que falló (ver
    # ConversationEngine.classify()) — el flujo sigue como si esto no existiera.
    fake_ce = _FakeConversationEngine(None)
    monkeypatch.setattr(orchestrator_module.orchestrator, "conversation_engine", fake_ce)
    monkeypatch.setattr(
        orchestrator_module.orchestrator, "planning_agent",
        type("_", (), {"run": staticmethod(lambda *a, **kw: _scripted_planning_result())})(),
    )

    response = client.post("/chat", json={"goal": "hola"})

    assert response.status_code == 200
    assert response.json()["final_answer"] == "Respuesta real del agente."
