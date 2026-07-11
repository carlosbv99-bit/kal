"""
Tests de error_handling/detector.py::classify_sandbox_error.

Puro Python, sin Docker — la clasificación opera sobre texto (stderr),
no sobre ejecución real. Verificado también manualmente por Claude
antes de esta entrega (ver conversación), pero se deja como suite
formal para que corra en CI junto al resto.
"""
from __future__ import annotations

from error_handling.detector import classify_sandbox_error


def test_classifies_module_not_found_error():
    stderr = (
        "Traceback (most recent call last):\n"
        '  File "main.py", line 1, in <module>\n'
        "ModuleNotFoundError: No module named 'requests'"
    )
    error_type, message = classify_sandbox_error(stderr)
    assert error_type == "ModuleNotFoundError"
    assert "No module named 'requests'" in message


def test_classifies_import_error():
    stderr = "Traceback (most recent call last):\nImportError: cannot import name 'x' from 'y'"
    error_type, _ = classify_sandbox_error(stderr)
    assert error_type == "ImportError"


def test_classifies_syntax_error():
    stderr = (
        '  File "main.py", line 1\n'
        "    def broken(:\n"
        "              ^\n"
        "SyntaxError: invalid syntax"
    )
    error_type, _ = classify_sandbox_error(stderr)
    assert error_type == "SyntaxError"


def test_unknown_error_type_falls_back_to_runtime_error():
    stderr = "Traceback (most recent call last):\n  File \"main.py\", line 3\nValueError: algo salió mal"
    error_type, message = classify_sandbox_error(stderr)
    assert error_type == "RuntimeError"
    assert "ValueError" in message


def test_empty_stderr_falls_back_to_runtime_error():
    error_type, message = classify_sandbox_error("")
    assert error_type == "RuntimeError"
    assert message  # no debe quedar vacío del todo, para que quede algo en el log


def test_classifies_static_validation_rejection_as_validation_error():
    """
    Bug real: esto caía en el fallback de RuntimeError, que se reintenta
    ciegamente (ver RuntimeErrorStrategy) — pero un rechazo del validador
    estático es determinista (el código ni llegó a ejecutarse), así que
    necesita su propia categoría que nunca reintenta (ValidationErrorStrategy).
    """
    stderr = "Validación estática falló: Import prohibido: os en línea 1"
    error_type, message = classify_sandbox_error(stderr)
    assert error_type == "ValidationError"
    assert "Import prohibido: os" in message


def test_validation_error_takes_priority_over_known_error_type_substrings():
    """
    Si el motivo de rechazo del validador menciona coincidentemente la
    palabra "SyntaxError" (p.ej. porque el propio validador detectó un
    error de sintaxis), debe seguir clasificando como ValidationError,
    no como SyntaxError — nunca llegó a ejecutarse, es el mismo caso
    determinista de "no tiene sentido reintentar".
    """
    stderr = "Validación estática falló: SyntaxError: invalid syntax"
    error_type, _ = classify_sandbox_error(stderr)
    assert error_type == "ValidationError"


def test_keyerror_and_other_builtin_exceptions_are_runtime_error():
    """
    No intentamos tener una estrategia por cada excepción built-in de
    Python — cualquier cosa fuera de las tres reconocidas explícitamente
    cae en RuntimeError como catch-all genérico.
    """
    for exc_name in ("KeyError", "TypeError", "ZeroDivisionError", "AttributeError"):
        stderr = f"Traceback (most recent call last):\n{exc_name}: detalle del error"
        error_type, _ = classify_sandbox_error(stderr)
        assert error_type == "RuntimeError", f"{exc_name} debería clasificar como RuntimeError"
