"""
Tests de los endpoints /settings/llm (agent_core/orchestrator.py).

El gate de token administrativo sobre POST ya se cubre en
tests/test_orchestrator_admin_auth.py — acá se prueba el contenido de
las respuestas y que un update exitoso reconstruye el cliente real y
lo re-inyecta en agent/planner/self_diagnosis (con
agent_core.llm_settings.update_llm_settings y
agent_core.orchestrator.build_llm_client mockeados: no se escribe en
el config.yaml/.env reales ni se construye un cliente de verdad).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from agent_core import orchestrator
from agent_core.llm_settings import LLMSettingsError
from agent_core.orchestrator import _ADMIN_TOKEN, app

client = TestClient(app)
_HEADERS = {"X-Kal-Admin-Token": _ADMIN_TOKEN}


def test_get_settings_reflects_module_state(monkeypatch):
    monkeypatch.setattr(
        orchestrator, "get_llm_settings",
        lambda: {"provider": "ollama", "base_url": "http://localhost:11434", "default_model": "qwen3-coder:30b", "has_api_key": False},
    )
    response = client.get("/settings/llm")
    assert response.status_code == 200
    assert response.json()["provider"] == "ollama"
    assert "api_key" not in response.json()


def test_post_maps_settings_error_to_400(monkeypatch):
    def _raise(**kwargs):
        raise LLMSettingsError("falta base_url")

    monkeypatch.setattr(orchestrator, "update_llm_settings", _raise)
    response = client.post("/settings/llm", json={"provider": "openai_compatible"}, headers=_HEADERS)
    assert response.status_code == 400
    assert response.json()["detail"] == "falta base_url"


def test_post_success_rebuilds_and_reinjects_the_client_everywhere(monkeypatch):
    # orchestrator.orchestrator es un singleton global compartido por
    # TODA la suite — sin restaurar, este test dejaría un objeto falso
    # instalado y rompería cualquier otro test que corra después en el
    # mismo proceso.
    real = orchestrator.orchestrator
    monkeypatch.setattr(real, "llm", real.llm)
    monkeypatch.setattr(real.agent, "llm", real.agent.llm)
    monkeypatch.setattr(real.planning_agent.planner, "llm", real.planning_agent.planner.llm)
    monkeypatch.setattr(real.self_diagnosis, "llm", real.self_diagnosis.llm)

    sentinel = object()
    monkeypatch.setattr(orchestrator, "update_llm_settings", lambda **kwargs: None)
    monkeypatch.setattr(orchestrator, "build_llm_client", lambda: sentinel)
    monkeypatch.setattr(
        orchestrator, "get_llm_settings",
        lambda: {"provider": "openai_compatible", "base_url": "https://api.x.ai/v1", "default_model": "grok-3", "has_api_key": True},
    )

    response = client.post(
        "/settings/llm",
        json={"provider": "openai_compatible", "base_url": "https://api.x.ai/v1", "api_key": "sk-test"},
        headers=_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["provider"] == "openai_compatible"
    # El mismo cliente (mockeado) queda inyectado en TODO lo que antes
    # tenía una referencia al viejo — sin esto, el cambio no tendría
    # efecto hasta reiniciar el proceso entero.
    assert orchestrator.orchestrator.llm is sentinel
    assert orchestrator.orchestrator.agent.llm is sentinel
    assert orchestrator.orchestrator.planning_agent.planner.llm is sentinel
    assert orchestrator.orchestrator.self_diagnosis.llm is sentinel


def test_list_local_ollama_models_endpoint_reflects_module_state(monkeypatch):
    monkeypatch.setattr(orchestrator, "list_local_ollama_models", lambda: ["qwen3-coder:30b", "llava:7b"])
    response = client.get("/settings/llm/ollama/models")
    assert response.status_code == 200
    assert response.json() == {"models": ["qwen3-coder:30b", "llava:7b"], "ollama_available": True}


def test_list_local_ollama_models_endpoint_degrades_gracefully_when_ollama_is_down(monkeypatch):
    def _raise():
        raise LLMSettingsError("no se pudo conectar")
    monkeypatch.setattr(orchestrator, "list_local_ollama_models", _raise)

    response = client.get("/settings/llm/ollama/models")

    assert response.status_code == 200  # Ollama caído es un estado real, no un 500
    assert response.json()["models"] == []
    assert response.json()["ollama_available"] is False


def test_pull_ollama_model_endpoint_success(monkeypatch):
    calls = []
    monkeypatch.setattr(orchestrator, "pull_ollama_model", lambda model: calls.append(model))

    response = client.post("/settings/llm/ollama/pull", json={"model": "qwen2.5-coder:14b"}, headers=_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"model": "qwen2.5-coder:14b", "status": "downloaded"}
    assert calls == ["qwen2.5-coder:14b"]


def test_pull_ollama_model_endpoint_maps_error_to_502(monkeypatch):
    def _raise(model):
        raise LLMSettingsError("no se pudo descargar")
    monkeypatch.setattr(orchestrator, "pull_ollama_model", _raise)

    response = client.post("/settings/llm/ollama/pull", json={"model": "no-existe"}, headers=_HEADERS)

    assert response.status_code == 502
    assert response.json()["detail"] == "no se pudo descargar"


def test_list_model_sources_endpoint_reflects_module_state(monkeypatch):
    monkeypatch.setattr(
        orchestrator, "list_model_sources",
        lambda: [{"name": "ollama", "label": "Local (Ollama)", "models": ["qwen3-coder:30b"]}],
    )
    response = client.get("/settings/llm/sources")
    assert response.status_code == 200
    assert response.json() == {"sources": [{"name": "ollama", "label": "Local (Ollama)", "models": ["qwen3-coder:30b"]}]}


def test_activate_profile_endpoint_success(monkeypatch):
    real = orchestrator.orchestrator
    monkeypatch.setattr(real, "llm", real.llm)
    monkeypatch.setattr(real.agent, "llm", real.agent.llm)
    monkeypatch.setattr(real.planning_agent.planner, "llm", real.planning_agent.planner.llm)
    monkeypatch.setattr(real.self_diagnosis, "llm", real.self_diagnosis.llm)

    calls = []
    sentinel = object()
    monkeypatch.setattr(orchestrator, "activate_cloud_profile", lambda name: calls.append(name))
    monkeypatch.setattr(orchestrator, "build_llm_client", lambda: sentinel)
    monkeypatch.setattr(
        orchestrator, "get_llm_settings",
        lambda: {"provider": "openai_compatible", "base_url": "https://api.groq.com/openai/v1", "default_model": "qwen3-coder:30b", "has_api_key": True},
    )

    response = client.post("/settings/llm/activate-profile", json={"name": "groq"}, headers=_HEADERS)

    assert response.status_code == 200
    assert calls == ["groq"]
    assert orchestrator.orchestrator.llm is sentinel


def test_activate_profile_endpoint_maps_error_to_400(monkeypatch):
    def _raise(name):
        raise LLMSettingsError(f"No existe un perfil guardado llamado '{name}'.")

    monkeypatch.setattr(orchestrator, "activate_cloud_profile", _raise)
    response = client.post("/settings/llm/activate-profile", json={"name": "no-existe"}, headers=_HEADERS)

    assert response.status_code == 400
    assert "no-existe" in response.json()["detail"]
