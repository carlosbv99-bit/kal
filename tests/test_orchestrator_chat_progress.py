"""
Tests de agent_core/routers/chat.py — recorrido en vivo (2026-07-24):
el usuario pidió poder monitorear, desde la interfaz web, qué modelo
está actuando EN VIVO mientras /chat todavía está procesando (no solo
al final). GET /chat/progress/{session_id} expone
Session.progress (agent_core/sessions.py), que /chat va llenando a
medida que ocurre cada etapa real (Conversation Engine, modelo
principal, cada llamada a herramienta vía on_step).

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


class _FakeConversationEngine:
    def __init__(self, result: ConversationEngineResult | None):
        self._result = result

    def classify(self, goal: str):
        return self._result


class _FakePlanningAgentThatCallsOnStep:
    """Simula lo que hace agent_loop.py de verdad: llama a on_step por
    cada AgentStep a medida que ocurre, ANTES de devolver el resultado
    final — así se puede probar que chat.py alimenta Session.progress
    correctamente, sin depender de AgentLoop real."""

    def __init__(self, steps: list[AgentStep]):
        self._steps = steps

    def run(self, goal, **kwargs):
        on_step = kwargs.get("on_step")
        if on_step is not None:
            for step in self._steps:
                on_step(step)
        agent_result = AgentRunResult(goal=goal, final_answer="Listo.", steps=self._steps)
        return PlanRunResult(
            goal=goal,
            plan=Plan(goal=goal, steps=[PlanStep(description=goal)]),
            step_results=[PlanStepResult(step=goal, result=agent_result)],
            final_answer="Listo.",
        )


def test_progress_includes_conversation_engine_main_model_and_tool_calls(monkeypatch):
    fake_ce = _FakeConversationEngine(
        ConversationEngineResult(
            intent="image-generation", confidence=0.9, required_capabilities=["image-generation"], user_reply="listo"
        )
    )
    steps = [AgentStep(tool_name="image_generation", arguments={"prompt": "x"}, observation="ok", artifact=None)]
    monkeypatch.setattr(orchestrator_module.orchestrator, "conversation_engine", fake_ce)
    monkeypatch.setattr(orchestrator_module.orchestrator, "planning_agent", _FakePlanningAgentThatCallsOnStep(steps))

    response = client.post("/chat", json={"goal": "generá una imagen"})
    session_id = response.json()["session_id"]

    progress = client.get(f"/chat/progress/{session_id}").json()["progress"]

    assert progress[0] == {
        "stage": "conversation_engine", "model": settings.conversation_engine.model,
        "intent": "image-generation", "confidence": 0.9,
    }
    assert progress[1] == {"stage": "main_model", "model": settings.llm.default_model}
    assert progress[2] == {
        "stage": "tool_call", "tool": "image_generation", "ok": True,
        "backend_model": settings.multimodal.image.model,
    }


def test_progress_includes_the_backend_model_for_analyze_image(monkeypatch):
    """Pedido explícito del usuario: quería ver llava:13b en acción en
    el panel — antes el recorrido solo mostraba el nombre de la
    herramienta, nunca qué modelo especializado la resuelve."""
    fake_ce = _FakeConversationEngine(None)
    steps = [AgentStep(tool_name="analyze_image", arguments={}, observation="ok", artifact=None)]
    monkeypatch.setattr(orchestrator_module.orchestrator, "conversation_engine", fake_ce)
    monkeypatch.setattr(orchestrator_module.orchestrator, "planning_agent", _FakePlanningAgentThatCallsOnStep(steps))

    response = client.post("/chat", json={"goal": "describí esta imagen"})
    session_id = response.json()["session_id"]

    progress = client.get(f"/chat/progress/{session_id}").json()["progress"]

    assert {"stage": "tool_call", "tool": "analyze_image", "ok": True, "backend_model": settings.multimodal.vision.model} in progress


def test_progress_omits_backend_model_for_a_tool_without_one(monkeypatch):
    fake_ce = _FakeConversationEngine(None)
    steps = [AgentStep(tool_name="run_code", arguments={}, observation="ok", artifact=None)]
    monkeypatch.setattr(orchestrator_module.orchestrator, "conversation_engine", fake_ce)
    monkeypatch.setattr(orchestrator_module.orchestrator, "planning_agent", _FakePlanningAgentThatCallsOnStep(steps))

    response = client.post("/chat", json={"goal": "corré este código"})
    session_id = response.json()["session_id"]

    progress = client.get(f"/chat/progress/{session_id}").json()["progress"]

    tool_call_entry = next(e for e in progress if e["stage"] == "tool_call")
    assert "backend_model" not in tool_call_entry


def test_progress_marks_a_failed_tool_call_as_not_ok(monkeypatch):
    fake_ce = _FakeConversationEngine(None)
    steps = [AgentStep(tool_name="import_resource", arguments={}, observation="ERROR: ruta inválida", artifact=None)]
    monkeypatch.setattr(orchestrator_module.orchestrator, "conversation_engine", fake_ce)
    monkeypatch.setattr(orchestrator_module.orchestrator, "planning_agent", _FakePlanningAgentThatCallsOnStep(steps))

    response = client.post("/chat", json={"goal": "logo"})
    session_id = response.json()["session_id"]

    progress = client.get(f"/chat/progress/{session_id}").json()["progress"]

    assert {"stage": "tool_call", "tool": "import_resource", "ok": False} in progress


def test_progress_resets_between_turns_of_the_same_session(monkeypatch):
    fake_ce = _FakeConversationEngine(None)
    monkeypatch.setattr(orchestrator_module.orchestrator, "conversation_engine", fake_ce)
    monkeypatch.setattr(
        orchestrator_module.orchestrator, "planning_agent",
        _FakePlanningAgentThatCallsOnStep(
            [AgentStep(tool_name="run_code", arguments={}, observation="ok", artifact=None)]
        ),
    )

    first = client.post("/chat", json={"goal": "primer pedido"})
    session_id = first.json()["session_id"]
    first_progress = client.get(f"/chat/progress/{session_id}").json()["progress"]
    assert len(first_progress) == 2  # main_model + el tool_call

    monkeypatch.setattr(orchestrator_module.orchestrator, "planning_agent", _FakePlanningAgentThatCallsOnStep([]))
    client.post("/chat", json={"goal": "segundo pedido", "session_id": session_id})

    second_progress = client.get(f"/chat/progress/{session_id}").json()["progress"]
    assert second_progress == [{"stage": "main_model", "model": settings.llm.default_model}]


def test_progress_for_an_unknown_session_id_is_an_empty_list_not_an_error():
    response = client.get("/chat/progress/una-sesion-que-nunca-existio")

    assert response.status_code == 200
    assert response.json() == {"progress": []}
