"""
Test de integración REAL de OpenAICompatibleClient contra Ollama
corriendo de verdad (no mockeado) — la prueba definitiva de que el
segundo LLMProvider de F2 no es solo una teoría de wire format, sino
que interopera con un servicio real. Se salta si Ollama no está
disponible en este entorno (mismo criterio que requires_docker en
conftest.py para los tests de sandbox).
"""
from __future__ import annotations

import pytest
import requests

from agent_core.llm.openai_compatible_client import OpenAICompatibleClient
from utils.config import settings


def _ollama_openai_endpoint_available() -> bool:
    try:
        response = requests.get(f"{settings.llm.base_url}/v1/models", timeout=3)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


requires_ollama_openai_endpoint = pytest.mark.skipif(
    not _ollama_openai_endpoint_available(),
    reason="Ollama no disponible o sin endpoint /v1 en este entorno",
)


@requires_ollama_openai_endpoint
def test_real_chat_round_trip_against_running_ollama():
    client = OpenAICompatibleClient()

    result = client.chat([{"role": "user", "content": "Respondé solo con la palabra: listo"}])

    assert result.content.strip() != ""


@requires_ollama_openai_endpoint
def test_real_list_models_against_running_ollama():
    client = OpenAICompatibleClient()

    models = client.list_models()

    assert isinstance(models, list)
    assert len(models) > 0


@requires_ollama_openai_endpoint
def test_real_is_available_true_against_running_ollama():
    assert OpenAICompatibleClient().is_available() is True
