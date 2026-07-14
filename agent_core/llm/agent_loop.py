"""
Loop de razonamiento con herramientas (estilo ReAct) que convierte a
kal de "infraestructura" a "agente utilizable": toma un objetivo en
lenguaje natural, decide qué hacer usando el modelo de Ollama
configurado, y ejecuta acciones reales (código en sandbox, memoria,
herramientas multimodales) hasta llegar a una respuesta final o agotar
el presupuesto de pasos.

Diseño ReAct simplificado:
  1. Se arma el mensaje de sistema con la descripción de kal y el
     catálogo de herramientas disponibles (JSON schema por herramienta).
  2. Se llama a Ollama con la conversación + las herramientas.
  3. Si el modelo pide llamar una herramienta: se ejecuta, se agrega el
     resultado a la conversación como mensaje role="tool", y se repite
     desde (2).
  4. Si el modelo responde con contenido final (sin tool_calls): esa es
     la respuesta, se corta el loop.
  5. Si se agota max_steps sin una respuesta final: se corta igual,
     devolviendo lo último que se tenga, marcado como incompleto — un
     agente que nunca se detiene es tan peligroso como uno que nunca
     actúa (mismo espíritu que el circuit breaker de auto-reparación).

Todo lo que este loop ejecuta como "código" pasa por
task_execution/executor.py::run_sandboxed (nunca in-process) — el LLM
decide QUÉ hacer, pero el sandbox sigue siendo quien decide qué tan
peligroso se le permite ser.

Catálogo de herramientas (arquitectura de plataforma): cuando no se
inyecta `tools=` explícito (el override que usan los tests para
inyectar dobles, que queda fijo tal cual se pasó), el catálogo se
recalcula en CADA run() combinando tool_integration.registry
(imagen/audio/video hoy; browser/skills/herramientas dinámicas del
agente en fases futuras, sin tocar este archivo) con tres `Tool` de
instancia atados a este loop en particular (run_code/remember/recall,
ver tool_integration/adapters/core_tools.py) — recalcular en cada
run() importa porque una herramienta dinámica creada a mitad de
conversación debe quedar disponible en el siguiente turno.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from agent_core.llm.json_extraction import extract_json_array, extract_json_object
from agent_core.llm.ollama_client import OllamaClient
from agent_core.llm.provider import LLMProvider, ProviderError, ToolCall
from agent_core.memory.manager import MemoryManager
from audit.audit_log import AuditEvent, audit_log
from task_execution.executor import TaskExecutor
from tool_integration.adapters.core_tools import CodeExecutionTool, MemoryRecallTool, MemoryRememberTool
from tool_integration.base_tool import Artifact, Tool
from tool_integration.permission_cascade import permission_cascade, trust_tier_for
from tool_integration.permissions import Permission
from tool_integration.registry import ToolRegistry
from tool_integration.registry import tool_registry as default_tool_registry
from utils.config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AgentTool:
    name: str
    description: str
    parameters_schema: dict[str, Any]
    handler: Callable[..., str]
    # Poblado por el handler de _agent_tool_from_tool() con el Artifact
    # crudo que devolvió la Tool real (antes de aplanarlo a texto) — así
    # run() puede trackear qué artefacto generó cada paso sin cambiar la
    # firma de handler (sigue devolviendo str, no rompe los AgentTool de
    # test que ya inyectan handlers propios).
    last_artifact: Artifact | None = None
    # Para la cascada de permisos (tool_integration/permissions.py::
    # PermissionCascade) — poblados por _agent_tool_from_tool() a partir
    # del ToolManifest real. Los AgentTool de test que se construyen a
    # mano (tools=[AgentTool(...)] inyectado) quedan con los defaults de
    # abajo: sin permisos declarados y tier "system", que la cascada
    # nunca restringe por defecto — no rompe ningún test existente.
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    trust_tier: str = "system"

    def to_ollama_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters_schema},
        }


@dataclass
class AgentStep:
    tool_name: str
    arguments: dict[str, Any]
    observation: str
    artifact: Artifact | None = None


@dataclass
class AgentRunResult:
    goal: str
    final_answer: str
    steps: list[AgentStep] = field(default_factory=list)
    status: str = "success"  # success | max_steps_exceeded | llm_error


SYSTEM_PROMPT = """Eres kal, un agente de IA que ejecuta tareas usando herramientas reales, \
no solo texto. Todo el código que ejecutas corre en un sandbox aislado (sin red por defecto, \
filesystem read-only salvo tu área de trabajo) — esto es una garantía de seguridad real, no una \
sugerencia, y no puedes ni debes intentar evadirla.

