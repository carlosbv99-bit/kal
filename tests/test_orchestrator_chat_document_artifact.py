"""
Tests de agent_core/routers/chat.py::chat()::_step_artifact() — la rama
nueva para modality="document" (ver tool_integration/adapters/text_file.py::CreateTextFileTool).
Mismo patrón que la rama "image" (traduce una ruta de archivo real a
una URL servida por /artifacts), más el campo "filename" adicional
que el frontend necesita para el link de descarga (ver frontend/app.js).

HALLAZGO REAL EN USO (2026-08-26) que motiva esta herramienta: un
pedido de "crear un .txt con un poema" desde el cliente web no tenía
ninguna forma de entregar el archivo — CreateTextFileTool cierra ese
hueco, reusando el mismo mecanismo de artifacts que imagen/audio/video.

`orchestrator.planning_agent.run` mockeado con un PlanRunResult
guionado — no se ejercita el LLM real, solo la serialización de la
respuesta de /chat.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agent_core import orchestrator as orchestrator_module
from agent_core.llm.agent_loop import AgentRunResult, AgentStep
from agent_core.llm.planner import Plan, PlanRunResult, PlanStep, PlanStepResult
from agent_core.orchestrator import _ARTIFACTS_DIR, app
from sdk.artifacts import Artifact

client = TestClient(app, base_url="http://localhost")


def _scripted_result(artifact: Artifact | None) -> PlanRunResult:
    step = AgentStep(tool_name="create_text_file", arguments={}, observation="listo", artifact=artifact)
    agent_result = AgentRunResult(goal="escribí un poema", final_answer="Listo, ahí tenés el poema.", steps=[step])
    return PlanRunResult(
        goal="escribí un poema",
        plan=Plan(goal="escribí un poema", steps=[PlanStep(description="escribí un poema")]),
        step_results=[PlanStepResult(step="escribí un poema", result=agent_result)],
        final_answer="Listo, ahí tenés el poema.",
    )


def test_document_artifact_is_serialized_with_url_and_filename(monkeypatch, tmp_path):
    # El archivo tiene que existir de verdad bajo _ARTIFACTS_DIR para
    # que _artifact_url() lo acepte (ver su propio chequeo de path
    # traversal) — no hace falta escribir contenido real, solo que
    # exista en la ruta esperada.
    real_path = _ARTIFACTS_DIR / "text_files" / "poema-abc12345.txt"
    real_path.parent.mkdir(parents=True, exist_ok=True)
    real_path.write_text("...", encoding="utf-8")

    artifact = Artifact(
        modality="document", uri=str(real_path),
        metadata={"filename": "poema-abc12345.txt", "length_chars": 3},
    )
    monkeypatch.setattr(
        orchestrator_module.orchestrator, "planning_agent",
        type("_", (), {"run": staticmethod(lambda *a, **kw: _scripted_result(artifact))})(),
    )

    response = client.post("/chat", json={"goal": "escribí un poema"})

    assert response.status_code == 200
    step = response.json()["steps"][0]
    assert step["artifact"]["modality"] == "document"
    assert step["artifact"]["url"] == "/artifacts/text_files/poema-abc12345.txt"
    assert step["artifact"]["filename"] == "poema-abc12345.txt"

    real_path.unlink()


def test_document_artifact_without_filename_metadata_falls_back_to_uri_basename(monkeypatch):
    real_path = _ARTIFACTS_DIR / "text_files" / "sin-metadata-xyz.txt"
    real_path.parent.mkdir(parents=True, exist_ok=True)
    real_path.write_text("...", encoding="utf-8")

    artifact = Artifact(modality="document", uri=str(real_path), metadata={})
    monkeypatch.setattr(
        orchestrator_module.orchestrator, "planning_agent",
        type("_", (), {"run": staticmethod(lambda *a, **kw: _scripted_result(artifact))})(),
    )

    response = client.post("/chat", json={"goal": "escribí un poema"})

    step = response.json()["steps"][0]
    assert step["artifact"]["filename"] == Path(real_path).name

    real_path.unlink()
