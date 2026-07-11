"""
Tests de error_handling/strategies.py::ValidationErrorStrategy.

Puro Python, sin Docker — la estrategia no ejecuta nada, solo decide
si vale la pena reintentar (nunca).
"""
from __future__ import annotations

from error_handling.strategies import RepairContext, ValidationErrorStrategy


def _ctx(error_message="Import prohibido: os en línea 1") -> RepairContext:
    return RepairContext(
        error_type="ValidationError",
        error_message=error_message,
        source_code="import os\nos.system('ls')",
        location="task:abc",
    )


def test_never_succeeds():
    """
    A diferencia de RuntimeErrorStrategy, esto nunca delega un reintento
    al llamador — un rechazo de validación es determinista, reintentar
    el mismo código produce exactamente el mismo rechazo.
    """
    result = ValidationErrorStrategy().repair(_ctx())

    assert result.success is False
    assert result.already_retried is False
    assert result.fixed_code is None


def test_detail_explains_why_retrying_wont_help():
    result = ValidationErrorStrategy().repair(_ctx("Import prohibido: os en línea 1"))

    assert "no llegó a correr" in result.detail or "nunca llegó a correr" in result.detail
    assert "Import prohibido: os en línea 1" in result.detail


def test_result_is_independent_of_error_message_content():
    """No importa cuál fue la violación puntual: nunca se reintenta."""
    for message in ["Import prohibido: subprocess", "Atributo prohibido: __globals__", ""]:
        result = ValidationErrorStrategy().repair(_ctx(message))
        assert result.success is False
