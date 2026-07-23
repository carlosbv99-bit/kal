"""
Tests de agent_core/conversation_engine.py — diseño "fail-open"
deliberado: classify() NUNCA lanza, cualquier falla (red, JSON
inválido, clave faltante, deshabilitado) devuelve None para que el
llamador (agent_core/routers/chat.py) siga con el flujo normal.
"""
from __future__ import annotations

from dataclasses import dataclass

from agent_core.conversation_engine import ConversationEngine
from agent_core.llm.provider import ProviderError
from utils.config import ConversationEngineConfig


@dataclass
class _FakeChatResponse:
    content: str


class _FakeLLMClient:
    """Doble mínimo — solo lo que ConversationEngine.classify() usa."""

    def __init__(self, content: str | None = None, raises: Exception | None = None):
        self._content = content
        self._raises = raises
        self.calls: list[dict] = []

    def chat(self, messages, model=None, response_format=None):
        self.calls.append({"messages": messages, "model": model, "response_format": response_format})
        if self._raises is not None:
            raise self._raises
        return _FakeChatResponse(content=self._content)


def _engine(content: str | None = None, raises: Exception | None = None, enabled: bool = True) -> tuple[ConversationEngine, _FakeLLMClient]:
    fake_llm = _FakeLLMClient(content=content, raises=raises)
    cfg = ConversationEngineConfig(enabled=enabled, model="qwen2.5:3b", confidence_threshold=0.5)
    return ConversationEngine(llm_client=fake_llm, cfg=cfg), fake_llm


def test_classify_parses_a_valid_response():
    engine, _ = _engine(content='{"intent": "crear_pagina_web", "confidence": 0.9, '
                                 '"required_capabilities": ["coding"], "user_reply": "Dale, arranco."}')

    result = engine.classify("Hacé una página web")

    assert result.intent == "crear_pagina_web"
    assert result.confidence == 0.9
    assert result.required_capabilities == ["coding"]
    assert result.user_reply == "Dale, arranco."


def test_classify_calls_the_llm_with_the_configured_model_and_json_format():
    engine, fake_llm = _engine(content='{"intent": "x", "confidence": 1.0, '
                                        '"required_capabilities": [], "user_reply": "y"}')

    engine.classify("hola")

    assert fake_llm.calls[0]["model"] == "qwen2.5:3b"
    assert fake_llm.calls[0]["response_format"] == "json"


def test_classify_defaults_required_capabilities_to_empty_list_when_absent():
    engine, _ = _engine(content='{"intent": "saludo", "confidence": 1.0, "user_reply": "Hola!"}')

    result = engine.classify("hola")

    assert result.required_capabilities == []


def test_classify_returns_none_when_disabled():
    engine, fake_llm = _engine(content="no debería llamarse", enabled=False)

    result = engine.classify("cualquier cosa")

    assert result is None
    assert fake_llm.calls == []


def test_classify_returns_none_on_provider_error():
    engine, _ = _engine(raises=ProviderError("Ollama no responde"))

    result = engine.classify("hola")

    assert result is None


def test_classify_returns_none_on_invalid_json():
    engine, _ = _engine(content="esto no es JSON")

    result = engine.classify("hola")

    assert result is None


def test_classify_returns_none_when_a_required_key_is_missing():
    engine, _ = _engine(content='{"intent": "x", "confidence": 0.9}')  # falta user_reply

    result = engine.classify("hola")

    assert result is None


def test_classify_returns_none_when_confidence_is_not_a_number():
    engine, _ = _engine(content='{"intent": "x", "confidence": "alta", '
                                 '"required_capabilities": [], "user_reply": "y"}')

    result = engine.classify("hola")

    assert result is None
