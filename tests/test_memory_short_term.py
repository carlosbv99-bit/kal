"""
Tests de agent_core/memory/short_term.py — puro Python, sin dependencias
externas ni Docker.
"""
from __future__ import annotations

from agent_core.memory.base import MemoryItem
from agent_core.memory.short_term import ShortTermMemory


def test_store_and_retrieve_returns_stored_item():
    mem = ShortTermMemory(max_tokens=1000)
    item = MemoryItem(content="hola mundo")
    mem.store(item)

    results = mem.retrieve("cualquier query", top_k=5)
    assert len(results) == 1
    assert results[0].id == item.id
    assert results[0].content == "hola mundo"


def test_retrieve_respects_top_k():
    mem = ShortTermMemory(max_tokens=10_000)
    for i in range(10):
        mem.store(MemoryItem(content=f"item {i}"))

    results = mem.retrieve("query", top_k=3)
    assert len(results) == 3


def test_retrieve_returns_most_recent_items():
    mem = ShortTermMemory(max_tokens=10_000)
    for i in range(5):
        mem.store(MemoryItem(content=f"item {i}"))

    results = mem.retrieve("query", top_k=2)
    contents = [r.content for r in results]
    # FIFO: los últimos 2 agregados deben ser "item 3" e "item 4"
    assert contents == ["item 3", "item 4"]


def test_eviction_when_exceeding_max_tokens():
    """
    Con max_tokens bajo, agregar suficientes items debe evictar los más
    antiguos (FIFO) para mantenerse bajo el límite.
    """
    # _estimate_tokens usa len(text)//4, así que "x"*40 ~= 10 tokens
    mem = ShortTermMemory(max_tokens=15)
    mem.store(MemoryItem(id="first", content="x" * 40))   # ~10 tokens
    mem.store(MemoryItem(id="second", content="y" * 40))  # ~10 tokens -> total ~20 > 15, evict "first"

    results = mem.retrieve("query", top_k=10)
    ids = [r.id for r in results]
    assert "first" not in ids
    assert "second" in ids


def test_forget_removes_specific_item():
    mem = ShortTermMemory(max_tokens=10_000)
    item1 = MemoryItem(content="mantener")
    item2 = MemoryItem(content="olvidar")
    mem.store(item1)
    mem.store(item2)

    mem.forget(item2.id)

    results = mem.retrieve("query", top_k=10)
    ids = [r.id for r in results]
    assert item1.id in ids
    assert item2.id not in ids


def test_consolidate_returns_items_and_clears_buffer():
    mem = ShortTermMemory(max_tokens=10_000)
    mem.store(MemoryItem(content="uno"))
    mem.store(MemoryItem(content="dos"))

    consolidated = mem.consolidate()
    assert len(consolidated) == 2

    # El buffer debe quedar vacío tras consolidar
    assert mem.retrieve("query", top_k=10) == []


def test_consolidate_on_empty_buffer_returns_empty_list():
    mem = ShortTermMemory(max_tokens=1000)
    assert mem.consolidate() == []


def test_retrieve_on_empty_memory_returns_empty_list():
    mem = ShortTermMemory(max_tokens=1000)
    assert mem.retrieve("cualquier cosa") == []
