"""
Context Service: decide qué entra al próximo mensaje al LLM.

Antes, esta lógica vivía repartida en agent_core/sessions.py::Session
(history_messages()/context_message()) — devolvía TODO el historial de
la sesión sin ningún límite, y el "contexto de sesión" era solo el
artefacto activo. Los frontends (la extensión de VS Code) armaban su
propio texto de contexto del editor y lo mandaban ya concatenado
dentro de `goal` — el frontend decidía qué entraba al prompt, no el
kernel.

Diseño acordado: los frontends mandan SEÑALES CRUDAS (texto del
editor, si es selección o archivo completo, etc.) — nunca texto ya
formateado — y este servicio decide el mensaje final. Vive in-process
(mismo patrón que agent_core/memory/manager.py::MemoryManager), NO se
expone por el Kernel Bus — las skills nunca necesitan construir un
prompt de chat, eso no es algo que una skill sandboxeada haga.

Alcance de esta iteración, deliberadamente mecánico (sin ninguna
llamada a LLM todavía): ventana de "últimos N turnos" en vez de
historial completo, y fusión de artefacto activo + contexto del
editor en UN ÚNICO mensaje de sistema — nunca dos mensajes system
separados (BUG REAL ya documentado en
agent_core/llm/agent_loop.py::run(): un segundo mensaje system hacía
que qwen3-coder:30b lo ignorara por completo). Resumen automático de
sesión, memoria de proyecto persistente, navegación de símbolos y
tracking de intención quedan fuera — necesitan una llamada real a un
LLM (resumen) o análisis de código por lenguaje (símbolos), y merecen
su propia validación antes de confiarlos.
"""
from __future__ import annotations

from dataclasses import dataclass

from tool_integration.base_tool import Artifact
from utils.config import settings


@dataclass
class EditorContextSignals:
    """Señal cruda del editor — el frontend NUNCA la formatea, solo la captura."""
    relative_path: str
    language_id: str
    text: str
    is_selection: bool


@dataclass
class ContextBundle:
    """Mismo shape que ya espera agent_core/llm/agent_loop.py::run() — ese módulo no cambia."""
    history: list[dict]
    session_context: dict | None


class ContextService:
    def __init__(self, max_recent_turns: int | None = None):
        self.max_recent_turns = max_recent_turns or settings.context.max_recent_turns

    def build(self, session, editor_context: EditorContextSignals | None = None) -> ContextBundle:
        history = self._windowed_history(session.turns)
        session_context = self._build_session_context(session.active_artifact, editor_context)
        return ContextBundle(history=history, session_context=session_context)

    def _windowed_history(self, turns: list) -> list[dict]:
        recent = turns[-self.max_recent_turns:] if self.max_recent_turns else turns
        messages: list[dict] = []
        for turn in recent:
            messages.append({"role": "user", "content": turn.goal})
            messages.append({"role": "assistant", "content": turn.final_answer})
        return messages

    def _build_session_context(
        self, active_artifact: Artifact | None, editor_context: EditorContextSignals | None
    ) -> dict | None:
        parts: list[str] = []
        if active_artifact is not None:
            parts.append(
                f"El último artefacto activo (generado por vos o subido por el usuario) es "
                f"{active_artifact.modality} en '{active_artifact.uri}'. Si el usuario se refiere a "
                '"la imagen"/"el audio"/"el video" sin dar más detalle, probablemente hable de este.'
            )
        if editor_context is not None:
            label = "selección" if editor_context.is_selection else "archivo completo"
            parts.append(
                f"Contexto del editor ({label} de {editor_context.relative_path}, "
                f"lenguaje {editor_context.language_id}):\n"
                f"```{editor_context.language_id}\n{editor_context.text}\n```"
            )

        if not parts:
            return None
        return {"role": "system", "content": "\n\n".join(parts)}
