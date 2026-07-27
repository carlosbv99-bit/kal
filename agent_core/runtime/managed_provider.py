"""
RuntimeManagedLLMProvider: implementa LLMProvider (conformidad
estructural, ver agent_core/llm/provider.py) delegando en el
RuntimeManager en vez de hablarle directo a un cliente concreto.

Punto clave de diseño: AgentLoop/Planner/SelfDiagnosisAgent siguen
llamando `self.llm.chat(...)` exactamente como siempre — nunca se
enteran de que este mecanismo existe. Lo único que cambió es QUÉ
objeto es `self.llm` (ver agent_core/orchestrator.py::build_llm_client()).
Cero cambio de comportamiento para el núcleo, mismo criterio que ya
validó el Provider Pattern anterior en este proyecto.
"""
from __future__ import annotations

from typing import Any

from agent_core.llm.provider import ChatResponse
from agent_core.runtime.manager import RuntimeManager
from agent_core.runtime.protocol import ExecutionRequest


class RuntimeManagedLLMProvider:
    def __init__(self, runtime_manager: RuntimeManager, runtime_name: str):
        self._rm = runtime_manager
        self._runtime_name = runtime_name

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        response_format: str | None = None,
        temperature: float | None = None,
    ) -> ChatResponse:
        # response_format/temperature solo se agregan al payload si el
        # llamador los pidió — así un Runtime cuyo cliente no los soporta
        # (p.ej. OllamaClient sin pedir ninguno de los dos) nunca recibe
        # un kwarg de más. Mismo criterio que OllamaClient.chat(): ambos
        # son opcionales, pensados para el Conversation Engine (ver
        # agent_core/conversation_engine.py), no usados por
        # AgentLoop/Planner/SelfDiagnosisAgent.
        payload: dict[str, Any] = {"messages": messages, "model": model, "tools": tools}
        if response_format is not None:
            payload["response_format"] = response_format
        if temperature is not None:
            payload["temperature"] = temperature
        request = ExecutionRequest(payload=payload)
        return self._rm.execute(self._runtime_name, request)

    def list_models(self) -> list[str]:
        # Metadata liviana — deliberadamente NO pasa por el semáforo de
        # execute(): debe responder aunque el runtime esté ocupado
        # ejecutando un chat() real, ver RuntimeManager.get_runtime().
        return self._rm.get_runtime(self._runtime_name).client.list_models()

    def is_available(self) -> bool:
        return self._rm.get_runtime(self._runtime_name).client.is_available()
