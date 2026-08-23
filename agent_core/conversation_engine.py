"""
Conversation Engine: primer paso opcional de /chat, ANTES del
planner/agent_loop completo — un modelo CHICO y siempre local (nunca
el proveedor configurable de llm.*, ver utils/config.py::
ConversationEngineConfig) clasifica la intención del pedido y decide
si hace falta correr el pipeline pesado, o si conviene responder de
inmediato con una aclaración.

Visión del usuario (2026-07-21): el modelo residente nunca debería
competir con los modelos grandes ni resolver el pedido él mismo — solo
entiende QUÉ quiere el usuario y qué CAPACIDADES hacen falta,
delegando el trabajo real al pipeline existente (por ahora) o a un
futuro Capability Broker (todavía no construido — ver
project_kernel_provider_pivot en la memoria del proyecto, sin ningún
caso real que lo justifique hoy).

Validado empíricamente (script standalone, no en este repo) contra
qwen2.5:3b, gemma3:4b y llama3.2:3b sobre 15 pedidos reales variados:
qwen2.5:3b fue el más confiable (formato JSON 15/15 en ambas rondas,
sin regresiones tras ajustar el prompt) — es el default de
ConversationEngineConfig.model.

Diseño "fail-open" deliberado: `classify()` NUNCA lanza — cualquier
falla (red, JSON inválido, clave faltante, clasificador deshabilitado)
devuelve None, y el llamador (agent_core/routers/chat.py) sigue con el
flujo normal como si esto no existiera. El Conversation Engine es una
optimización de UX/cómputo (responder rápido ante un pedido ambiguo
sin correr el agente completo), nunca un gate que pueda romper un
pedido real.
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass

from agent_core.llm.ollama_client import OllamaClient
from agent_core.llm.openai_compatible_client import OpenAICompatibleClient
from agent_core.llm.provider import LLMProvider, ProviderError
from agent_core.runtime.llm_runtimes import OllamaRuntime, OpenAICompatibleRuntime
from agent_core.runtime.managed_provider import RuntimeManagedLLMProvider
from agent_core.runtime.manager import runtime_manager
from utils.config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# Nombre fijo bajo el que se registra el runtime local del Conversation
# Engine en runtime_manager (agent_core/runtime/manager.py) — un slot
# PROPIO, separado de _ACTIVE_RUNTIME_NAME en agent_core/orchestrator.py:
# ese otro puede terminar apuntando a un proveedor en la nube si el
# usuario lo elige para el chat principal, pero este modelo tiene que
# seguir siendo chico y local siempre (ver docstring del módulo).
_RUNTIME_NAME = "conversation_engine"

_SYSTEM_PROMPT = """Sos el "Conversation Engine" de kal, un asistente de IA. Tu único trabajo es \
entender la intención del usuario y decidir qué capacidades del sistema hacen falta para \
responderle — NUNCA resolvés el pedido vos mismo, NUNCA generás código/imágenes/texto largo.

Capacidades posibles, con su significado EXACTO (no lo adivines, usá esta definición):
- "coding": el usuario quiere que se CREE algo (una página web, una app, un script, un programa). \
"Hacé una página web" es SIEMPRE coding, nunca web-browsing, aunque diga "web".
- "web-browsing": el usuario quiere BUSCAR o CONSULTAR información que ya existe en internet \
(una noticia, un dato, un precio). Nunca uses esto si el pedido es CREAR algo nuevo.
- "text-to-speech": el usuario tiene TEXTO y quiere que se convierta en AUDIO (texto → audio). \
Ejemplos: "leeme esto en voz alta", "convertí este texto en audio".
- "speech-to-text": el usuario tiene un AUDIO ya existente y quiere que se convierta en TEXTO \
(audio → texto). Ejemplos: "transcribí este audio", "qué dice esta grabación". \
NUNCA uses speech-to-text si el pedido es al revés (texto a audio) — son direcciones opuestas, \
usá solo UNA de las dos salvo que el pedido pida EXPLÍCITAMENTE ambas direcciones.
- "image-generation": crear una imagen nueva desde cero (a partir de una descripción). "Creá una \
naranja"/"hacé un gato"/"generá una torta" son SIEMPRE image-generation (crear una IMAGEN de eso), \
NUNCA "conversation" ni un rechazo tipo "no puedo crear un objeto físico" — nadie te está pidiendo \
el objeto real, te están pidiendo una imagen de él. BUG REAL ENCONTRADO EN USO: "crea una naranja" \
se clasificó como intent="conversation" con user_reply "no puedo crear una naranja" — mal, tenía \
que ser image-generation.
- "image-editing": modificar una imagen YA EXISTENTE (fondo, recorte, colores).
- "vision": describir o analizar el CONTENIDO de una imagen ya existente.
- "video": crear o editar un video — nunca uses image-editing para un pedido sobre VIDEO.
- "conversation": charla simple, sin ninguna tarea especial (saludos, preguntas generales, \
pedir aclaración).

Respondé ÚNICAMENTE con un objeto JSON, sin texto antes ni después, con EXACTAMENTE esta forma:
{
  "intent": "string corto en snake_case describiendo la intención",
  "confidence": 0.0 a 1.0 (qué tan seguro estás de haber entendido el pedido),
  "required_capabilities": ["lista de 0 o más capacidades de la lista de arriba"],
  "user_reply": "una frase corta en español que le dirías al usuario mientras arranca la tarea real"
}

Si el pedido es ambiguo o le falta información, bajá la confianza (menor a 0.5) y hacé que \
user_reply sea una pregunta aclaratoria en vez de un aviso de que ya estás trabajando. Si en \
cambio el pedido es claro, NO pidas aclaraciones innecesarias (p.ej. no preguntes "¿qué resolución \
querés?" para un pedido de imagen que ya está completo) — subí la confianza y avisá que ya arrancás.

