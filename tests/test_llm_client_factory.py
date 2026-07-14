"""
Tests de agent_core/orchestrator.py::build_llm_client() — kal se
distribuye a usuarios con hardware muy distinto (no es un proyecto de
uso personal, ver docs/HISTORY.md), así que el LLM real no puede
quedar hardcodeado a Ollama local: provider: openai_compatible deja
apuntar a cualquier API compatible con OpenAI (Qwen, Grok/xAI, OpenAI,
OpenRouter...).
"""
from __future__ import annotations

import pytest

import agent_core.llm_settings as llm_settings
from agent_core.llm.ollama_client import OllamaClient
from agent_core.llm.openai_compatible_client import OpenAICompatibleClient
from agent_core.orchestrator import build_llm_client
from utils.config import settings


@pytest.fixture(autouse=True)
def _isolate_env_file(tmp_path, monkeypatch):
    # BUG REAL ENCONTRADO EN USO: build_llm_client() lee LLM_API_KEY vía
    # read_llm_env_var() (agent_core/llm_settings.py), que SIEMPRE
    # prefiere el .env real del proyecto en disco por sobre os.environ
    # (ver docs/HISTORY.md, sección "os.environ obsoleto") — necesario
    # para no confiar en un os.environ potencialmente viejo, pero sin
    # esto estos tests quedaban enmascarados por lo que hubiera en el
    # .env real del proyecto, ignorando monkeypatch.setenv/delenv por
    # completo. Redirigir a un archivo que no existe hace que
    # read_llm_env_var() caiga a os.environ, como esperan estos tests.
    monkeypatch.setattr(llm_settings, "_ENV_PATH", tmp_path / ".env")


def test_default_provider_builds_ollama_client(monkeypatch):
    monkeypatch.setattr(settings.llm, "provider", "ollama")
    client = build_llm_client()
    assert isinstance(client, OllamaClient)


def test_openai_compatible_provider_without_api_key_fails_closed(monkeypatch):
    monkeypatch.setattr(settings.llm, "provider", "openai_compatible")
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="LLM_API_KEY no configurada"):
        build_llm_client()


def test_openai_compatible_provider_with_api_key_builds_client_pointed_at_configured_url(monkeypatch):
    monkeypatch.setattr(settings.llm, "provider", "openai_compatible")
    monkeypatch.setattr(settings.llm, "base_url", "https://api.x.ai/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key-123")

    client = build_llm_client()

    assert isinstance(client, OpenAICompatibleClient)
    assert client.base_url == "https://api.x.ai/v1"
    assert client.api_key == "test-key-123"
