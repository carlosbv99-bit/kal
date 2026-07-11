"""
Tests de error_handling/detector.py::ErrorDetector.

Cubre específicamente el bug encontrado durante el desarrollo: sin
inyección de dependencias, ErrorDetector siempre instanciaba las
estrategias con sus defaults (strategy_cls()), ignorando cualquier
mid_term/runner que el llamador quisiera compartir — lo que hacía que
RuntimeErrorStrategy nunca viera los checkpoints guardados por
TaskExecutor en un mid_term inyectado (p.ej. uno de test, aislado del
archivo real del proyecto).
"""
from __future__ import annotations

import pytest

from agent_core.memory.base import MemoryItem
from agent_core.memory.mid_term import MidTermMemory
from error_handling.detector import ErrorDetector
from error_handling.strategies import RepairContext, RuntimeErrorStrategy


@pytest.fixture
def mid_term(tmp_path):
    return MidTermMemory(db_path=tmp_path / "detector_test.db")


def test_without_injection_strategy_uses_its_own_default_mid_term(mid_term):
    """
    Documenta el comportamiento SIN inyección: la estrategia por
    defecto no ve el checkpoint guardado en un mid_term aislado, porque
    crea el suyo propio (apuntando al archivo real del proyecto, no al
    tmp_path de este test). Este test existe para dejar constancia del
    comportamiento, no porque sea deseable — ver el siguiente test para
    el comportamiento correcto con inyección.
    """
    mid_term.store(MemoryItem(id="checkpoint:aislado", content="checkpoint solo visible en este mid_term"))

    detector = ErrorDetector()  # sin strategies inyectadas
    ctx = RepairContext(error_type="RuntimeError", error_message="boom", source_code="x", location="task:aislado")
    result = detector.handle(ctx)

    # Sin inyección, la estrategia no puede ver el checkpoint del
    # mid_term aislado de este test (usa su propio mid_term por defecto).
    assert result.success is False


def test_with_injection_strategy_uses_the_injected_mid_term(mid_term):
    mid_term.store(MemoryItem(id="checkpoint:aislado", content="checkpoint solo visible en este mid_term"))

    detector = ErrorDetector(strategies={"RuntimeError": RuntimeErrorStrategy(mid_term=mid_term)})
    ctx = RepairContext(error_type="RuntimeError", error_message="boom", source_code="x", location="task:aislado")
    result = detector.handle(ctx)

    assert result.success is True


def test_circuit_breaker_opens_for_persistently_failing_signature(mid_term):
    """
    Sin checkpoint (para que la estrategia realmente falle cada vez),
    el circuit breaker debe abrir tras max_repair_attempts intentos con
    la misma firma de error, y las llamadas posteriores deben quedar
    bloqueadas sin siquiera invocar la estrategia de nuevo.
    """
    detector = ErrorDetector(strategies={"RuntimeError": RuntimeErrorStrategy(mid_term=mid_term)})
    ctx = RepairContext(error_type="RuntimeError", error_message="siempre falla", source_code="x", location="task:sin-checkpoint-nunca")

    outcomes = []
    for _ in range(6):
        result = detector.handle(ctx)
        outcomes.append(result.detail)

    assert "circuit_breaker_open" in outcomes


def test_unknown_error_type_escalates_immediately(mid_term):
    detector = ErrorDetector()
    ctx = RepairContext(error_type="ZeroDivisionError", error_message="boom", source_code="x", location="task:x")
    result = detector.handle(ctx)

    assert result.success is False
    assert result.detail == "no_strategy_registered"
