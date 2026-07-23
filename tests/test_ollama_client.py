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


class FakeResourceBroker:
    """Doble de kernel/broker/resource_broker.py::ResourceBroker — solo
    cuenta llamadas, sin recursos reales ni psutil."""

    def __init__(self):
        self.evict_calls = 0

    def evict_idle_and_pressured(self):
        self.evict_calls += 1


def _client(post_fn=None, get_fn=None, sleep_fn=None, connection_retries=2, resource_broker=None):
    return OllamaClient(
        post_fn=post_fn,
        get_fn=get_fn,
        sleep_fn=sleep_fn or (lambda seconds: None),  # nunca dormir de verdad en tests
        connection_retries=connection_retries,
        resource_broker=resource_broker or FakeResourceBroker(),
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


def test_chat_sends_format_in_payload_when_response_format_is_given():
    # Usado por agent_core/conversation_engine.py para forzar que Ollama
    # devuelva JSON válido en message.content — ver ConversationEngine.
    captured = {}

    def post_fn(url, json=None, **kw):
        captured["payload"] = json
        return FakeResponse({"message": {"content": "{}"}})

    client = _client(post_fn=post_fn)
    client.chat([{"role": "user", "content": "hola"}], response_format="json")

    assert captured["payload"]["format"] == "json"


def test_chat_omits_format_from_payload_by_default():
    captured = {}

    def post_fn(url, json=None, **kw):
        captured["payload"] = json
        return FakeResponse({"message": {"content": "hola"}})

    client = _client(post_fn=post_fn)
    client.chat([{"role": "user", "content": "hola"}])

    assert "format" not in captured["payload"]


def test_chat_parses_tool_call_id_when_present():
    # BUG REAL ENCONTRADO EN USO: Groq (a diferencia de Ollama) valida
    # ESTRICTO el formato OpenAI y exige un 'id' por tool_call para
    # correlacionar la respuesta de la herramienta con la llamada que
    # la originó — sin propagarlo acá, agent_loop.py no tenía de dónde
    # sacarlo para providers estrictos.
    response = FakeResponse(
        {
            "message": {
                "content": "",
                "tool_calls": [
                    {"id": "call_abc", "function": {"name": "run_code", "arguments": {"code": "print(1)"}}}
                ],
            }
        }
    )
    client = _client(post_fn=lambda *a, **kw: response)

    result = client.chat([{"role": "user", "content": "ejecutá esto"}])

    assert result.tool_calls[0].id == "call_abc"


def test_chat_parses_tool_call_without_id_as_none():
    """Ollama no siempre manda 'id' — no debe romper el parseo."""
    response = FakeResponse(
        {"message": {"content": "", "tool_calls": [{"function": {"name": "run_code", "arguments": {}}}]}}
    )
    client = _client(post_fn=lambda *a, **kw: response)

    result = client.chat([{"role": "user", "content": "ejecutá esto"}])

    assert result.tool_calls[0].id is None


def test_chat_evicts_idle_resources_before_calling_ollama():
    """BUG REAL ENCONTRADO EN USO: sin esto, un pipeline de imagen/audio
    de varios GB se queda en RAM para siempre, compitiendo con Ollama
    por la misma RAM del sistema (confirmado: Ollama quedaba con
    "Connection refused" justo después de generar una imagen). Ver
    kernel/broker/resource_broker.py."""

    def post_fn(*a, **kw):
        return FakeResponse({"message": {"content": "hola"}})

    broker = FakeResourceBroker()
    client = _client(post_fn=post_fn, resource_broker=broker)

    client.chat([{"role": "user", "content": "hola"}])

    assert broker.evict_calls == 1


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


def test_chat_attaches_images_to_last_message():
    """Formato de /api/chat de Ollama para modelos de visión
    (llama3.2-vision): 'images' es una lista de base64 en el mensaje,
    no un campo separado del payload."""
    payloads = []

    def post_fn(url, json, **kw):
        payloads.append(json)
        return FakeResponse({"message": {"content": "una foto de un gato"}})

    client = _client(post_fn=post_fn)
    client.chat(
        [{"role": "user", "content": "¿qué hay en esta imagen?"}],
        model="llama3.2-vision:latest",
        images=["ZmFrZWJhc2U2NA=="],
    )

    assert payloads[0]["messages"][-1]["images"] == ["ZmFrZWJhc2U2NA=="]
    assert payloads[0]["messages"][-1]["content"] == "¿qué hay en esta imagen?"


def test_chat_without_images_does_not_add_the_key():
    payloads = []

    def post_fn(url, json, **kw):
        payloads.append(json)
        return FakeResponse({"message": {"content": "hola"}})

    client = _client(post_fn=post_fn)
    client.chat([{"role": "user", "content": "hola"}])

    assert "images" not in payloads[0]["messages"][-1]


def test_chat_with_images_does_not_mutate_caller_messages():
    original_messages = [{"role": "user", "content": "hola"}]
    client = _client(post_fn=lambda *a, **kw: FakeResponse({"message": {"content": "ok"}}))

    client.chat(original_messages, images=["abc"])

    assert "images" not in original_messages[0]