Ejemplos (no los repitas literalmente, son solo para que entiendas el criterio):
Usuario: "Hacé una página web para una veterinaria"
{"intent": "crear_pagina_web", "confidence": 0.9, "required_capabilities": ["coding"], "user_reply": "Dale, ya arranco con la página."}

Usuario: "Convertí este texto en audio"
{"intent": "texto_a_audio", "confidence": 0.9, "required_capabilities": ["text-to-speech"], "user_reply": "Listo, genero el audio ahora."}
"""


# Mejora de latencia (2026-08-23, ver docs/HISTORY.md "diagnóstico de
# lentitud"): classify() es una llamada COMPLETA a un modelo aparte
# (qwen2.5:3b) que corre ANTES del modelo principal, incluso para un
# simple "hola" — confirmado en vivo (journalctl -u ollama) que esto
# duplica el número de cargas de modelo por mensaje. Para el puñado de
# mensajes donde SYSTEM_PROMPT (agent_core/llm/agent_loop.py) ya le
# dice al modelo "responder directo, sin llamar a NINGUNA herramienta"
# (saludos, despedidas, preguntas de identidad), clasificar intención/
# capacidades no aporta nada — no hay ninguna capacidad que desbloquear
# ni ninguna ambigüedad que aclarar. Allowlist deliberadamente angosta
# y de coincidencia EXACTA (nunca substring dentro de un mensaje más
# largo) — el riesgo de saltear classify() por error en un pedido real
# es peor que el ahorro, así que ante cualquier duda se sigue llamando
# al Conversation Engine como siempre.
_TRIVIAL_MESSAGES = frozenset({
    "hola", "hola!", "hola.", "buenas", "buen dia", "buenos dias", "buenas tardes",
    "buenas noches", "hey", "hi", "hello",
    "como estas", "como estas?", "que tal", "que tal?", "todo bien?",
    "quien sos", "quien sos?", "quien eres", "quien eres?", "who are you",
    "gracias", "muchas gracias", "gracias!", "thank you", "thanks",
    "chau", "chau!", "adios", "bye", "nos vemos", "hasta luego",
})


def is_trivial_message(goal: str) -> bool:
    """
    True si `goal` (normalizado: minúsculas, sin tildes, sin espacios
    de más) coincide EXACTO con un saludo/despedida/pregunta de
    identidad conocida — ver el comentario de _TRIVIAL_MESSAGES arriba
    para la justificación completa. Coincidencia de mensaje ENTERO,
    nunca de una palabra suelta dentro de un pedido más largo.
    """
    normalized = unicodedata.normalize("NFD", goal.strip().lower())
    normalized = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    return normalized in _TRIVIAL_MESSAGES


@dataclass
class ConversationEngineResult:
    intent: str
    confidence: float
    required_capabilities: list[str]
    user_reply: str


class ConversationEngine:
    def __init__(self, llm_client: LLMProvider | None = None, cfg=None):
        self.cfg = cfg or settings.conversation_engine
        self.llm_client = llm_client or self._build_default_client()

    def _build_default_client(self) -> LLMProvider:
        """
        Arma el cliente real según self.cfg.provider y lo registra en
        runtime_manager bajo `_RUNTIME_NAME` — mismo mecanismo que
        agent_core.orchestrator.build_llm_client(), pero en un slot
        propio (ver comentario de `_RUNTIME_NAME`). base_url explícito
        en ambos casos, mismo motivo que ImageAnalysisTool/VisionConfig
        (tool_integration/adapters/image_analysis.py): NUNCA el default
        de cada cliente, que cae al proveedor en la nube si ese perfil
        está activo — este modelo tiene que seguir siendo local siempre.

        Antes esto instanciaba OllamaClient directo, asumiendo que el
        backend local SIEMPRE habla el formato nativo de Ollama — ahora
        pasa por el Runtime Manager como el chat principal, ganando
        control de concurrencia (settings.runtimes) y la posibilidad de
        apuntar a otro backend local vía provider="openai_compatible"
        (ver ConversationEngineConfig.provider).
        """
        if self.cfg.provider == "openai_compatible":
            client = OpenAICompatibleClient(base_url=self.cfg.base_url, api_key=self.cfg.api_key)
            runtime = OpenAICompatibleRuntime(client, max_parallel=settings.runtimes.openai_compatible.max_parallel)
        else:
            client = OllamaClient(base_url=self.cfg.base_url)
            runtime = OllamaRuntime(client, max_parallel=settings.runtimes.ollama.max_parallel)
        runtime_manager.register(_RUNTIME_NAME, runtime)
        return RuntimeManagedLLMProvider(runtime_manager, _RUNTIME_NAME)

    def classify(self, goal: str) -> ConversationEngineResult | None:
        """
        None = el clasificador está deshabilitado, o falló (red, JSON
        inválido, clave faltante) — el llamador debe seguir con el
        flujo normal como si esto no existiera. Nunca lanza.
        """
        if not self.cfg.enabled:
            return None

        try:
            response = self.llm_client.chat(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": goal},
                ],
                model=self.cfg.model,
                response_format="json",
                temperature=self.cfg.temperature,
            )
        except ProviderError as e:
            logger.warning(f"Conversation Engine no disponible, se sigue con el flujo normal: {e}")
            return None

        try:
            data = json.loads(response.content)
            return ConversationEngineResult(
                intent=str(data["intent"]),
                confidence=float(data["confidence"]),
                required_capabilities=list(data.get("required_capabilities", [])),
                user_reply=str(data["user_reply"]),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.warning(f"Conversation Engine devolvió una respuesta no válida, se sigue con el flujo normal: {e}")
            return None
