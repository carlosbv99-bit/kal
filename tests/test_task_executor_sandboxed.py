"""
Tests de integración end-to-end de task_execution/executor.py::run_sandboxed
contra Docker real. Esto es la prueba definitiva de que "auto-reparación"
funciona como sistema completo, no solo como piezas unitarias sueltas.

Usa el paquete "six" como dependencia de prueba porque es diminuto
(un solo archivo, sin dependencias propias) y estable en PyPI — no
importa si en algún momento deja de existir, cualquier paquete pequeño
y real serviría igual.
"""
from __future__ import annotations

import pytest

from agent_core.memory.mid_term import MidTermMemory
from task_execution.executor import TaskExecutor
from task_execution.task import TaskStatus
from tests.conftest import requires_docker
from utils.config import settings

pytestmark = requires_docker


@pytest.fixture
def executor(tmp_path):
    return TaskExecutor(mid_term=MidTermMemory(db_path=tmp_path / "executor_test.db"))


def test_successful_code_runs_without_repair(executor):
    task = executor.submit("código simple sin errores")
    result = executor.run_sandboxed(task, "print('hola desde kal')")

    assert result.status == TaskStatus.SUCCESS
    assert "hola desde kal" in result.result


def test_import_error_blocked_by_default_human_approval_gate(executor):
    """
    Con la config por defecto (network requiere aprobación
    humana), el ImportError NO debe repararse automáticamente — debe
    quedar en FAILED, no en SUCCESS. Este es el comportamiento correcto
    por diseño: instalar paquetes con red es una acción sensible.
    """
    assert "network" in settings.tool_integration.require_human_approval_for

    task = executor.submit("importa un paquete faltante")
    result = executor.run_sandboxed(task, "import six\nprint(six.__name__)")

    assert result.status == TaskStatus.FAILED
    assert result.error  # debe quedar registrado el motivo del fallo


def test_import_error_auto_repaired_when_network_approved(executor, monkeypatch):
    """
    El happy path completo: con la config relajada explícitamente
    (decisión consciente, ver test anterior para el comportamiento por
    defecto), un ImportError de un paquete real e instalable debe
    resultar en SUCCESS tras la auto-reparación.

    Requiere red saliente real desde el host para instalar "six" desde
    PyPI dentro del contenedor efímero.
    """
    monkeypatch.setattr(
        settings.tool_integration, "require_human_approval_for", ["filesystem_write"]
    )

    task = executor.submit("importa un paquete faltante, con aprobación de red")
    result = executor.run_sandboxed(task, "import six\nprint('six version:', six.__version__)")

    assert result.status == TaskStatus.SUCCESS
    assert "six version" in result.result


def test_non_installable_or_nonexistent_package_fails_gracefully(executor, monkeypatch):
    """
    Un nombre de paquete que no existe en PyPI debe fallar limpiamente
    (FAILED), no colgar el sistema ni lanzar una excepción no manejada.
    """
    monkeypatch.setattr(
        settings.tool_integration, "require_human_approval_for", ["filesystem_write"]
    )

    task = executor.submit("importa un paquete que no existe")
    result = executor.run_sandboxed(
        task, "import paquete_que_definitivamente_no_existe_en_pypi_12345\nprint('no debería llegar aquí')"
    )

    assert result.status == TaskStatus.FAILED


def test_runtime_error_without_checkpoint_fails_without_infinite_retry(executor):
    """
    Un RuntimeError genuino (no ImportError) sin checkpoint previo debe
    fallar de forma acotada, no reintentar indefinidamente. Confirma
    que el ciclo completo respeta el límite de max_retries incluso
    cuando la estrategia no encuentra nada que reparar.
    """
    task = executor.submit("código que falla en runtime")
    result = executor.run_sandboxed(task, "raise ValueError('fallo intencional')", max_retries=2)

    assert result.status == TaskStatus.FAILED
    assert "ValueError" in result.error


def test_validation_rejection_fails_once_without_burning_circuit_breaker_attempts(executor):
    """
    Bug real encontrado en uso: código rechazado por el validador
    estático (p.ej. un import prohibido) se clasificaba como
    RuntimeError, que SÍ se reintenta ciegamente — una sola llamada a
    run_sandboxed() con max_retries=2 terminaba recorriendo 3 intentos
    idénticos (siempre el mismo rechazo, nunca iba a cambiar) y podía
    abrir el circuit breaker de una sola vez. Con ValidationErrorStrategy
    (nunca reintenta), un código rechazado por el validador debe fallar
    de inmediato en el primer intento, sin abrir ningún circuito nuevo.
    """
    from error_handling.circuit_breaker import circuit_breaker

    open_before = circuit_breaker.open_circuit_count()

    task = executor.submit("código con import prohibido")
    result = executor.run_sandboxed(task, "import os\nos.system('ls')")

    assert result.status == TaskStatus.FAILED
    assert "Validación estática falló" in result.error
    assert circuit_breaker.open_circuit_count() == open_before, (
        "un solo rechazo de validación no debería abrir ningún circuito nuevo "
        "(antes del fix, se reintentaba 3 veces el mismo código rechazado)"
    )


def test_circuit_breaker_opens_after_repeated_identical_failures(executor):
    """
    Reutiliza la MISMA tarea (mismo task.id -> misma location -> misma
    firma de error) en cada invocación, simulando que algo externo
    sigue reintentando esta tarea específica tras cada fallo. Con
    max_retries=0 en cada llamada, cada invocación cuenta como un
    intento distinto ante el circuit breaker, que debería abrir tras
    max_repair_attempts (3 por defecto) y escalar a humano.
    """
    task = executor.submit("tarea que siempre falla igual")
    statuses = []
    for _ in range(6):
        result = executor.run_sandboxed(task, "raise RuntimeError('siempre el mismo fallo')", max_retries=0)
        statuses.append(result.status)

    assert TaskStatus.ESCALATED in statuses, f"el circuit breaker debería haber escalado; estados: {statuses}"
