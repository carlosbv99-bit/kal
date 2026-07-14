"""
Tests de los endpoints /integrations/vscode/* (agent_core/orchestrator.py).

El gate de token administrativo sobre POST /install ya se cubre en
tests/test_orchestrator_admin_auth.py — acá se prueba el contenido de
las respuestas, con agent_core.vscode_integration mockeado (no
corremos una instalación real desde la suite).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from agent_core import orchestrator
from agent_core.orchestrator import _ADMIN_TOKEN, app
from agent_core.vscode_integration import VSCodeIntegrationError

client = TestClient(app)
_HEADERS = {"X-Kal-Admin-Token": _ADMIN_TOKEN}


def test_status_reflects_module_state(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_vscode_status", lambda: {"code_cli_available": True, "installed": False})
    response = client.get("/integrations/vscode/status")
    assert response.status_code == 200
    assert response.json() == {"code_cli_available": True, "installed": False}


def test_install_returns_message_on_success(monkeypatch):
    monkeypatch.setattr(orchestrator, "install_extension", lambda: "Extensión de kal instalada en VS Code.")
    response = client.post("/integrations/vscode/install", headers=_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"message": "Extensión de kal instalada en VS Code."}


def test_install_maps_integration_error_to_500(monkeypatch):
    def _raise():
        raise VSCodeIntegrationError("npm no está instalado")

    monkeypatch.setattr(orchestrator, "install_extension", _raise)
    response = client.post("/integrations/vscode/install", headers=_HEADERS)
    assert response.status_code == 500
    assert response.json()["detail"] == "npm no está instalado"