Reglas:
- Usa una herramienta SOLO si la tarea realmente la necesita (cálculos, generar contenido,
  buscar en memoria). Preguntas conversacionales o sobre vos mismo se responden directo, sin
  llamar a ninguna herramienta.
- No inventes resultados de una herramienta que no llamaste.
- Si una herramienta falla, decide si tiene sentido reintentar con otro enfoque o informar el fallo.
- La memoria que trae recall() puede estar desactualizada. Cada resultado indica su nivel de
  confianza entre corchetes ([temporal], [aprendida], [verificada], [permanente], [externa]). Si
  algo que ya generaste u observaste EN ESTA MISMA conversación (el resultado de una herramienta
  que acabás de ejecutar) contradice lo que trajo recall(), confiá en tu observación directa y
  reciente, no en la memoria recuperada — especialmente si está marcada [temporal] o [aprendida].
- No inventes ni guardes con remember() datos que no confirmaste realmente (una ruta de archivo,
  un resultado, un hecho). Si no estás seguro de algo, decilo en vez de inventar algo plausible.
- Cuando tengas la respuesta final, respóndela directamente sin llamar a más herramientas.
- Sé directo y conciso en la respuesta final.
- Generá EXACTAMENTE lo que se pidió, ni más ni menos: si piden "una imagen de X", generá UNA
  sola, no varias variantes. No encadenes herramientas extra (agregar texto/título, componer o
  combinar imágenes) a menos que el pedido lo mencione explícitamente. Bug real encontrado en uso:
  pedido "generame un sombrero" terminó generando CUATRO imágenes de sombreros, agregándole título
  a dos, y combinando dos en una composición — nada de eso se pidió, y cada llamada de más
  desperdicia tiempo y recursos reales (cada generación de imagen tarda minutos en esta máquina).
- run_code NUNCA puede crear archivos que el usuario se lleve (una página web, una app, un
  proyecto con varios archivos): `import os` y `open()` están prohibidos a propósito en ese
  sandbox, cualquier intento falla con un error de validación ANTES de ejecutar nada. Si el pedido
  requiere ese tipo de archivo Y tenés disponible la herramienta propose_project_files, usala en
  cambio — es la forma correcta de crear archivos reales, el usuario los revisa y aprueba antes de
  que se escriba nada. Si NO la tenés disponible, no intentes escribirlo con run_code de todos
  modos — es un error conocido; respondé con el código completo en la respuesta final en cambio.
  Bug real encontrado en uso: pedido "creá la página web para una panadería" generó código con
  `open('index.html', 'w')` y `import os`, rechazado por el validador, después de gastar un paso
  entero en el intento fallido.

Ejemplos de cuándo NO llamar a ninguna herramienta (bugs reales encontrados en uso — el modelo
llamó herramientas irrelevantes en casos exactamente como estos):
- "hola" / "¿quién sos?" -> responder directo. NO es necesario generar audio ni ninguna otra cosa.
- "¿qué hace este código? explicame" + código ya pegado en el mensaje -> leer el código dado y
  explicarlo con texto. NO hace falta ejecutar el código, ni buscar nada en internet, ni pedir
  información del sistema (system_info) — el código ya está completo en el mensaje, no falta info.
- Un pedido ambiguo en español con una palabra que también podría significar un dispositivo o
  concepto distinto (p.ej. "el ratón" puede ser el animal de una imagen o el dispositivo de PC) ->
  interpretar por el CONTEXTO de la conversación (si se venía hablando de una imagen, es el animal),
  no asumir el significado menos relacionado con lo que se venía haciendo.
- Si la pregunta ya se responde con algo que está en el HISTORIAL de la conversación o en el
  "Contexto de esta sesión" (p.ej. el artefacto activo: la última imagen/audio/video generado) ->
  respondé con esa información tal cual, directo, sin llamar a NINGUNA herramienta. NUNCA vuelvas a
  generar/ejecutar algo que ya existe solo para "confirmar" o "recordar" un dato que ya tenés — eso
  produce un artefacto nuevo y distinto del original, y tu respuesta terminaría siendo incorrecta.
  Ejemplo real: preguntado "¿qué imagen generaste recién y en qué ruta quedó guardada?", la
  respuesta correcta es citar la ruta que ya aparece en el historial/contexto — llamar de nuevo a
  generar una imagen es un error, no una forma de "estar seguro".
