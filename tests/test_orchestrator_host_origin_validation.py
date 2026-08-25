"""
Tests de agent_core/orchestrator.py::TrustedHostMiddleware/_OriginValidationMiddleware.

Recomendación de una auditoría externa (2026-08-24, ver docs/HISTORY.md):
defensa en profundidad adicional, distinta de lo que ya protegía
/admin-token (request.client.host, no falsificable por un cliente
remoto — ver test_orchestrator_admin_auth.py) y distinta del SSRF del
agente (ya cerrado por kernel/permissions/network_safety.py::is_unsafe_ip).
Esto cubre el vector de una página de OTRO origen, en el mismo
navegador del usuario, intentando disparar pedidos contra localhost:8000.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from agent_core.orchestrator import app

client = TestClient(app, base_url="http://localhost")


def test_request_without_origin_header_is_allowed():
    """La mayoría de los clientes reales (VS Code vía Node, curl) nunca mandan Origin."""
    response = client.get("/health")
    assert response.status_code == 200


def test_request_with_allowed_origin_localhost_is_allowed():
    response = client.get("/health", headers={"Origin": "http://localhost:8000"})
    assert response.status_code == 200


def test_request_with_allowed_origin_loopback_ip_is_allowed():
    response = client.get("/health", headers={"Origin": "http://127.0.0.1:8000"})
    assert response.status_code == 200


def test_request_with_foreign_origin_is_rejected():
    """
    El caso real que esto previene: una pestaña abierta en otro sitio
    intentando disparar un fetch/POST contra localhost:8000.
    """
    response = client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert response.status_code == 403


def test_request_with_foreign_host_header_is_rejected():
    response = client.get("/health", headers={"Host": "evil.example.com"})
    assert response.status_code == 400


def test_request_with_allowed_host_header_is_allowed():
    response = client.get("/health", headers={"Host": "127.0.0.1"})
    assert response.status_code == 200
