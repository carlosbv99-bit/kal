"""
Cliente HTTP mínimo para Ollama — una implementación de LLMProvider
(agent_core/llm/provider.py) entre varias posibles. El "cerebro" de kal
corre 100% local vía Ollama por defecto, nunca contra una API en la
nube (ver LLMConfig en utils/config.py: modelos ":cloud" como
glm-5.1:cloud deben seleccionarse explícitamente, nunca como default).

NOTA DE TRANSPARENCIA: no tengo forma de ejecutar Ollama en el entorno
donde escribo este código (sin red, sin el binario instalado). La
implementación sigue la API HTTP documentada de Ollama (/api/chat,
formato de tools estilo OpenAI) tal como la conozco, pero si tu versión
de Ollama difiere en el formato exacto de tool_calls o del mensaje de
resultado de herramienta (role="tool"), puede necesitar un ajuste menor
— avisar si el primer intento real falla, mismo patrón que tuvimos con
piper-tts y moviepy.

Esta llamada HTTP la hace el proceso principal del agente hacia un
servicio local (Ollama en localhost:11434), no código sandboxeado —
por eso no pasa por las restricciones de red del sandbox (ver
sandbox/docker_runner.py): es el propio agente usando un servicio local
de la máquina, igual que los adaptadores multimodales usan modelos
locales directamente.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable

import requests

from agent_core.llm.provider import ChatResponse, ProviderError, ToolCall
from kernel_bus.resource_broker import resource_broker as _default_resource_broker
from utils.config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

PostFn = Callable[..., Any]
GetFn = Callable[..., Any]
SleepFn = Callable[[float], None]


class OllamaError(ProviderError):
    """Error específico de OllamaClient. Subclase de ProviderError — el
    núcleo (agent_loop.py, planner.py, self_diagnosis.py) atrapa
    ProviderError, nunca este tipo directamente."""


class OllamaClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: int | None = None,
        connection_retries: int | None = None,
        retry_backoff_seconds: float | None = None,
        post_fn: PostFn | None = None,
        get_fn: GetFn | None = None,
        sleep_fn: SleepFn | None = None,
        resource_broker=None,
    ):
        self.base_url = (base_url or settings.llm.base_url).rstrip("/")
        self.timeout = timeout or settings.llm.timeout_seconds
        # BUG REAL ENCONTRADO EN USO: con generación de imagen/audio/video
        # corriendo en la misma máquina, Ollama puede quedar momentáneamente
        # sin responder (recargando el modelo en VRAM/RAM) y romper TODA la
        # tarea con un solo ConnectionError transitorio. Reintentar cubre ese
        # hueco real sin esconder una caída de verdad (no se reintenta en
        # Timeout: eso es una generación lenta, no una desconexión — ni en
        # HTTPError: eso es un error real del servidor, reintentar no ayuda).
        self.connection_retries = (
            connection_retries if connection_retries is not None else settings.llm.connection_retries
        )
        self.retry_backoff_seconds = (
            retry_backoff_seconds if retry_backoff_seconds is not None else settings.llm.retry_backoff_seconds
        )
        # post_fn/get_fn/sleep_fn inyectables para tests sin red real ni
        # esperas reales (mismo patrón que OpenAICompatibleClient).
        self._post = post_fn or requests.post
        self._get = get_fn or requests.get
        self._sleep = sleep_fn or time.sleep
        # inyectable para tests; el default real es el singleton
        # compartido de kernel_bus/resource_broker.py.
        self._resource_broker = resource_broker or _default_resource_broker

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        """
        Llama a POST /api/chat. `messages` sigue el formato
        {"role": "system"|"user"|"assistant"|"tool", "content": str}.
        `tools` sigue el formato de function-calling estilo OpenAI:
        [{"type": "function", "function": {"name", "description", "parameters"}}].
        """
        # Libera RAM de servicios multimedia inactivos ANTES de pedirle a
        # Ollama (local, misma RAM del sistema) que genere — ver
        # kernel_bus/resource_broker.py, bug real de contención de RAM.
        self._resource_broker.evict_idle_and_pressured()

        payload: dict[str, Any] = {
            "model": model or settings.llm.default_model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        response = self._post_with_retry(payload)
        data = response.json()
        message = data.get("message", {})
        content = message.get("content", "") or ""

        tool_calls = []
        for raw_call in message.get("tool_calls", []) or []:
            function = raw_call.get("function", {})
            arguments = function.get("arguments", {})
            # Defensivo: algunas versiones/modelos podrían devolver los
            # argumentos como string JSON en vez de objeto ya parseado.
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    logger.warning(f"No se pudo parsear arguments de tool_call como JSON: {arguments!r}")
                    arguments = {}
            tool_calls.append(ToolCall(name=function.get("name", ""), arguments=arguments, id=raw_call.get("id")))

        return ChatResponse(content=content, tool_calls=tool_calls, raw=data)

    def _post_with_retry(self, payload: dict[str, Any]):
        attempts = self.connection_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                response = self._post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
                response.raise_for_status()
                return response
            except requests.exceptions.ConnectionError as e:
                if attempt >= attempts:
                    raise OllamaError(
                        f"No se pudo conectar a Ollama en {self.base_url} tras {attempts} intentos. "
                        "¿Está corriendo? ('ollama serve' o el servicio del sistema)"
                    ) from e
                logger.warning(
                    f"Ollama no respondió (intento {attempt}/{attempts}), reintentando en "
                    f"{self.retry_backoff_seconds}s: {e}"
                )
                self._sleep(self.retry_backoff_seconds)
            except requests.exceptions.Timeout as e:
                raise OllamaError(
                    f"Ollama no respondió en {self.timeout}s (un modelo grande en CPU puede tardar; "
                    "subir llm.timeout_seconds en config.yaml si esto pasa seguido)"
                ) from e
            except requests.exceptions.HTTPError as e:
                raise OllamaError(f"Ollama devolvió un error HTTP: {e}") from e

    def list_models(self) -> list[str]:
        """Consulta GET /api/tags para listar modelos disponibles localmente."""
        try:
            response = self._get(f"{self.base_url}/api/tags", timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise OllamaError(f"No se pudo listar modelos de Ollama: {e}") from e
        data = response.json()
        return [m["name"] for m in data.get("models", [])]

    def is_available(self) -> bool:
        try:
            self._get(f"{self.base_url}/api/tags", timeout=5)
            return True
        except requests.exceptions.RequestException:
            return False