"""


def _artifact_to_observation(artifact: Artifact) -> str:
    """
    Convierte el resultado tipado de una Tool (Artifact) en el texto
    que se agrega a la conversación como mensaje role="tool". Dos
    convenciones cubren todas las Tool actuales:
      - modality="text" con "status" en metadata (convención de
        DynamicSandboxedTool/CodeExecutionTool): éxito -> stdout,
        fallo -> "ERROR (status): stderr".
      - modality="text" con "summary" en metadata (remember/recall):
        se devuelve tal cual.
      - cualquier otra modalidad (image/audio/video): referencia al
        artefacto generado.
    """
    if artifact.modality == "text":
        if "status" in artifact.metadata:
            if artifact.metadata["status"] == "success":
                return artifact.metadata.get("stdout") or "(sin salida)"
            return f"ERROR ({artifact.metadata['status']}): {artifact.metadata.get('stderr', '')}"
        if "summary" in artifact.metadata:
            return artifact.metadata["summary"]
        return str(artifact.metadata)
    if artifact.modality == "project_files":
        # Nunca el contenido completo de los archivos acá — infla el
        # historial de la conversación sin necesidad, el modelo no
        # necesita releerlo (la vista previa real la ve el USUARIO, del
        # lado de la extensión de VS Code, no el modelo).
        if artifact.metadata.get("status") == "requires_approval":
            return (
                "ERROR: esta acción requiere aprobación humana explícita antes de poder "
                "proponerse (política de filesystem_access en config.yaml) — avisale al "
                "usuario, no se creó ni propuso ningún archivo."
            )
        files = artifact.metadata.get("files", [])
        names = ", ".join(f["path"] for f in files)
        return f"Se prepararon {len(files)} archivo(s) para el proyecto ({names}) — el usuario decidirá si los aplica."
    return f"{artifact.modality}: archivo generado en {artifact.uri}"


def _agent_tool_from_tool(name: str, tool: Tool) -> AgentTool:
    # Construcción en dos pasos: el handler necesita una referencia al
    # AgentTool ya creado para poder guardarle last_artifact.
    agent_tool = AgentTool(
        name=name,
        description=tool.manifest.description,
        parameters_schema=tool.manifest.parameters_schema,
        handler=None,  # se completa abajo
        permissions=tool.manifest.permissions,
        trust_tier=trust_tier_for(tool),
    )

    def handler(**kwargs) -> str:
        artifact = tool.execute(**kwargs)
        agent_tool.last_artifact = artifact
        return _artifact_to_observation(artifact)

    agent_tool.handler = handler
    return agent_tool


# Herramientas de generación/edición multimedia, excluidas del toolset
# cuando client="vscode" (ver agent_core/context_service.py y
# AgentLoop._build_tools_from_registry). Restricción ESTRUCTURAL, no
# una instrucción de prompt: ya se probó en vivo que una regla de
# SYSTEM_PROMPT sola no evita que el modelo llame a estas herramientas
# para pedidos de código ("creá la página web para una panadería"
# generó fotos de panadería en vez de HTML/CSS/JS, dos veces, con
# distintas reglas de prompt) — mismo criterio que max_tool_repeats
# más abajo: un tope estructural, no una petición que el modelo puede
# ignorar. Lista explícita (no una categoría genérica en ToolManifest
# todavía): si se agrega una herramienta multimedia nueva, hay que
# sumarla acá a mano.
_MULTIMEDIA_TOOL_NAMES = frozenset({
    "image_generation", "audio_generation", "video_composition",
    "image_editing", "image_composition", "speech_to_text",
    "image_via_kernel", "audio_via_kernel",
    "voice_roundtrip_via_kernel", "image_inpaint_via_kernel",
})

# Inverso del conjunto de arriba: herramientas que SOLO tienen sentido
# para client="vscode" — el backend nunca escribe el archivo real él
# mismo (ver tool_integration/adapters/vscode_files.py), la escritura
# ocurre del lado de la extensión tras la aprobación del usuario. El
# cliente web no tiene ningún canal para aplicar esa propuesta, así que
# ofrecérsela solo generaría una respuesta que nadie puede usar.
_VSCODE_ONLY_TOOL_NAMES = frozenset({"propose_project_files"})


class AgentLoop:
    def __init__(
        self,
        llm_client: LLMProvider | None = None,
        task_executor: TaskExecutor | None = None,
        memory: MemoryManager | None = None,
        tools: list[AgentTool] | None = None,
        tool_registry: ToolRegistry | None = None,
    ):
        self.llm = llm_client or OllamaClient()
        self.task_executor = task_executor or TaskExecutor()
        self.memory = memory or MemoryManager()
        self.tool_registry = tool_registry or default_tool_registry
        # Si se pasa `tools=` explícito, queda fijo tal cual (usado por
        # tests para inyectar dobles) — nunca se mezcla con el registry.
        self._explicit_tools: dict[str, AgentTool] | None = (
            {tool.name: tool for tool in tools} if tools is not None else None
        )

    def _current_tools(self, client: str | None = None) -> dict[str, AgentTool]:
        if self._explicit_tools is not None:
            return self._explicit_tools
        return self._build_tools_from_registry(client)

    def _build_tools_from_registry(self, client: str | None = None) -> dict[str, AgentTool]:
        instance_tools: dict[str, Tool] = {
            "run_code": CodeExecutionTool(self.task_executor),
            "remember": MemoryRememberTool(self.memory),
            "recall": MemoryRecallTool(self.memory),
        }
        merged: dict[str, Tool] = {**self.tool_registry.active_tools(), **instance_tools}
        if client == "vscode":
            merged = {name: tool for name, tool in merged.items() if name not in _MULTIMEDIA_TOOL_NAMES}
        else:
            merged = {name: tool for name, tool in merged.items() if name not in _VSCODE_ONLY_TOOL_NAMES}
        return {name: _agent_tool_from_tool(name, tool) for name, tool in merged.items()}

    def _extract_fallback_tool_call(self, content: str, tools: dict[str, AgentTool]) -> ToolCall | None:
        """
        Detecta un tool call imitado como texto plano/JSON cuando el
        modelo no completó message.tool_calls nativo.

        BUG REAL ENCONTRADO EN PRUEBAS: no todos los modelos servidos
        por Ollama completan message.tool_calls (el campo
        estructurado), aunque se les pase el parámetro `tools` —
        depende de si la plantilla de chat de ESE modelo en Ollama
        soporta tool-calling nativo. Confirmado con qwen2.5-coder:14b:
        en vez de tool_calls estructurado, el modelo imita el formato
        como texto plano en `content` (a veces envuelto en
        ```json ... ```). Sin este fallback, ese texto se mostraba tal
        cual al usuario como si fuera la respuesta final, sin ejecutar
        nada.

        Solo se acepta si el JSON tiene "name" con un nombre de
        herramienta que existe — así un JSON cualquiera que el modelo
        mencione al pasar no se confunde con un tool call.
        """
        data = extract_json_object(content)
        if data is not None and data.get("name") in tools:
            arguments = data.get("arguments", {})
            if isinstance(arguments, dict):
                return ToolCall(name=data["name"], arguments=arguments)

        # BUG REAL ENCONTRADO EN USO: para propose_project_files en
        # particular, el modelo a veces "imita" la llamada como un
        # array JSON crudo de archivos — ni siquiera envuelto en
        # {"name", "arguments"} como el resto de los tool calls
        # imitados que sí detecta el chequeo de arriba. Sin esto, ese
        # texto se mostraba tal cual al usuario (con los saltos de
        # línea de cada archivo escapados como "\n" literal, pareciendo
        # "todo el código en una sola línea") en vez de crear la
        # propuesta de verdad.
        if "propose_project_files" in tools:
            files = extract_json_array(content)
            if files and all(
                isinstance(f, dict) and isinstance(f.get("path"), str) and isinstance(f.get("content"), str)
                for f in files
            ):
                return ToolCall(name="propose_project_files", arguments={"files": files})

        return None

    # --- Loop principal ---

    def run(
        self,
        goal: str,
        model: str | None = None,
        max_steps: int | None = None,
        max_tool_repeats: int | None = None,
        history: list[dict] | None = None,
        session_context: dict | None = None,
        denied_permissions: frozenset[Permission] = frozenset(),
        client: str | None = None,
    ) -> AgentRunResult:
        """
        `history` (turnos previos de la misma sesión, ver
        agent_core/sessions.py) y `session_context` (p.ej. el artefacto
        activo) son opcionales — sin ellos, el comportamiento es
        exactamente el de antes (conversación nueva de cero).
        `denied_permissions`: override de la cascada de permisos para
        ESTA sesión (ver tool_integration/permissions.py::PermissionCascade
        y agent_core/sessions.py::Session.denied_permissions) — vacío por
        defecto, no restringe nada más de lo que ya restringen el techo
        global y el nivel de confianza de cada herramienta.
        `max_tool_repeats`: tope estructural a cuántas veces se puede
        llamar a la MISMA herramienta dentro de este run() — ver
        settings.llm.max_tool_repeats. BUG REAL ENCONTRADO EN USO:
        "genera una raqueta de tenis" generó la imagen correcta una vez
        y después, en el mismo turno, 3 imágenes más de paisajes sin
        relación, sin llegar nunca a una respuesta final. El modelo
        nunca ve el resultado visual de una generación (la observación
        es solo la ruta del archivo, ver _artifact_to_observation) — no
        estaba "reintentando por mala calidad", perdió el hilo de la
        tarea. La regla de SYSTEM_PROMPT sola no alcanzó (ya estaba
        activa cuando pasó esto) — este tope es la barrera estructural
        que no depende de que el modelo la respete.
        `client`: "vscode" excluye del toolset las herramientas de
        generación/edición multimedia (ver _MULTIMEDIA_TOOL_NAMES más
        arriba) — mismo criterio que max_tool_repeats: una restricción
        ESTRUCTURAL (el modelo ni siquiera ve estas herramientas en la
        lista disponible), no una instrucción de prompt. Ya se probó en
        vivo que pedirle por prompt que no las llame no alcanza.
        """
        max_steps = max_steps or settings.llm.max_agent_steps
        max_tool_repeats = max_tool_repeats or settings.llm.max_tool_repeats
        tools = self._current_tools(client)
        # BUG REAL ENCONTRADO EN USO: session_context como un SEGUNDO
        # mensaje role="system" separado (en vez de fundido en el
        # primero) hacía que qwen3-coder:30b lo ignorara por completo —
        # confirmado con una prueba directa contra Ollama: con dos
        # mensajes system, el modelo negaba tener cualquier artefacto
        # activo aunque la info estuviera ahí; fundiendo el contexto en
        # el ÚNICO mensaje system, lo usó correctamente. El historial
        # (roles user/assistant) sí funciona bien como mensajes propios
        # — el problema es específico de un segundo system.
        system_content = SYSTEM_PROMPT
        if session_context:
            system_content = f"{SYSTEM_PROMPT}\n\n{session_context['content']}"
        messages: list[dict] = [{"role": "system", "content": system_content}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": goal})
        tool_schemas = [t.to_ollama_schema() for t in tools.values()]
        steps: list[AgentStep] = []
        tool_call_counts: dict[str, int] = {}

        for _ in range(max_steps):
            try:
                response = self.llm.chat(messages, model=model, tools=tool_schemas)
            except ProviderError as e:
                logger.error(f"Error llamando al proveedor de LLM: {e}")
                return AgentRunResult(goal=goal, final_answer=str(e), steps=steps, status="llm_error")

            effective_tool_calls = list(response.tool_calls)
            if not effective_tool_calls:
                fallback = self._extract_fallback_tool_call(response.content, tools)
                if fallback is not None:
                    logger.info(f"Tool call detectado como texto plano (fallback, modelo sin tool-calling nativo): {fallback.name}")
                    effective_tool_calls = [fallback]

            if not effective_tool_calls:
                return AgentRunResult(goal=goal, final_answer=response.content, steps=steps, status="success")

            # BUG REAL ENCONTRADO EN USO: el formato OpenAI (que Groq valida
            # ESTRICTO, a diferencia de Ollama que es tolerante) exige un
            # 'id' único por tool_call — para correlacionar la respuesta de
            # la herramienta (mensaje role="tool", tool_call_id) con la
            # llamada que la originó. Ollama no siempre lo devuelve, y el
            # fallback de texto plano tampoco tiene uno — se genera acá si
            # falta, nunca se manda un tool_call sin id hacia un proveedor
            # que sí lo exige.
            for tc in effective_tool_calls:
                if tc.id is None:
                    tc.id = f"call_{uuid4().hex[:24]}"

            # BUG REAL ENCONTRADO EN USO: el formato OpenAI (que Groq valida
            # ESTRICTO, a diferencia de Ollama que es tolerante) exige que
            # tool_calls[].function.arguments sea un STRING con JSON adentro,
            # nunca el objeto ya parseado — sin este dumps, Groq rechazaba
            # CUALQUIER turno posterior a una llamada a herramienta con 400
            # ("arguments: value must be a string"), rompiendo toda tarea de
            # más de un paso contra un proveedor en la nube.
            messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": [
                        {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                        for tc in effective_tool_calls
                    ],
                }
            )

            for tool_call in effective_tool_calls:
                tool_call_counts[tool_call.name] = tool_call_counts.get(tool_call.name, 0) + 1
                artifact = None
                if tool_call_counts[tool_call.name] > max_tool_repeats:
                    # Rechazado ANTES de ejecutar — cada llamada real a una
                    # herramienta de generación cuesta minutos de cómputo acá,
                    # no tiene sentido gastarlos en una repetición que ya
                    # sabemos que vamos a cortar.
                    observation = (
                        f"ERROR: ya llamaste a '{tool_call.name}' {max_tool_repeats} veces en este turno — "
                        "no la llames de nuevo. Da tu respuesta final ahora con lo que ya generaste/obtuviste."
                    )
                    logger.warning(f"Tope de repeticiones excedido para '{tool_call.name}' (límite={max_tool_repeats}), rechazado sin ejecutar")
                else:
                    observation = self._dispatch_tool(tool_call.name, tool_call.arguments, tools, denied_permissions)
                    dispatched_tool = tools.get(tool_call.name)
                    artifact = dispatched_tool.last_artifact if dispatched_tool is not None else None
                steps.append(
                    AgentStep(
                        tool_name=tool_call.name, arguments=tool_call.arguments,
                        observation=observation, artifact=artifact,
                    )
                )
                messages.append({"role": "tool", "content": observation, "tool_call_id": tool_call.id})

        logger.warning(f"Agente agotó max_steps={max_steps} sin respuesta final para: {goal!r}")
        return AgentRunResult(
            goal=goal,
            final_answer="No llegué a una respuesta final dentro del límite de pasos permitido.",
            steps=steps,
            status="max_steps_exceeded",
        )

    def _dispatch_tool(
        self, name: str, arguments: dict[str, Any], tools: dict[str, AgentTool],
        denied_permissions: frozenset[Permission] = frozenset(),
    ) -> str:
        tool = tools.get(name)
        if tool is None:
            return f"ERROR: herramienta '{name}' no existe"

        # Cascada de permisos (ver tool_integration/permissions.py::
        # PermissionCascade): se resetea last_artifact ANTES del chequeo
        # para que un rechazo nunca deje pasar un artefacto viejo de una
        # llamada anterior a esta misma herramienta en el mismo run().
        tool.last_artifact = None
        missing = permission_cascade.missing_permissions(tool.permissions, tool.trust_tier, denied_permissions)
        if missing:
            reason = (
                f"ERROR: '{name}' requiere permiso(s) no autorizados en este contexto "
                f"(nivel de confianza '{tool.trust_tier}'): {', '.join(sorted(p.value for p in missing))}"
            )
            logger.warning(reason)
            audit_log.record(
                AuditEvent(
                    event_type="permission_denied",
                    summary=f"Herramienta '{name}' rechazada por la cascada de permisos: {reason}",
                    context={
                        "tool_name": name, "trust_tier": tool.trust_tier,
                        "missing_permissions": sorted(p.value for p in missing),
                    },
                    outcome="failure",
                )
            )
            return reason

        try:
            return tool.handler(**arguments)
        except TypeError as e:
            return f"ERROR: argumentos inválidos para '{name}': {e}"
        except Exception as e:
            logger.exception(f"Fallo inesperado ejecutando herramienta '{name}'")
            return f"ERROR inesperado ejecutando '{name}': {e}"
