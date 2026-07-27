"""
KnowledgeMiner: implementa agent_core.memory.events.MemoryObserver —
ver agent_core/knowledge/__init__.py.

Deliberadamente sin ninguna lógica de minería real: `on_memory_event()`
no hace nada hoy. El punto de este archivo es que el PUNTO DE ENGANCHE
ya exista (MemoryManager ya notifica, este observer ya se puede
registrar) — el día que se implemente clustering/similaridad real
sobre los eventos acumulados, no hace falta tocar MemoryManager ni
ningún llamador existente, solo esta clase.
"""
from __future__ import annotations

from agent_core.knowledge.base import KnowledgeBase
from agent_core.memory.events import MemoryEvent


class KnowledgeMiner:
    def __init__(self, knowledge_base: KnowledgeBase | None = None):
        self.knowledge_base = knowledge_base or KnowledgeBase()

    def on_memory_event(self, event: MemoryEvent) -> None:
        pass  # deliberadamente vacío — ver docstring del módulo
