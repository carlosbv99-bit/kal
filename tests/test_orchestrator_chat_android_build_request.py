"""
Tests de agent_core/routers/chat.py::chat()::_step_artifact() — la rama
"android_build_request" (ver tool_integration/adapters/vscode_android.py
::AndroidBuildScreenshotTool). A diferencia de "workspace_file_request",
esto no lleva ningún dato adicional (ni "path" ni contenido) — solo el
request_id, porque la extensión resuelve todo el trabajo real (compilar,
instalar, capturar) sin necesitar encadenar la respuesta de vuelta al
modelo (ver vscode-extension/src/androidBuild.ts).

`orchestrator.planning_agent.run` mockeado con un PlanRunResult
guionado — mismo patrón que test_orchestrator_chat_workspace_file_request.py.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from agent_core import orchestrator as orchestrator_module
from agent_core.llm.agent_loop import AgentRunResult, AgentStep
from agent_core.llm.planner import Plan, PlanRunResult, PlanStep, PlanStepResult
from agent_core.orchestrator import app
from sdk.artifacts import Artifact

client = TestClient(app, base_url="http://localhost")


def _scripted_result(artifact: Artifact | None) -> PlanRunResult:
    step = AgentStep(tool_name="android_build_and_screenshot", arguments={}, observation="pendiente", artifact=artifact)
    agent_result = AgentRunResult(
        goal="mostrame el progreso de la app", final_answer="Estoy compilando el proyecto.", steps=[step]
    )
    return PlanRunResult(
        goal="mostrame el progreso de la app",
        plan=Plan(goal="mostrame el progreso de la app", steps=[PlanStep(description="mostrame el progreso de la app")]),
        step_results=[PlanStepResult(step="mostrame el progreso de la app", result=agent_result)],
        final_answer="Estoy compilando el proyecto.",
    )


def test_android_build_request_artifact_is_serialized_with_request_id(monkeypatch):
    artifact = Artifact(modality="android_build_request", uri="", metadata={"request_id": "req-789"})
    monkeypatch.setattr(
        orchestrator_module.orchestrator,
        "planning_agent",
        type("_", (), {"run": staticmethod(lambda *a, **kw: _scripted_result(artifact))})(),
    )

    response = client.post("/chat", json={"goal": "mostrame el progreso de la app", "client": "vscode"})

    assert response.status_code == 200
    step = response.json()["steps"][0]
    assert step["artifact"]["modality"] == "android_build_request"
    assert step["artifact"]["request_id"] == "req-789"
