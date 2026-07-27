"""
Tests de agent_core/memory/manager.py — wiring del Memory Security
Policy Engine (Fase 1, ver agent_core/memory/security_policy.py):
clasificación+redactado SOLO en la promoción a largo plazo, default
fail-closed de `sharing` en remember(), y el derecho al olvido
(forget()/forget_matching()). Con backends FALSOS livianos, mismo
patrón que test_memory_manager_observers.py (sin chromadb real).
"""
from __future__ import annotations

from agent_core.memory.base import MemoryItem
from agent_core.memory.manager import MemoryManager


class _FakeBackend:
    def __init__(self, candidates=None, items_to_consolidate=None):
        self._candidates = candidates or []
        self._items = items_to_consolidate or []
        self.stored: list[MemoryItem] = []
        self.forgotten: list[str] = []

    def store(self, item):
        self.stored.append(item)

    def retrieve(self, query, top_k=5):
        return []

    def get_by_id(self, item_id):
        return None

    def forget(self, item_id):
        self.forgotten.append(item_id)
        self.stored = [i for i in self.stored if i.id != item_id]

    def consolidate(self):
        return self._items

    def candidates_for_promotion(self):
        return self._candidates

    def list_all(self):
        return list(self.stored)


def _manager(**kwargs):
    return MemoryManager(
        short_term=kwargs.get("short_term", _FakeBackend()),
        mid_term=kwargs.get("mid_term", _FakeBackend()),
        long_term=kwargs.get("long_term", _FakeBackend()),
    )


# --- remember(): default fail-closed de sharing ---


def test_remember_defaults_sharing_to_local_only():
    manager = _manager()

    item = manager.remember("dato cualquiera")

    assert item.metadata["sharing"] == "local_only"


def test_remember_respects_an_explicit_sharing_value():
    manager = _manager()

    item = manager.remember("dato explícitamente compartible", sharing="cloud_ok")

    assert item.metadata["sharing"] == "cloud_ok"


def test_remember_preserves_other_metadata_alongside_sharing():
    manager = _manager()

    item = manager.remember("x", metadata={"origen": "conversacion"})

    assert item.metadata["origen"] == "conversacion"
    assert item.metadata["sharing"] == "local_only"


# --- promote_mid_to_long(): clasificación + redactado ---


def test_promotion_classifies_public_content_without_touching_it():
    candidate = MemoryItem(content="un patrón normal sin secretos", repetitions=5, relevance_score=0.9)
    long_term = _FakeBackend()
    manager = _manager(mid_term=_FakeBackend(candidates=[candidate]), long_term=long_term)

    manager.promote_mid_to_long()

    promoted = long_term.stored[0]
    assert promoted.metadata["classification"] == "public"
    assert promoted.content == "un patrón normal sin secretos"


def test_promotion_redacts_a_secret_before_persisting_to_long_term():
    candidate = MemoryItem(
        content="mi key es sk-abcdefghijklmnopqrstuvwx, ayudame a depurar",
        repetitions=5, relevance_score=0.9,
    )
    long_term = _FakeBackend()
    manager = _manager(mid_term=_FakeBackend(candidates=[candidate]), long_term=long_term)

    manager.promote_mid_to_long()

    promoted = long_term.stored[0]
    assert promoted.metadata["classification"] == "secret"
    assert "sk-abcdefghijklmnopqrstuvwx" not in promoted.content
    assert "[REDACTED:openai_key]" in promoted.content
    assert "ayudame a depurar" in promoted.content


def test_remember_and_consolidate_never_redact_a_secret():
    """
    Decisión explícita: corto/mediano plazo necesitan poder contener una
    credencial pegada para que el agente la use en la tarea inmediata —
    solo lo que se vuelve PERMANENTE se filtra.
    """
    manager = _manager()
    item = manager.remember("mi key es sk-abcdefghijklmnopqrstuvwx")

    assert "sk-abcdefghijklmnopqrstuvwx" in item.content

    manager.mid_term.store(item)
    assert "sk-abcdefghijklmnopqrstuvwx" in manager.mid_term.stored[0].content


# --- forget() / forget_matching(): derecho al olvido ---


def test_forget_delegates_to_the_right_backend_by_tier():
    long_term = _FakeBackend()
    manager = _manager(long_term=long_term)

    manager.forget("algun-id", "long_term")

    assert long_term.forgotten == ["algun-id"]


def test_forget_rejects_an_invalid_tier():
    import pytest

    manager = _manager()
    with pytest.raises(ValueError):
        manager.forget("algun-id", "not_a_real_tier")


def test_forget_matching_requires_at_least_one_filter():
    import pytest

    manager = _manager()
    with pytest.raises(ValueError):
        manager.forget_matching()


def test_forget_matching_by_keyword_deletes_only_matches():
    item_a = MemoryItem(content="contiene la palabra clave openai")
    item_b = MemoryItem(content="no tiene nada que ver")
    mid_term = _FakeBackend()
    mid_term.stored = [item_a, item_b]
    manager = _manager(mid_term=mid_term)

    deleted = manager.forget_matching(keyword="openai")

    assert deleted == 1
    assert mid_term.forgotten == [item_a.id]


def test_forget_matching_by_classification():
    secret_item = MemoryItem(content="x", metadata={"classification": "secret"})
    public_item = MemoryItem(content="y", metadata={"classification": "public"})
    long_term = _FakeBackend()
    long_term.stored = [secret_item, public_item]
    manager = _manager(long_term=long_term)

    deleted = manager.forget_matching(classification="secret")

    assert deleted == 1
    assert long_term.forgotten == [secret_item.id]


def test_forget_matching_by_date_range():
    old_item = MemoryItem(content="viejo", created_at=100.0)
    new_item = MemoryItem(content="nuevo", created_at=900.0)
    long_term = _FakeBackend()
    long_term.stored = [old_item, new_item]
    manager = _manager(long_term=long_term)

    deleted = manager.forget_matching(before=500.0)

    assert deleted == 1
    assert long_term.forgotten == [old_item.id]


def test_forget_matching_scoped_to_a_single_tier():
    matching_in_mid = MemoryItem(content="openai en mediano")
    matching_in_long = MemoryItem(content="openai en largo")
    mid_term = _FakeBackend()
    mid_term.stored = [matching_in_mid]
    long_term = _FakeBackend()
    long_term.stored = [matching_in_long]
    manager = _manager(mid_term=mid_term, long_term=long_term)

    deleted = manager.forget_matching(keyword="openai", tier="mid_term")

    assert deleted == 1
    assert mid_term.forgotten == [matching_in_mid.id]
    assert long_term.forgotten == []


def test_forget_matching_across_all_three_tiers_by_default():
    short_term = _FakeBackend()
    short_term.stored = [MemoryItem(content="openai en corto")]
    mid_term = _FakeBackend()
    mid_term.stored = [MemoryItem(content="openai en mediano")]
    long_term = _FakeBackend()
    long_term.stored = [MemoryItem(content="openai en largo")]
    manager = _manager(short_term=short_term, mid_term=mid_term, long_term=long_term)

    deleted = manager.forget_matching(keyword="openai")

    assert deleted == 3
