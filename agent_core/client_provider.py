"""
CONTRATO PÚBLICO entre el núcleo del agente (context_service.py,
agent_loop.py) y "qué cliente está pidiendo esto" — mismo espíritu que
agent_core/llm/provider.py::LLMProvider, aplicado a un eje distinto: en
vez de "qué motor de lenguaje responde", acá es "qué interfaz hizo el
pedido" (hoy: la web, o la extensión de VS Code).

Antes de este archivo, `client == "vscode"` aparecía repetido en 2
lugares (context_service.py y agent_loop.py), cada uno decidiendo algo
distinto (qué instrucción de prompt agregar, qué herramientas excluir)
a partir del mismo string crudo. Este archivo es el único lugar que
sabe qué significa cada valor de `client` — los llamadores solo piden
`get_client_provider(client).algo()`, nunca comparan el string ellos
mismos.

Primer caso real de "Provider" fuera de LLMProvider (2026-07-21,
pedido explícito del usuario tras el pivote de visión hacia un
Kernel que coordina sin decidir) — deliberadamente el caso más chico
posible: solo 2 puntos de decisión existían antes de este archivo.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

# Solo se agrega cuando el pedido viene del cliente "vscode" (ver
# ChatRequest.client en agent_core/routers/chat.py) — la interfaz web
# sigue generando imagen/audio/video como comportamiento default, ya
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

# Herramientas de generación/edición multimedia, excluidas del toolset
# cuando client="vscode" — restricción ESTRUCTURAL, no una instrucción
# de prompt: ya se probó en vivo que una regla de SYSTEM_PROMPT sola no
# evita que el modelo llame a estas herramientas para pedidos de código
# ("creá la página web para una panadería" generó fotos de panadería
# en vez de HTML/CSS/JS, dos veces, con distintas reglas de prompt).
_MULTIMEDIA_TOOL_NAMES = frozenset({
    "image_generation", "audio_generation", "video_composition",
    "image_editing", "image_composition", "speech_to_text",
    "image_via_kernel", "audio_via_kernel",
    "voice_roundtrip_via_kernel", "image_inpaint_via_kernel",
})

# Inverso del conjunto de arriba: herramientas que SOLO tienen sentido
# para client="vscode" — el backend nunca toca el filesystem real del
# usuario él mismo (ver tool_integration/adapters/vscode_files.py):
# propose_project_files/import_resource escriben recién del lado de la
# extensión, tras la aprobación del usuario; read_workspace_file lee
# recién del lado de la extensión, que encadena la respuesta
# automáticamente (ver vscode-extension/src/readWorkspaceFile.ts). El
# cliente web no tiene ningún workspace real que leer ni ningún canal
# para aplicar una propuesta de escritura, así que ofrecerle cualquiera
# de las tres solo generaría una respuesta que nadie puede usar.
#
# También se usa en agent_core/llm/agent_loop.py para el tope de
# repeticiones por turno de estas 3 herramientas específicamente — ESE
# uso es una propiedad intrínseca de las herramientas (piden aprobación
# async, una segunda llamada en el mismo turno nunca tiene información
# nueva), no depende de cuál sea el `client` activo, así que no pasa
# por ClientProvider — solo importa esta misma constante.
_VSCODE_ONLY_TOOL_NAMES = frozenset({"propose_project_files", "import_resource", "read_workspace_file"})


@runtime_checkable
class ClientProvider(Protocol):
    """
    Toda interfaz que consume el agente (hoy: web, VS Code) implementa
    esta forma (conformidad estructural, como LLMProvider). El núcleo
    (context_service.py, agent_loop.py) solo llama estos 2 métodos —
    nunca vuelve a comparar `client == "algo"` él mismo.
    """

    def system_prompt_addendum(self) -> str | None: ...

    def excluded_tool_names(self) -> frozenset[str]: ...


class VSCodeClientProvider:
    def system_prompt_addendum(self) -> str | None:
        return _VSCODE_CLIENT_INSTRUCTION

    def excluded_tool_names(self) -> frozenset[str]:
        return _MULTIMEDIA_TOOL_NAMES


class WebClientProvider:
    def system_prompt_addendum(self) -> str | None:
        return None

    def excluded_tool_names(self) -> frozenset[str]:
        return _VSCODE_ONLY_TOOL_NAMES


def get_client_provider(client: str | None) -> ClientProvider:
    """Único lugar del código que compara `client` contra un string literal."""
    return VSCodeClientProvider() if client == "vscode" else WebClientProvider()
