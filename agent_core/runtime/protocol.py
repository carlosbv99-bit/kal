"""
Contrato genérico para cualquier Runtime que el Kernel pueda usar —
Ollama y un endpoint OpenAI-compatible hoy, MLX/vLLM/ComfyUI/etc.
mañana. El Kernel (RuntimeManager, ver manager.py) SOLO conoce esta
forma: capabilities()/status()/execute(). Nunca sabe qué hardware hay
detrás (VRAM, CUDA, ROCm, Vulkan, Metal, RAM compartida) — eso es
responsabilidad exclusiva de cada Runtime concreto, que declara
`max_parallel` según su propio criterio (un número abstracto de
"cuántas ejecuciones concurrentes tolero", nunca una cuenta de
memoria).

Motivado por un problema real (no hipotético): varios pedidos
concurrentes compitiendo por cargar/descargar modelos grandes en la
misma máquina — el Kernel nunca debería tener que razonar sobre POR
QUÉ eso pasa, solo sobre CUÁNTAS ejecuciones simultáneas un runtime
declara tolerar. Ver docs/HISTORY.md "Runtime Manager" (2026-07-25).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class RuntimeCapabilities:
    supports: frozenset[str]  # p.ej. {"chat"} — vocabulario de capacidades ya usado por capability_broker.py
    max_parallel: int  # cuántas ejecuciones simultáneas tolera ESTE runtime — nunca una cifra de memoria


@dataclass(frozen=True)
class RuntimeStatus:
    available: bool
    queue_depth: int = 0


@dataclass
class ExecutionRequest:
    """
    Sobre genérico de un pedido de ejecución — para el caso real de
    hoy (chat) coincide con los parámetros que LLMProvider.chat() ya
    recibe (ver agent_core/llm/provider.py). `payload` es deliberadamente
    `Any`: un futuro Runtime de otra capacidad (imagen, audio) pasaría
    ahí su propio tipo de pedido, sin que RuntimeManager necesite saber
    qué es.
    """
    payload: Any


@runtime_checkable
class Runtime(Protocol):
    """
    Conformidad estructural (no hace falta heredar) — mismo criterio
    que LLMProvider en agent_core/llm/provider.py.
    """

    def capabilities(self) -> RuntimeCapabilities: ...

    def status(self) -> RuntimeStatus: ...

    def execute(self, request: ExecutionRequest) -> Any: ...
