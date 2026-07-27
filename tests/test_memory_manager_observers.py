"""
Tests de agent_core/memory/manager.py::MemoryManager — mecanismo de
observadores (2026-07-25, infraestructura preparada para un futuro
Knowledge Miner, ver agent_core/knowledge/). Con backends FALSOS
livianos (sin chromadb real) — a diferencia de test_memory_manager.py,
que sí requiere chromadb/sentence-transformers para el ciclo completo
real; acá solo se prueba el mecanismo de notificación en sí.
"""
from __future__ import annotations

from agent_core.memory.base import MemoryItem
from agent_core.memory.events import MemoryEvent
from agent_core.memory.manager import MemoryManager


class _FakeShortTerm:
    def __init__(self, items_to_consolidate=None):
        self._items = items_to_consolidate or []

    def store(self, item):
        pass

    def retrieve(self, query, top_k=5):
        return []

    def forget(self, item_id):
        pass

    def consolidate(self):
        return self._items


class _FakeMidTerm:
    def __init__(self, candidates=None):
        self._candidates = candidates or []
        self.stored: list[MemoryItem] = []

    def store(self, item):
        self.stored.append(item)

    def retrieve(self, query, top_k=5):
        return []

    def get_by_id(self, item_id):
        return None

    def forget(self, item_id):
        pass

    def candidates_for_promotion(self):
        return self._candidates


class _FakeLongTerm:
    def __init__(self):
        self.stored: list[MemoryItem] = []

    def store(self, item):
        self.stored.append(item)

    def retrieve(self, query, top_k=5):
        return []

    def get_by_id(self, item_id):
        return None

    def forget(self, item_id):
        pass


class _RecordingObserver:
    def __init__(self):
        self.events: list[MemoryEvent] = []

    def on_memory_event(self, event):
        self.events.append(event)


class _RaisingObserver:
    def on_memory_event(self, event):
        raise RuntimeError("un observer experimental roto")


def test_consolidate_notifies_registered_observers_with_a_consolidated_event():
    item = MemoryItem(content="algo dicho por el usuario")
    manager = MemoryManager(
        short_term=_FakeShortTerm([item]), mid_term=_FakeMidTerm(), long_term=_FakeLongTerm(),
    )
    observer = _RecordingObserver()
    manager.register_observer(observer)

    manager.consolidate_short_to_mid()

    assert len(observer.events) == 1
    assert observer.events[0].kind == "consolidated"
    assert observer.events[0].item is item


def test_promote_notifies_registered_observers_with_a_promoted_event():
    item = MemoryItem(content="un patrón repetido", repetitions=5, relevance_score=0.9)
    manager = MemoryManager(
        short_term=_FakeShortTerm(), mid_term=_FakeMidTerm(candidates=[item]), long_term=_FakeLongTerm(),
    )
    observer = _RecordingObserver()
    manager.register_observer(observer)

    manager.promote_mid_to_long()

    assert len(observer.events) == 1
    assert observer.events[0].kind == "promoted"
    assert observer.events[0].item is item


def test_multiple_observers_all_get_notified():
    item = MemoryItem(content="x")
    manager = MemoryManager(
        short_term=_FakeShortTerm([item]), mid_term=_FakeMidTerm(), long_term=_FakeLongTerm(),
    )
    first, second = _RecordingObserver(), _RecordingObserver()
    manager.register_observer(first)
    manager.register_observer(second)

    manager.consolidate_short_to_mid()

    assert len(first.events) == 1
    assert len(second.events) == 1


def test_an_observer_that_raises_never_breaks_the_real_consolidation_cycle():
    """Fail-safe a propósito: un observer experimental (p.ej. un
    Knowledge Miner futuro todavía sin madurar) nunca debe poder romper
    el ciclo real de memoria."""
    item = MemoryItem(content="x")
    fake_mid_term = _FakeMidTerm()
    manager = MemoryManager(
        short_term=_FakeShortTerm([item]), mid_term=fake_mid_term, long_term=_FakeLongTerm(),
    )
    manager.register_observer(_RaisingObserver())

    count = manager.consolidate_short_to_mid()

    assert count == 1
    assert fake_mid_term.stored == [item]  # la consolidación real sí ocurrió


def test_without_any_registered_observer_nothing_breaks():
    item = MemoryItem(content="x")
    manager = MemoryManager(
        short_term=_FakeShortTerm([item]), mid_term=_FakeMidTerm(), long_term=_FakeLongTerm(),
    )

    count = manager.consolidate_short_to_mid()

    assert count == 1
