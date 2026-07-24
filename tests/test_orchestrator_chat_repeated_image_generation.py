"""
Tests de agent_core/routers/chat.py — deduplicación de imágenes
repetidas en un mismo turno. BUG REAL ENCONTRADO EN USO (2026-07-24):
el autochequeo de image_generation (generar -> analyze_image ->
regenerar UNA vez si hace falta, ver agent_loop.py::self_checked_tools)
llama a la MISMA herramienta dos veces — el frontend mostraba las DOS
imágenes como si fueran resultados distintos, en vez de la segunda
(post-autochequeo) reemplazando a la primera.

Deliberado usar `self_checked_tools` (ver AgentRunResult) en vez de
comparar argumentos idénticos entre llamadas: confirmado en vivo que
el modelo a veces REFORMULA el prompt al regenerar ("un globo
aerostático en el cielo azul" pasó a "...con una silueta de tierra y
líneas costeras" en el reintento) — una comparación de argumentos
idénticos no habría detectado ese caso real.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from agent_core import orchestrator as orchestrator_module
from agent_core.llm.agent_loop import AgentRunResult, AgentStep
from agent_core.llm.planner import Plan, PlanRunResult, PlanStep, PlanStepResult
from agent_core.orchestrator import app
from sdk.artifacts import Artifact

client = TestClient(app)


def _scripted_result(steps: list[AgentStep], self_checked_tools: frozenset[str] = frozenset()) -> PlanRunResult:
    agent_result = AgentRunResult(
        goal="crea un globo aerostático", final_answer="Listo.", steps=steps,
        self_checked_tools=self_checked_tools,
    )
    return PlanRunResult(
        goal="crea un globo aerostático",
        plan=Plan(goal="crea un globo aerostático", steps=[PlanStep(description="crea un globo aerostático")]),
        step_results=[PlanStepResult(step="crea un globo aerostático", result=agent_result)],
        final_answer="Listo.",
    )


def test_self_checked_regeneration_with_the_same_prompt_only_shows_the_last_image(monkeypatch):
    steps = [
        AgentStep(
            tool_name="image_generation", arguments={"prompt": "un globo aerostático"},
            observation="imagen 1", artifact=Artifact(modality="image", uri="data/artifacts/images/imagen1.png"),
        ),
        AgentStep(
            tool_name="analyze_image", arguments={"image_path": "data/artifacts/images/imagen1.png", "question": "¿es correcta?"},
            observation="no es ideal", artifact=None,
        ),
        AgentStep(
            tool_name="image_generation", arguments={"prompt": "un globo aerostático"},
            observation="imagen 2", artifact=Artifact(modality="image", uri="data/artifacts/images/imagen2.png"),
        ),
    ]
    monkeypatch.setattr(
        orchestrator_module.orchestrator, "planning_agent",
        type("_", (), {"run": staticmethod(lambda *a, **kw: _scripted_result(steps, frozenset({"image_generation"})))})(),
    )

    response = client.post("/chat", json={"goal": "crea un globo aerostático"})

    body = response.json()
    image_steps = [s for s in body["steps"] if s["tool"] == "image_generation"]
    assert len(image_steps) == 2  # ambos pasos se siguen viendo en el log...
    assert image_steps[0]["artifact"] is None  # ...pero solo el ÚLTIMO trae la imagen adjunta.
    assert image_steps[1]["artifact"] is not None
    assert image_steps[1]["artifact"]["path"] == "data/artifacts/images/imagen2.png"


def test_self_checked_regeneration_with_a_reworded_prompt_still_only_shows_the_last_image(monkeypatch):
    """
    Caso real confirmado en vivo: el prompt de la regeneración quedó
    reformulado distinto al original ("un globo aerostático en el
    cielo azul" -> "...con una silueta de tierra y líneas costeras").
    Comparar argumentos idénticos NO detecta esto — self_checked_tools sí.
    """
    steps = [
        AgentStep(
            tool_name="image_generation", arguments={"prompt": "un globo aerostático en el cielo azul"},
            observation="imagen 1", artifact=Artifact(modality="image", uri="data/artifacts/images/imagen1.png"),
        ),
        AgentStep(
            tool_name="analyze_image", arguments={"image_path": "data/artifacts/images/imagen1.png", "question": "¿es correcta?"},
            observation="no es ideal", artifact=None,
        ),
        AgentStep(
            tool_name="image_generation",
            arguments={"prompt": "un globo aerostático en el cielo azul, con una silueta de tierra y líneas costeras"},
            observation="imagen 2", artifact=Artifact(modality="image", uri="data/artifacts/images/imagen2.png"),
        ),
    ]
    monkeypatch.setattr(
        orchestrator_module.orchestrator, "planning_agent",
        type("_", (), {"run": staticmethod(lambda *a, **kw: _scripted_result(steps, frozenset({"image_generation"})))})(),
    )

    response = client.post("/chat", json={"goal": "crea un globo aerostático"})

    body = response.json()
    image_steps = [s for s in body["steps"] if s["tool"] == "image_generation"]
    assert image_steps[0]["artifact"] is None
    assert image_steps[1]["artifact"] is not None


def test_two_genuinely_different_image_requests_in_the_same_turn_both_show(monkeypatch):
    """
    Distinción clave: dos llamadas a image_generation que NO fueron
    marcadas como autochequeadas (nunca se llamó analyze_image sobre
    ninguna de las dos en este turno) son dos imágenes de verdad
    distintas pedidas en el mismo turno — no deben deduplicarse.
    """
    steps = [
        AgentStep(
            tool_name="image_generation", arguments={"prompt": "un logo"},
            observation="imagen 1", artifact=Artifact(modality="image", uri="data/artifacts/images/logo.png"),
        ),
        AgentStep(
            tool_name="image_generation", arguments={"prompt": "un fondo de pantalla"},
            observation="imagen 2", artifact=Artifact(modality="image", uri="data/artifacts/images/fondo.png"),
        ),
    ]
    monkeypatch.setattr(
        orchestrator_module.orchestrator, "planning_agent",
        type("_", (), {"run": staticmethod(lambda *a, **kw: _scripted_result(steps))})(),
    )

    response = client.post("/chat", json={"goal": "un logo y un fondo"})

    body = response.json()
    image_steps = [s for s in body["steps"] if s["tool"] == "image_generation"]
    assert len(image_steps) == 2
    assert image_steps[0]["artifact"] is not None
    assert image_steps[1]["artifact"] is not None
