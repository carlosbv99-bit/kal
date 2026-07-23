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
from dataclasses import dataclass

from agent_core.llm.ollama_client import OllamaClient
from agent_core.llm.provider import ProviderError
from utils.config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

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
- "image-generation": crear una imagen nueva desde cero (a partir de una descripción).
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


@dataclass
class ConversationEngineResult:
    intent: str
    confidence: float
    required_capabilities: list[str]
    user_reply: str


class ConversationEngine:
    def __init__(self, llm_client: OllamaClient | None = None, cfg=None):
        self.cfg = cfg or settings.conversation_engine
        # base_url explícito, mismo motivo que ImageAnalysisTool/VisionConfig
        # (tool_integration/adapters/image_analysis.py): NUNCA el default de
        # OllamaClient, que cae al proveedor en la nube si ese perfil está
        # activo — este modelo tiene que seguir siendo local siempre.
        self.llm_client = llm_client or OllamaClient(base_url=self.cfg.base_url)

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
