"""
Eventos de MemoryManager — infraestructura preparada para un futuro
Knowledge Miner (ver docs/HISTORY.md y la memoria de proyecto "modelo
de madurez de 4 estados"), sin ninguna lógica de minería real todavía.

MemoryManager es quien EMITE estos eventos — el contrato vive acá, del
lado de memoria (mismo criterio que agent_core/llm/provider.py::
LLMProvider: el contrato vive donde está el emisor central, no donde
vive cada implementación concreta futura). Un futuro
agent_core/knowledge/miner.py::KnowledgeMiner IMPLEMENTA este Protocol,
nunca al revés.

Solo dos tipos de evento — los DOS puntos de transición que
MemoryManager ya tiene hoy (consolidate_short_to_mid/
promote_mid_to_long). No se inventan eventos para operaciones que
todavía no existen.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from agent_core.memory.base import MemoryItem

MemoryEventKind = Literal["consolidated", "promoted"]


@dataclass
class MemoryEvent:
    kind: MemoryEventKind
    item: MemoryItem


@runtime_checkable
class MemoryObserver(Protocol):
    """Conformidad estructural (no hace falta heredar) — mismo criterio
    que LLMProvider/Runtime en este proyecto. Un solo método
    (`on_memory_event`), no uno por tipo de evento: más fácil de
    extender sin tener que tocar el Protocol cada vez que aparezca un
    tercer tipo de evento real."""

    def on_memory_event(self, event: MemoryEvent) -> None: ...
