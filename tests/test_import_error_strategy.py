"""
Tests unitarios de error_handling/strategies.py::ImportErrorStrategy.

Estos NO requieren Docker: prueban validación de nombres, extracción
del módulo faltante desde el mensaje de error, y el gate de aprobación
humana — que por diseño debe cortar ANTES de tocar el sandbox/runner.
El happy path real (instalar y reejecutar) sí requiere Docker y vive en
test_task_executor_sandboxed.py.
"""
from __future__ import annotations

import pytest

from error_handling.strategies import ImportErrorStrategy, RepairContext
from utils.config import settings


@pytest.mark.parametrize(
    "name,expected",
    [
        ("requests", True),
        ("scikit-learn", True),
        ("zope.interface", True),
        ("pkg_with_underscore", True),
        ("mal nombre", False),
        ("pkg; rm -rf /", False),
        ("", False),
        ("a" * 300, False),
    ],
)
def test_package_name_validation(name, expected):
    assert ImportErrorStrategy._is_valid_package_name(name) is expected


@pytest.mark.parametrize(
    "error_message,expected_module",
    [
        ("No module named 'requests'", "requests"),
        ("No module named 'a.b.c'", "a.b.c"),
        ("otro error cualquiera sin match", None),
    ],
)
def test_extract_module_name(error_message, expected_module):
    assert ImportErrorStrategy._extract_module_name(error_message) == expected_module


def test_default_config_requires_human_approval_for_network():
    """
    Confirma la postura de seguridad por defecto: instalar paquetes
    requiere red, y config.yaml trae "network" en
    require_human_approval_for por defecto. Si este test falla, alguien
    cambió el default de seguridad — debe ser una decisión consciente,
    no un accidente.
    """
    assert "network" in settings.tool_integration.require_human_approval_for


def test_repair_blocks_before_touching_runner_when_approval_required(monkeypatch):
    """
    El gate de aprobación debe cortar el flujo ANTES de invocar el
    runner del sandbox. Se confirma pasando un runner que rompería
    ruidosamente si se llegara a usar (AttributeError sobre None),
    para asegurar que el corte ocurre donde el código dice que ocurre.
    """
    monkeypatch.setattr(
        settings.tool_integration, "require_human_approval_for", ["network"]
    )

    class ExplodingRunner:
        def run(self, *args, **kwargs):
            raise AssertionError("el runner nunca debería invocarse con aprobación pendiente")

    strategy = ImportErrorStrategy(runner=ExplodingRunner())
    ctx = RepairContext(
        error_type="ImportError",
        error_message="No module named 'requests'",
        source_code="import requests",
        location="task:abc",
    )

    result = strategy.repair(ctx)

    assert result.success is False
    assert result.detail == "requiere_aprobacion_humana_para_acceso_de_red"


def test_repair_proceeds_when_network_not_in_approval_list(monkeypatch):
    """
    Con la config explícitamente relajada (decisión consciente del
    operador), el runner SÍ debe invocarse. Usa un runner falso para no
    requerir Docker en este test — la ejecución real contra Docker vive
    en test_task_executor_sandboxed.py.
    """
    monkeypatch.setattr(
        settings.tool_integration, "require_human_approval_for", ["filesystem_write"]
    )

    calls = []

    class FakeSandboxResult:
        status = "success"
        stdout = "ok"
        stderr = ""
        exit_code = 0

    class FakeRunner:
        def run(self, script, image=None, network_mode=None):
            calls.append({"script": script, "image": image, "network_mode": network_mode})
            return FakeSandboxResult()

    strategy = ImportErrorStrategy(runner=FakeRunner())
    ctx = RepairContext(
        error_type="ImportError",
        error_message="No module named 'requests'",
        source_code="import requests\nprint('ok')",
        location="task:abc",
    )

    result = strategy.repair(ctx)

    assert result.success is True
    assert result.already_retried is True
    assert result.output == "ok"
    assert len(calls) == 1
    assert calls[0]["network_mode"] == "bridge"
    assert "requests" in calls[0]["script"]
    assert "import requests" in calls[0]["script"]  # el código original va incluido


def test_invalid_package_name_never_reaches_runner(monkeypatch):
    monkeypatch.setattr(
        settings.tool_integration, "require_human_approval_for", ["filesystem_write"]
    )

    class ExplodingRunner:
        def run(self, *args, **kwargs):
            raise AssertionError("no debería llegar a invocarse con un nombre de paquete inválido")

    strategy = ImportErrorStrategy(runner=ExplodingRunner())
    ctx = RepairContext(
        error_type="ImportError",
        error_message="No module named 'pkg; rm -rf /'",
        source_code="x",
        location="task:abc",
    )

    result = strategy.repair(ctx)
    assert result.success is False
