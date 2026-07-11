"""
Tests de error_handling/strategies.py::RuntimeErrorStrategy.

Sin Docker: la estrategia solo consulta MidTermMemory (SQLite), no
ejecuta nada. El reintento real end-to-end vive en
test_task_executor_sandboxed.py.
"""
from __future__ import annotations

import pytest

from agent_core.memory.base import MemoryItem
from agent_core.memory.mid_term import MidTermMemory
from error_handling.strategies import RepairContext, RuntimeErrorStrategy


@pytest.fixture
def mid_term(tmp_path):
    return MidTermMemory(db_path=tmp_path / "checkpoints.db")


@pytest.fixture
def strategy(mid_term):
    return RuntimeErrorStrategy(mid_term=mid_term)


def test_no_checkpoint_fails_cleanly(strategy):
    ctx = RepairContext(
        error_type="RuntimeError", error_message="boom", source_code="x", location="task:sin-checkpoint"
    )
    result = strategy.repair(ctx)
    assert result.success is False
    assert "checkpoint" in result.detail.lower()


def test_existing_checkpoint_allows_retry(strategy, mid_term):
    mid_term.store(MemoryItem(id="checkpoint:con-checkpoint", content="checkpoint de prueba"))

    ctx = RepairContext(
        error_type="RuntimeError", error_message="boom", source_code="x", location="task:con-checkpoint"
    )
    result = strategy.repair(ctx)

    assert result.success is True
    assert result.already_retried is False  # delega el reintento, no lo hace ella misma
    assert result.fixed_code is None  # no hay corrección de código, se reintenta el mismo


def test_malformed_location_fails_without_querying_memory(strategy):
    ctx = RepairContext(
        error_type="RuntimeError", error_message="boom", source_code="x", location="ubicacion-sin-prefijo-task"
    )
    result = strategy.repair(ctx)
    assert result.success is False


def test_checkpoint_lookup_is_exact_not_fuzzy(strategy, mid_term):
    """
    Confirma que se usa get_by_id (exacto), no retrieve (LIKE difuso):
    un checkpoint de OTRA tarea con contenido similar no debe usarse
    como si fuera el de esta tarea.
    """
    mid_term.store(MemoryItem(id="checkpoint:otra-tarea", content="checkpoint de otra tarea distinta"))

    ctx = RepairContext(
        error_type="RuntimeError", error_message="boom", source_code="x", location="task:esta-tarea"
    )
    result = strategy.repair(ctx)
    assert result.success is False
