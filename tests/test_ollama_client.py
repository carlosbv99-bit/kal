"""
Tests de agent_core/llm/ollama_client.py::OllamaClient — en particular el
reintento ante ConnectionError transitorio (bug real: con generación de
imagen/audio/video corriendo en la misma máquina, Ollama puede quedar
momentáneamente sin responder y romper toda la tarea con un solo
ConnectionError, aunque esté bien un segundo antes y un segundo después).
Sin red real: `post_fn`/`get_fn`/`sleep_fn` inyectados (mismo patrón que
test_openai_compatible_client.py).
"""
from __future__ import annotations

import pytest
import requests

from agent_core.llm.ollama_client import OllamaClient, OllamaError
from agent_core.llm.provider import ProviderError


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"status {self.status_code}")


def _client(post_fn=None, get_fn=None, sleep_fn=None, connection_retries=2):
    return OllamaClient(
        post_fn=post_fn,
        get_fn=get_fn,
        sleep_fn=sleep_fn or (lambda seconds: None),  # nunca dormir de verdad en tests
        connection_retries=connection_retries,
    )


def test_chat_succeeds_on_first_try_without_retrying():
    calls = []

    def post_fn(*a, **kw):
        calls.append(1)
        return FakeResponse({"message": {"content": "hola"}})

    client = _client(post_fn=post_fn)
    result = client.chat([{"role": "user", "content": "hola"}])

    assert result.content == "hola"
    assert len(calls) == 1


def test_chat_retries_on_transient_connection_error_then_succeeds():
    attempts = {"n": 0}

    def post_fn(*a, **kw):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise requests.exceptions.ConnectionError("ollama recargando el modelo")
        return FakeResponse({"message": {"content": "ya volvió"}})

    slept = []
    client = _client(post_fn=post_fn, sleep_fn=lambda s: slept.append(s), connection_retries=2)

    result = client.chat([{"role": "user", "content": "hola"}])

    assert result.content == "ya volvió"
    assert attempts["n"] == 3  # 2 fallos + 1 éxito
    assert len(slept) == 2  # una pausa antes de cada reintento


def test_chat_raises_after_exhausting_retries_on_connection_error():
    def broken_post(*a, **kw):
        raise requests.exceptions.ConnectionError("no conecta")

    client = _client(post_fn=broken_post, connection_retries=2)

    with pytest.raises(ProviderError):
        client.chat([{"role": "user", "content": "hola"}])


def test_chat_does_not_retry_on_timeout():
    """Un timeout es una generación lenta, no una desconexión — reintentar
    solo duplicaría la espera de algo que ya sabemos que tarda."""
    calls = []

    def slow_post(*a, **kw):
        calls.append(1)
        raise requests.exceptions.Timeout("tardó demasiado")

    client = _client(post_fn=slow_post, connection_retries=2)

    with pytest.raises(OllamaError):
        client.chat([{"role": "user", "content": "hola"}])
    assert len(calls) == 1


def test_chat_does_not_retry_on_http_error():
    def bad_status_post(*a, **kw):
        return FakeResponse({}, status_code=500)

    client = _client(post_fn=bad_status_post, connection_retries=2)

    with pytest.raises(OllamaError):
        client.chat([{"role": "user", "content": "hola"}])


def test_list_models_uses_injected_get_fn():
    client = _client(get_fn=lambda *a, **kw: FakeResponse({"models": [{"name": "qwen3-coder:30b"}]}))
    assert client.list_models() == ["qwen3-coder:30b"]


def test_is_available_false_on_connection_error():
    def broken_get(*a, **kw):
        raise requests.exceptions.ConnectionError("no conecta")

    client = _client(get_fn=broken_get)
    assert client.is_available() is False
