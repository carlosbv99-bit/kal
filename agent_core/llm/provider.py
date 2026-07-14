"""
CONTRATO PÚBLICO DE LARGO PLAZO entre el núcleo del agente (AgentLoop,
Planner, SelfDiagnosisAgent) y cualquier motor de lenguaje concreto —
Ollama hoy (ver ollama_client.py), otros mañana (API en la nube, otro
runtime local). El núcleo SOLO puede depender de lo que hay en este
archivo: nunca debe importar OllamaClient/OllamaError directamente en
su lógica de decisión (sí puede usarlo como default concreto en un
constructor, ver agent_loop.py).

Esto es lo que hace posible que kal deje de ser "una app que usa
Ollama" y pase a ser un kernel: una skill de tipo "llm_provider"
escrita hoy contra este contrato debe seguir funcionando aunque el
motor de lenguaje por debajo cambie por completo. Cambios que rompan
compatibilidad hacia atrás en ChatResponse/ToolCall/LLMProvider rompen
a CUALQUIER proveedor de LLM ya instalado — tratar como se trataría un
cambio de versión mayor, no como un refactor interno cualquiera.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    # BUG REAL ENCONTRADO EN USO: el formato OpenAI (que Groq valida
    # ESTRICTO, a diferencia de Ollama) exige un 'id' único por
    # tool_call, para correlacionar la respuesta de la herramienta
    # (mensaje role="tool", campo tool_call_id) con la llamada que la
    # originó — sin esto, un proveedor estricto rechaza cualquier turno
    # posterior a una llamada a herramienta. Default None: Ollama no
    # siempre lo devuelve, y el fallback de texto plano
    # (_extract_fallback_tool_call) tampoco tiene uno — agent_loop.py
    # genera uno nuevo si falta, nunca deja pasar un ToolCall sin id
    # hacia afuera.
    id: str | None = None


@dataclass
class ChatResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class ProviderError(Exception):
    """
    Error genérico de cualquier LLMProvider. El núcleo atrapa ESTE
    tipo, nunca el de un proveedor concreto (p.ej. OllamaError) — así
    agent_loop.py/planner.py/self_diagnosis.py no necesitan saber qué
    proveedor está detrás para manejar una falla del LLM.
    """


@runtime_checkable
class LLMProvider(Protocol):
    """
    Todo motor de lenguaje que el núcleo pueda usar implementa esta
    forma (conformidad estructural — no hace falta heredar de esta
    clase explícitamente, alcanza con tener estos 3 métodos con esta
    firma). `@runtime_checkable` permite verificarlo con
    `isinstance(cliente, LLMProvider)` en tests de contrato.
    """

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse: ...

    def list_models(self) -> list[str]: ...

    def is_available(self) -> bool: ...
