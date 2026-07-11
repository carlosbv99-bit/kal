"""
Segundo LLMProvider real (agent_core/llm/provider.py) — no un stub.
Existe para validar que el contrato de F1 generaliza de verdad: este
cliente habla el formato OpenAI-compatible (respuesta envuelta en
"choices[].message", tool_calls con "arguments" siempre como string
JSON) en vez del formato nativo de Ollama (/api/chat, ver
ollama_client.py) — un wire format genuinamente distinto, no una
copia con otro nombre.

Por defecto apunta al propio endpoint OpenAI-compatible que Ollama ya
expone (`{base_url}/v1/chat/completions`, `/v1/models`) — el mismo
Ollama local que ya tenés corriendo, sin costo ni instalación nueva,
pero ejercitando un código de parseo completamente distinto. Con un
`base_url`/`api_key` apuntando a OpenAI real (o cualquier otro servicio
compatible: OpenRouter, vLLM, etc.) la misma clase sirve tal cual — no
hay nada específico de Ollama acá.
"""
from __future__ import annotations

import json
from typing import Any, Callable

import requests

from agent_core.llm.provider import ChatResponse, ProviderError, ToolCall
from utils.config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

PostFn = Callable[..., Any]
GetFn = Callable[..., Any]


class OpenAICompatibleError(ProviderError):
    """Error específico de OpenAICompatibleClient."""


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
        post_fn: PostFn | None = None,
        get_fn: GetFn | None = None,
    ):
        # Default: el endpoint OpenAI-compatible del propio Ollama local
        # (settings.llm.base_url ya apunta a Ollama) — ver docstring del
        # módulo. `post_fn`/`get_fn` inyectables para tests sin red real
        # (mismo patrón que AudioGenerationTool(http_post=...)).
        self.base_url = (base_url or f"{settings.llm.base_url}/v1").rstrip("/")
        self.api_key = api_key
        self.timeout = timeout or settings.llm.timeout_seconds
        self._post = post_fn or requests.post
        self._get = get_fn or requests.get

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        """
        POST {base_url}/chat/completions. Misma forma de `tools` que ya
        usa AgentTool.to_ollama_schema() (function-calling estilo
        OpenAI) — eso ya era compatible; lo que cambia de verdad acá es
        cómo se PARSEA la respuesta.
        """
        payload: dict[str, Any] = {
            "model": model or settings.llm.default_model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools

        try:
            response = self._post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise OpenAICompatibleError(
                f"No se pudo conectar a {self.base_url}. ¿El servicio está corriendo?"
            ) from e
        except requests.exceptions.Timeout as e:
            raise OpenAICompatibleError(
                f"{self.base_url} no respondió en {self.timeout}s"
            ) from e
        except requests.exceptions.HTTPError as e:
            raise OpenAICompatibleError(f"{self.base_url} devolvió un error HTTP: {e}") from e

        data = response.json()
        choices = data.get("choices") or []
        message = choices[0].get("message", {}) if choices else {}
        content = message.get("content") or ""

        tool_calls = []
        for raw_call in message.get("tool_calls", []) or []:
            function = raw_call.get("function", {})
            arguments = function.get("arguments", {})
            # A diferencia de Ollama (a veces objeto ya parseado), el
            # formato OpenAI manda "arguments" SIEMPRE como string JSON.
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    logger.warning(f"No se pudo parsear arguments de tool_call como JSON: {arguments!r}")
                    arguments = {}
            tool_calls.append(ToolCall(name=function.get("name", ""), arguments=arguments))

        return ChatResponse(content=content, tool_calls=tool_calls, raw=data)

    def list_models(self) -> list[str]:
        """Consulta GET {base_url}/models — formato {"data": [{"id": ...}, ...]}."""
        try:
            response = self._get(f"{self.base_url}/models", headers=self._headers(), timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise OpenAICompatibleError(f"No se pudo listar modelos de {self.base_url}: {e}") from e
        data = response.json()
        return [m["id"] for m in data.get("data", [])]

    def is_available(self) -> bool:
        try:
            response = self._get(f"{self.base_url}/models", headers=self._headers(), timeout=5)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException:
            return False
