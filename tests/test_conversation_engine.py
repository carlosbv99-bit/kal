"""
Tests de agent_core/conversation_engine.py — diseño "fail-open"
deliberado: classify() NUNCA lanza, cualquier falla (red, JSON
inválido, clave faltante, deshabilitado) devuelve None para que el
llamador (agent_core/routers/chat.py) siga con el flujo normal.
"""
from __future__ import annotations

from dataclasses import dataclass

from agent_core.conversation_engine import _RUNTIME_NAME, ConversationEngine
from agent_core.llm.ollama_client import OllamaClient
from agent_core.llm.openai_compatible_client import OpenAICompatibleClient
from agent_core.llm.provider import ProviderError
from agent_core.runtime.managed_provider import RuntimeManagedLLMProvider
from agent_core.runtime.manager import runtime_manager
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

    def chat(self, messages, model=None, response_format=None, temperature=None):
        self.calls.append({
            "messages": messages, "model": model, "response_format": response_format, "temperature": temperature,
        })
        if self._raises is not None:
            raise self._raises
        return _FakeChatResponse(content=self._content)


def _engine(content: str | None = None, raises: Exception | None = None, enabled: bool = True) -> tuple[ConversationEngine, _FakeLLMClient]:
    fake_llm = _FakeLLMClient(content=content, raises=raises)
    cfg = ConversationEngineConfig(enabled=enabled, model="qwen2.5:3b", confidence_threshold=0.5, temperature=0.1)
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


def test_classify_uses_the_configured_low_temperature():
    """
    BUG REAL ENCONTRADO EN USO (2026-07-25): sin fijar temperature, el
    mismo pedido exacto ("crea una naranja") devolvía confidence=0.9 en
    una llamada y <0.5 en la siguiente — no determinístico, cruzaba
    confidence_threshold al azar. Confirmar que se pasa el temperature
    configurado (bajo) en vez de dejar el default alto de Ollama.
    """
    engine, fake_llm = _engine(content='{"intent": "x", "confidence": 1.0, '
                                        '"required_capabilities": [], "user_reply": "y"}')

    engine.classify("crea una naranja")

    assert fake_llm.calls[0]["temperature"] == 0.1


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


class TestDefaultClientGoesThroughTheRuntimeManager:
    """
    Antes ConversationEngine() (sin llm_client explícito) instanciaba
    OllamaClient directo, asumiendo que el backend local SIEMPRE habla
    el formato nativo de Ollama. Ahora pasa por el mismo Runtime Manager
    que agent_core.orchestrator.build_llm_client() usa para el chat
    principal, pero en un slot PROPIO (_RUNTIME_NAME), para no terminar
    apuntando a un proveedor en la nube si el usuario elige eso para el
    trabajo pesado — este modelo tiene que seguir siendo local siempre.
    """

    def test_default_provider_registers_an_ollama_runtime_pointed_at_the_configured_base_url(self):
        cfg = ConversationEngineConfig(base_url="http://localhost:11434", model="qwen2.5:3b")

        engine = ConversationEngine(cfg=cfg)

        assert isinstance(engine.llm_client, RuntimeManagedLLMProvider)
        real_client = runtime_manager.get_runtime(_RUNTIME_NAME).client
        assert isinstance(real_client, OllamaClient)
        assert real_client.base_url == "http://localhost:11434"

    def test_openai_compatible_provider_registers_a_client_pointed_at_the_configured_local_backend(self):
        cfg = ConversationEngineConfig(
            provider="openai_compatible", base_url="http://localhost:1234/v1", model="algun-modelo",
        )

        engine = ConversationEngine(cfg=cfg)

        assert isinstance(engine.llm_client, RuntimeManagedLLMProvider)
        real_client = runtime_manager.get_runtime(_RUNTIME_NAME).client
        assert isinstance(real_client, OpenAICompatibleClient)
        assert real_client.base_url == "http://localhost:1234/v1"

    def test_openai_compatible_provider_never_requires_an_api_key(self):
        # A diferencia de LLMConfig.provider (build_llm_client() falla
        # cerrado sin LLM_API_KEY), acá es un backend LOCAL — la mayoría
        # no exige autenticación, así que nunca debe fallar por esto.
        cfg = ConversationEngineConfig(provider="openai_compatible", base_url="http://localhost:1234/v1")

        engine = ConversationEngine(cfg=cfg)  # no debe lanzar

        assert isinstance(engine.llm_client, RuntimeManagedLLMProvider)
