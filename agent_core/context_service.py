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

from dataclasses import dataclass, field

from sdk.artifacts import Artifact
from utils.config import settings


@dataclass
class EditorContextSignals:
    """Señal cruda del editor — el frontend NUNCA la formatea, solo la captura."""
    relative_path: str
    language_id: str
    text: str
    is_selection: bool
    # Pieza mínima de "Editor Context Provider" (2026-07-20, pedido
    # explícito del usuario tras un bug real: kal creó un archivo nuevo
    # en el lugar equivocado por no saber que un proyecto ya existía
    # como subcarpeta). Rutas relativas nomás — nunca contenido, eso
    # sigue siendo carísimo en tokens para mandar de más de un archivo
    # (ver read_workspace_file para leer uno puntual bajo demanda).
    # `workspace_tree`: listado (acotado) de archivos visibles en el
    # Explorer. `open_editors`: pestañas actualmente abiertas (subconjunto
    # del árbol, pero más probable que sea relevante AHORA MISMO).
    workspace_tree: list[str] = field(default_factory=list)
    open_editors: list[str] = field(default_factory=list)


@dataclass
class ContextBundle:
    """Mismo shape que ya espera agent_core/llm/agent_loop.py::run() — ese módulo no cambia."""
    history: list[dict]
    session_context: dict | None


