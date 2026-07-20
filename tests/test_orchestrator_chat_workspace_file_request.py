"""
Tests de agent_core/routers/chat.py::chat()::_step_artifact() — la rama
"workspace_file_request" (ver tool_integration/adapters/vscode_files.py
::ReadWorkspaceFileTool). Antes de este fix, esta rama no existía y
_step_artifact() devolvía None para cualquier modality que no fuera
"project_files"/"image" — la extensión de VS Code nunca hubiera podido
detectar el pedido pendiente ni encadenar la lectura real del archivo.

`orchestrator.planning_agent.run` mockeado con un PlanRunResult
guionado — no se ejercita el LLM real, solo la serialización de la
respuesta de /chat (mismo patrón que test_orchestrator_chat_project_files.py).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from agent_core import orchestrator as orchestrator_module
from agent_core.llm.agent_loop import AgentRunResult, AgentStep
from agent_core.llm.planner import Plan, PlanRunResult, PlanStep, PlanStepResult
from agent_core.orchestrator import app
from sdk.artifacts import Artifact

client = TestClient(app)


def _scripted_result(artifact: Artifact | None) -> PlanRunResult:
    step = AgentStep(tool_name="read_workspace_file", arguments={"path": "restaurante-web/menu.html"}, observation="pendiente", artifact=artifact)
    agent_result = AgentRunResult(goal="agregar fotos al menú", final_answer="Estoy revisando el archivo.", steps=[step])
    return PlanRunResult(
        goal="agregar fotos al menú",
        plan=Plan(goal="agregar fotos al menú", steps=[PlanStep(description="agregar fotos al menú")]),
        step_results=[PlanStepResult(step="agregar fotos al menú", result=agent_result)],
        final_answer="Estoy revisando el archivo.",
    )


def test_workspace_file_request_artifact_is_serialized_with_request_id_and_path(monkeypatch):
    artifact = Artifact(
        modality="workspace_file_request",
        uri="",
        metadata={"status": "pending", "request_id": "req-456", "path": "restaurante-web/menu.html"},
    )
    monkeypatch.setattr(
        orchestrator_module.orchestrator,
        "planning_agent",
        type("_", (), {"run": staticmethod(lambda *a, **kw: _scripted_result(artifact))})(),
    )

    response = client.post("/chat", json={"goal": "agregar fotos al menú", "client": "vscode"})

    assert response.status_code == 200
    step = response.json()["steps"][0]
    assert step["artifact"]["modality"] == "workspace_file_request"
    assert step["artifact"]["request_id"] == "req-456"
    assert step["artifact"]["path"] == "restaurante-web/menu.html"
