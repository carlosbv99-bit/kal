"""
Tests de agent_core/knowledge/ — Knowledge Miner / Knowledge Base
(2026-07-25, infraestructura preparada, ver agent_core/knowledge/__init__.py
y la memoria de proyecto del "modelo de madurez de 4 estados").
Deliberadamente NO prueban ningún clustering/similaridad real — eso
todavía no existe a propósito, esta fase es solo el contrato/mecanismo.
"""
from __future__ import annotations

from agent_core.knowledge.base import KnowledgeBase
from agent_core.knowledge.miner import KnowledgeMiner
from agent_core.knowledge.models import Pattern
from agent_core.memory.base import MemoryItem
from agent_core.memory.events import MemoryEvent, MemoryObserver


def test_pattern_has_a_random_id_by_default():
    a, b = Pattern(), Pattern()
    assert a.id != b.id


def test_knowledge_base_add_and_query():
    kb = KnowledgeBase()
    kb.add(Pattern(summary="algo"))

    # query() todavía no hace ninguna búsqueda real — ver docstring del
    # módulo, es la firma final de la fase "Infraestructura", el
    # comportamiento real llega en la fase "Funcionalidad".
    assert kb.query("algo") == []


def test_knowledge_miner_satisfies_the_memory_observer_protocol():
    assert isinstance(KnowledgeMiner(), MemoryObserver)


def test_knowledge_miner_on_memory_event_does_nothing_yet():
    miner = KnowledgeMiner()
    event = MemoryEvent(kind="promoted", item=MemoryItem(content="x"))

    result = miner.on_memory_event(event)

    assert result is None
    assert miner.knowledge_base._patterns == []


def test_knowledge_miner_defaults_to_its_own_knowledge_base():
    miner = KnowledgeMiner()
    assert isinstance(miner.knowledge_base, KnowledgeBase)


def test_knowledge_miner_can_be_registered_as_a_memory_manager_observer():
    """Prueba de integración mínima: el punto de enganche real
    (MemoryManager.register_observer) acepta un KnowledgeMiner sin
    romper nada — sin backends reales, solo confirma que el tipo encaja."""
    from agent_core.memory.manager import MemoryManager

    class _FakeBackend:
        def store(self, item):
            pass

        def retrieve(self, query, top_k=5):
            return []

        def forget(self, item_id):
            pass

        def consolidate(self):
            return [MemoryItem(content="x")]

        def candidates_for_promotion(self):
            return []

    manager = MemoryManager(short_term=_FakeBackend(), mid_term=_FakeBackend(), long_term=_FakeBackend())
    miner = KnowledgeMiner()

    manager.register_observer(miner)
    manager.consolidate_short_to_mid()  # no debería lanzar nada
