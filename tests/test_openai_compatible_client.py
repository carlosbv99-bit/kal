"""
Tests de agent_core/llm/openai_compatible_client.py::OpenAICompatibleClient
— el segundo LLMProvider real que existe para validar que el contrato
de F1 (agent_core/llm/provider.py) generaliza de verdad. Sin red real:
`post_fn`/`get_fn` inyectados con respuestas guionadas (mismo patrón
que AudioGenerationTool(http_post=...) en test_audio_gen.py).

Respuesta real verificada contra Ollama corriendo de verdad (2026-07-09,
`qwen3-coder:30b` vía su endpoint /v1/chat/completions) para confirmar
que este formato ("choices"[0]."message") no es una suposición: es lo
que Ollama devuelve en la práctica.
"""
from __future__ import annotations

import pytest

from agent_core.llm.openai_compatible_client import OpenAICompatibleClient, OpenAICompatibleError
from agent_core.llm.provider import ProviderError


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")


def _client(post_fn=None, get_fn=None):
    return OpenAICompatibleClient(base_url="http://fake:1234/v1", post_fn=post_fn, get_fn=get_fn)


def test_chat_parses_content_from_choices_message():
    response = FakeResponse(
        {"choices": [{"message": {"role": "assistant", "content": "hola"}}]}
    )
    client = _client(post_fn=lambda *a, **kw: response)

    result = client.chat([{"role": "user", "content": "hola"}])

    assert result.content == "hola"
    assert result.tool_calls == []


def test_chat_parses_tool_calls_with_arguments_as_json_string():
    # Bug real que este test previene: a diferencia de Ollama (a veces
    # ya viene como dict), OpenAI-compatible SIEMPRE manda "arguments"
    # como un string JSON — si no se parsea, el dict de argumentos le
    # llegaría a AgentLoop como texto crudo en vez de kwargs utilizables.
    response = FakeResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "run_code", "arguments": '{"code": "print(1)"}'},
                            }
                        ],
                    }
                }
            ]
        }
    )
    client = _client(post_fn=lambda *a, **kw: response)

    result = client.chat([{"role": "user", "content": "ejecutá esto"}])

    assert result.has_tool_calls is True
    assert result.tool_calls[0].name == "run_code"
    assert result.tool_calls[0].arguments == {"code": "print(1)"}


def test_chat_raises_provider_error_on_connection_failure():
    import requests

    def broken_post(*a, **kw):
        raise requests.exceptions.ConnectionError("no conecta")

    client = _client(post_fn=broken_post)

    with pytest.raises(ProviderError):
        client.chat([{"role": "user", "content": "hola"}])


def test_list_models_parses_data_id_field():
    response = FakeResponse({"data": [{"id": "qwen3-coder:30b"}, {"id": "deepseek-r1:14b"}]})
    client = _client(get_fn=lambda *a, **kw: response)

    assert client.list_models() == ["qwen3-coder:30b", "deepseek-r1:14b"]


def test_is_available_true_when_get_succeeds():
    client = _client(get_fn=lambda *a, **kw: FakeResponse({"data": []}))
    assert client.is_available() is True


def test_is_available_false_when_get_fails():
    import requests

    def broken_get(*a, **kw):
        raise requests.exceptions.ConnectionError("no conecta")

    client = _client(get_fn=broken_get)
    assert client.is_available() is False


def test_openai_compatible_error_is_a_provider_error():
    assert issubclass(OpenAICompatibleError, ProviderError)