# Tope de rutas del árbol de archivos mostradas en el prompt (ver
# EditorContextSignals.workspace_tree) — un proyecto real puede tener
# miles de archivos (node_modules, .git, etc., aunque la extensión ya
# los excluye antes de mandarlos); esto es una segunda barrera del
# lado del backend para nunca inflar el prompt sin límite, sea cual
# sea el tamaño real de lo que mande la extensión.
_MAX_WORKSPACE_TREE_PATHS_IN_PROMPT = 200


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
    "una propuesta chica que sí se aplica, que una enorme que falla a la mitad.\n\n"
    "BUG REAL ENCONTRADO EN USO: pedido de agregar una foto real a una página, el modelo navegó "
    "bien con browser (action='images') para conseguir una URL real, pero después la puso "
    "directamente en un <img src=\"...\"> del HTML en vez de llamar import_resource — eso es un "
    "ENLACE remoto (hotlink), NO una descarga real, y es exactamente lo que este pedido pide evitar. "
    "Por eso, siempre que el pedido sea agregar una foto/imagen REAL (no generada por IA) que el "
    "usuario se lleve como archivo propio del proyecto: (1) usá browser con action='images' sobre "
    "una página real del sitio permitido para conseguir URLs de imagen REALES — nunca inventes una "
    "URL de Unsplash/Pexels/etc. a ciegas; (2) llamá import_resource con una de esas URLs "
    "confirmadas y un destination_path dentro de una carpeta de assets del proyecto (p.ej. "
    "'<proyecto>/assets/foto.jpg'). NUNCA pongas esa URL directamente en el HTML como <img "
    "src=\"https://...\"> ni la menciones como enlace — eso NO descarga ni guarda nada real, tenés "
    "que llamar import_resource de verdad para que el archivo termine siendo parte del proyecto.\n\n"
    "BUG REAL ENCONTRADO EN USO: pedido de fotos para un menú — probaste con www.google.com (no "
    "permitido) y le respondiste al usuario \"no tengo acceso a Internet ni a servicios externos\", "
    "una generalización FALSA: si un dominio puntual no está permitido, NO significa que no haya acceso "
    "a internet en absoluto — la herramienta browser sí funciona sobre dominios reales ya permitidos "
    "(hoy incluyen unsplash.com, pexels.com y pixabay.com para fotos). Ante un dominio rechazado, "
    "reintentá con browser sobre unsplash.com/pexels.com/pixabay.com en vez de rendirte, y nunca le "
    "digas al usuario que no hay acceso a internet cuando lo que pasó es que ESE dominio puntual no "
    "está en la lista.\n\n"
    "BUG REAL ENCONTRADO EN USO: pedido de \"generá vos mismo las imágenes\" — respondiste \"no tengo "
    "la capacidad de generar imágenes, no puedo crear ni editar imágenes en el sistema\" y le sugeriste "
    "usar herramientas EXTERNAS al usuario. Eso es engañoso: kal SÍ genera imágenes con IA (SDXL-Turbo "
    "local), simplemente esa herramienta no está disponible en ESTE modo (agente de código en VS Code, "
    "para no mezclar generación de imágenes con pedidos de código). Si te piden generar imágenes vos "
    "mismo y no tenés esa herramienta disponible acá, aclará que es una limitación de ESTE modo (no una "
    "incapacidad general de kal) y ofrecé la alternativa que SÍ funciona acá: buscar fotos reales con "
    "browser (unsplash.com/pexels.com/pixabay.com) e importarlas con import_resource — nunca le digas "
    "al usuario que vaya a buscar herramientas externas por su cuenta cuando kal mismo puede resolverlo.\n\n"
    "IMPORTANTE: tenés disponible read_workspace_file para pedir el contenido REAL de un archivo del "
    "árbol del proyecto (ver el listado de 'Árbol de archivos' de esta conversación) que no esté ya "
    "incluido acá — nunca inventes o asumas qué contiene un archivo que no viste. Llamala con la ruta "
    "relativa exacta (tomada del árbol, nunca adivinada) y esperá: el contenido real te va a llegar "
    "automáticamente en un paso siguiente de este mismo turno, no hace falta pedirlo dos veces ni "
    "avisarle al usuario que esperés. Usala quirúrgicamente — para ENTENDER un archivo puntual antes de "
    "modificarlo o antes de responder una pregunta sobre él — no para leer todo el árbol de una vez ni "
    "'por las dudas': cada archivo pedido implica un paso adicional real antes de tu respuesta final."
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
            if active_artifact.modality == "image":
                # BUG REAL ENCONTRADO EN USO: pedido "describe esta imagen"
                # (sobre una imagen recién generada, ya anunciada como
                # artefacto activo arriba) respondió "no puedo ver o
                # analizar imágenes en este entorno" — el modelo tenía el
                # path del artefacto activo Y la herramienta analyze_image
                # disponible, pero nunca conectó una cosa con la otra,
                # cayendo en su respuesta genérica de "no tengo visión".
                # Mismo patrón que otros hallazgos de esta sesión: tener la
                # herramienta disponible no alcanza sin una instrucción
                # explícita que la conecte con la intención del usuario.
                parts.append(
                    "Si el usuario pide describir, analizar, o identificar qué hay en esta imagen "
                    "(o hace una pregunta sobre su contenido), NUNCA respondas que no podés ver "
                    "imágenes — llamá a la herramienta analyze_image con "
                    f"image_path='{active_artifact.uri}' y question igual al pedido del usuario."
                )
        if editor_context is not None:
            if editor_context.text:
                label = "selección" if editor_context.is_selection else "archivo completo"
                parts.append(
                    f"Contexto del editor ({label} de {editor_context.relative_path}, "
                    f"lenguaje {editor_context.language_id}):\n"
                    f"```{editor_context.language_id}\n{editor_context.text}\n```"
                )
            else:
                # BUG REAL ENCONTRADO EN USO (2026-07-20, VS Code): pedido
                # de agregar fotos a "la página de menú" con esa página
                # abierta de verdad en el editor — kal no tenía forma de
                # saberlo (la vista de chat de la barra lateral no mandaba
                # NINGÚN contexto del editor) y creó un archivo nuevo en
                # el lugar equivocado, desconectado del proyecto real. Esta
                # rama cubre un contexto LIVIANO (solo ruta, sin contenido
                # — ver vscode-extension/src/editorContext.ts::
                # captureEditorSnapshot(includeContent=false)), mandado
                # automáticamente en cada pedido de esa vista: mandar el
                # archivo COMPLETO en cada mensaje de un chat libre sería
                # carísimo en tokens sin necesidad real la mayoría de las
                # veces — alcanza con que el modelo sepa EN QUÉ ruta está
                # trabajando el usuario.
                parts.append(
                    f"El usuario tiene actualmente abierto '{editor_context.relative_path}' en su "
                    "editor (no se incluyó su contenido acá). Si el pedido es agregar o modificar "
                    "algo de ESE archivo o del proyecto al que pertenece, usá esa ruta real como "
                    "referencia en vez de adivinar o inventar una ruta nueva."
                )
            if editor_context.workspace_tree:
                tree = editor_context.workspace_tree[:_MAX_WORKSPACE_TREE_PATHS_IN_PROMPT]
                listing = "\n".join(f"- {p}" for p in tree)
                omitted = len(editor_context.workspace_tree) - len(tree)
                if omitted > 0:
                    listing += f"\n... y {omitted} archivo(s) más (no se muestran todos)."
                parts.append(
                    "Árbol de archivos REAL visible en el Explorer del proyecto — usalo para saber "
                    "qué existe ANTES de decidir dónde crear algo nuevo. Si ya existe un proyecto/"
                    "carpeta relacionado con el pedido (p.ej. 'restaurante-web/' para un pedido sobre "
                    "el menú de un restaurante), agregá o modificá archivos AHÍ ADENTRO — nunca crees "
                    "un archivo suelto en la raíz con el mismo nombre que uno que ya existe en otra "
                    "ruta de esta lista, eso deja dos archivos desconectados en vez de uno solo real:\n"
                    f"{listing}"
                )
            if editor_context.open_editors:
                parts.append(
                    "Pestañas actualmente abiertas en el editor (más probable que sean relevantes "
                    "para este pedido puntual que el resto del árbol): "
                    + ", ".join(editor_context.open_editors)
                )

        if not parts:
            return None
        return {"role": "system", "content": "\n\n".join(parts)}
