"""
Tests de agent_core/memory/mid_term.py — usa SQLite en un archivo
temporal por test (no requiere Docker ni red).
"""
from __future__ import annotations

import time

import pytest

from agent_core.memory.base import MemoryItem
from agent_core.memory.mid_term import MidTermMemory


@pytest.fixture
def mem(tmp_path):
    return MidTermMemory(db_path=tmp_path / "test_memory.db")


def test_store_and_retrieve_by_content_match(mem):
    item = MemoryItem(content="el cielo es azul")
    mem.store(item)

    results = mem.retrieve("cielo")
    assert len(results) == 1
    assert results[0].id == item.id


def test_retrieve_no_match_returns_empty(mem):
    mem.store(MemoryItem(content="contenido irrelevante"))
    results = mem.retrieve("término que no aparece")
    assert results == []


def test_store_or_replace_same_id_updates_content(mem):
    item = MemoryItem(id="fixed-id", content="versión original")
    mem.store(item)

    updated = MemoryItem(id="fixed-id", content="versión actualizada")
    mem.store(updated)

    results = mem.retrieve("actualizada")
    assert len(results) == 1
    assert results[0].content == "versión actualizada"

    # Confirma que no quedó duplicado bajo el mismo id
    results_original = mem.retrieve("original")
    assert results_original == []


def test_forget_removes_item(mem):
    item = MemoryItem(content="a olvidar")
    mem.store(item)
    mem.forget(item.id)

    assert mem.retrieve("olvidar") == []


def test_purge_expired_removes_old_items_only(mem):
    old_item = MemoryItem(content="viejo", created_at=time.time() - 1_000_000)
    recent_item = MemoryItem(content="reciente", created_at=time.time())
    mem.store(old_item)
    mem.store(recent_item)

    # Fuerza un TTL corto para el test, en vez de depender del valor de config.yaml
    mem.ttl_seconds = 100

    removed = mem.purge_expired()
    assert removed == 1

    remaining = mem.retrieve("reciente")
    assert len(remaining) == 1
    assert remaining[0].content == "reciente"


def test_candidates_for_promotion_respects_thresholds(mem):
    from utils.config import settings

    cfg = settings.memory.long_term.promotion
    below_threshold = MemoryItem(
        content="poco relevante",
        repetitions=cfg.min_repetitions - 1,
        relevance_score=cfg.min_relevance_score,
    )
    meets_threshold = MemoryItem(
        content="muy relevante",
        repetitions=cfg.min_repetitions,
        relevance_score=cfg.min_relevance_score,
    )
    mem.store(below_threshold)
    mem.store(meets_threshold)

    candidates = mem.candidates_for_promotion()
    ids = [c.id for c in candidates]
    assert meets_threshold.id in ids
    assert below_threshold.id not in ids


def test_metadata_round_trips_correctly(mem):
    item = MemoryItem(content="con metadata", metadata={"origen": "test", "n": 42})
    mem.store(item)

    results = mem.retrieve("metadata")
    assert results[0].metadata == {"origen": "test", "n": 42}
