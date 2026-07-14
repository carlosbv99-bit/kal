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


# Solo se agrega cuando el pedido viene del cliente "vscode" (ver
# ChatRequest.client en orchestrator.py) — la interfaz web sigue
# generando imagen/audio/video como comportamiento default, ya
# validado. Bug real encontrado en uso: sin esta distinción, "creá la
# página web para una panadería" generó fotos de panadería sin
# relación con el pedido de código en vez de HTML/CSS/JS.
_VSCODE_CLIENT_INSTRUCTION = (
    "Estás actuando como agente de programación dentro de VS Code (una faceta distinta de la "
    "interfaz web de kal, donde SÍ corresponde generar imagen/audio/video). Acá, si piden crear una "
    "página web, una app, un script o cualquier proyecto de código, nunca generes imagen/audio/video "
    "para ese pedido, aunque el contenido describa algo visual (una panadería, una tienda, etc.): "
    "acá \"página web\" es un pedido de código, no de imágenes.\n\n"
    "IMPORTANTE: tenés disponible la herramienta propose_project_files para crear archivos/carpetas "
    "REALES en el proyecto del usuario (él revisa una vista previa y decide si aplicarla, nunca se "
    "escribe nada sin su aprobación). BUG REAL ENCONTRADO EN USO: sin esta instrucción, el modelo "
    "seguía mostrando el código en la respuesta y pidiéndole al usuario que lo copie a mano, aunque "
    "la herramienta ya existía y estaba disponible — un hábito de responder solo en texto que no se "
    "corrige solo por tener la herramienta ofrecida. Por eso: si el pedido implica crear uno o más "
    "archivos nuevos que el usuario se va a llevar (una página, un proyecto, un script para guardar), "
    "usá SIEMPRE propose_project_files — no te limites a mostrar el código en bloques y sugerir que "
    "lo copien, eso ya no hace falta. Si el proyecto tiene VARIOS archivos (p.ej. HTML + CSS + "
    "JavaScript separados), llamá la herramienta UNA sola vez con TODOS los archivos juntos en la "
    "lista 'files' — nunca describas algunos en texto y otros en la herramienta, ni expliques en "
    "texto cómo se vería la llamada a la herramienta en vez de hacerla de verdad. Reservá responder "
    "solo con código en texto para cuando el "
    "pedido es una explicación o un fragmento de referencia, no un archivo real a crear.\n\n"
    "BUG REAL ENCONTRADO EN USO: pedidos de proyectos distintos en la misma conversación (p.ej. una "
    "página para una barbería y después otra para una panadería) proponían todos sus archivos SUELTOS "
    "en la raíz del proyecto (todos 'index.html', 'estilos.css', etc.) — se mezclaban entre sí, "
    "pisándose unos a otros. Por eso: si el pedido es un proyecto NUEVO y distinto de lo que ya se "
    "venía haciendo en esta conversación, poné TODOS sus archivos dentro de una subcarpeta con un "
    "nombre corto y descriptivo derivado del pedido (p.ej. 'barberia-web/index.html', nunca "
    "'index.html' suelto en la raíz) — así proyectos distintos nunca se mezclan. Si en cambio el "
    "pedido es agregar o modificar algo del MISMO proyecto que ya se venía creando en esta "
    "conversación, o el usuario pide explícitamente una ruta/carpeta distinta, seguí esa instrucción "
    "en cambio, no crees una subcarpeta nueva.\n\n"
    "BUG REAL ENCONTRADO EN USO: pedido de un proyecto grande (una app Android completa, con "
    "manifest/build.gradle/actividades/layouts/modelos en varias carpetas) generó una llamada tan "
    "larga que se cortó a la mitad, sin llegar a proponer nada. Por eso: si el proyecto pedido tiene "
    "MUCHOS archivos (más de 4-5, o alguno muy largo), NO intentes generarlos todos en una sola "
    "llamada — proponé primero SOLO los archivos esenciales para que el proyecto compile/funcione de "
    "forma mínima (p.ej., para Android: el manifest, el build.gradle, y la actividad principal con su "
    "layout), decile al usuario en tu respuesta qué archivos faltan y que te los pida a continuación, "
    "y esperá el siguiente pedido para agregarlos con otra llamada a propose_project_files. Mejor "
    "una propuesta chica que sí se aplica, que una enorme que falla a la mitad."
)


class ContextService:
    def __init__(self, max_recent_turns: int | None = None):
        self.max_recent_turns = max_recent_turns or settings.context.max_recent_turns

    def build(
        self,
        session,
        editor_context: EditorContextSignals | None = None,
        client: str | None = None,
    ) -> ContextBundle:
        history = self._windowed_history(session.turns)
        session_context = self._build_session_context(session.active_artifact, editor_context, client)
        return ContextBundle(history=history, session_context=session_context)

    def _windowed_history(self, turns: list) -> list[dict]:
        recent = turns[-self.max_recent_turns:] if self.max_recent_turns else turns
        messages: list[dict] = []
        for turn in recent:
            messages.append({"role": "user", "content": turn.goal})
            messages.append({"role": "assistant", "content": turn.final_answer})
        return messages

    def _build_session_context(
        self,
        active_artifact: Artifact | None,
        editor_context: EditorContextSignals | None,
        client: str | None = None,
    ) -> dict | None:
        parts: list[str] = []
        if client == "vscode":
            parts.append(_VSCODE_CLIENT_INSTRUCTION)
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
