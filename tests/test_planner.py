"""Tests de agent_core/llm/planner.py::Planner (descomposición en pasos)."""
from __future__ import annotations

from agent_core.llm.ollama_client import OllamaError
from agent_core.llm.planner import Planner
from agent_core.llm.provider import ChatResponse


class FakeOllamaClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, model=None, tools=None):
        self.calls.append({"messages": messages, "model": model})
        if not self.responses:
            raise AssertionError("FakeOllamaClient se quedó sin respuestas guionadas")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_plan_parses_json_steps_list():
    llm = FakeOllamaClient([ChatResponse(content='{"steps": ["paso 1", "paso 2"]}')])
    planner = Planner(llm_client=llm)

    plan = planner.plan("un objetivo complejo")

    assert [s.description for s in plan.steps] == ["paso 1", "paso 2"]
    assert plan.goal == "un objetivo complejo"


def test_plan_parses_steps_wrapped_in_markdown_fence():
    llm = FakeOllamaClient([ChatResponse(content='```json\n{"steps": ["a", "b"]}\n```')])
    planner = Planner(llm_client=llm)

    plan = planner.plan("objetivo")

    assert [s.description for s in plan.steps] == ["a", "b"]


def test_plan_falls_back_to_single_step_on_unparseable_response():
    llm = FakeOllamaClient([ChatResponse(content="esto no es JSON en absoluto")])
    planner = Planner(llm_client=llm)

    plan = planner.plan("hacé algo simple")

    assert [s.description for s in plan.steps] == ["hacé algo simple"]


def test_plan_falls_back_to_single_step_on_empty_steps_list():
    llm = FakeOllamaClient([ChatResponse(content='{"steps": []}')])
    planner = Planner(llm_client=llm)

    plan = planner.plan("objetivo simple")

    assert [s.description for s in plan.steps] == ["objetivo simple"]


def test_plan_falls_back_to_single_step_when_steps_is_not_a_list():
    llm = FakeOllamaClient([ChatResponse(content='{"steps": "no es una lista"}')])
    planner = Planner(llm_client=llm)

    plan = planner.plan("objetivo")

    assert [s.description for s in plan.steps] == ["objetivo"]


def test_plan_falls_back_to_single_step_on_ollama_error():
    llm = FakeOllamaClient([OllamaError("ollama caído")])
    planner = Planner(llm_client=llm)

    plan = planner.plan("objetivo")

    assert [s.description for s in plan.steps] == ["objetivo"]


def test_plan_ignores_non_string_entries_in_steps_list():
    llm = FakeOllamaClient([ChatResponse(content='{"steps": ["a", 42, "", "b"]}')])
    planner = Planner(llm_client=llm)

    plan = planner.plan("objetivo")

    assert [s.description for s in plan.steps] == ["a", "b"]
