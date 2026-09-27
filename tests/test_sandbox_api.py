"""
Tests de kernel/api/sandbox_api.py — el servicio HTTP interno que
ejecuta código dentro del sandbox.

VULNERABILIDAD REAL ENCONTRADA EN AUDITORÍA EXTERNA (C-3, 2026-09-26):
/execute no tenía NINGUNA autenticación ni límite de tamaño de body.
Estos tests cubren el fix: fail-closed sin token configurado, rechazo
de token incorrecto/ausente/no-ASCII (sin 500, ver M-6), y rechazo de
un body más grande que el límite.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from kernel.lifecycle.docker_runner import SandboxResult


class _FakeRunner:
    """Doble de prueba: nunca toca Docker real."""

    def run(self, source_code, **kwargs):
        return SandboxResult(status="success", stdout="ok", stderr="", exit_code=0)


@pytest.fixture
def sandbox_api_module(monkeypatch):
    """
    Recarga el módulo con SANDBOX_API_TOKEN ya seteado en el entorno
    ANTES del import — el módulo lo lee una sola vez, a nivel de
    módulo, al arrancar (mismo patrón que SANDBOX_IMAGE en
    docker_runner.py).
    """
    monkeypatch.setenv("SANDBOX_API_TOKEN", "el-secreto-correcto")
    import kernel.api.sandbox_api as mod

    importlib.reload(mod)
    mod.executor.runner = _FakeRunner()
    yield mod
    monkeypatch.delenv("SANDBOX_API_TOKEN", raising=False)
    importlib.reload(mod)


@pytest.fixture
def client(sandbox_api_module):
    return TestClient(sandbox_api_module.app)


def test_health_needs_no_token(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_execute_without_token_is_rejected(client):
    response = client.post("/execute", json={"source_code": "print('hola')"})
    assert response.status_code == 401


def test_execute_with_wrong_token_is_rejected(client):
    response = client.post(
        "/execute", json={"source_code": "print('hola')"}, headers={"x-sandbox-token": "incorrecto"}
    )
    assert response.status_code == 401


def test_execute_with_correct_token_succeeds(client):
    response = client.post(
        "/execute",
        json={"source_code": "print('hola')"},
        headers={"x-sandbox-token": "el-secreto-correcto"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_non_ascii_token_is_rejected_without_a_500(sandbox_api_module):
    """
    M-6 (mismo informe): secrets.compare_digest con un string no-ASCII
    lanza TypeError si se compara directo — acá se compara como bytes,
    así que debe rechazarse limpio, nunca con una excepción sin atrapar.

    Prueba `_verify_token` directo, sin pasar por TestClient/httpx2:
    la librería cliente rechaza de por sí mandar un header no-ASCII
    (ValueError/UnicodeEncodeError del lado cliente), pero un cliente
    crudo/adversarial que arme el request a mano no tiene esa
    restricción — ASGI trata los headers como bytes, y Starlette los
    decodifica como latin-1, así que un byte no-ASCII SÍ puede llegar
    acá como un str con caracteres no-ASCII.
    """
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        sandbox_api_module._verify_token(x_sandbox_token="tóken-ñoño")

    assert exc_info.value.status_code == 401


def test_execute_rejected_when_token_env_var_is_not_configured(monkeypatch):
    """Fail-closed: sin SANDBOX_API_TOKEN en el entorno, todo pedido se
    rechaza — nunca "abierto por default" por un despliegue que se
    olvidó de configurar el secreto."""
    monkeypatch.delenv("SANDBOX_API_TOKEN", raising=False)
    import kernel.api.sandbox_api as mod

    importlib.reload(mod)
    mod.executor.runner = _FakeRunner()
    unauthenticated_client = TestClient(mod.app)

    response = unauthenticated_client.post(
        "/execute", json={"source_code": "print('hola')"}, headers={"x-sandbox-token": "cualquier-cosa"}
    )

    assert response.status_code == 401
    importlib.reload(mod)


def test_execute_rejects_a_body_larger_than_the_limit(client, sandbox_api_module):
    huge_source = "x" * (sandbox_api_module._MAX_BODY_BYTES + 1)
    response = client.post(
        "/execute",
        json={"source_code": huge_source},
        headers={"x-sandbox-token": "el-secreto-correcto"},
    )
    assert response.status_code == 413
