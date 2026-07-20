# Historial de ingeniería de kal

Este archivo es el diario de ingeniería completo del proyecto: cada
fase, cada decisión de diseño, cada bug real encontrado y cómo se
corrigió, en orden cronológico, con fecha. Es la fuente de verdad
detallada — útil para entender el "por qué" de cualquier parte del
código, retomar contexto entre sesiones, o auditar cómo llegó el
proyecto a su estado actual.

Para una introducción al proyecto (qué es, arquitectura, estado
actual), ver [README.md](../README.md) en la raíz del repo. Este
archivo es historia acumulada, no la carta de presentación — el
contenido de acá abajo empieza siendo, literalmente, el README.md tal
como existía antes de reestructurar la documentación (2026-07-11).

---

# Kal — Agente IA autónomo con auto-reparación

Agente IA autónomo con auto-reparación, memoria en tres niveles, capacidades
multimodales (imagen/audio/video) y capacidad de crear/usar herramientas nuevas.
Diseñado con seguridad como restricción transversal, no como feature añadida al final.

## Segundo rumbo: kal como kernel de agentes

Después de validar el agente de programación en VS Code (sección
siguiente), nueva reorientación: en vez de "una app que usa Ollama",
`agent_core/` pasa a ser un **kernel** con una API estable, sobre el
que terceros construyan "skills" — analogía explícita con Android/
Linux, pensada para un público final **no experto en programación**
que instale "distribuciones" curadas de skills. La promesa central: una
skill escrita hoy debe seguir funcionando en 5 años aunque cambie el
motor de LLM, de imágenes, o de almacenamiento por dentro — para eso el
núcleo debe depender de contratos/protocolos, nunca de implementaciones
concretas.

Plan de 5 fases (F1 primero, por ser la de menor riesgo y la que ya
resuelve un problema real de esta sesión — ver más abajo):

### F1 (COMPLETA): extraer la interfaz del LLM — `agent_core/llm/provider.py`

Antes de F1: `AgentLoop`, `Planner` y `SelfDiagnosisAgent` importaban
`OllamaClient`/`OllamaError` directo — cambiar el modelo default de
`qwen2.5-coder:14b` a `qwen3-coder:30b` (sección de más abajo) ya había
sido solo un cambio de config, pero cambiar de MOTOR (a una API en la
nube, u otro runtime local) habría requerido tocar el núcleo.

Nuevo archivo `agent_core/llm/provider.py` — contrato estable:
`ChatResponse`/`ToolCall` (movidos desde `ollama_client.py`),
`ProviderError` (error genérico que el núcleo atrapa, nunca el
específico de un proveedor concreto), y `LLMProvider` (`Protocol`
`@runtime_checkable` con `.chat()`/`.list_models()`/`.is_available()`).
`OllamaClient` pasa a ser una implementación entre varias posibles
(`OllamaError` ahora hereda de `ProviderError`). `AgentLoop`/`Planner`/
`SelfDiagnosisAgent` tipan su parámetro `llm_client` como `LLMProvider`
(el default concreto `OllamaClient()` se sigue eligiendo en cada
constructor, pero el CONTRATO del que depende la lógica es la
abstracción). `orchestrator.py` atrapa `ProviderError`, no
`OllamaError`.

De paso, se generalizó un nombre que se había filtrado hasta la API
pública HTTP: `GET /status` devolvía `"ollama_available"`, ahora
`"llm_available"` (único consumidor: `frontend/app.js`, actualizado
junto con la etiqueta visible "ollama" → "LLM" en `frontend/index.html`).

Nuevo `tests/test_llm_provider.py`: confirma con `isinstance()` que
`OllamaClient` cumple `LLMProvider` de verdad (no solo en el papel) y
que `OllamaError` es subclase de `ProviderError` — un test de contrato,
no solo de comportamiento. Suite completa: 308 passed, sin
regresiones.

### F2 (COMPLETA): validar LLMProvider contra un segundo proveedor real

Antes de construir la mecánica de instalar/desinstalar proveedores
como skills (eso queda para más adelante, ver nota al final), primero
había que confirmar que el contrato de F1 generaliza de verdad y no
tiene fugas — probándolo contra una implementación genuinamente
distinta, no un stub que finge.

Nuevo `agent_core/llm/openai_compatible_client.py` —
`OpenAICompatibleClient`, un segundo `LLMProvider` real que habla el
formato OpenAI-compatible (`choices[0].message`, `tool_calls` con
`arguments` SIEMPRE como string JSON) en vez del formato nativo de
Ollama (`/api/chat`) — un wire format genuinamente distinto, no una
copia con otro nombre. Por defecto apunta al propio endpoint
OpenAI-compatible que Ollama ya expone (`/v1/chat/completions`,
`/v1/models`) — mismo Ollama local ya corriendo, sin costo ni
instalación nueva, pero con una `OpenAICompatibleError` propia
(subclase de `ProviderError`) y su propio parseo de principio a fin.
Con `base_url`/`api_key` apuntando a OpenAI real (u otro servicio
compatible) la misma clase serviría tal cual.

Verificado en vivo antes de escribir el parser (`curl` directo a
`/v1/chat/completions` con `qwen3-coder:30b`): la forma real coincide
con la documentada por OpenAI, sin sorpresas.

Tests: `tests/test_openai_compatible_client.py` (unitarios, con
`post_fn`/`get_fn` inyectados — mismo patrón que
`AudioGenerationTool(http_post=...)` — sin red real, cubre el caso real
que un formato distinto puede esconder: `arguments` como string JSON
que hay que parsear, a diferencia de Ollama que a veces ya lo manda
como objeto). `tests/test_openai_compatible_integration.py`: 3 tests
de round-trip REAL contra Ollama corriendo (saltables si no está
disponible, mismo criterio que `requires_docker`). `test_llm_provider.py`
suma `isinstance(OpenAICompatibleClient(), LLMProvider)`. Suite
completa: 319 passed, sin regresiones.

### F5 (parcial, COMPLETA): hardening del enforcement de permisos que ya existe

Al investigar F5 (cerrar la brecha de enforcement — hoy solo 3 de 9
permisos declarables tienen motor real), se encontró que **5 de esos 6
"sin motor" (`GPU`/`CAMERA`/`MICROPHONE`/`CLIPBOARD`/`DOCKER`) no
tienen ningún tool/skill real que los use hoy** — construir enforcement
para ellos ahora sería la misma trampa que F3/F4: infraestructura sin
demanda real que la valide. El sexto, `BROWSER`, sí tiene enforcement
real (allowlist de dominios). Se reorientó F5 hacia hardening de lo
que YA se enforce (network/filesystem_write/browser) — trabajo con
demanda real, no especulativo.

**Bug real y explotable encontrado en `tool_integration/adapters/browser.py`**:
`PlaywrightBrowserDriver` llama a `page.goto(url)`, y Playwright sigue
automáticamente cualquier redirect HTTP — pero el allowlist de
dominios solo se chequeaba contra la URL de ENTRADA, nunca contra la
URL FINAL tras el redirect. Un dominio permitido con un endpoint de
redirect abierto (analytics, `/out?url=`, login flows, acortadores —
extremadamente común en la web real) podía llevar el navegador a
cualquier otro dominio nunca aprobado, y ESE contenido sí se devolvía
al agente como si viniera de un dominio confiable — la puerta de
entrada real para inyección de prompt indirecta vía contenido web no
confiable.

**Fix**: `PlaywrightBrowserDriver` ahora también devuelve la URL final
(`page.url` tras seguir redirects) en sus 3 métodos;
`BrowserTool.execute()` vuelve a chequearla contra el allowlist antes
de devolver cualquier contenido — si el redirect llevó fuera del
allowlist, se descarta el resultado (y se borra el archivo si era una
captura de pantalla) y se audita como `failure`. No se bloquea el
redirect en sí (comportamiento normal de un navegador); se bloquea que
contenido de un destino no aprobado llegue al agente.

De paso, `_is_domain_allowed()` pasó de `urlparse(url).netloc` a
`.hostname`: `netloc` incluye userinfo (`user@host`) y puerto
(`host:8443`), que rompían la comparación exacta — negando de más URLs
legítimas. `.hostname` es lo correcto y no debilita nada (el caso
`http://evil.com@allowed.com/`, que antes se negaba por accidente,
ahora se permite correctamente porque el destino real de red SÍ es
`allowed.com`).

11 tests nuevos en `tests/test_browser_tool.py` (redirect rechazado
para texto/links/screenshot, limpieza del archivo parcial, redirect
legítimo entre dominios ya aprobados que NO debe romperse, auditoría,
y los dos casos de `hostname` vs `netloc`). Suite completa: 327
passed, sin regresiones.

**Siguientes fases** (F3: identidad de autor + verificación de
paquetes, DISTINTA de `signing.py` actual, que firma con la clave de
kal para detectar tampering, no para verificar terceros — F4:
instalación tipo "Play Store" — el resto de F5, motores reales para
GPU/CAMERA/MICROPHONE/CLIPBOARD/DOCKER) quedan para después,
deliberadamente: son infraestructura cara que necesita demanda real
(autores externos, o un skill concreto que pida esos permisos) para
validarse bien. La generalización de `skills.py` con `kind:
"llm_provider"` y el dogfooding de Ollama-como-skill (mecánica de
instalar/desinstalar proveedores en runtime) también queda pendiente —
F2 ya demostró que la ABSTRACCIÓN aguanta un segundo proveedor real;
falta la mecánica de empaquetado, que es un problema distinto.

### Continuidad conversacional + artefacto activo por sesión

Discutiendo la visión de "kal como kernel" (proyectos, ítem activo),
se encontró que **kal no tenía ninguna continuidad conversacional**:
cada `POST /chat` armaba la conversación desde cero — ni el frontend
ni la extensión de VS Code mandaban historial, y `AgentLoop.run()` ni
siquiera aceptaba uno. Si el usuario decía "hazme un logo" y después
"hazle el fondo azul", el segundo pedido no tenía ninguna noción de
que el primero existió. Esto era un prerrequisito real antes de poder
construir cualquier noción de "proyecto/ítem activo".

**Nuevo `agent_core/sessions.py`**: `SessionManager` en memoria del
proceso (mismo criterio que `circuit_breaker`/`registry`: no persiste
a disco, se resetea con `--reload`). Cada `Session` guarda el
historial de turnos (`Turn(goal, final_answer)`) y el último artefacto
generado (imagen/audio/video) de esa sesión. `get_or_create()` degrada
con gracia ante un `session_id` desconocido (p.ej. backend reiniciado)
en vez de fallar — arranca una sesión nueva bajo ese mismo id, mismo
espíritu que `Planner.plan()`.

**`agent_core/llm/agent_loop.py`**: `AgentLoop.run()` gana
`history`/`session_context` opcionales, insertados antes del `goal`
nuevo. Para trackear el artefacto activo sin romper el contrato
existente de `AgentTool.handler` (sigue devolviendo `str`, muchos
tests inyectan handlers propios), `_agent_tool_from_tool()` ahora
guarda el `Artifact` crudo en un campo nuevo `AgentTool.last_artifact`
antes de aplanarlo a texto; `run()` lo lee después de cada dispatch y
lo adjunta al `AgentStep` correspondiente (campo nuevo `.artifact`).
`PlanningAgentLoop.run()` reenvía los mismos parámetros a cada
subtarea.

**`agent_core/orchestrator.py`**: `ChatRequest` gana `session_id`
opcional; `POST /chat` resuelve la sesión, le pasa su historial y
contexto al agente, guarda el turno nuevo al terminar, y actualiza el
artefacto activo si algún paso generó uno (imagen/audio/video, no
texto). La respuesta gana `"session_id"` — el cliente lo reusa en el
siguiente mensaje.

**Clientes**: `frontend/app.js` guarda el `session_id` en una variable
de módulo (dura mientras la pestaña esté abierta). La extensión de VS
Code lo guarda como campo de instancia de `ChatPanel` (un panel = una
conversación). Deliberadamente **fuera** de esto:
`vscode-extension/src/applyEdit.ts` ("Aplicar cambios a la selección")
sigue sin sesión — es un pedido puntual de reescritura de código, no
una conversación; mezclarle historial de chat podría confundir el
prompt.

**Validado en vivo** (no solo con tests): dos `curl` reales a `/chat`
contra `qwen3-coder:30b`. Primero: "Me llamo Kalin. Recordá mi
nombre." → devuelve un `session_id`. Segundo, reusando ese mismo id:
"¿Cómo me llamo?" → respondió "Te llamas Kalin" en 2.5s, **sin llamar
ninguna herramienta** — la continuidad vino pura del historial
insertado en el prompt, no de `recall()`. Suite completa: 343 passed,
sin regresiones.

**Bug real de uso encontrado probando el artefacto activo, y arreglado**:
generé una imagen real (zorro en el bosque), y en el siguiente turno
de la misma sesión pregunté "¿qué imagen generaste recién y en qué
ruta quedó guardada?". El modelo describió la imagen correctamente
(prueba de que el contexto de sesión SÍ le llegó), pero en vez de
responder con la ruta ya conocida, **volvió a llamar a
`image_generation`** y reportó una ruta nueva y distinta — la misma
familia de bug que el de sobre-uso de herramientas ya documentado más
arriba, ahora disparado por el historial de sesión en vez de por
`recall()`. Fix: un quinto ejemplo concreto en el `SYSTEM_PROMPT`
("si la pregunta ya se responde con el historial/contexto de sesión,
respondé directo, NUNCA vuelvas a generar/ejecutar algo que ya
existe"). Reprobado en vivo tras el fix: mismo escenario (imagen de un
gato), la pregunta de seguimiento devolvió `"steps": []` (cero
llamadas) y citó la ruta EXACTA original, en 5.95s en vez de
regenerar la imagen entera.

**Fuera de alcance a propósito** (para no repetir el error de construir
infraestructura sin validar la parte más chica primero): "Proyectos"
con carpetas/versiones, elección dinámica de modelo por recursos,
"quién puede hacer esto", scheduler determinista sin LLM, abstracción
de archivos grandes — se evalúan después de confirmar que esta base
(historial + artefacto activo) resulta valiosa en uso real.

### Limitación real encontrada probando el artefacto activo: kal no tiene visión

Probando en vivo (primero por `curl`, después el usuario lo repitió en
la interfaz real): kal generó una imagen con dos palomas, y al pedirle
"veo dos palomas, borra una de ellas" llamó a `image_editing`
(`inpaint`) con un `box` adivinado — pero como el LLM nunca ve la
imagen que generó, el recorte no correspondía a ninguna paloma en
particular. **Confirmado 3 veces de forma consistente** (incluida una
corrida repetida por el usuario mismo): la imagen resultante queda
prácticamente sin cambios, las dos palomas siguen ahí.

Esto no es un bug puntual, es una limitación de fondo: `qwen3-coder`/
`qwen2.5-coder` son modelos de texto puro, sin ningún camino entrenado
para interpretar píxeles — ninguna herramienta puede darles "visión"
por arriba. Dos caminos reales para resolverlo en el futuro, ninguno
trivial: (a) cambiar el modelo por defecto a uno multimodal (`llava`,
`qwen2-vl` en Ollama), lo que requiere extender el protocolo
`ChatResponse`/mensajes de F1 para aceptar bloques de imagen — un
cambio de modelo, no de config; o (b) agregar una herramienta separada
de detección de objetos (un modelo chico tipo YOLO) que traduzca la
imagen a texto ("paloma en [x,y,x,y]") para que el LLM de texto siga
razonando sobre texto, no píxeles — más chico, más acotado, no toca el
LLM principal. Ninguno de los dos está implementado — se documenta acá
como limitación conocida y aceptada por ahora, no como algo a resolver
en esta iteración.

**Mitigación aplicada** (no resuelve la puntería, sí evita una
afirmación falsa): la descripción de la herramienta `image_editing`
ahora le aclara al modelo que el `box` de `inpaint` es una estimación
a ciegas, y que debe avisarle al usuario en su respuesta en vez de
afirmar que la edición salió bien como si hubiera confirmado el
resultado viéndolo.

**Importante — lo que SÍ funciona sin depender de visión**, confirmado
en el mismo test: `remove_background` (segmentación automática vía
`rembg`, sin `box` ni coordenadas) funciona bien. La composición tipo
video (`video_composition`) tampoco depende de visión, solo secuencia
artefactos ya generados.

### Nueva herramienta: `image_composition` (overlay / side_by_side)

De la misma prueba salió un hallazgo distinto: **no existía ninguna
herramienta para combinar dos imágenes** (superponer un logo sobre una
foto, armar un collage) — no por la limitación de visión, sino porque
nunca se construyó. Nuevo
`tool_integration/adapters/image_composition.py` — 100% Pillow, sin
modelo nuevo (mismo criterio que `crop`/`upscale` en
`image_editing.py`):

- **`overlay`**: pega una imagen sobre otra. Sin `position`, la
  centra automáticamente — mismo espíritu de honestidad que arriba:
  pedirle una posición exacta ("en la esquina") sería adivinar a
  ciegas, así que centrar es el default seguro. Respeta transparencia
  real (si el overlay viene de `remove_background`, no pega un
  rectángulo sólido).
- **`side_by_side`**: concatena 2+ imágenes en fila o columna.

Habilita un flujo real encadenando 3 herramientas en una sola
conversación (gracias a la continuidad de sesión ya construida):
generar una imagen → `remove_background` → `image_composition`
(superponerla sobre otra). 13 tests nuevos, suite completa: 356
passed, sin regresiones.

### Subir una imagen propia (upload) — y el bug real que expuso

Pedido natural después de lo anterior: poder subir una foto propia
(no generada por kal) para, por ejemplo, quitarle el fondo. No existía
ningún mecanismo para eso. Nuevo `POST /uploads` (`agent_core/
orchestrator.py`) — valida tipo de archivo (png/jpeg/webp) y tamaño
máximo (20MB por defecto, configurable), guarda en
`data/artifacts/uploads/`, y **convierte la imagen subida en el
artefacto activo de la sesión** automáticamente (reusa
`SessionManager.update_active_artifact`) — así "quitale el fondo" no
necesita repetir ninguna ruta. Nuevo mount `/artifacts` (solo lectura)
para que el navegador pueda mostrar una vista previa real de lo
subido, no solo una ruta en texto — de paso, esto también deja
preparado el terreno para mostrar imágenes generadas inline en el chat
a futuro (no se hizo en esta iteración, ver alcance abajo). Botón de
subir (📎) nuevo en el frontend, al lado del input de chat.
Deliberadamente sin equivalente en la extensión de VS Code (no es un
contexto natural para subir fotos).

**Bug real y serio encontrado validando esto en vivo**: al subir una
imagen y preguntar "¿qué imagen tengo activa?", el modelo
**alucinó por completo** una imagen y ruta ficticias que no tenían
nada que ver con lo subido. Diagnóstico con pruebas directas contra
Ollama (bypaseando kal): con el `session_context` mandado como un
**segundo mensaje `role="system"` separado**, el modelo lo ignoraba
totalmente — incluso con el `SYSTEM_PROMPT` real completo. Fusionando
ese contexto en el **único** mensaje `system` (en vez de agregarlo
como mensaje aparte), el modelo lo usó correctamente y de inmediato.
Fix aplicado en `AgentLoop.run()` (`agent_core/llm/agent_loop.py`) —
el historial de conversación (roles `user`/`assistant`) no tenía este
problema, es específico de un segundo `system`. Revalidado en vivo de
punta a punta contra el `/chat` real (no solo contra Ollama directo):
subir una imagen → preguntar por ella → responde con la ruta exacta,
sin llamar ninguna herramienta.

### Dos correcciones de UI encontradas probando en el navegador

- **La página entera scrolleaba** en vez de solo el panel de chat —
  bug clásico de flexbox/grid: un hijo con `flex: 1` no se achica por
  debajo de la altura de su contenido a menos que se declare
  `min-height: 0` explícitamente: sin eso, crece y empuja toda la
  página. Arreglado en `.layout`/`.chat-panel`/`.chat-scroll`/
  `.dash-panel`/`.dash-body` (`frontend/style.css`).
- **El cuadro de texto del chat no crecía** al pegar texto largo
  (código, por ejemplo) — quedaba en una sola línea con scroll interno
  minúsculo. Ahora crece con el contenido hasta 160px (después sigue
  con scroll normal) y vuelve a una línea al enviar
  (`frontend/app.js::autoResizeChatInput()`).

### Imágenes inline en el chat + botón de cancelar

Toda imagen (subida, generada, o editada/corregida) aparece ahora como
un mensaje más del chat, en el orden en que ocurrió — antes solo se
veía una miniatura suelta en el chat al subir, y las imágenes
generadas por kal ni se mostraban (solo la ruta en texto). `POST
/chat` expone `steps[].artifact` (`agent_core/orchestrator.py`) para
que el frontend sepa qué paso generó una imagen y dónde — reusa el
mismo mount `/artifacts` (solo lectura) que ya servía las imágenes
subidas. Cualquier resolución real se redimensiona para caber en el
mensaje (`object-fit: contain` + `max-height: 50vh`) sin forzar scroll
de la página.

Primera iteración de esto fue un visor flotante único con pestañas,
apoyado arriba del cuadro de texto (posicionamiento absoluto,
z-index, lógica de pestañas abrir/cerrar). Funcionaba una vez resuelto
el bug de caché del navegador de abajo, pero al probarlo el usuario
notó que ese patrón (varios documentos abiertos en pestañas) es de
editor/IDE, no de chat — coincidimos y se simplificó a lo que está
ahora: cada imagen es un mensaje normal del historial, sin pestañas ni
concepto de "imagen activa". Menos código y menos superficie para
bugs de posicionamiento.

**Botón de cancelar**: ya no es un mensaje más del historial, es un
indicador fijo ("kal está trabajando" + botón Cancelar) pegado justo
arriba del selector de modelo, visible mientras haya un `/chat` o
`/uploads` en curso, vía `AbortController`. Límite honesto: `/chat` es
un endpoint sincrónico — cancelar corta la ESPERA del lado del
navegador, pero kal puede seguir procesando del lado del servidor un
rato más (no hay forma barata de interrumpir a mitad una llamada al
modelo o una generación de imagen ya en curso sin re-arquitecturar el
endpoint como asincrónico con cancelación cooperativa real — no hecho
en esta iteración).

### Bug real de uso: Ollama se desconecta a mitad de tarea y se pierde toda la respuesta

Probando repetidamente con generación de imágenes de por medio, el
usuario reportó que kal "no realiza la tarea encomendada" — la
respuesta llegaba como error de Ollama, no como el resultado esperado,
de forma reproducible. Causa real en
`agent_core/llm/ollama_client.py::OllamaClient.chat()`: cada paso del
loop de razonamiento (`agent_core/llm/agent_loop.py`) llama a Ollama de
nuevo, y un solo `ConnectionError` en CUALQUIER paso intermedio abortaba
la tarea COMPLETA con `status="llm_error"`, aunque los pasos anteriores
hubieran salido bien. Con generación de imagen/audio/video (SDXL-turbo,
etc.) corriendo en la misma máquina, Ollama puede quedar momentáneamente
sin responder mientras recarga su modelo en VRAM/RAM tras competir por
el mismo hardware — un hueco real de uno o dos segundos, no una caída
de verdad.

Fix: `OllamaClient` reintenta ahora ante `ConnectionError` (config
`llm.connection_retries`, default 2 intentos extra, con
`llm.retry_backoff_seconds` de pausa entre cada uno) antes de rendirse.
Deliberadamente NO reintenta en `Timeout` (un modelo grande en CPU
puede tardar de verdad — reintentar solo duplicaría la espera) ni en
`HTTPError` (error real del servidor, reintentar no cambia nada).
`post_fn`/`get_fn`/`sleep_fn` ahora son inyectables (mismo patrón que
`OpenAICompatibleClient`), lo que permitió escribir
`tests/test_ollama_client.py` con reintentos verificados sin red real
ni esperas reales.

### Tercer rumbo: kal como "el Linux de la Inteligencia Artificial"

Reformulación mayor del pivot a kernel de agentes (arriba): en vez de
"kernel estable + skills + marketplace" como una serie de fases
técnicas, la meta pasa a ser explícitamente una PLATAFORMA ABIERTA —
un kernel seguro y extensible sobre el que cualquier desarrollador
puede construir skills inteligentes, y cualquier usuario final (sin
saber programar) puede instalarlas con la misma facilidad que una app
de celular, sin depender de un modelo de IA ni un proveedor concreto.
Ver el archivo de memoria del proyecto para el documento completo de
visión (kernel con 7 superficies de API, marketplace con pipeline de
firma/auditoría, "Proyectos" persistentes más allá de la conversación).
**Decisión de alcance**: a partir de acá, generación/edición de
imagen/audio/video y el navegador quedan en pausa — el foco pasa a
fortalecer la seguridad, informado por una comparación técnica propia
contra OpenClaw (arquitectura hub-and-spoke, ClawHub). Conclusión
compartida: kal ya le gana a OpenClaw en sandboxing sin excepción para
código del agente, contenedores efímeros, auditoría con integridad
criptográfica y pipeline de self-modification — pero AMBOS proyectos
comparten la misma debilidad: las skills de terceros corren en el
mismo proceso que el núcleo, sin aislamiento real (la única mitigación
en los dos es heurística estática). Resolver esto antes de un
marketplace supera a OpenClaw en este eje, no solo lo iguala.

### Aislamiento real de ejecución de skills de terceros

Hasta ahora, `tool_integration/skills.py::load_skills()` importaba el
`.py` de una skill y la instanciaba directo — cada `.execute()`
posterior corría en el mismo proceso principal de kal, sin ningún
confinamiento (la única barrera real era `enabled: false` por defecto
en `skill.yaml`, revisado por un humano). Ahora, lo que queda
registrado nunca es la clase real de la skill: es un
`SandboxedSkillTool` (`tool_integration/sandboxed_skill.py`) cuyo
`.execute()` corre DENTRO de un contenedor Docker efímero
(`sandbox/skill_runner.py`), con las mismas garantías que ya tenía
`run_code` (sin red por defecto, filesystem read-only salvo
`/workspace`, límites de recursos, usuario sin privilegios) — nunca en
el proceso principal.

Alcance elegido para esta primera versión (completo, no el mínimo):

- **Dependencias por skill**: `skill.yaml` gana un campo `requirements`
  (specs de pip). Si la skill lo declara, `sandbox/skill_image_builder.py`
  construye (o reusa, cacheada por hash de las requirements) una imagen
  Docker derivada — misma técnica de endurecimiento que
  `sandbox/images/minimal/Dockerfile` (usuario 1000:1000, pip/apt
  desinstalados DESPUÉS de instalar lo que la skill pidió, nunca
  disponibles en tiempo de ejecución). El build en sí necesita red
  (bajar de PyPI) pero el contenedor de EJECUCIÓN sigue sin red salvo
  que la skill declare el permiso `network` — misma excepción acotada
  que ya usa `error_handling/strategies.py::ImportErrorStrategy`.
- **Archivos de salida reales**: convención `KAL_SKILL_OUTPUT_DIR`
  (variable de entorno que el runner define dentro del contenedor) — una
  skill que genera un archivo (imagen/audio/etc.) lo escribe ahí y
  devuelve solo el nombre relativo en `Artifact.uri`; `SandboxedSkillTool`
  lo persiste después a una ruta de host real
  (`data/artifacts/skills/<nombre>/`). Requirió extender
  `sandbox/docker_runner.py` (`SandboxResult.output_files`,
  `run(..., output_dir=)`) para leer archivos de vuelta del workdir
  antes de que se destruya — antes solo se capturaba stdout/stderr.

**Hallazgo de diseño importante**: el runner que ejecuta una skill
dentro del contenedor (`sandbox/skill_runner.py`) necesita
`os`/`importlib` — ambos están en el denylist AST de
`code_analysis/denylist.py`, pensado para código NO confiable
propuesto por el agente. Pasar el runner (código de PRIMERA PARTE, de
este mismo repo) por esa validación sería un error de categoría y lo
rechazaría. Se agregó `SandboxExecutor.execute_trusted()` — mismo rol
que `execute()` (siempre audita, respeta permisos sin motor real) pero
sin `validate_code()`, documentado explícitamente por qué es seguro
saltárselo solo en este caso.

**Bug real encontrado probando esto con Docker de verdad**: toda skill
hace `from tool_integration.base_tool import Artifact, Tool,
ToolManifest` — el contenedor no tenía ese paquete disponible, así que
CUALQUIER skill real fallaba con `ModuleNotFoundError`, no un caso
raro. Fix: `base_tool.py`/`permissions.py` (ambos sin dependencias
riesgosas, solo `dataclasses`/`abc`/`enum` de stdlib) se copian como
parte fija del workspace en cada ejecución.

**Skill de referencia nueva**: `skills/qr_code/` (genera un PNG de
código QR, paquete `qrcode` + `pillow`) — valida el pipeline COMPLETO
con algo real: dependencia declarada, imagen derivada construida y
cacheada, archivo de salida real persistido. Confirmado en vivo contra
Docker real, no solo con dobles de prueba.

**Limitación conocida y deliberada, no resuelta acá**: leer
`tool_cls.manifest` todavía requiere importar el `.py` de la skill en
el proceso principal (aunque nunca se instancia la clase ni se llama a
`.execute()` ahí) — así que código a nivel de módulo de la skill sigue
corriendo en el host, igual que antes. Cerrar también esa brecha
requeriría declarar manifest/parameters_schema en el propio
`skill.yaml` en vez de leerlos de la clase Python — cambio más grande,
fuera de alcance en esta iteración.

29 tests nuevos (`tests/test_skill_image_builder.py`,
`tests/test_sandboxed_skill.py`, más adiciones a `tests/test_skills.py`
y `tests/test_sandbox_integration.py`), incluyendo una prueba de
seguridad negativa (una skill sin permiso `network` no puede alcanzar
internet, mismo mecanismo que ya garantiza `test_sandbox_integration.py`
para `run_code`). Suite completa: 397 passed, 0 regresiones.

### Cascada de permisos multi-nivel

Segunda mitad de la comparación con OpenClaw (la primera fue el
aislamiento de skills, arriba). Brecha encontrada: kal no tenía NINGÚN
nivel de política por encima de la herramienta individual — el único
chequeo real era `UNSUPPORTED_RUNTIME_PERMISSIONS` (rechaza permisos
sin motor técnico: GPU/CAMERA/MICROPHONE/CLIPBOARD/DOCKER, sin importar
quién los pida) más el mapeo ad-hoc `Permission.NETWORK -> network_mode`
duplicado en `DynamicSandboxedTool`/`SandboxedSkillTool`. Nada
distinguía "un adaptador propio pide red" de "una skill de un tercero
pide red" — ambos pasaban exactamente igual.

Cascada nueva de 4 niveles (`tool_integration/permissions.py::
PermissionCascade`), "más restrictivo gana", adaptada a lo que YA
EXISTE en kal (no una copia literal de los 5 niveles de OpenClaw, que
tiene "proveedor"/"canal" sin equivalente acá):

1. **Global** (`config.yaml: permissions.globally_denied`) — techo del
   sistema entero.
2. **Nivel de confianza** (`permissions.trust_tier_caps`) — por CÓMO
   quedó registrada la herramienta: `"system"` (adaptadores propios),
   `"agent"` (herramientas dinámicas propuestas por el LLM, ya
   alineado con `require_human_approval_for` existente), `"skill"`
   (skills de terceros — deliberadamente el techo más bajo: sin red ni
   escritura por defecto, aunque el manifest de la skill declare
   `requires_network=True`).
3. **Sesión** (`agent_core/sessions.py::Session.denied_permissions`) —
   override opcional por conversación, vía `POST /chat:
   deny_permissions` (reemplaza, no acumula — evita que algo quede
   bloqueado "para siempre" sin que el usuario lo vea venir).
4. **Manifiesto de la herramienta** (`ToolManifest.permissions`, ya
   existente) — sin cambios.

**Hallazgo de diseño importante**: `ToolManifest.created_by` NO puede
ser la señal de nivel de confianza — es un campo que la propia
herramienta/skill se AUTODECLARA (`skills/system_info/tool.py` y
`skills/qr_code/tool.py` ya ponen `created_by="system"` sin que nada lo
valide). Si la cascada confiara en ese campo, cualquier autor de skill
podría autodeclararse `"system"` y saltarse el techo pensado justo para
terceros. La señal correcta es el TIPO del wrapper con el que la
herramienta quedó registrada (`tool_integration/permissions.py::
trust_tier_for()`): `SandboxedSkillTool` → `"skill"`,
`DynamicSandboxedTool` → `"agent"`, cualquier otra cosa → `"system"` —
nunca se lee `manifest.created_by`.

Enforcement centralizado en `AgentLoop._dispatch_tool()` (agrega
`AgentTool.permissions`/`trust_tier`, poblados en
`_agent_tool_from_tool()`): si lo que la herramienta necesita no está
cubierto por los 4 niveles, se rechaza ANTES de llamar al handler (fail
closed) — nunca se ejecuta con menos permisos de los que la herramienta
asume tener, eso produciría fallos confusos a mitad de camino en vez de
un rechazo claro de entrada. Queda auditado como
`"permission_denied"` (nuevo `EventType`). El gate existente de
`UNSUPPORTED_RUNTIME_PERMISSIONS` sigue igual, es un chequeo
independiente ("¿se puede confinar esto técnicamente?" vs. "¿este
contexto puede pedirlo?").

**Bug real encontrado corriendo la suite completa con Docker de
verdad**: la primera versión puso `PermissionCascade`/`trust_tier_for`
en el mismo archivo que `Permission`
(`tool_integration/permissions.py`) — pero ESE archivo se copia tal
cual dentro de cada contenedor de skill (toda skill necesita
`Permission` a través de `base_tool.py`, ver la sección de aislamiento
de skills arriba). Como `PermissionCascade` necesita
`settings.permissions` de `utils/config.py`, y `utils/` nunca se envía
al contenedor, CUALQUIER skill real (incluida `qr_code`) empezó a
fallar con `ModuleNotFoundError: No module named 'utils'` en cuanto el
contenedor intentaba importar `base_tool.py`. Fix: `PermissionCascade`/
`trust_tier_for` se movieron a un archivo nuevo,
`tool_integration/permission_cascade.py`, que nunca se envía a un
contenedor — `permissions.py` volvió a ser 100% stdlib, como tenía que
seguir siendo.

18 tests nuevos (`tests/test_permission_cascade.py` nuevo,
`tests/test_agent_loop.py`, `tests/test_planning_agent_loop.py`,
`tests/test_sessions.py`). **Verificado en vivo** contra el `/chat`
real con `qwen3-coder:30b` corriendo de verdad: pedido "navegá a
example.com" con `deny_permissions: ["browser"]` en la sesión — el
paso `browser` se rechazó con el mensaje de la cascada ANTES de que
`BrowserTool` intentara nada, y el modelo respondió explicando la
restricción en vez de fallar confuso. Suite completa: 414 passed, 0
regresiones.

### Cerrar la brecha del import de manifest en el host

Última pieza de seguridad de skills de esta sesión. Limitación
documentada y aceptada en las dos iteraciones anteriores:
`load_skills()` ya no instanciaba la clase real de una skill ni
llamaba a `.execute()` en el proceso principal, pero SÍ seguía
importando su `.py` por ruta (`_import_entry_point()`, vía
`exec_module()`) solo para leer `tool_cls.manifest`
(nombre/descripción/permisos/parameters_schema). Ese import ejecutaba
cualquier código a nivel de módulo de la skill en el host — un
`os.system(...)` puesto fuera de cualquier función ya corría en el
proceso principal, sin que nadie llamara a `execute()`.

Ahora `skill.yaml` es la ÚNICA fuente de verdad — gana un campo nuevo
`parameters_schema` (antes vivía en `tool_cls.manifest.parameters_schema`)
y `load_skills()` arma el `ToolManifest` completo desde el YAML,
`entry_point` pasa a ser un string que solo se resuelve DENTRO del
contenedor (ya era así para la ejecución, ahora también para la carga).
`_import_entry_point()` se eliminó; en su lugar,
`_validate_entry_point_reference()` valida SOLO formato y que el
archivo exista — sin ejecutar una sola línea. `skills/system_info/tool.py`
y `skills/qr_code/tool.py` perdieron su atributo `manifest =
ToolManifest(...)`, que quedó vestigial (nada lo lee).

**Trade-off real y aceptado**: ya no se detectan a tiempo de carga una
sintaxis rota, una clase de `entry_point` inexistente, o que no sea
subclase de `Tool` — esos casos ahora se descubren en la primera
ejecución real (dentro de Docker), donde ya se manejaban con gracia
(error prolijo, nunca un crash). A cambio, se gana algo más importante
que cerrar un detalle: una skill HABILITADA con código malicioso a
nivel de módulo ya NO se ejecuta ni una sola vez en el host, ni
siquiera al cargarla — antes sí lo hacía (aunque el resultado no
rompiera nada visible). No se agregó un "dry-run" dentro de Docker en
el arranque para recuperar esas tres validaciones tempranas — más
infraestructura y latencia de arranque por adelantar un descubrimiento
que de todos modos se maneja bien al primer uso real (mismo criterio
usado para no construir F3/F4 sin demanda real).

Efecto secundario notado y documentado: como `ToolManifest` ahora se
arma ENTERO desde `skill.yaml`, el nombre con el que una skill se
registra es el mismo `name:` del manifiesto — antes, en teoría, la
clase Python podía declarar un `ToolManifest(name=...)` distinto del
`name:` de `skill.yaml` (nunca se validaba que coincidieran). Ahora
solo hay un nombre, más simple y sin esa inconsistencia latente
posible.

24 tests en `tests/test_skills.py` (varios reescritos: los tres que
antes esperaban `"import_failed"` en la carga ahora confirman que la
skill se REGISTRA igual y falla recién al ejecutar, con Docker real;
nuevo test confirmando que una skill habilitada con
`raise RuntimeError(...)` a nivel de módulo se registra sin problema
—prueba directa de que nunca se importó—). Verificado en vivo:
`skills/qr_code/` y `skills/system_info/` reales, ya sin
`manifest =` en su Python, se cargan y ejecutan igual que antes
(`qr_code` generando un PNG real de nuevo). Suite completa: 419
passed, 0 regresiones.

### Kernel Service Bus — protocolo genérico Skill↔Kernel, servicio "image"

Pedido original: migrar las 6 herramientas de primera parte
(image_gen, audio_gen, video_gen, browser, speech_to_text,
image_editing, image_composition) a `skills/`. Bloqueador real
encontrado: 4 de las 6 cargan un modelo pesado (hasta 14GB, SDXL-Turbo)
de forma perezosa y lo mantienen caliente en memoria entre llamadas
— posible hoy porque viven en un proceso que nunca muere. Los
contenedores de skills son EFÍMEROS (uno nuevo por llamada); migrarlas
tal cual forzaría recargar el modelo entero desde disco en cada
llamada.

Propuesta inicial (un "Model Manager" interno del host, sin canal
hacia las skills) fue redirigida acertadamente por el usuario: si se
va a construir CUALQUIER canal entre una skill aislada y el proceso
principal, ese canal define la superficie de API del kernel a largo
plazo — se diseñó como protocolo de servicios genérico
(`kernel.call(service=..., action=..., params=...)`), no como un
puente específico para modelos. Analogía de diseño real (no inventada
para este proyecto): mismo principio que LSP (Language Server
Protocol, JSON-RPC sobre stdio) o el extension host de VS Code — un
proceso aislado habla con el host SOLO por mensajes, nunca por
memoria compartida.

**Transporte**: socket Unix (nunca TCP) montado en
`/workspace/.kal/kernel.sock` dentro del contenedor — la skill sigue
sin red real (`network_mode="none"`), coherente con todo el sandbox
existente. `sandbox/docker_runner.py::run()` ganó `extra_mounts`
(bind mounts adicionales, genérico, no específico de sockets).

**Protocolo**: JSON-RPC 2.0 sobre líneas newline-delimited
(`kernel_bus/protocol.py`) — se adoptó el formato ya usado por LSP en
vez de inventar uno propio (semántica de errores gratis, `id` para
matchear pedido/respuesta). `method` es `"<servicio>.<acción>"`
(p.ej. `"image.generate"`). Referencias de artefacto como
`artifact://<modalidad>/<id>` (no `project://` — "Proyectos"
persistentes todavía no existen en kal).

**Paquete nuevo `kernel_bus/`** (a nivel de kernel, no dentro de
`tool_integration/`): `services.py` (`ImageService` — la lógica que
antes vivía privada en `image_gen.py::_get_pipeline()`, ahora
compartida), `bus.py` (`KernelServiceBus`: registro + despacho,
mantiene además un mapeo interno `artifact://... -> ruta real de
host`, para que una skill pueda devolver la MISMA referencia que
recibió sin nunca ver una ruta real del filesystem del host),
`socket_server.py` (expone el bus a UN contenedor por UNA ejecución;
permisos: allowlist plano declarado por la skill —
`kernel_services: [...]` en `skill.yaml`, NO pasa por
`PermissionCascade`, es más parecido a qué herramientas tiene
disponibles un agente que a un recurso del sistema—; auditado con 2
`EventType` nuevos, `kernel_service_call`/`kernel_service_denied`;
límite de requests + timeout para que una skill no acapare un
servicio compartido).

`tool_integration/kernel_client.py` (nuevo): SDK de ~60 líneas, 100%
stdlib, que se copia dentro de cada contenedor igual que
`base_tool.py`/`permissions.py` — la skill nunca importa nada de
`kernel_bus`, solo habla el protocolo.

**Unificación real, no solo nueva infraestructura**:
`tool_integration/adapters/image_gen.py` ahora delega en el MISMO
`ImageService` que usa el bus (`tool_integration/registry.py`
construye una única instancia y la registra en ambos lugares) — el
pipeline se carga una sola vez para el adaptador de primera parte Y
para cualquier skill, no una copia por cada consumidor. `image_gen.py`
sigue funcionando exactamente igual para tests que monkeypatchean
`settings.multimodal.image.artifact_dir` (cada `ImageGenerationTool()`
sin instancia inyectada explícita sigue armando su propio
`ImageService` con su mismo `self.cfg`, ya resuelto en ese momento).

**Skill de referencia nueva**: `skills/image_via_kernel/` — genera una
imagen SIN NINGUNA dependencia de ML propia (`requirements: []`, ni
torch ni diffusers) pidiéndosela al kernel. Confirmado visualmente de
punta a punta con Docker real y el modelo SDXL-Turbo real (ya
cacheado): un bote rojo en un lago en calma, generado por una skill
que no puede tocar el modelo.

**Bug real encontrado en la primera corrida del test de integración
real**: el timeout por defecto del sandbox (30s) mataba el contenedor
mientras esperaba la respuesta del socket, aunque el servicio nunca
falló — 30s alcanza de sobra para `run_code` pero no para una
generación de imagen real. Fix:
`sandbox/docker_runner.py::run()`/`SandboxExecutor.execute_trusted()`
ganaron `timeout_seconds` (override por ejecución);
`SandboxedSkillTool` lo sube a 300s SOLO cuando la skill declara
`kernel_services`, nunca para el resto.

**Alcance deliberado de esta iteración** (acordado con el usuario):
protocolo completo y genérico, pero un solo servicio real validado de
punta a punta (`image.generate`). Audio/STT/inpaint quedan como el
mismo patrón aplicado después. Browser/OCR/Antivirus documentados como
extensión futura, no construidos — ninguno de los dos últimos existe
todavía como capacidad real en kal.

~45 tests nuevos (`tests/test_kernel_bus_protocol.py`,
`tests/test_kernel_bus.py`, `tests/test_kernel_bus_socket_server.py`,
`tests/test_kernel_bus_image_service_integration.py`, más adiciones a
`tests/test_sandboxed_skill.py` y `tests/test_sandbox_integration.py`).
Suite completa confirmada: 449 passed, 0 regresiones (corrida completa, ~9 min, incluye los tests reales con Docker + SDXL-turbo).

## Nuevo rumbo: agente de programación integrable en un IDE

Después de la Fase 11 (motores multimodales adicionales), decidimos redirigir
el proyecto: la generación multimodal (imagen/audio/video) resultó
decepcionante frente al esfuerzo invertido en la arquitectura de plataforma
(licencias no-comerciales de los modelos locales, calidad limitada, nada de
video real) — la plataforma en sí (permisos, sandbox, tool_integration,
planner, skills, self-modification con aprobación humana) es agnóstica al
dominio y no se tira, solo se redirige hacia el objetivo original: un agente
de programación integrable en un IDE, con navegación web, uso de
herramientas bajo supervisión, y automatización de tareas complejas — lo
multimodal queda como una skill más entre otras, no central.

Primera pieza de ese rumbo: **`vscode-extension/`** — extensión de VS Code
con panel de chat + contexto del editor, cliente sobre la API HTTP que ya
expone `agent_core/orchestrator.py`. Ver `vscode-extension/README.md`.

### Bug real encontrado probando la extensión: reintentos ciegos de código rechazado

Al probar el panel de chat de verdad, un intento del agente de correr código
con `import os` (prohibido por el denylist) hizo saltar el circuit breaker —
la franja de estado quedó en rojo ("circuitos abiertos"). Causa raíz: un
rechazo del validador estático (`sandbox/executor.py`, "Validación estática
falló: ...") no calzaba con ningún tipo de error conocido en
`error_handling/detector.py::classify_sandbox_error`, así que caía en el
fallback genérico `RuntimeError` — y `RuntimeErrorStrategy` reintenta el
mismo código ciegamente (ver su propia limitación ya documentada). Un
rechazo de validación es **determinista**: el código ni llegó a ejecutarse,
reintentarlo produce exactamente el mismo rechazo cada vez — 3 intentos
desperdiciados para un fallo que ya se sabía de entrada que nunca iba a
cambiar.

Se agregó una clasificación `ValidationError` (detectada antes que el resto,
por el prefijo del mensaje) y `ValidationErrorStrategy`, que nunca reintenta
— falla una sola vez, con un mensaje que explica que hace falta código
distinto, no el mismo de nuevo (`error_handling/strategies.py`). Verificado
con un test real contra Docker: un rechazo de validación ya no abre ningún
circuito nuevo (antes sí, en una sola llamada). 6 tests nuevos, 304/304 en
total.

**Qué hacer si el circuit breaker vuelve a quedar abierto (franja roja)**:
1. `GET /status` — `open_circuit_breakers` > 0 confirma que hay uno abierto,
   pero **no bloquea conversaciones nuevas**: la firma del circuito incluye
   el ID de la tarea puntual que falló, así que una tarea nueva nunca
   coincide con una firma vieja. Es seguro seguir usando kal.
2. `GET /audit/tail?n=20` — buscar el evento `circuit_breaker_triggered` más
   reciente y los `error_repair`/`sandbox_execution` justo antes: ahí está
   el código y el motivo real del fallo repetido.
3. Si `./scripts/run_kal.sh` corre con `--reload` (default), el indicador se
   limpia solo apenas se guarda cualquier cambio a un archivo `.py` del
   proyecto (reinicia el proceso, borra el estado en memoria) — no hace
   falta nada más para "resetearlo" en desarrollo.
4. Si el mismo patrón de fallo se repite seguido (no un caso aislado), es
   señal de que falta una clasificación/estrategia — como pasó acá.

### Bug real de uso: el planner sobre-descompone preguntas simples y llama herramientas irrelevantes

Probando la extensión de VS Code, pedidos simples y conversacionales
("hola", "¿qué hace este código, explicame?") terminaban en llamadas a
herramientas completamente irrelevantes (generar audio, navegar a
`google.com`/`example.com`, pedir `system_info`) en vez de responder
directo — a pesar de que el `SYSTEM_PROMPT` de `agent_loop.py` ya decía
explícitamente "preguntas conversacionales se responden directo, sin
llamar a ninguna herramienta".

Comparación en vivo de la misma pregunta ("explicame este código" + código
real pegado en el mensaje): con `use_planner=true` (default anterior) no
terminó ni en 90s y el modelo intentó navegar a dominios al azar; con
`use_planner=false`, respondió bien (respuesta correcta y completa) en
~97s, con como mucho una llamada de herramienta de más. El planner —
pensado originalmente para descomponer objetivos multimodales compuestos
("generá una imagen y despues un audio")— con el modelo local default
(qwen2.5-coder:14b, 14B) tiende a sobre-descomponer hasta preguntas de una
sola acción en pasos artificiales que arrastran herramientas que no
vienen al caso.

**Cambios**: `config.yaml: llm.planning_enabled` pasa a `false` por
defecto (overrideable por request, `ChatRequest.use_planner`). El
`SYSTEM_PROMPT` de `agent_loop.py` gana ejemplos concretos (no solo reglas
abstractas) de cuándo NO llamar herramientas, incluyendo el caso real de
"ratón" (animal vs. dispositivo) que también se observó en pruebas.

**Límite honesto de este fix**: reduce el patrón, no lo elimina — sigue
siendo un modelo local de 14B sin garantías de instruction-following
perfecto. Además, el problema de FONDO de latencia (90-150+ segundos por
respuesta en esta máquina, sin GPU) es un compromiso aparte, inherente a
correr un modelo de este tamaño 100% en CPU — no algo que un ajuste de
prompt o de config resuelva. Alternativas si la latencia importa más que
correr todo local/gratis: un modelo más chico, o el backend `api` (OpenAI,
Fase 11) para el chat en sí (hoy `/chat` solo usa Ollama, no tiene
backend alternativo).

Durante estas pruebas encontré además que este propio proceso de
diagnóstico (varias llamadas directas a `/chat` para reproducir el bug)
agotó los threads del backend y lo dejó completamente colgado — tuve que
terminarlo y pedirle al usuario que lo reinicie desde su terminal. No es
un bug de kal en sí, pero es una limitación real de correr `uvicorn` sin
un límite de concurrencia explícito para llamadas largas al LLM.

### Cambio de modelo: qwen3-coder:30b reemplaza a qwen2.5-coder:14b

Comparación empírica en vivo, misma máquina, mismos pedidos (ver
`config.yaml:llm.default_model` para el detalle completo):

| Pedido | `qwen2.5-coder:14b` | `qwen3-coder:30b` |
|---|---|---|
| "explicame este código" | ~150s, a veces 1 llamada de herramienta de más | 96s, 0 llamadas de herramienta, explicación correcta |
| código que sí necesita ejecutarse | — | 7.4s, llamó a `run_code` correctamente, resultado correcto |
| "hola" | — | 1s, 0 llamadas de herramienta |

`qwen3-coder:30b` es un modelo MoE (mixture-of-experts): "pesa" más en
parámetros totales (30B vs 14B) pero activa solo una fracción por
token, por eso no es más lento en la práctica — y sigue mejor las
instrucciones del `SYSTEM_PROMPT` sobre cuándo no usar herramientas.
Cambiado en `config.yaml` y su respaldo en `utils/config.py`.

Nota encontrada de paso: `uvicorn --reload` solo vigila archivos `.py`
por defecto, no `config.yaml` — si editás el yaml solo, el reload no se
dispara hasta que también toques algún `.py`.

### Hito 2 de la extensión: aplicar cambios propuestos directo al editor

El plan original asumía reusar el pipeline de aprobación humana de
`agent_core/self_modification.py` para este paso. Al investigarlo, ese
pipeline resultó estar construido específicamente para que **kal
modifique su propio repo**: `SelfModificationManager.project_root`
apunta siempre al directorio de kal, y la validación de "sin
regresión" corre el pytest de kal contra una copia temporal — no
generaliza a "editar un archivo de un proyecto arbitrario abierto en
VS Code" (que puede no tener pytest, o ni siquiera ser Python). Además,
por diseño explícito de `audit/audit_log.py` ("se registra aquí, y
SOLO aquí, cualquier evento donde el agente actuó sin intervención
humana directa"), un cambio que el usuario revisa y aprueba con un
click no encaja en ese log — es una acción supervisada, no autónoma.

En vez de generalizar `self_modification.py`, el comando nuevo
(`kal.applySuggestedEdit`, "Kal: Aplicar cambios a la selección") usa
el mecanismo **nativo de VS Code**: kal propone el reemplazo (prompt
que le pide únicamente el código, sin explicación), se abre un diff
nativo (antes/después) y el usuario aprueba con "Aplicar" o
"Descartar" — `WorkspaceEdit` escribe el cambio y el undo (`Ctrl+Z`)
queda cubierto gratis por el propio editor. No requirió ningún cambio
en el backend Python.

**Validado en vivo** contra un proyecto Android/Kotlin real, con dos
bugs reales encontrados y arreglados en el proceso:

1. El diálogo de confirmación "¿Aplicarlo?" (`showInformationMessage`
   sin modal) podía desaparecer solo — por inactividad o al interactuar
   con otra parte de VS Code (p.ej. cerrar el panel de chat) — antes de
   que el usuario llegara a elegir. Arreglado forzándolo a `{ modal:
   true }`, que se queda fijo hasta una elección explícita. Ver
   `vscode-extension/src/applyEdit.ts`.
2. Seleccionar un fragmento que NO se abre y cierra a sí mismo (p.ej.
   una clase entera sin sus llaves de cierre, porque cierran mucho más
   abajo en el archivo) hace que kal complete el fragmento con sus
   propias llaves — que chocan con las reales del archivo y rompen el
   balance al aplicar. No es un bug de kal ni de la extensión en sí,
   es una restricción real de cómo funciona un reemplazo de rango
   exacto: la selección tiene que ser un bloque autocontenido. Detalle
   y ejemplo en `vscode-extension/README.md`.

Como seguimiento directo del punto 2, se agregó `checkBraceBalance()`
(`applyEditFormat.ts`): un conteo simple de `{}`/`()`/`[]` sobre la
selección que, si no está balanceada, avisa con un modal antes de
llamar a kal — el usuario puede continuar igual o cancelar. No es un
parser real (puede confundirse con llaves dentro de strings/
comentarios), por eso es una advertencia salteable, no un bloqueo.

## Estado de este repo

Esto es un **esqueleto**: interfaces, contratos y estructura de módulos definidos,
con implementaciones mínimas o stubs (`NotImplementedError` / TODO) donde falta
lógica real. Pensado para desarrollarse fase a fase según el plan de trabajo.

## Estructura

```
kal/
├── agent_core/          # Orquestador + memoria (corto/mediano/largo plazo)
├── error_handling/       # Detección y reparación de errores + circuit breaker
├── code_analysis/         # Validación estática AST (denylist, chequeos)
├── sandbox/               # Ejecución aislada de código no confiable
├── tool_integration/       # Herramientas multimodales + registro de herramientas dinámicas
├── skills/                  # Skills instalables como plugins (skill.yaml por carpeta)
├── task_execution/          # Registro y ejecución de tareas
├── audit/                    # Log de auditoría inmutable (append-only)
├── utils/                     # Config y logging centralizado
├── tests/                      # Tests
├── config/config.yaml            # Configuración versionada
├── Dockerfile / docker-compose.yml
└── requirements.txt
```

## Principios de diseño (no negociables)

1. **Deny-by-default.** Todo lo que no está explícitamente permitido (red, filesystem,
   capacidades) está bloqueado por defecto en sandbox y herramientas nuevas.
2. **El núcleo no se auto-modifica sin revisión humana.** `agent_core/` y
   `error_handling/` están fuera del alcance de self-modification autónoma
   (ver `agent_core/orchestrator.py`, sección SELF_MODIFICATION_SCOPE).
3. **Ninguna ejecución de código generado ocurre fuera del sandbox.** Sin excepciones.
4. **Toda decisión autónoma relevante queda auditada** de forma inmutable (`audit/`).
5. **Circuit breaker obligatorio** en cualquier bucle de reparación o reintento.

## Arranque rápido

```bash
cp .env.example .env          # completar credenciales
docker compose build
docker compose up
```

## Próximos pasos de desarrollo (ver plan de trabajo completo)

- [x] Fase 0 / Etapa 1: sandbox real con Docker efímero — **verificado con Docker real**
      (41 tests: aislamiento básico, resistencia a fuga, imagen minimizada, auditoría)
- [x] Fase 1 / Etapa 2: memoria en tres niveles — **verificado end-to-end**
      (28 tests: corto plazo RAM, mediano plazo SQLite, largo plazo Chroma + embeddings
      locales vía sentence-transformers, ciclo completo de consolidación y promoción)
- [x] Etapa 3: auto-reparación — **verificado end-to-end con Docker real**
      (35 tests: ImportError con instalación real de PyPI + gate de aprobación humana,
      RuntimeError con checkpoints, clasificación de errores desde stderr, circuit
      breaker probado con fallos persistentes reales)
- [x] Fase 2: multimodal — **verificado con hardware real, 100% local, sin GPU**
      (9 tests: imagen vía diffusers+sd-turbo, audio vía piper-tts, video como
      composición imagen+narración+ffmpeg. 4 bugs reales de API encontrados y
      corregidos en el camino — ver historial de conversación)
- [x] Fase 3: herramientas dinámicas — **verificado (sandbox falso, lógica de pipeline)**
      (12 tests: pipeline propuesta->validación->sandbox->aprobación->activación real.
      3 bugs reales encontrados: herramientas "activadas" nunca quedaban invocables,
      sin clase que ejecutara source_code aprobado, aprobación de red no se traducía
      en network_mode real al ejecutar)
- [x] Fase 4: self-modification — **verificado completo (15/15)**
      (bloqueo de núcleo, código inseguro, path traversal, detección de
      regresión corriendo el test suite real dos veces (baseline vs candidato),
      aplicación con backup, rollback — todo confirmado con pytest real.
      1 bug real encontrado: el bloqueo de núcleo no dejaba un evento de
      auditoría con desenlace, solo un "pending" huérfano — corregido)
- [ ] Fase 5: hardening de seguridad continuo (imagen minimizada ya disponible, ver abajo)
- [x] Fase 6: fundamentos de plataforma — **verificado (60 tests nuevos)**
      (permisos granulares por herramienta estilo Android —
      `tool_integration/permissions.py`, otorgados solo durante la ejecución;
      firma Ed25519 de cada versión de herramienta dinámica activada
      —`tool_integration/signing.py`; versionado real en disco de herramientas
      dinámicas con rollback —`tool_integration/versioning.py` +
      `ToolRegistry.rollback_tool()`— y del propio self-modification
      —`SelfModificationManager.rollback_to()`; memoria con 5 niveles de
      confianza ortogonales al horizonte temporal —`MemoryConfidence`: temporal/
      permanente/verificada/aprendida/externa. 1 bug real encontrado: dos
      `apply()` de self-modification en el mismo segundo generaban el mismo
      nombre de archivo de backup y el segundo pisaba al primero —corregido
      incluyendo el número de versión en el nombre del backup)
- [x] Fase 7: planner + arquitectura de plataforma — **verificado (28 tests nuevos)**
      (el catálogo de herramientas del agente (`agent_core/llm/agent_loop.py`)
      ya no es una lista escrita a mano — se arma en cada `run()` a partir de
      `tool_registry.active_tools()` (imagen/audio/video hoy, browser/skills en
      fases futuras sin tocar este archivo) más tres `Tool` de instancia nuevas
      —`tool_integration/adapters/core_tools.py`: `CodeExecutionTool`,
      `MemoryRememberTool`, `MemoryRecallTool`—, así el núcleo solo decide qué
      herramienta usar, nunca cablea una nueva a mano. `agent_core/llm/planner.py`
      añade un `Planner` que descompone el objetivo en subtareas ordenadas
      (degradando con gracia a un solo paso si el modelo no responde JSON
      parseable o Ollama está caído) y un `PlanningAgentLoop` que las ejecuta en
      secuencia sobre el mismo `AgentLoop`, sintetizando una respuesta final
      cuando hay más de un paso. `/chat` lo expone vía `use_planner` opcional
      por request, con default en `config.yaml: llm.planning_enabled`)
- [x] Fase 8: navegador web (Browser Agent) — **verificado (14 tests nuevos)**
      (`tool_integration/adapters/browser.py`: `BrowserTool` sobre Playwright/
      Chromium, registrada como herramienta estática más — gracias a la Fase 7
      se integró al catálogo del agente sin tocar `agent_loop.py`. Confinamiento
      vía allowlist de dominios (`config.yaml: browser.allowed_domains`),
      **vacío por defecto** (deny-by-default, igual principio que
      `sandbox.network_mode: "none"`): la herramienta existe pero no navega a
      ningún lado hasta que se agreguen dominios explícitos. `Permission.BROWSER`
      sigue rechazada por `SandboxExecutor` para código sandboxeado (herramientas
      dinámicas del agente, `run_code`) — eso no cambió a propósito, solo esta
      herramienta de primera parte (código nuestro, no generado por el agente)
      tiene motor real. Cada navegación queda auditada
      (`EventType.browser_navigation`))

- [x] Fase 9: sistema de skills como plugins — **verificado (15 tests nuevos)**
      (`tool_integration/skills.py`: skills instalables como carpetas bajo
      `skills/<nombre>/` con su propio `skill.yaml` (name/description/version/
      entry_point/enabled/permissions) — mismo principio de plataforma que la
      Fase 7: `registry.py::load_skills()` las registra en `tool_registry` y
      quedan disponibles para el agente sin tocar `agent_loop.py`. Confianza:
      una skill la instala un humano copiando una carpeta (no el agente en
      caliente), así que se importa directo sin pasar por el validador AST de
      `code_analysis` — ese denylist bloquea `os`/`subprocess` pensando en
      código sandboxeado sin filesystem/red real, y una skill de verdad
      necesita esas capacidades. El control real es **deny-by-default a nivel
      de manifiesto**: cada `skill.yaml` trae `enabled: false`, y ni una línea
      de código de una skill deshabilitada se ejecuta jamás — probado
      explícitamente con una skill de prueba que explotaría al importarse.
      Una skill rota (manifiesto inválido, import roto, clase que no es
      `Tool`) nunca tira abajo el arranque ni afecta a las demás skills;
      cada intento de carga real queda auditado (`EventType.skill_loaded`).
      Incluye `skills/system_info/` como skill de ejemplo real (sin
      credenciales ni red) que prueba el pipeline completo de punta a punta)

- [x] Fase 10: auto-diagnóstico y propuesta de auto-reparación — **verificado
      (13 tests nuevos)** — nace de un caso real: la cadena de auditoría se
      rompió por una condición de carrera de desarrollo (ver Fase 8/nota de
      `audit_log.py` abajo), diagnosticada y corregida a mano. Este módulo
      generaliza ese proceso: `AuditLog.diagnose_chain()` distingue
      mecánicamente (sin LLM) una entrada con `event_hash` inválido —indicio
      de manipulación real— de una con solo el encadenamiento roto pero
      contenido íntegro —típico de una condición de carrera entre
      escritores concurrentes—. `agent_core/self_diagnosis.py::
      SelfDiagnosisAgent` toma ese diagnóstico, se lo pasa al LLM pidiendo
      causa raíz + archivo corregido completo, y somete la propuesta a
      través del pipeline de self-modification YA existente (test de
      regresión baseline/candidato, nunca auto-aplica). Disparo **solo bajo
      demanda** (`GET /diagnostics`, `POST /diagnostics/{invariante}/
      self-repair`) — nunca automático, para no gastar llamadas al LLM sin
      que alguien lo pida. Registro extensible (`INVARIANT_CHECKS`): agregar
      un invariante nuevo a futuro es una función `check_xxx()` más, sin
      tocar el resto del pipeline. Cada corrida con intento de LLM queda
      auditada (`EventType.self_diagnosis_run`) — un chequeo sano no genera
      ruido en el log, ninguna llamada al LLM ocurre si el invariante ya
      está bien)
- [x] Fase 11: motores multimodales adicionales + edición de imágenes —
      **verificado (19 tests nuevos)** — `image_gen.py`/`audio_gen.py` ganan
      un backend `"api"` real (OpenAI Images/TTS, antes declarado en
      config.yaml pero nunca implementado) vía HTTP inyectable, apagado por
      defecto (`backend: local` sigue siendo el default — preferencia
      confirmada de local/gratis primero) y usando `IMAGE_GEN_API_KEY`/
      `AUDIO_GEN_API_KEY` (ya declaradas en `.env.example` desde el inicio,
      nunca conectadas hasta ahora — `utils/config.py` ahora sí llama
      `load_dotenv()`). Nuevo `speech_to_text.py` (Whisper vía
      `faster-whisper`, modelo "tiny" ~75MB, 100% local) — verificado de
      punta a punta encadenando dos motores reales (piper genera audio,
      whisper lo transcribe). Nuevo `image_editing.py`: recortar (Pillow),
      eliminar fondo (`rembg`, real, ~176MB) y "upscale" — este último es
      un resize Lanczos de alta calidad, **no IA real**: se investigó
      `realesrgan` pero su dependencia `basicsr` no instala en este entorno
      (incompatible con torchvision recientes), documentado honestamente en
      vez de fingir super-resolución que no existe. "Relleno IA" (inpainting)
      queda diferido a una fase futura. Restricción real de esta fase: el
      disco tenía 2.2GB libres al planificar (subió a ~27GB durante la
      implementación) — los modelos de mayor calidad local (SDXL-Turbo,
      XTTS-v2) no se descargaron aquí por ese motivo, solo se dejó lista la
      arquitectura para activarlos por config)

Las doce piezas construidas hasta ahora (seguridad, memoria, auto-reparación,
multimodal, herramientas dinámicas, self-modification, fundamentos de
plataforma, planner, navegador, skills, auto-diagnóstico, motores
multimodales adicionales) están cerradas: **298/298 tests pasando** contra
sistemas reales (Docker, Chroma, PyPI, modelos de ML locales, pytest real),
no solo código que "debería" funcionar.

### Upgrade de calidad: SDXL-Turbo reemplaza a sd-turbo

`multimodal.image.model` por defecto pasa de `stabilityai/sd-turbo` a
`stabilityai/sdxl-turbo` — misma idea de distilación (1-4 pasos, sin CFG),
pero arquitectura SDXL: mejor calidad, nativo a 1024x1024 (antes 512x512).
Confirmado con descarga y generación reales en este entorno: ~14GB de
descarga (fp32 — float16 no es fiable en CPU, mismo motivo que ya regía
para sd-turbo), y sustancialmente más lento por imagen en CPU (~100s+ acá,
vs segundos con sd-turbo). Efecto en cadena: `video_gen.py` genera una
imagen por escena, así que componer un video ahora tarda proporcionalmente
más por escena también. `image_generation` gana `width`/`height`
opcionales en su `parameters_schema` (antes solo `prompt`) para poder pedir
otras relaciones de aspecto (p.ej. 1024x576 para 16:9) — el código ya
soportaba esto vía config, solo faltaba exponerlo al LLM. Para volver al
modelo liviano anterior: `config.yaml: multimodal.image.model:
"stabilityai/sd-turbo"` + `height`/`width` a 512.

**Importante sobre licencia**: tanto sd-turbo como sdxl-turbo se distribuyen
bajo la licencia no-comercial de investigación de Stability AI — antes de
usar las imágenes generadas para algo comercial, hay que leer esa licencia
directamente (no la resumo acá como asesoría legal). Si el uso comercial de
lo generado importa, las alternativas son: el checkpoint SDXL/SD1.5
completo, no-turbo (licencias más permisivas, pero ~50 pasos — mucho más
lento, se pierde la ventaja de velocidad del turbo), o el backend `api`
(OpenAI Images, Fase 11) con sus propios términos de uso.

### Inpainting real con IA (edición iterativa de imágenes)

Nace de un caso real: pedirle a kal "agregá un queso delante del ratón"
sobre una imagen ya generada no tenía ninguna herramienta real que llamar
— `image_editing.py` solo tenía crop/remove_background/upscale. Nueva
operación `"inpaint"` sobre `runwayml/stable-diffusion-inpainting` (modelo
de difusión COMPLETO, no distilado — mucho más lento que sd-turbo, del
orden de minutos por edición en CPU) vía `AutoPipelineForInpainting`,
mismo mecanismo genérico que ya usa `image_gen.py`. Permite iterar sobre
una imagen ya creada con instrucciones sucesivas, cada edición produce un
artefacto nuevo (nunca sobreescribe el original). Verificado con el modelo
real descargado (~5.5GB) y corriendo inferencia real en CPU (4 tests
nuevos, pasos reducidos a propósito para no volver la suite impráctica).

### Nueva operación: `add_text` — escribir texto real sobre una imagen

Bug real encontrado en uso: pedido "escribí como título 'EL COLIBRI'
arriba de la imagen del colibrí", el modelo llamó a
`image_composition` con `operation: "overlay"` pasando la MISMA imagen
como `base_image_path` y `overlay_image_path` — no existía ninguna
herramienta real para escribir texto, así que improvisó algo sin
sentido (pegar la imagen sobre sí misma no cambia ni un píxel) y aun
así afirmó en su respuesta final que el título se había agregado
correctamente. Ni la generación por difusión (`image_gen.py`,
SDXL-turbo) ni el overlay de `image_composition.py` pueden escribir
texto de forma confiable — los modelos de difusión no renderizan letras
legibles de manera consistente, y overlay solo compone imágenes ya
existentes, no dibuja texto nuevo.

Nueva operación `"add_text"` en `image_editing.py`, 100% Pillow (sin
ningún modelo): `ImageFont.load_default(size=...)` — fuente vectorial
integrada en Pillow desde la versión 10.1, sin depender de que haya
fuentes del sistema instaladas — con contorno negro sobre relleno
blanco (legible sobre cualquier fondo, sin necesidad de saber qué color
tiene esa zona de la imagen, que el modelo tampoco puede ver). Solo dos
parámetros: `text` y `text_position` (`"top"`/`"bottom"`, centrado
horizontalmente) — nada de coordenadas en píxeles que el modelo tendría
que adivinar a ciegas. La descripción de la tool ahora indica
explícitamente usar `add_text` (nunca `image_composition` ni pedirle
texto a `image_generation`) para cualquier pedido de escribir
texto/título sobre una imagen. 5 tests nuevos en
`tests/test_image_editing.py`, incluyendo uno que verifica que los
píxeles de la franja pedida realmente cambian (el fallo original no
cambiaba ninguno).

### Fix real de uso: memoria recuperada vs. observación fresca

Bug real encontrado usando el chat de verdad: el modelo generó una imagen
nueva, pero al reportar la ruta final citó la de una imagen VIEJA — porque
`recall()` trajo una memoria desactualizada y el modelo confió en ella en
vez de en el resultado de su propio `image_generation` de ese mismo turno.
Peor: en el turno siguiente, en vez de corregir, alucinó una ruta
inventada y la guardó con `remember()` como si fuera un hecho verificado.

`MemoryRecallTool.execute()` (`tool_integration/adapters/core_tools.py`)
ahora marca cada resultado con su nivel de confianza entre corchetes
(`[temporal]`, `[verificada]`, etc. — ver `MemoryConfidence` de la Fase 6),
y el `SYSTEM_PROMPT` de `agent_loop.py` instruye explícitamente al modelo a
preferir sus propias observaciones frescas de la conversación actual por
sobre memoria `[temporal]`/`[aprendida]` recuperada, y a no inventar ni
guardar con `remember()` datos que no confirmó. No elimina la posibilidad
de alucinación de un modelo chico — la reduce, no la garantiza.

Nota sobre la Fase 8 (navegador): no se pudo instalar/ejercitar Playwright
con un Chromium real en este entorno de desarrollo (sin red para
descargarlo) — los 14 tests de esa fase cubren la lógica de `BrowserTool`
(allowlist, despacho por acción, manejo de errores, auditoría) con un driver
falso inyectado, mismo patrón que el resto del proyecto usa para no depender
de Docker/Ollama en la suite rápida. La integración real con Playwright/
Chromium queda pendiente de confirmar con
`pip install playwright && playwright install chromium`.

### Deuda técnica conocida (aceptada, no bloqueante)

- `agent_core/memory/mid_term.py` — la búsqueda usa `LIKE` simple
  (substring literal), no búsqueda semántica ni full-text real.
  Suficiente para el volumen actual; migrar a FTS5 de SQLite si el
  volumen de memoria de mediano plazo crece.
- `agent_core/memory/long_term.py` — falta definir la política de
  sanitización de contenido sensible (credenciales, PII) antes de
  persistir a largo plazo. Ver TODO en `_flatten_metadata()`. Debe
  resolverse antes de usar con datos reales de usuario en producción.
- `error_handling/strategies.py::RuntimeErrorStrategy` — no es un
  rollback de estado real, es "reintentar con el mismo código de
  entrada" tras confirmar que existió un checkpoint previo. Un rollback
  más fino requeriría un sistema de versionado de estado que no existe hoy.
- `error_handling/strategies.py::SyntaxErrorStrategy` — sin implementar,
  requiere integrar un modelo generador (LLM) para proponer correcciones.
- `error_handling/strategies.py::ImportErrorStrategy` — el nombre de
  import no siempre coincide con el nombre real del paquete en PyPI
  (p.ej. `sklearn` vs `scikit-learn`); solo funciona cuando coinciden.


## Seguridad: cómo verificar el sandbox tú mismo

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Tests que NO requieren Docker (validador AST + auditoría)
pytest tests/test_ast_validator.py tests/test_audit_log.py -v

# Tests que SÍ requieren Docker real
pytest tests/test_sandbox_integration.py tests/test_sandbox_escape_resistance.py -v

# Opcional: construir la imagen de ejecución minimizada (sin pip/apt/dpkg)
./scripts/build_sandbox_image.sh
pytest tests/test_sandbox_image_hardening.py -v
```

Para usar la imagen minimizada en vez de `python:3.11-slim` por defecto:

```bash
export SANDBOX_IMAGE=kal-sandbox-minimal:latest
```

## Verificación: memoria (Etapa 2)

```bash
# Corto y mediano plazo, sin dependencias pesadas
pytest tests/test_memory_short_term.py tests/test_memory_mid_term.py -v

# Largo plazo: primera vez descarga el modelo de embeddings (~80MB, una sola vez)
pytest tests/test_memory_long_term.py tests/test_memory_manager.py -v
```

## Verificación: auto-reparación (Etapa 3)

```bash
# Sin Docker
pytest tests/test_error_classification.py tests/test_import_error_strategy.py \
       tests/test_runtime_error_strategy.py tests/test_error_detector.py -v

# Con Docker — ciclo completo end-to-end, instala un paquete real de PyPI
pytest tests/test_task_executor_sandboxed.py -v
```

## Verificación: multimodal (Fase 2)

```bash
pip install diffusers accelerate piper-tts huggingface_hub moviepy
sudo apt install ffmpeg   # binario del sistema, no es paquete de pip

pytest tests/test_image_gen.py tests/test_audio_gen.py tests/test_video_gen.py -v
```

## Verificación: herramientas dinámicas (Fase 3)

```bash
pytest tests/test_tool_registry.py -v   # usa un sandbox falso, no requiere Docker
```

## Verificación: self-modification (Fase 4)

```bash
pytest tests/test_self_modification.py -v
```

15/15 confirmado. Los primeros 10 son rápidos (no invocan pytest real
como subproceso); los últimos 5 sí lo hacen (corren un pytest real dos
veces contra un proyecto sintético de prueba) y por eso son algo más
lentos (~2s en total).

## Frontend + chat (Ollama)

kal ahora tiene un "cerebro": `agent_core/llm/agent_loop.py` es un loop
de razonamiento estilo ReAct que usa un modelo local vía Ollama para
decidir qué hacer, y ejecuta acciones reales (código en sandbox,
memoria, generación multimedia) — nunca solo texto. El frontend
(`frontend/`) es una página estática (sin build step, HTML+CSS+JS
vanilla) servida por el mismo proceso de FastAPI.

### Arrancar

```bash
pip install -r requirements.txt   # agrega `requests`, ya deberías tener el resto

# Docker debe estar corriendo ANTES de arrancar — TaskExecutor se
# conecta al iniciar, no de forma perezosa. Ollama es opcional al
# arrancar (solo afecta /chat), pero sin él el chat no funciona.
./scripts/run_kal.sh
```

Abrir `http://localhost:8000` — el frontend se sirve ahí mismo.

### Qué hace la interfaz

- **Chat**: escribís un objetivo, kal decide qué herramientas usar
  (código sandboxeado, memoria, generación de imagen/audio) y responde.
- **Franja de estado** (arriba): indicadores en vivo de las garantías
  de seguridad reales — cadena de auditoría íntegra, modo de red del
  sandbox, circuitos abiertos, aprobaciones pendientes, disponibilidad
  de Ollama. No es decoración, son las propiedades que hacen que kal
  sea seguro de usar.
- **Panel lateral**: tareas recientes, búsqueda en memoria, herramientas
  activas/pendientes de aprobación (con botón para aprobar), propuestas
  de self-modification (con botón para aplicar), y el tail del registro
  de auditoría.

### Modelo por defecto

`qwen3-coder:30b` (reemplazó a `qwen2.5-coder:14b` tras comparación
empírica en vivo, misma máquina, mismos pedidos):

| Pedido | `qwen2.5-coder:14b` (post-fix del planner) | `qwen3-coder:30b` |
|---|---|---|
| "explicame este código" (código ya en el mensaje) | ~150s, a veces 1 llamada de herramienta de más | 96s, 0 llamadas de herramienta, explicación correcta |
| "ejecutá esto: `print(sum(range(1,11)))`" | — (no reprobado con este modelo) | 7.4s, llamó a `run_code` correctamente, resultado correcto (55) |
| "hola" | — | 1s, 0 llamadas de herramienta, respuesta directa |

`qwen3-coder:30b` es un modelo MoE (mixture-of-experts): aunque "pesa"
más en parámetros totales (30B vs 14B), activa solo una fracción por
token, lo que explica que en la práctica no sea más lento — y en el
caso de necesitar una herramienta, fue notablemente más rápido. Además
sigue las instrucciones del `SYSTEM_PROMPT` sobre cuándo NO usar
herramientas mejor que el modelo anterior, sin perder precisión cuando
sí hace falta usarlas.

Cambiable en `config.yaml:llm.default_model` (y su default de
respaldo en `utils/config.py`) o desde el selector del propio
frontend. `glm-5.1:cloud` (o cualquier modelo `:cloud`) nunca es el
default — no es local, y usar un modelo en la nube debe ser una
decisión explícita, no un default silencioso.

Nota: `uvicorn --reload` solo vigila archivos `.py` por defecto, no
`config.yaml` — si editás el yaml solo, el reload no se dispara hasta
que también toques algún `.py` (por eso en la práctica conviene editar
`utils/config.py` y `config.yaml` juntos, o hacer `touch` a cualquier
`.py` después para forzar el reload).

### Verificación

```bash
pytest tests/test_agent_loop.py -v   # lógica del loop, sin Ollama ni Docker reales
```

Lo que este archivo NO puede probar sin Ollama corriendo de verdad: si
el formato exacto de `tool_calls` que devuelve tu versión de Ollama
coincide con lo que asumí en `ollama_client.py` (documentado como nota
de transparencia en ese archivo — mismo patrón que tuvimos con
piper-tts y moviepy: probablemente funcione, pero no lo sabremos hasta
que lo confirmes).

## Revisión de seguridad (2026-07-09) y token administrativo

Pedida explícitamente ("analiza esto como especialista en seguridad
informática, busca vulnerabilidades") sobre todo el proyecto, con foco
en lo construido en la sesión del Kernel Service Bus. Se encontraron 9
hallazgos reales, priorizados por severidad; los dos críticos ya están
corregidos, el resto queda documentado como deuda de seguridad
conocida y aceptada por ahora.

**Crítico #1 — API del orquestador sin autenticación, publicada a la
LAN.** `docker-compose.yml` mapeaba `agent` como `"8000:8000"`, que
Docker bindea a `0.0.0.0` del host por defecto — cualquier dispositivo
de la red local (no solo esta máquina) podía llamar a
`POST /self-modification/apply` o `/tools/{name}/approve` con
`approved_by` como un string libre elegido por el propio cliente, sin
verificar identidad real. Todo el modelo de "aprobación humana
obligatoria" que describe el resto del código se reducía, en la
práctica, a un campo de formulario.

**Crítico #2 — `self_modification.py::propose()` ejecuta el código
candidato de verdad, fuera de Docker.** `_run_tests()` corre `pytest`
vía `subprocess` directo en el host (no en un contenedor) sobre una
copia del proyecto con el archivo ya modificado — pytest importa ese
archivo para poder correr los tests, así que el código propuesto se
ejecuta con los privilegios del propio proceso de kal. La única
barrera es el filtro AST de `code_analysis/denylist.py`, que su propio
docstring reconoce como heurístico y con un hueco conocido y aceptado
(el backstop real, en el resto del proyecto, es Docker — acá no
interviene). Combinado con el hallazgo #1, un atacante en la red podía
lograr ejecución de código en el host con solo llamar a
`/self-modification/propose`, sin necesitar `apply()`.

**Corrección aplicada** (dos capas independientes, no una sola):

1. `docker-compose.yml`: `agent` ahora publica `"127.0.0.1:8000:8000"`
   — el puerto deja de ser alcanzable desde la LAN.
2. Token administrativo nuevo (`utils/admin_token.py`): generado una
   sola vez, persistido en `data/keys/admin_token` (permisos 0600).
   `agent_core/orchestrator.py` lo exige (header `X-Kal-Admin-Token`,
   comparación con `secrets.compare_digest`) en los 5 endpoints que
   hacen de facto de aprobación humana:
   `/self-modification/propose`, `/self-modification/apply`,
   `/tools/{name}/approve`, `/tools/{name}/rollback`,
   `/diagnostics/{invariant}/self-repair`. El token se imprime en el
   log al arrancar (`http://localhost:8000/?admin_token=...`);
   `frontend/app.js` lo toma una vez de la URL, lo guarda en
   `localStorage` y lo manda como header en cada llamada — no hace
   falta pegarlo de nuevo en visitas siguientes.

Tests nuevos: `tests/test_admin_token.py` (creación/persistencia del
token, permisos 0600) y `tests/test_orchestrator_admin_auth.py` (los 5
endpoints rechazan sin token o con uno incorrecto, y SÍ llegan a la
lógica real — no un simple 200, sino un error de negocio 400/404 en
vez de 401 — con el token correcto; usa `target_path`/`proposal_id`/
nombres de herramienta inexistentes a propósito, para no pagar el
costo real de copiar el proyecto y correr el test suite completo dos
veces solo para probar el gate).

**Hallazgos NO corregidos esta vez** (documentados, no bloqueantes
para el uso normal de un usuario único en su propia máquina, pero
reales):

- `KernelBusSocketServer._read_line()` (`kernel_bus/socket_server.py`)
  no limita el tamaño de línea — una skill que manda datos sin salto
  de línea agota memoria de un hilo del proceso HOST (de confianza),
  no del contenedor aislado.
- Sin lock alrededor del pipeline compartido de `ImageService` — el
  agente y cualquier cantidad de skills concurrentes golpean el mismo
  objeto de PyTorch sin sincronización.
- Errores internos del kernel bus se devuelven como texto crudo a la
  skill; si esa misma skill también tiene permiso de red, podría
  exfiltrar detalles del host.
- `KernelServiceBus.dispatch()` resuelve la acción con `getattr`
  genérico, sin una lista explícita de acciones "seguras" por
  servicio — hoy inofensivo con un solo servicio, a vigilar cuando se
  agreguen más.
- `docker_runner.py::_prepare_workdir` deja el directorio de trabajo
  en 0777 en el host, legible/escribible por cualquier usuario local
  en un host compartido.
- `_artifact_url()` en `orchestrator.py` no es `..`-safe por sí sola
  (depende de que Starlette bloquee el traversal real); hoy no hay
  ningún camino conocido donde el atacante controle `uri` lo
  suficiente para explotarlo.

## eBPF — observabilidad y enforcement a nivel de kernel (fases E, 2026-07-10)

Plan de 8 fases propuesto por el usuario para agregar una capa de
observabilidad/enforcement de kernel (eBPF) al sandbox, evitando
arrancar directo con Tetragon completo (pensado para clusters, más
pesado de lo que pide un NUC) — primero validar con `bpftrace` puntual
y datos propios, recién después decidir el mecanismo definitivo con
esos datos, nunca con benchmarks públicos de un contexto distinto
(clusters de cientos de nodos con carga sostenida vs. ráfagas cortas en
un solo host).

**Fase E-1 (compatibilidad del kernel) — ejecutada**:
```
uname -r                    → 7.0.0-27-generic
/sys/kernel/btf/vmlinux     → existe (CO-RE viable)
CONFIG_BPF_LSM              → y (compilado)
/sys/kernel/security/lsm    → lockdown,capability,landlock,yama,apparmor,ima,evm
```
Hallazgo importante no obvio: `CONFIG_BPF_LSM=y` (compilado) no implica
que el LSM de BPF esté ACTIVO — `bpf` no aparece en
`/sys/kernel/security/lsm` ni hay `lsm=` en `/proc/cmdline`. Hoy: observación
vía tracepoints funciona perfecto (bpftrace, Tetragon en modo tracing);
enforcement real vía hooks LSM NO, hasta agregar `bpf` al parámetro
`lsm=` de GRUB y reiniciar — decisión explícita a tomar recién en la
Fase E3, con su propio riesgo/downtime, no un detalle de config menor.

**Activado (2026-07-10), decisión explícita del usuario**: se agregó
`bpf` a `GRUB_CMDLINE_LINUX_DEFAULT` (`lsm=landlock,lockdown,yama,integrity,apparmor,bpf`)
en `/etc/default/grub` (con backup previo del archivo), `update-grub`,
y reinicio real de la máquina. Confirmado post-reboot:
`/sys/kernel/security/lsm` ahora incluye `bpf`, mismo kernel
(`7.0.0-27-generic`, sin otros cambios). El prerequisito que bloqueaba
la Fase E5 (enforcement real) queda resuelto.

**Fase E6 (DNS rebinding en browser.py) — implementada, adelantada
respecto al resto del plan**: de las 8 fases, esta era la única que
cierra una brecha real hoy (las demás refuerzan garantías que Docker
ya provee — ver más abajo), así que se priorizó. `_is_domain_allowed()`
solo comparaba el hostname (string) contra `browser.allowed_domains`
— nunca validaba la IP real a la que Chromium se conectaba. Un dominio
permitido cuyo DNS apuntara (rebinding, o mala configuración) a una IP
privada/reservada (127.0.0.1, 169.254.169.254, RFC1918, etc.) pasaba
sin problema. Fix: `PlaywrightBrowserDriver` ahora también devuelve la
IP real de la conexión vía `Response.server_addr()` de Playwright — la
IP que Chromium mismo reportó haber usado, no una resolución DNS
aparte hecha por nosotros, así que no hay ventana de carrera entre "lo
que resolvimos" y "a dónde se conectó de verdad" (a diferencia de
hacer nuestra propia resolución, que sí tendría ese hueco clásico de
TOCTOU). `_reject_if_unsafe_destination()` (antes `_reject_if_redirected`,
renombrado porque ahora hace dos chequeos) valida esa IP con
`ipaddress` antes de exponer cualquier contenido — falla cerrado
(rechaza) si la IP no se pudo determinar.

Límite conocido y aceptado: valida solo la navegación principal, no
subrecursos que la propia página cargue después (una imagen/fetch
embebida apuntando a una IP interna es un pedido que hace el
navegador, no interceptado hoy); y si Chromium sirve una respuesta
desde caché sin conexión viva, `server_addr()` devuelve `None` y se
rechaza (puede sobre-rechazar algún caso legítimo raro, se prefiere
eso a asumir que es seguro).

Tests nuevos en `tests/test_browser_tool.py`: 13 tests (7 IPs no
seguras parametrizadas — privada/loopback/link-local/reservada/no-
determinable — para la acción `text`, más rechazo específico para
`screenshot` y `links`, IP pública sigue funcionando, rechazo
auditado, y unit tests de `_is_unsafe_ip()`). Suite completa
confirmada tras este fix: 469 passed, 0 regresiones (subiendo de 456).

**Fase E1 (prototipo bpftrace) — corrida real completada, concepto
validado**: `sandbox/ebpf/prototype_syscalls.bt` traza `connect` (con
IP/puerto real vía `ntop()`), `setuid`/`setresuid`, `ptrace`, y
`execve` (vía `sched:sched_process_exec`, más confiable que el
tracepoint de syscall crudo). `sandbox/ebpf/measure_overhead.sh` corre
`tests/test_sandbox_escape_resistance.py` dos veces (con y sin el
prototipo activo) y compara tiempo/memoria — pide sudo una sola vez
para bpftrace (el usuario lo corrió él mismo; Claude no tiene sudo sin
contraseña en esta máquina, confirmado).

Bug real encontrado y corregido en la primera corrida: `AF_INET` no es
un identificador reconocido por bpftrace v0.25.0 (falla con "Unknown
identifier") — se reemplazó por el valor numérico fijo `2` (AF_INET en
Linux, todas las arquitecturas), con el porqué documentado inline en
el `.bt`.

**Overhead real medido en el NUC** (7 tests, `test_sandbox_escape_resistance.py`):

| | Sin eBPF | Con eBPF |
|---|---|---|
| CPU | 27% | 27% |
| Tiempo total | 1.33s | 1.30s |
| RSS máximo | 61684 KB | 61624 KB |

Indetectable para esta carga — la diferencia está dentro del ruido de
una corrida a otra. Confirma en datos propios (no en benchmarks de
cluster) que bpftrace no se nota en el patrón de ráfagas cortas de kal.

**Cross-validación exitosa**: el prototipo capturó
`SETUID pid=... comm=python uid_pedido=0` — exactamente el intento de
`setuid(0)` de `test_privilege_escalation_via_setuid_is_blocked`, de
forma independiente al propio test de Docker. Cero eventos de
`CONNECT`/`PTRACE`, correctamente (ningún test de ese archivo ejercita
esos dos). Sin falsos positivos.

**Limitación confirmada en la práctica**: sin filtro de cgroup, el
`EXECVE` capturó también toda la maquinaria propia de Docker lanzando
cada contenedor (`docker`, `runc`, `containerd-shim-runc-v2`,
`docker-init`, y varios `/proc/self/fd/6` — runc re-ejecutándose desde
un memfd sellado, comportamiento normal, no una señal de ataque) — con
solo 7 tests ya compite con la señal real; la Fase E7 necesita el
filtro de cgroup preciso (Docker cgroup driver=systemd, cgroup v2 en
esta máquina) para que esto sea usable en producción sin ahogarse en
ruido de infraestructura.

**E1 queda cerrada con datos reales.**

**Fase E2 (esquema de eventos + integración con la auditoría) —
implementada** (diseño puro, sin daemon todavía — eso es E4):

- `sandbox/ebpf/syscall_events.bt`: mismas 4+1 syscalls que
  `prototype_syscalls.bt` (validado en E1, dejado intacto a
  propósito), pero cada evento como una línea JSON en vez de texto
  libre, para que se pueda parsear de forma confiable en vez de con
  regex sobre texto pensado para humanos.
- `sandbox/ebpf/event_consumer.py`: `parse_event_line()` (JSON ->
  `SyscallEvent`, `None` en vez de excepción para ruido no-evento de
  bpftrace — banners, warnings), `record_syscall_event()`,
  `consume_stream()` (procesa un stream completo, tolera líneas
  inválidas mezcladas). Todo escribe a la auditoría exclusivamente vía
  `audit_log.record()` — el mismo escritor único con lock de
  `fcntl.flock` que ya usa el resto del proyecto, nunca un lock
  aparte. Justo el punto que motivó esta fase (ver justificación
  original del plan): no repetir la condición de carrera de
  múltiples escritores que ya se corrigió en `audit_log.py`.
- Nuevo `EventType` en `audit/audit_log.py`: `"syscall_policy_violation"`.

**Decisión de diseño importante, no pedida explícitamente por el plan
original pero necesaria dado lo que mostró la corrida real de E1**: no
todo syscall observado se audita como "violación". `connect`/`setuid`/
`setresuid`/`ptrace` dentro de un contenedor del sandbox SIEMPRE son
inesperados (`network_mode=none`, `cap_drop=ALL`, usuario no-root — no
hay ningún escenario legítimo), así que verlos ya es una violación
real. `execve` NO se audita como violación: la corrida real de E1
mostró que la mayoría de los `execve` son la propia maquinaria de
Docker (`docker`/`runc`/`containerd-shim`) lanzando el contenedor —
auditar cada uno diluiría el evento hasta volverlo inútil para
alertar de verdad. Si más adelante hace falta visibilidad de qué se
ejecuta dentro del sandbox, debería ser un `event_type` propio, nunca
mezclado con `syscall_policy_violation`.

Sobre quién corre esto en producción (E4): el consumidor de eventos de
kernel es una superficie privilegiada nueva en la arquitectura —
debería vivir en el mismo tier de confianza que `sandbox_runner` (ya
el único con acceso al socket de Docker), no como un cuarto componente
privilegiado distinto.

12 tests nuevos en `tests/test_ebpf_event_consumer.py` (parseo de
eventos válidos, ruido de bpftrace ignorado sin excepción, JSON sin
campos requeridos ignorado, violación vs. telemetría rutinaria,
`consume_stream` sobre un stream realista mezclado).

**Fase E3 (decisión: Tetragon standalone vs. programa propio) —
decidida**: **programa propio (bpftrace + `event_consumer.py`), no se
adopta Tetragon.**

Motivo, con los datos reales de E0/E1/E2:

- El overhead de nuestro propio prototipo ya es indetectable en esta
  máquina (ver E1: 27% CPU / 1.30-1.33s / ~61.6-61.9MB RSS, sin
  diferencia real con/sin eBPF activo). No hay un problema de
  rendimiento que Tetragon resolvería mejor.
- El alcance de enforcement ya quedó deliberadamente acotado en el
  plan (E5: solo `connect`/`setuid` dentro del sandbox, los dos casos
  sin ambigüedad) — no es una superficie de detección abierta y
  creciente que se beneficiaría del motor de políticas más rico de
  Tetragon (pensado para bastante más que 4-5 syscalls puntuales).
- `BPF_LSM` no está activo todavía en este kernel (ver Fase E-1) — el
  enforcement real vía LSM que Tetragon ya trae resuelto no es
  utilizable HOY de cualquier forma; activarlo requiere la misma
  decisión de reiniciar con `lsm=bpf` sin importar qué mecanismo se
  elija.
- Ya tenemos, funcionando y testeado (E1/E2), exactamente lo que hace
  falta para el alcance actual: captura de los 4 syscalls, formato de
  evento propio, y un consumidor que escribe a la auditoría de forma
  segura. Adoptar Tetragon significaría reemplazar algo que ya
  funciona por un daemon persistente con su propio ciclo de release y
  superficie de cadena de suministro — un costo continuo real a
  cambio de un beneficio que hoy no necesitamos.

Lo que Tetragon SÍ resuelve mejor y que el camino propio todavía debe
construir (documentado como trabajo pendiente real, no ignorado): la
atribución precisa por contenedor/cgroup (ver limitación de E1 — acá
el filtro es `comm == "python"`, no cgroup) y el propio motor de
enforcement LSM, el día que haga falta bloquear de verdad en E5.

**Límite honesto de esta decisión** (mismo criterio que el resto de
esta sección): no se instaló ni se midió Tetragon en este NUC — la
comparación es estructural (alcance, superficie de confianza,
modelo de daemon vs. efímero), no una corrida lado a lado con números
de Tetragon propios. Se decidió así a propósito: instalar una
herramienta que probablemente no se va a adoptar solo para
benchmarkearla es, en sí mismo, el tipo de infraestructura sin
demanda real validada que este proyecto evita (mismo criterio ya
aplicado a F3/F4 y a no construir servicios del Kernel Bus sin
consumidor real). **Condición de revisión explícita**: si en E5/E7 el
alcance crece más allá de estos 4-5 syscalls puntuales, o si la
atribución por cgroup construida a mano resulta más frágil/costosa de
mantener de lo esperado, ahí sí vale la pena volver a poner a Tetragon
en la balanza con datos propios reales.

**Fase E4 (despliegue en modo solo-observación) — implementada**:

- `sandbox/ebpf/observer.py`: `run(lines)` consume un stream de
  eventos línea por línea (a diferencia de
  `event_consumer.consume_stream()`, cuenta de forma incremental para
  no perder el número real si se corta a mitad de una sesión larga —
  el caso normal de uso acá es Ctrl+C, no un stream que termina solo).
  `main()` es el entry point CLI (`python3 -m sandbox.ebpf.observer`),
  lee de stdin por defecto.
- `sandbox/ebpf/run_observer.sh`: arma el pipe completo —
  `sudo bpftrace sandbox/ebpf/syscall_events.bt | python3 -m sandbox.ebpf.observer`.
  El pipe separa el privilegio correctamente: bpftrace corre con sudo
  (lo mínimo necesario para cargar los programas), el consumidor
  Python corre SIN privilegios (solo lee texto y llama a
  `audit_log.record()`, que ya se protege solo con su propio lock).

**Decisión de arranque, tomada explícitamente por el usuario (no
asumida)**: manual, con sudo, por sesión — ni una regla sudoers
permanente ni un servicio systemd todavía. Encaja con que E4 es una
ventana de evaluación acotada ("correr durante uso real el tiempo
suficiente para conocer la tasa de falsos positivos"), no un
compromiso a que esto quede siempre encendido — esa decisión de
producción (systemd, sudoers) queda para E7 si esta evaluación
resulta útil.

Hallazgo al diseñar esto, no en el plan original: la separación
"`agent` sin acceso a Docker / `sandbox_runner` como único privilegiado"
de `docker-compose.yml` es un diseño para un despliegue containerizado
— en el uso real actual (kal corriendo directo en el host, vía
`uvicorn`/`pytest` en el venv, confirmado en toda esta sesión) no hay
dos procesos separados: es un solo proceso corriendo con el usuario
normal, que ya toca Docker directo (`docker.from_env()`). La brecha de
privilegio real no es "agent vs. sandbox_runner" sino, simplemente,
"kal corre sin privilegios, bpftrace necesita root" — el pipe con sudo
acotado a un solo comando es la respuesta mínima a ESA brecha real, no
a la de docker-compose (que hoy no está en uso).

5 tests nuevos en `tests/test_ebpf_observer.py` (stream mixto
realista, stream vacío, interrupción por Ctrl+C sin perder el conteo,
escritura confirmada al log de auditoría único, `main()` sin
excepciones).

**Evaluación real hecha (2026-07-10), con el usuario corriendo
`bash sandbox/ebpf/run_observer.sh` en vivo mientras usaba kal (QR
generado, imagen generada, un intento de navegación a YouTube
rechazado por el propio `browser.py` antes de tocar la red) — dos
hallazgos reales, los dos corregidos en el momento**:

1. **Bug real de filtrado**: el proceso PRINCIPAL de kal (arranca como
   `.venv/bin/python3 .venv/bin/uvicorn ...`) tiene `comm` real
   `"python3"`, no `"python"` — confirmado con
   `ps -eo pid,comm,cmd | grep uvicorn`. El filtro `comm == "python"`
   de los `.bt` lo dejaba completamente invisible (las skills
   sandboxeadas sí aparecían porque `docker_runner.py` invoca
   literalmente el binario `"python"`, sin el 3, dentro del
   contenedor). Corregido en `syscall_events.bt` y
   `prototype_syscalls.bt`: el filtro ahora acepta `"python"` o
   `"python3"`.

2. **Falso positivo real, más importante**: una vez arreglado el bug
   anterior, la primera corrida con el proceso principal visible
   mostró 12 violaciones de tipo `connect` — pero eran conexiones
   `AF_UNIX` del propio kal (probablemente resolución de nombres vía
   `systemd-resolved` u otra actividad interna normal), no de una
   skill sandboxeada. Esto reveló que el filtro por `comm` **no
   distingue una skill sandboxeada (donde `connect`/`setuid` siempre
   son una violación real) del proceso principal de kal (que sí tiene
   red real — hablar con Ollama es normal)**. Con enforcement
   activado, esto habría bloqueado al propio kal.

   **Fix, adelantando parte de la Fase E7**: nueva función
   `sandbox/ebpf/event_consumer.py::is_sandboxed_container_process(pid)`
   — lee `/proc/<pid>/cgroup` y confirma que el proceso vive bajo un
   cgroup de Docker (`docker-<id>.scope` del driver systemd, o
   `/docker/<id>` del driver cgroupfs) antes de tratar la syscall como
   violación real. `record_syscall_event()` ahora exige las dos
   condiciones: syscall en `VIOLATION_SYSCALLS` **y** proceso dentro
   de un contenedor. Heurística de mejor esfuerzo para modo
   observación (lee /proc después del hecho, fail-closed si el proceso
   ya no existe) — un enforcement real (E5) necesitaría este mismo
   chequeo dentro del propio programa eBPF
   (`bpf_get_current_cgroup_id()`), no desde afuera.

5 tests nuevos en `test_ebpf_event_consumer.py` (4 para
`is_sandboxed_container_process` — driver systemd, driver cgroupfs,
proceso normal del host, archivo de cgroup inexistente — más el caso
de regresión del falso positivo real). `test_ebpf_observer.py` no
sumó tests nuevos, solo se ajustó para forzar el filtro de cgroup a
`True` vía monkeypatch (ya no depende de un pid real). 22 tests
totales entre los dos archivos, todos pasando.

**E4 queda cerrada de verdad**: mecanismo funcionando, evaluación real
hecha, y — más importante — encontró y corrigió dos bugs reales antes
de llegar a E5. Exactamente el propósito de esta fase.

**Reverificación con el fix de cgroup activo (2026-07-10)**: nueva
corrida en vivo, uso normal de kal (chat) durante ~2:20 min — 197
líneas procesadas, **0 violaciones**. Confirma que el filtro de cgroup
excluye correctamente la actividad legítima del proceso principal,
cerrando el falso positivo real encontrado en la corrida anterior.

**Fase E5 (enforcement selectivo) — decidida: NO desplegar bloqueo
real por ahora, prerequisito resuelto, diseño documentado.**

Con `BPF_LSM` ya activo (ver Fase E-1 arriba), el prerequisito técnico
para poder bloquear de verdad (no solo observar) está resuelto. Aun
así, se decidió explícitamente NO construir el programa de enforcement
esta sesión, por la misma disciplina de "validar antes de comprometerse"
de todo este plan:

- **Beneficio marginal**: dentro del sandbox, `connect` y `setuid` YA
  fallan estructuralmente por Docker (`network_mode=none`,
  `cap_drop=ALL`) — no hay ninguna ruta de red ni capability real, así
  que ya fallan solos. El valor de E5 sería "detectar más temprano +
  auditar", no cerrar un agujero que hoy esté abierto.
- **Riesgo real y asimétrico**: un hook LSM (a diferencia de un
  tracepoint, que solo observa) se aplica a TODO el sistema, todos los
  procesos — no solo a los contenedores del sandbox — a menos que el
  propio programa verifique el cgroup correcto antes de decidir
  bloquear. Un error en esa lógica de scoping no rompe "una skill": en
  el peor caso, ningún proceso del sistema podría conectarse a la red
  o hacer `setuid` hasta revertirlo. Y no hay forma de validar este
  tipo de programa sin sudo real (que Claude no tiene en esta
  máquina) — la primera prueba real habría sido directamente en la
  máquina de producción del usuario.

Diseño que quedaría listo para implementar si en el futuro el
cálculo cambia (más plataformas, más servicios expuestos, necesidad
real de contención adicional): programa `BPF_PROG_TYPE_LSM` enganchado
a `security_socket_connect`/`security_task_fix_setuid`, con el mismo
chequeo de cgroup que ya construimos para observación (ver
`is_sandboxed_container_process`) pero implementado DENTRO del propio
programa eBPF vía `bpf_get_current_cgroup_id()` — nunca post-hoc desde
Python, que es aceptable para observar pero no para respaldar una
decisión de bloqueo en tiempo real.

**Fase E7 (tests permanentes + documentación honesta) — en gran parte
ya cumplida durante E1-E4, cerrada acá formalmente**:

- Tests permanentes: 22 tests entre `test_ebpf_event_consumer.py` y
  `test_ebpf_observer.py`, cubriendo parseo de eventos, la distinción
  violación/telemetría, y — el más importante — el filtro de cgroup
  que encontró y corrigió el falso positivo real de la Fase E4.
- Filtro de cgroup preciso: ya construido (adelantado desde esta misma
  evaluación, no quedó pendiente) — `is_sandboxed_container_process()`
  en `sandbox/ebpf/event_consumer.py`.
- Documentación honesta de qué cubre esta capa y qué NO:
  - Cubre: observación (nunca bloqueo, ver decisión de E5) de
    `connect`/`setuid`/`setresuid`/`ptrace`/`execve` dentro de
    contenedores del sandbox, con atribución correcta por cgroup
    (no por `comm`, que resultó insuficiente en la práctica),
    registrado en la cadena de auditoría existente sin un segundo
    escritor paralelo.
  - NO cubre: un exploit del kernel mismo (eBPF corre dentro del mismo
    kernel que se quiere vigilar — un bug de kernel que comprometa el
    kernel compromete también esta capa); un bug en el propio programa
    eBPF o en `event_consumer.py` (validado con tests, pero sin la
    garantía formal que tendría, por ejemplo, un programa verificado
    matemáticamente); subrecursos de una página web cargados por
    `browser.py` después de la navegación principal (ver Fase E6);
    cualquier plataforma que no sea Linux (eBPF no existe en
    Windows/macOS, ver conversación de esta sesión) — la garantía de
    esta capa es explícitamente Linux-only.

**El plan de 8 fases queda cerrado**: E-1 a E7, cada una con datos
reales de esta máquina, no de benchmarks ajenos ni de intuición —
exactamente el criterio con el que el usuario lo planteó desde el
principio.

## Tope estructural a repeticiones de herramienta (2026-07-10)

Reportado por el usuario en uso real: pedirle una imagen casi siempre
generaba dos; un pedido puntual ("genera una raqueta de tenis")
generó la imagen correcta UNA vez y después, en el mismo turno, TRES
imágenes más de paisajes sin relación, sin llegar nunca a una
respuesta final (agotó `max_agent_steps`). Confirmado en
`logs/agent.log`:
```
Generando imagen (2 pasos): 'Una raqueta de tenis profesional...'
Generando imagen (2 pasos): 'A serene landscape with a mountain...'
Generando imagen (2 pasos): 'A serene landscape with a mountain range...'
Generando imagen (2 pasos): 'A beautiful landscape with mountains...'
Agente agotó max_steps=8 sin respuesta final para: 'genera una raqueta de tenis'
```

Primer intento de fix (regla nueva en `SYSTEM_PROMPT`: "generá
exactamente lo pedido, no encadenes herramientas extra") ayudó en un
caso (un pavo real salió bien, una sola imagen) pero **no evitó** este
segundo caso — confirma que una instrucción de prompt sola no es
una barrera confiable: el modelo no ve el resultado visual de una
generación (`_artifact_to_observation` solo devuelve la ruta del
archivo como texto), así que no está "reintentando por mala calidad"
— pierde el hilo de la tarea y empieza a divagar.

**Fix estructural**: `agent_core/llm/agent_loop.py::AgentLoop.run()`
ahora cuenta cuántas veces se llamó a CADA herramienta (por nombre)
dentro del mismo turno — más allá de `settings.llm.max_tool_repeats`
(nuevo, default `3`), la llamada se rechaza SIN ejecutar (no se gastan
los ~2-2.5 minutos reales que cuesta cada generación en esta máquina)
y se le devuelve al modelo un error explícito pidiéndole que responda
ya. El contador es independiente por nombre de herramienta — pedir 2
imágenes y después ejecutar código no consume el mismo cupo.

Configurable en `config.yaml: llm.max_tool_repeats` (o `run(...,
max_tool_repeats=N)` por llamada, mismo patrón que `max_steps`). 4
tests nuevos en `tests/test_agent_loop.py` (rechazo más allá del
límite sin ejecutar, límite exacto funciona normal, conteo
independiente por herramienta, default desde config) — 30 tests
totales en ese archivo. Suite completa confirmada: 495 passed, 0
regresiones.

## Firma de identidad del autor para skills (F3 del plan de marketplace, 2026-07-10)

Retomando el plan de distribución general/marketplace: el usuario
confirmó explícitamente que kal es para uso general, no personal
("open route") — cada usuario instala su propio kal y sus propias
skills, con la meta de tener comunidad y marketplace a largo plazo.
Revisando qué falta para que eso sea seguro con terceros reales: el
aislamiento de ejecución de una skill (Docker, sin red, `cap_drop=ALL`,
usuario no-root, cascada de permisos con "skill" como el techo más
bajo) ya es sólido — la brecha real no es que una skill pueda escapar
del sandbox (no puede), es que **no había forma de saber si el
paquete de una skill de un tercero fue alterado entre que su autor lo
publicó y que este usuario lo instaló**.

**Alcance acordado explícitamente con el usuario** (eligió la opción
acotada vía `AskUserQuestion`): solo firma/verificación de integridad
del paquete. Esto responde "¿este paquete fue alterado desde que se
firmó?" — **deliberadamente NO responde** "¿debería confiar en este
autor?" (eso necesitaría un registro/reputación de autores real, sin
sentido de construir sin un marketplace real con autores externos
todavía). El reemplazo del `enabled: true` manual por un flujo guiado
de instalación (F4 del plan original) queda explícitamente fuera de
esta iteración.

**`tool_integration/skill_signing.py`** (nuevo) — mismo patrón
criptográfico que `tool_integration/signing.py` (Ed25519 vía
`cryptography`) pero para la clave de un AUTOR externo, nunca la
misma identidad que usa kal para sus propias herramientas dinámicas:
- `SkillSigner(key_dir)`: gestiona el keypair del autor (genera/reusa,
  permisos 0600 en la clave privada). `sign_skill(skill_dir)` calcula
  un manifiesto canónico — sha256 de CADA archivo de la skill
  (incluye `skill.yaml` a propósito: ahí viven `permissions`/
  `kernel_services`, tienen que quedar cubiertos por la firma; excluye
  `__pycache__`/`.pyc`, no son contenido real), lo firma, y devuelve
  el dict a escribir como `skill.sig`.
- `verify_skill_signature(skill_dir) -> "unsigned" | "verified" | "tampered"`:
  sin `skill.sig` -> `"unsigned"` (compatibilidad total, ninguna skill
  existente tiene firma y las tres siguen cargando exactamente igual).
  Con `skill.sig`: recalcula el manifiesto desde el estado ACTUAL de
  la carpeta (nunca confía en lo que el propio archivo dice que
  firmó) — cualquier archivo modificado, agregado o quitado desde que
  se firmó invalida la verificación. JSON corrupto/campos faltantes
  también cuenta como `"tampered"`, nunca una excepción sin manejar.

**`tool_integration/skills.py::load_skills()`** — nueva verificación
justo después del chequeo de `enabled` (una skill deshabilitada ni se
verifica) y ANTES de validar `entry_point`: una firma `"tampered"`
rechaza la carga por completo (nuevo status terminal
`"signature_invalid"`, auditado, fail closed — nunca se registra esa
skill). `SkillStatus` gana el campo `signature_status`.

**`scripts/sign_skill.py`** (nuevo) — CLI para que un autor firme su
propia skill: `python3 scripts/sign_skill.py skills/mi_skill/
[--key-dir data/keys]`. Genera/reusa el keypair del autor, escribe
`skill.sig`, imprime el fingerprint de la clave pública.

12 tests nuevos en `tests/test_skill_signing.py` (roundtrip,
tampering de código/manifiesto/archivos agregados-quitados detectado,
`skill.sig` corrupto manejado sin crash, `__pycache__` ignorado,
persistencia de la identidad del autor, dos autores no se confunden
entre sí) + 4 tests nuevos en `tests/test_skills.py` (skill sin firmar
sigue cargando igual, skill firmada correctamente carga como
"verified", firma alterada rechaza la carga por completo, auditado
como fallo).

## Instalación guiada de skills (F4 del plan de marketplace, 2026-07-10)

Continuación directa de F3 (firma/verificación de integridad, arriba).
Hasta ahora, habilitar una skill era editar a mano `enabled: false` ->
`enabled: true` en su `skill.yaml` con un editor de texto — un punto
de decisión real (¿reviso permisos/`requirements`/`kernel_services`
antes de habilitar?) sin ninguna guía ni protección contra errores de
tipeo.

**Alcance**: un script CLI que reemplaza esa edición manual, mostrando
toda la información relevante de una vez y pidiendo confirmación
explícita — NO una UI web (no existe ningún panel de skills en
`frontend/` hoy), NO un instalador que descargue de un marketplace
remoto (no existe todavía), y NO una segunda capa de aprobación tipo
`propose_dynamic_tool`/`approve_pending_tool` — a diferencia de las
herramientas que el AGENTE propone, una skill siempre la instala un
humano copiando una carpeta a mano; ese ya es el punto de decisión
humana, el script solo lo hace informado y seguro en vez de "editar
YAML a ciegas".

**`tool_integration/skills.py`** gana dos funciones reusables:
- `set_skill_enabled(skill_dir, enabled)`: edita solo la línea
  `enabled:` del `skill.yaml` con un reemplazo de texto dirigido
  (nunca `yaml.dump()`, que destruiría los comentarios explicativos
  que ya trae cada manifiesto real). Si la línea no existe la agrega
  al final.
- `audit_skill_enable_change(...)`: registra la decisión humana en el
  audit log (`EventType` gana `"skill_enabled"`/`"skill_disabled"` en
  `audit/audit_log.py`).

(`_parse_manifest` perdió el guion bajo -> `parse_manifest`: pasa a
ser reusada también por el script, ya no es puramente interna del
módulo.)

**`scripts/enable_skill.py`** (nuevo):
```
python3 scripts/enable_skill.py skills/mi_skill/            # pide confirmación
python3 scripts/enable_skill.py skills/mi_skill/ --yes      # sin preguntar
python3 scripts/enable_skill.py skills/mi_skill/ --disable  # deshabilita, sin confirmación (dirección segura)
```
Antes de habilitar: si ya está habilitada, no-op. Calcula
`verify_skill_signature()` — una firma `"tampered"` aborta sin
escribir nada (mismo fail-closed que ya aplica `load_skills()`, mismo
criterio que F3, pero detectado acá antes de perder tiempo habilitando
algo que el servidor va a rechazar igual). Muestra nombre, versión,
descripción, `permissions`, `requirements` (marcado explícitamente
como paquetes de pip que se van a instalar), `kernel_services`, y el
estado de firma (con advertencia visible si `"unsigned"`). Recién ahí
pide confirmación interactiva (salvo `--yes`).

6 tests nuevos en `tests/test_skills.py` para `set_skill_enabled`/
`audit_skill_enable_change` (flip en ambos sentidos, preserva
comentarios y el resto de los campos, inserta la línea si faltaba,
ambos eventos de auditoría). El script CLI en sí (`argparse`/`print`/
`input`) queda sin test automatizado, mismo criterio que
`scripts/sign_skill.py` — verificado con un smoke test manual sobre
una copia temporal (nunca sobre `skills/` real): habilitar, confirmar
idempotencia en una segunda corrida, deshabilitar, y el caso de firma
alterada (rechaza sin escribir nada).

## Bug real: self_modification.enabled era un flag muerto (2026-07-11)

Retomando la lista de brechas de marketplace pendientes (ver
`project_kernel_pivot.md`): el usuario eligió revisar la ejecución de
self-modification en el host. Investigando antes de proponer nada, se
encontró un bug concreto: `SelfModificationConfig.enabled`
(`utils/config.py`) existe hace tiempo (default `False` en el modelo
Pydantic), `config/config.yaml` lo tenía en `true` — pero
**`SelfModificationManager.propose()` nunca leía ese valor**. La
funcionalidad quedaba SIEMPRE activa sin importar qué dijera la
config; un operador que la "desactivara" a mano no obtenía ninguna
protección real.

También se confirmó el alcance real del riesgo: self-modification NO
es alcanzable por el agente de chat de forma autónoma — solo se llega
vía la API con token administrativo (`/self-modification/propose`) o
el flujo "bajo demanda" de autodiagnóstico
(`agent_core/self_diagnosis.py`, disparado por
`/diagnostics/{invariante}/self-repair`). El riesgo real es que, al
llegar ahí, `_run_tests()` corre el test suite completo (baseline +
candidato) como `subprocess.run` directo sobre el HOST, sin ningún
aislamiento — a diferencia de skills/herramientas dinámicas, que
pasan por el mismo validador AST (`code_analysis/denylist.py`, que se
autodescribe como "filtro barato de primera línea, NO la garantía de
seguridad") y LUEGO por contención real en Docker.

**Alcance decidido explícitamente con el usuario** (vía
`AskUserQuestion`, entre 3 opciones con costos muy distintos: solo el
flag / aislamiento liviano sin Docker / sandbox Docker completo con
una imagen nueva pesada): **solo arreglar el flag muerto**. Sandboxear
también la ejecución del subprocess de tests quedó descartado por
ahora — construir y mantener una imagen Docker con todas las
dependencias pesadas del proyecto (torch, diffusers, playwright) para
una funcionalidad que hoy casi no se usa no es proporcional; queda
como riesgo residual conocido y documentado, aceptable para un solo
usuario en su propia máquina.

**Implementado**: `SelfModificationManager.propose()` ahora chequea
`settings.self_modification.enabled` como el PRIMER chequeo de todos
—antes incluso del bloqueo de rutas núcleo—, y si es `false` rechaza
la propuesta en un solo evento de auditoría (nuevo status terminal
`"disabled"`), sin tocar disco ni correr un solo test. `config.yaml`
cambia el default a `enabled: false` (opt-in explícito, coincide con
el default que ya tenía el modelo Pydantic).

4 tests nuevos en `tests/test_self_modification.py` (rechazo cuando
está deshabilitado, y que ese chequeo se resuelve ANTES que el
bloqueo de núcleo — confirmado pasando un `target_path` de núcleo y
viendo que el status es `"disabled"`, no `"blocked_core"`). Como el
resto de ese archivo (y de `test_self_modification_versions.py`)
asumía el default viejo (`true`), ambos ganaron un fixture
`autouse` que habilita la funcionalidad por defecto para esos tests
puntuales — el gate en sí se prueba explícitamente desactivándolo.
`tests/test_orchestrator_admin_auth.py` no necesitó cambios (solo
verifica códigos HTTP 401 vs no-401, nunca el contenido del `status`
de la propuesta). `tests/test_self_diagnosis.py` tampoco (usa un
`FakeSelfModificationManager`, nunca el pipeline real).

## Terminar de desacoplar el resto de herramientas al Kernel Service Bus (2026-07-11)

Continuación directa del Kernel Service Bus (arriba, validado hasta
ahora solo para `image.generate`). De las 6 herramientas de primera
parte originales, quedaban 5 sin migrar — investigando cada
adaptador, solo 3 cargan un modelo pesado que necesita mantenerse
caliente en memoria (el problema real que motivó todo el bus):
**audio_gen** (voz Piper), **speech_to_text** (Whisper) e
**image_editing**, solo su operación `inpaint` (diffusers).
`video_gen`/`image_composition` no cargan ningún modelo (moviepy/
Pillow puro) — quedaron fuera de esta iteración por elección
explícita del usuario. `browser` sigue documentado como extensión
futura, no tocado.

**`kernel_bus/services.py`** gana `AudioService` (`.synthesize()`,
movido de `AudioGenerationTool` con los 3 bugs reales de piper-tts ya
corregidos ahí) y `STTService` (`.transcribe()`, movido de
`SpeechToTextTool`) — mismo patrón que `ImageService`. `ImageService`
gana `.inpaint()` (movido de `ImageEditingTool`) y un segundo
parámetro de config (`editing_cfg`, sección `settings.multimodal.image_editing`,
distinta de `cfg` que sigue siendo la de generación) — comparten la
clase por ser el mismo dominio "image", no la misma config ni el
mismo pipeline. Los 3 adaptadores delegan en su servicio compartido
correspondiente, con los métodos `_get_voice()`/`_get_model()`/
`_get_inpaint_pipeline()` conservados como shims (varios tests
existentes los llaman directo para forzar la carga del modelo antes
de tiempo) — mismo patrón que ya usaba `ImageGenerationTool`.

**Pieza nueva de protocolo**: `KernelServiceBus.dispatch()`
(`kernel_bus/bus.py`) ahora también resuelve artefactos de ENTRADA,
no solo de salida — `image.generate`/`audio.synthesize` nunca
reciben un artefacto como parámetro, pero `stt.transcribe`
(necesita un audio ya existente) e `image.inpaint` (necesita una
imagen ya existente) sí. Cualquier valor de los parámetros que
empiece con `"artifact://"` se reemplaza por la ruta real de host
ANTES de invocar la acción — nuevo `ArtifactNotFoundError` si la
referencia no se conoce. Esto permite que una skill componga dos
llamadas del bus en una misma ejecución (genera algo, pasa esa
referencia como entrada de la siguiente llamada) sin ver nunca una
ruta real de host.

**3 skills de referencia nuevas** (mismo patrón que
`skills/image_via_kernel/`, `requirements: []`, sin ninguna
dependencia de ML):
- `skills/audio_via_kernel/`: espejo directo de `image_via_kernel`, aplicado a audio.
- `skills/voice_roundtrip_via_kernel/`: encadena `audio.synthesize` y
  `stt.transcribe` en una sola ejecución — es la que realmente
  ejercita la resolución de artefactos de entrada.
- `skills/image_inpaint_via_kernel/`: encadena `image.generate` e
  `image.inpaint`.

`tool_integration/sandboxed_skill.py::_KERNEL_SERVICE_TIMEOUT_SECONDS`
sube de 300 a 600 — inpainting real en CPU ya estaba documentado como
"del orden de minutos" él solo, y las 2 skills compuestas hacen DOS
llamadas de modelo en una misma ejecución.

**Verificado de punta a punta, con Docker real y los modelos reales**
(nada quedó cacheado de una sesión anterior que hiciera falta
descargar de nuevo): las 3 skills nuevas generan/transcriben/editan
contenido real (`tests/test_kernel_bus_audio_stt_inpaint_integration.py`).
Un test adicional (`tests/test_sandboxed_skill.py`) valida la
resolución de artefactos de entrada con Docker real pero un servicio
FALSO (instantáneo, sin esperar un modelo), para separar "el
protocolo funciona" de "el modelo funciona". Toda la suite existente
de `test_audio_gen.py`/`test_speech_to_text.py`/`test_image_editing.py`
sigue pasando sin tocar sus fixtures — confirma que la delegación no
cambió ningún comportamiento observable.

7 tests nuevos (3 de resolución de artefactos en `test_kernel_bus.py`,
1 de plomería encadenada en `test_sandboxed_skill.py`, 3 de
integración real). Suite completa: 526 passed, 0 regresiones
(17m12s — la mayor parte del tiempo son los modelos reales de ML,
no el código nuevo en sí).

## Repositorio público + Fase A del plan de comunidad: instalación remota de skills (2026-07-11)

El usuario planteó su próximo objetivo: construir una comunidad de
desarrolladores alrededor de kal, con instalación automatizada de
skills desde un "market" — apuntando a desarrolladores/consumidores
domésticos. Antes de nada: kal no era ni siquiera un repositorio git.
Se inicializó (`git init`, rama `main`), se eligió licencia **Apache
2.0** (permisiva + protección de patentes, estándar para proyectos de
plataforma con muchos contribuidores — evaluada explícitamente contra
MIT y AGPL-3.0; las skills de referencia quedan bajo la misma
licencia), se revisó/amplió `.gitignore` (backups locales de 139MB,
zips de distribución, estado de runtime de Claude Code — ninguna clave
privada quedó expuesta), y se subió a
**https://github.com/carlosbv99-bit/kal** (público).

**Plan de comunidad acordado, 3 fases** (evitando construir un backend
de marketplace propio desde el día uno — instalación automática de
código de terceros es la mayor superficie de riesgo nueva que tendría
kal):
- **Fase A** (esta iteración): mecanismo de descarga+verificación+
  instalación, validado de punta a punta.
- **Fase B** (no empezada): página estática navegable sobre el mismo
  contenido.
- **Fase C** (no empezada, la más delicada): política de curación de
  quién puede publicar — firma (F3) prueba integridad, nunca
  autoridad del autor.

**Fase A implementada**: el "market" es, deliberadamente, solo un
repositorio Git con la misma estructura que ya usa `skills/`
localmente — **sin índice separado que mantener sincronizado**:
listar las skills disponibles es clonar el repo (shallow) y parsear
cada `skill.yaml` con `parse_manifest()` (ya existente). El propio
repo `carlosbv99-bit/kal`, con sus 6 skills de referencia, es el
primer market real (dogfooding, sin repo nuevo).

`tool_integration/skill_market.py` (nuevo): `list_market_skills()` y
`fetch_skill_from_market()`, ambos vía `git clone --depth 1 --branch
<ref>` a un directorio temporal — errores de red/ref inexistente dan
un `MarketError` claro, nunca un traceback crudo de subprocess.

**Política de seguridad nueva y deliberadamente más estricta que F4
local**: una skill traída de un market remoto DEBE estar firmada y
verificar (`verify_skill_signature() == "verified"`) — a diferencia
de una skill LOCAL (donde "sin firmar" se permite con advertencia,
porque un humano ya tuvo la carpeta en su disco), acá "unsigned" y
"tampered" bloquean la instalación por igual, sin excepción. Esto
sigue sin resolver la brecha de fondo (integridad ≠ confianza en el
autor — Fase C), pero es el piso mínimo razonable para un flujo que
instala y ejecuta código sin que ningún humano lo haya leído antes.

`scripts/install_from_market.py` (nuevo, mismo estilo que
`enable_skill.py`/`sign_skill.py`): `--list` para ver las skills
disponibles; instalar un nombre descarga a un directorio temporal,
verifica la firma (aborta sin escribir nada si no es `"verified"`),
muestra el mismo resumen que F4 (permisos/requirements/
kernel_services) + confirmación, y recién ahí copia a `skills/<nombre>/`
real + `set_skill_enabled()` + `audit_skill_enable_change(..., source="market")`
(este último ganó un parámetro `source` opcional, default `"local"`,
sin romper el llamador existente de F4).

**Paso operativo necesario, no solo código**: como F3 solo se había
probado sobre copias temporales, ninguna de las 6 skills reales tenía
`skill.sig` todavía — se firmaron las 6 de verdad, con una identidad
propia del proyecto (`data/keys/kal_project/`, gitignoreada), y los
`skill.sig` resultantes se commitearon y pushearon — sin esto, el
market real no tendría nada instalable.

8 tests nuevos en `tests/test_skill_market.py` (listar/traer desde un
repo Git LOCAL sintético bajo `tmp_path` — `git clone` funciona igual
contra un path local que contra una URL remota, no hace falta red
real para probar la lógica; nombre inexistente da la lista de
disponibles en el error; ref inexistente da `MarketError`, no un
traceback; la política de firma se prueba con la interacción real
`skill_market.py` + `skill_signing.py`: sin firma/alterada rechazan,
verificada pasa) + 1 test nuevo en `tests/test_skills.py` para el
parámetro `source` de auditoría. El script CLI en sí queda sin test
automatizado (mismo criterio que `enable_skill.py`/`sign_skill.py`) —
verificado con un smoke test manual completo sobre un market Git local
sintético (nunca sobre `skills/` real durante la prueba): `--list`,
rechazo sin firma, instalación exitosa firmada, y rechazo por "ya
existe" en una segunda instalación.

Además de la Fase A, esta sesión reestructuró la documentación del
proyecto: `README.md` pasó a ser un pitch corto en inglés (arquitectura
real, estado verificado contra el código, no aspiracional) para
atraer desarrolladores externos — este archivo (`docs/HISTORY.md`) es
donde se preserva el diario de ingeniería completo que antes vivía en
el README. Ver memoria `technical_docs_readme_vs_history_split` para
el detalle de esa decisión, incluida una revisión de una propuesta
inicial del usuario que tenía varios componentes de arquitectura
inventados (corregidos antes de publicar).

## Fase B del plan de comunidad: página navegable del market (2026-07-11)

Continuación directa de Fase A. Mismo principio de "sin backend
nuevo": GitHub Pages sirve contenido estático directamente desde
`/docs` en `main` (donde ya vivía este archivo) — sin rama `gh-pages`
separada, sin servidor.

`scripts/generate_market_page.py` (nuevo): `render_market_html()`
recorre `skills/*/skill.yaml` (reusa `parse_manifest()`,
`tool_integration/skills.py`) y calcula el estado de firma de cada una
con `verify_skill_signature()` (ya existente) — genera un único
`docs/index.html` autocontenido (CSS inline, sin JS, sin dependencias
nuevas, ni Jinja2: alcanza con f-strings de Python). A diferencia de
`load_skills()`, NO filtra por `enabled` — el catálogo del market
muestra todo lo publicado en el repo, `enabled` es una decisión de
instalación local de cada usuario, no una propiedad del catálogo.
Cada tarjeta muestra nombre/versión/descripción/permisos/requirements/
kernel services/insignia de firma, más el comando exacto de
instalación.

**Alcance deliberado**: se genera a mano (`python3
scripts/generate_market_page.py`), no automáticamente en cada push vía
GitHub Actions — mismo criterio de "validar barato antes de
automatizar" de todo el plan de comunidad. Si el catálogo crece y esto
se vuelve tedioso, un workflow de CI es un paso posterior simple.

8 tests nuevos en `tests/test_generate_market_page.py` (placeholder
con cero skills; insignia "unsigned" vs "signature verified" — el
test tuvo que corregirse para no confundir la palabra "unsigned" en la
propia hoja de estilos CSS con el badge real; escape de caracteres
HTML en la descripción; manifiesto roto se ignora sin tumbar la página
entera). Generado `docs/index.html` real sobre las 6 skills reales del
proyecto — las 6 muestran "signature verified" (ya estaban firmadas
desde Fase A). Suite completa: 543 passed, 0 regresiones (535+8).

GitHub Pages activado de verdad vía `gh api -X POST repos/.../pages`
(`branch=main`, `path=/docs`) — build confirmado, y
**https://carlosbv99-bit.github.io/kal/** responde HTTP 200 con las 6
skills reales. Linkeado desde `README.md`.

## Fase C del plan de comunidad: curación de quién puede publicar (2026-07-11)

Cierre de las 3 fases. Hallazgo antes de plantear el plan: el repo no
tenía protección de rama, ni workflow de CI, ni `CONTRIBUTING.md` — un
solo colaborador (`carlosbv99-bit`, admin). La "curación" ya existía
DE HECHO (nadie más tiene permiso de escritura), pero sin ninguna
regla escrita ni automatizada.

**Decisión confirmada con el usuario, vía `AskUserQuestion`**: la
protección de rama nueva NO incluye al mantenedor único — sigue
pusheando directo a `main` igual que en toda la sesión. La regla de
"PR + CI obligatorio" aplica solo a futuros colaboradores externos
(que de todas formas solo pueden llegar vía PR, GitHub ya lo impide
por permisos). **No se agregó revisión de PR obligatoria** (segunda
persona) — no tiene sentido forzarlo con un solo mantenedor real hoy,
sería fricción sin beneficio; documentado honestamente en
`CONTRIBUTING.md` que la revisión de CONTENIDO (no solo integridad)
es hoy un paso manual, no automatizado.

**Implementado**: `scripts/validate_skills.py` (mismo chequeo que ya
exige la instalación remota — cada `skill.yaml` parsea, cada
`skill.sig` verifica — sobre TODAS las skills del repo, no solo las
de un PR puntual). `.github/workflows/validate-skills.yml` lo corre
en cada push/PR que toque `skills/**` (instala solo las 4 dependencias
reales de la cadena de imports — `pyyaml`, `python-dotenv`, `pydantic`,
`cryptography` —, no todo `requirements.txt`; torch/diffusers no hacen
falta para este chequeo. BUG REAL encontrado al correr el workflow de
verdad por primera vez: el plan asumía solo pyyaml+cryptography,
pero `tool_integration/skills.py` importa `utils/logger.py` ->
`utils/config.py`, que necesita `python-dotenv` y `pydantic` — el
primer run manual falló con `ModuleNotFoundError: dotenv`, corregido
verificando antes en un venv aislado local con exactamente esas 4
dependencias). `CONTRIBUTING.md` (nuevo, en
inglés): proceso para publicar (fork, firmar con tu propia clave, PR),
explícito sobre qué prueba una firma verificada (integridad) y qué
NO prueba (que el autor sea confiable, que el código haga lo que dice).

8 tests nuevos en `test_validate_skills.py`, incluido uno que corre el
chequeo real sobre `skills/` del proyecto (confirma que el propio repo
ya pasaría el CI que se está agregando). Protección de rama activada
sobre `main` vía `gh api` (`enforce_admins: false`, status check
requerido = el workflow nuevo).

Con esto, las 3 fases del plan de comunidad (instalación remota +
página navegable + curación) quedan completas.

## Context Service — alcance mecánico, sin LLM (2026-07-11)

Discusión de arquitectura sobre cómo se maneja la ventana de contexto:
el usuario propuso un "Context Engine" completo (capas por tipo de
información, presupuesto de tokens, resumen automático, contexto de
editor consciente de símbolos, tracking de intención, Context
Planner). Acordado: sí a la dirección (contexto como recurso
gestionado por el kernel, no una feature de un frontend puntual), pero
secuenciado — no construir las 7 capas de una. Primer corte,
explícitamente mecánico (sin ninguna llamada a LLM, para no meter el
riesgo de que un resumen automático distorsione información
silenciosamente sin poder validarlo en vivo todavía).

Antes de esto, discusión aparte sobre si la integración de VS Code
debería ser una "Integration Skill" — se corrigió: aplicar parches y
navegar símbolos necesitan filesystem real (escribir en el proyecto
abierto del usuario), algo estructuralmente incompatible con el
sandbox de una skill (Docker efímero, sin acceso al filesystem real
del host). Esa lógica queda del lado de confianza total de la
extensión (`applyEdit.ts`), nunca sandboxeada ni instalable por
terceros sin revisión — un "Integration Skill"/"Connector" con
permiso de escritura real sería, en la práctica, la superficie de
ataque más peligrosa que kal tendría.

**Implementado**: `agent_core/context_service.py` (nuevo) —
`ContextService.build(session, editor_context)` decide qué entra al
próximo mensaje al LLM: ventana de últimos `settings.context.max_recent_turns`
(default 8, antes NINGÚN límite — `Session.history_messages()` devolvía
todo el historial sin recortar) turnos, y fusiona artefacto activo +
contexto del editor en UN SOLO mensaje `role=system` (nunca dos
separados — bug real ya documentado, un segundo system hacía que
qwen3-coder:30b lo ignorara por completo). Vive in-process, mismo
patrón que `MemoryManager` — NO se expone por el Kernel Bus, las
skills nunca necesitan construir un prompt de chat.

`agent_core/sessions.py::Session` vuelve a ser solo datos —
`history_messages()`/`context_message()` se eliminaron (la lógica se
mudó al servicio). `agent_core/orchestrator.py`: `ChatRequest` gana
`editor_context` (4 campos: ruta relativa, lenguaje, texto, si es
selección) — señal CRUDA, nunca texto pre-formateado.

**Extensión de VS Code deja de concatenar texto**: antes,
`formatEditorContext()` armaba un bloque de texto y lo "prellenaba"
en el cuadro de entrada del chat (el usuario veía todo el código
pegado a su pregunta). Ahora `extension.ts` captura la señal cruda
(`EditorSnapshot`) y se la pasa a `ChatPanel`, que la guarda como
adjunto de un solo uso y muestra un indicador simple
("📎 archivo.py (selección)" + botón para descartar) en vez de volcar
el texto — el mensaje del usuario queda limpio. `kalClient.ts` manda
la señal cruda como `editor_context` en el POST; el backend decide el
formato final. `formatEditorContext()`/su test se eliminaron (lógica
movida a Python); `EditorSnapshot` se conserva (lo sigue usando
`applyEditFormat.ts` para su propio flujo, sin relación con esto). El
frontend web no cambia nada — nunca mandó `editor_context`, se
beneficia igual de la ventana de turnos porque es enteramente del
lado del servidor.

Bug real menor encontrado al correr los tests de la extensión: `npm
test` seguía fallando sobre un `editorContextFormat.test.js`
compilado VIEJO en `out/` después de borrar el `.ts` fuente — `tsc`
no limpia archivos de salida huérfanos en un build incremental.
Corregido borrando `out/` antes de recompilar.

Tests nuevos: `tests/test_context_service.py` (9, Python — ventana de
turnos, fusión en un único mensaje system, formato del contexto de
editor) + 2 nuevos en `kalClient.test.ts` (TypeScript). `test_sessions.py`
simplificado a probar solo almacenamiento. Suite completa de Python y
`npm test` de la extensión confirmados sin regresiones.

**Deliberadamente fuera de esta iteración**: resumen automático de
sesión (necesita LLM, requiere validación en vivo), memoria de
proyecto persistente, contexto de editor consciente de símbolos (vía
las APIs de símbolos de VS Code, no un parser propio), tracking de
intención, envolver esto como Kernel Bus service (no hace falta —
las skills no lo necesitan).

## Escaneo de malware en artefactos de skills, fail-closed (2026-07-11)

El usuario planteó, a futuro, un antivirus real que proteja "el
equipo" (no solo kal) — reconocido explícitamente como un proyecto de
otra escala (bases de firmas, motores heurísticos, años de esfuerzo
de equipos dedicados como ClamAV/CrowdStrike), pospuesto para cuando
exista una comunidad apreciable. Por ahora, alcance acotado: reforzar
"que kal nunca introduzca ni ejecute algo malicioso en tu máquina".

Investigando el código real (no una recomendación genérica) se
encontró el hueco concreto:
`tool_integration/sandboxed_skill.py::_to_artifact()` copiaba
VERBATIM (sin re-codificar) los bytes que una skill devuelve —
código de la confianza MÁS BAJA del sistema, potencialmente de un
tercero del market — al filesystem real del host, sin ningún
escaneo, listos para que el usuario los abra después. `ImageService`/
`AudioService` (SDXL-Turbo/Whisper/Piper) quedan fuera a propósito:
son contenido de primera parte, los bytes los controla la propia
librería de encoding, no una skill de un tercero.

**Decisión confirmada con el usuario, vía `AskUserQuestion`**:
fail-closed — si no se puede escanear (ClamAV no instalado), el
artefacto se bloquea, no se entrega (mismo criterio que la firma no
verificada en Fase A del market). Consecuencia real explicada de
antemano: como ClamAV no estaba instalado en esta máquina, el cambio
habría bloqueado toda skill con salida de archivo hasta instalarlo —
el usuario lo instaló (`clamav`+`clamav-daemon` vía apt +
`freshclam` para la base de firmas) como parte de este trabajo.

**Implementado**: `tool_integration/malware_scan.py` (nuevo) —
`is_clamav_available()`, `scan_bytes(data, suffix)` vía subprocess a
`clamscan` (no reimplementa detección; usa un motor real y
mantenido). Empieza con `clamscan` simple (recarga la base de firmas
en cada invocación) en vez de `clamd` (demonio persistente, más
rápido) — lo más simple que funciona primero, mismo criterio de todo
el proyecto; `clamd` queda como optimización futura si la latencia
por escaneo resulta un problema real de uso.
`sandboxed_skill.py::_to_artifact()` escanea los bytes de la skill
ANTES de escribirlos al host — si se detecta algo (o ClamAV no está
disponible), el artefacto nunca se escribe, se devuelve un error y se
audita (`EventType` nuevo: `"artifact_scan_blocked"`).

**Verificado con detección real, no solo mockeada**: los tests de
`scan_bytes()` corrieron contra el ClamAV real recién instalado,
incluida la cadena de prueba estándar **EICAR** (inocua, pero que
todo antivirus real reconoce como "virus de prueba") — ClamAV la
detectó correctamente de punta a punta. 8 tests nuevos en
`test_malware_scan.py` (4) y `test_sandboxed_skill.py` (4: bloqueo
por detección, bloqueo por ClamAV ausente simulado, auditoría del
bloqueo, confirmación de que un artefacto de texto puro nunca dispara
un escaneo). El resto de `test_sandboxed_skill.py` ganó un fixture
`autouse` que simula "limpio" por defecto (no depende de tener
ClamAV real instalado para probar la lógica de `SandboxedSkillTool`
en sí, que es un concern distinto del escaneo).

## Guía de usuario para VS Code + instalación automatizada (2026-07-11)

Con la extensión de VS Code ya funcional (Hito 1/2, más arriba), faltaba
la pieza que la hace usable por alguien no técnico: una guía concreta
paso a paso (`docs/GUIA_VSCODE.md`, nueva) — instalar prerequisitos,
preparar el proyecto, arrancar kal, cargar la extensión, usar los tres
comandos, con un "✅ cómo saber que funcionó" en cada paso, pensada para
quien nunca usó kal (ver memoria: usuario no programador).

A pedido explícito, se automatizó buena parte de esa guía en
`scripts/setup_all.sh` (nuevo): detecta y ofrece instalar (con
confirmación antes de cada `sudo`) Docker/Python 3.11+/ffmpeg/Node
18+/Ollama, prepara `.venv` + `pip install`, y compila+empaqueta+instala
la extensión de forma **permanente** vía `vsce package` +
`code --install-extension` — en vez del flujo de desarrollo (F5,
"Extension Development Host") que documentaba el README original de la
extensión. Alcance deliberado: solo Ubuntu/Debian (`apt`); en otra
distro, avisa y remite a la guía manual. Es re-ejecutable (cada paso se
salta si ya está hecho).

**Bug real encontrado al probarlo** (no solo escrito, corrido de
verdad en esta máquina): el primer intento de empaquetar con
`npx @vscode/vsce package` usaba flags inventados (`-q`,
`--packagePath` duplicado con `--out`) que no existen en esa CLI —
`vsce package --help` reveló las flags reales
(`--no-dependencies --allow-missing-repository --out <path>`).
Corregido y confirmado con `code --list-extensions` mostrando
`undefined_publisher.kal-vscode@0.1.0` instalado. De paso, se notó que
el `.vsix` empaquetaba también los tests compilados
(`out/test/*.test.js`, no excluidos por `.vscodeignore` — solo `test/**`,
la fuente `.ts`, sí lo estaba) — agregado `out/test/**` a
`vscode-extension/.vscodeignore`.

## Integración de VS Code v1 — botón "Instalar" desde la web (2026-07-11)

El usuario propuso una arquitectura ambiciosa: un "Integration
Manager" del Kernel, protocolo de handshake con session tokens,
"Capability Packages" instalables desde un marketplace, generalizado a
cualquier IDE (JetBrains, Neovim, Photoshop...). Mismo criterio de
disciplina de alcance ya aplicado en este proyecto: se documentó la
visión como norte a futuro, pero se escopó una v1 concreta —

- **Lo que NO se construyó, y por qué**: instalar VS Code mismo (la
  app, cross-platform, alto riesgo, sin demanda validada); un
  handshake con negociación de versión/capabilities (resuelve un
  problema — múltiples tipos de cliente — que no existe con un solo
  cliente HTTP); "Capability Packages" genéricos vía marketplace para
  integraciones (generalización prematura sin un segundo caso real de
  IDE que la justifique).
- **Lo que sí**: reusar lo ya construido y probado en
  `scripts/setup_all.sh`. Nuevo `agent_core/vscode_integration.py`
  (`get_status()`, `install_extension()` — compila, empaqueta e
  instala vía subprocess, cada intento auditado — éxito o fracaso —
  con el `EventType` nuevo `"vscode_extension_installed"`). Dos
  endpoints nuevos en `agent_core/orchestrator.py`:
  `GET /integrations/vscode/status` (sin auth, solo lectura) y
  `POST /integrations/vscode/install` (gateado con el mismo token
  administrativo que ya protege self-modification/rollback — no un
  mecanismo nuevo). Nuevo tab **"Integraciones"** en la interfaz web
  (`frontend/index.html`/`app.js`/`style.css`) con la tarjeta VS Code
  (estado + botón Instalar/Reinstalar) exactamente como la propuso el
  usuario.
- **Verificado real, de punta a punta, no solo con mocks**: se
  desinstaló la extensión (`code --uninstall-extension`), se confirmó
  `installed: false` vía el status endpoint real, se disparó el POST
  real con el token admin real, y se confirmó la instalación con
  `code --list-extensions` — más el evento correspondiente en el log
  de auditoría, con la cadena íntegra. 18 tests nuevos (unitarios de
  `vscode_integration.py` con subprocess mockeado +
  endpoints con el auth gate ya existente extendido a la nueva ruta).

## Ícono en la Activity Bar + ítem en la barra de estado (2026-07-11)

Pregunta de un usuario no técnico tras usar el botón "Instalar": "¿va a
aparecer un botón de kal en la interfaz de VS Code?" — respuesta
honesta: no, la extensión solo contribuía comandos de paleta
(`Ctrl+Shift+P`), sin ningún elemento visible. A pedido explícito, se
agregaron dos puntos de entrada visibles:

- **Ítem en la barra de estado** ("💬 Kal", abajo a la derecha) que
  corre el comando `kal.openChat` ya existente — sin contribución
  nueva en `package.json`, se crea programáticamente en
  `extension.ts` vía `vscode.window.createStatusBarItem`.
- **Ícono propio en la Activity Bar** (barra lateral izquierda, junto
  a otras extensiones de agentes de IA que el usuario tenga
  instaladas) — nuevo `viewsContainers`/`views` en `package.json`,
  ícono `media/activity-icon.svg` (un trazo simple en forma de "k",
  sin dependencia de fuentes: VS Code recolorea íconos monocromáticos
  automáticamente). Abre una vista de chat fija (`ChatViewProvider`,
  nuevo, implementa `vscode.WebviewViewProvider`) — conversación
  **independiente** de la que abre `ChatPanel` (su propio
  `session_id`, no comparten historial); no participa del flujo de
  "contexto del editor adjunto" de "Preguntar sobre la selección",
  eso sigue siendo específico de `ChatPanel`.

El HTML del webview (`buildHtml()` en `ChatPanel`) era casi idéntico a
lo que necesitaba `ChatViewProvider` — segundo consumidor real, no
hipotético, así que se extrajo a `chatWebviewHtml.ts` compartido
(`buildChatHtml()` + `getNonce()`) en vez de duplicarlo.

**Verificado real**: `npm test` (20 tests existentes, sin
regresiones) + reinstalación real vía el mismo botón "Instalar" de la
web (desinstalar → instalar → confirmar con `code --list-extensions`
y `find ~/.vscode/extensions/.../out/src` que el `.vsix` instalado
contiene `chatViewProvider.js`/`chatWebviewHtml.js` y que
`package.json` dentro del paquete instalado trae `viewsContainers` y
`kal.chatView`). **Límite honesto**: no hay forma de abrir una ventana
real de VS Code en este entorno (sin GUI) para confirmar visualmente
que el ícono se ve bien en la Activity Bar — validado que el paquete
está bien formado y VS Code lo aceptó sin error, pero la confirmación
visual queda para cuando el usuario lo pruebe.

## Límite de tamaño de línea en el Kernel Bus (2026-07-11)

Primer hallazgo corregido de los 7 documentados como "deuda aceptada"
en la revisión de seguridad del 2026-07-09 (ver
[[project_security_review_2026_07_09]]) — elegido explícitamente por
ser "el único que un tercero real podría disparar hoy con una skill
instalada desde el market": `KernelBusSocketServer._read_line()`
(`kernel_bus/socket_server.py`) acumulaba bytes en un buffer sin
ningún límite mientras esperaba un `\n` — una skill (la confianza MÁS
BAJA del sistema, hoy instalable desde el market remoto vía Fase A)
que mandara datos sin salto de línea agotaba memoria del proceso HOST
de confianza, no de su propio contenedor aislado. DoS real, no solo
teórico, y alcanzable desde el punto de menor confianza del sistema.

**Implementado**: constante `_MAX_LINE_BYTES = 1_048_576` (1 MiB) —
los pedidos legítimos de hoy son JSON con texto de prompt y
referencias `artifact://...` (nunca bytes binarios inline), de unos
pocos KB; 1 MiB deja más de 100x de margen sin dejar de acotar el peor
caso. `_read_line()` levanta `LineTooLongError` en cuanto el buffer
supera ese límite, antes de intentar decodificar nada. `_serve()` la
atrapa igual que ya atrapaba `socket.timeout`/`OSError`: corta esa
conexión (sin responder nada — mismo criterio que cuando el cliente
cierra temprano) y sigue sirviendo conexiones siguientes con
normalidad, auditado (`EventType` nuevo:
`"kernel_bus_line_too_long"`).

**Fuera de alcance, a propósito**: `tool_integration/kernel_client.py`
(el SDK que se copia DENTRO del contenedor de cada skill) tiene la
misma función `_read_line()` duplicada, mismo patrón sin límite — pero
ahí el riesgo es al revés: agotaría memoria de la propia skill
(sandboxeada, ya con límites de recursos de Docker), nunca del host.
No es el hallazgo que motivó este trabajo; queda anotado por si algún
día se decide hacerlo simétrico por prolijidad, no por necesidad de
seguridad.

3 tests nuevos en `tests/test_kernel_bus_socket_server.py`: unitario
directo de `_read_line()` con un `conn` falso que nunca manda un
salto de línea (rápido, sin socket real); confirmación de que un
pedido legítimo grande (200KB, bien por debajo del límite) sigue
funcionando igual — el fix no penaliza pedidos reales, solo el caso
sin límite; y un test de punta a punta con un socket Unix real que
manda >1 MiB sin salto de línea, confirma que el servidor corta esa
conexión sin respuesta, lo audita, y sigue atendiendo la conexión
siguiente con normalidad (una skill hostil no puede tumbar el
servicio para las demás). Suite completa: 583 passed, 0 regresiones.

## Enter para enviar en el chat de la extensión de VS Code (2026-07-11)

Reporte de uso real (capturas de pantalla del usuario probando el
panel de chat instalado): `Enter` no enviaba el mensaje, solo agregaba
un salto de línea — a diferencia de `frontend/app.js` (interfaz web),
donde `Enter` ya envía y `Shift+Enter` hace salto de línea.
`vscode-extension/media/chat.js` tenía la condición invertida
(`ev.ctrlKey || ev.metaKey`, es decir Ctrl/Cmd+Enter para enviar).
Corregido a `!ev.shiftKey`, mismo comportamiento que la web.

## Distinción cliente web vs. agente IDE + restricción estructural de herramientas (2026-07-11)

**Hallazgo real, en las mismas capturas**: pedirle a kal desde la
extensión de VS Code "creá la página web para una panadería" fallaba
de tres formas distintas, en tres intentos sucesivos, cada uno
probado de verdad contra el modelo (`qwen3-coder:30b` vía Ollama), no
en teoría:

1. **Intento 1 (sin ningún fix)**: el modelo generó código Python con
   `import os` y `open('index.html', 'w')` dentro de `run_code` —
   rechazado por el validador estático (`code_analysis/denylist.py`,
   que prohíbe `os`/`open()` a propósito en ese sandbox). Diagnóstico
   real: `run_code` nunca pudo escribir archivos persistentes, el
   modelo no lo sabía y lo intentaba de todos modos.
2. **Intento 2 (regla de prompt genérica)**: se agregó una regla al
   `SYSTEM_PROMPT` pidiendo explícitamente responder con el código en
   la respuesta en vez de intentar escribir archivos. Probado en
   vivo: el modelo dejó de intentar `open()`, pero interpretó "página
   web" como "necesito imágenes" — generó 3 fotos de panadería sin
   relación con HTML/CSS/JS, intentó una 4ta imagen totalmente ajena
   (paisaje de montaña), chocó con el tope de repeticiones, y
   respondió "¡Entendido!" sin código ni explicación.
3. **Aquí el usuario aclaró un límite de alcance importante**: esta
   corrección de comportamiento debía aplicar SOLO a la faceta de
   agente IDE (VS Code) — la interfaz web debía seguir generando
   imagen/audio/video como comportamiento validado de siempre. Esto
   requirió que el backend supiera de qué cliente viene cada pedido.
   **Implementado**: `ChatRequest.client: str | None` nuevo
   (`agent_core/orchestrator.py`) — `None`/`"web"` = comportamiento de
   siempre, `"vscode"` = la extensión (`kalClient.ts::chat()` ahora
   manda `client: "vscode"` siempre). `ContextService.build()` gana un
   parámetro `client`; si es `"vscode"`, agrega una instrucción nueva
   (`_VSCODE_CLIENT_INSTRUCTION`) al único mensaje system fusionado
   (respeta la restricción ya documentada de nunca usar un segundo
   mensaje system).
4. **Intento 3, con la distinción de cliente ya en su lugar (regla de
   prompt condicional)**: probado en vivo de nuevo con
   `client: "vscode"` — el modelo TODAVÍA generó 2 imágenes + llamó a
   `system_info` 4 veces, chocó con el tope de repeticiones, y
   respondió con un párrafo confuso sin código. **Conclusión real,
   confirmada dos veces con reglas de prompt distintas**: pedirle al
   modelo por texto que no llame a una herramienta disponible no es
   una garantía — mismo patrón ya documentado con
   `max_tool_repeats` (bug de la "raqueta de tenis": "la regla de
   SYSTEM_PROMPT sola no alcanzó").
5. **Fix real, estructural, no de prompt**: `AgentLoop` excluye del
   toolset que arma para el modelo (`_build_tools_from_registry`,
   `agent_core/llm/agent_loop.py`) las herramientas multimedia cuando
   `client == "vscode"` — nueva constante `_MULTIMEDIA_TOOL_NAMES`
   (image_generation, audio_generation, video_composition,
   image_editing, image_composition, speech_to_text,
   image_via_kernel, audio_via_kernel, voice_roundtrip_via_kernel,
   image_inpaint_via_kernel). El modelo ni siquiera VE estas
   herramientas en la lista que se le manda a Ollama — no es una
   petición que pueda ignorar. `client` se enhebra desde
   `ChatRequest` → `PlanningAgentLoop.run()` → `AgentLoop.run()` →
   `_current_tools(client)`.

**Verificación**: 6 tests nuevos (3 en `test_context_service.py`: la
instrucción se agrega solo con `client="vscode"`, nunca con
`None`/`"web"`, y se fusiona correctamente con artefacto/contexto de
editor en el único mensaje system; 3 en `test_agent_loop.py`: el
toolset real de herramientas — no un doble de prueba — excluye las
multimedia con `client="vscode"`, las mantiene con `client=None`, y un
tool_call "alucinado" hacia una herramienta excluida se rechaza como
desconocida en vez de ejecutarse). `npm test` de la extensión: 21/21.

**Límite honesto sobre la confirmación en vivo final**: el último
intento de reproducir el caso completo contra Ollama real dio timeout
de 120s, dos veces — investigado a fondo, no es un fallo del fix: esta
máquina está bajo presión real de memoria ahora mismo (el proceso de
Ollama con `qwen3-coder:30b` usa ~18.7GB de RAM de 27GB totales, con
apenas ~3.5GB "disponibles" contando el resto de procesos del
sistema/navegador). El mecanismo en sí (qué herramientas se le mandan
al modelo) es código determinístico ya verificado con tests reales
sobre el registry real de herramientas, no un doble — no depende de
que el modelo "elija bien", así que esa verificación alcanza aunque no
se haya podido repetir el flujo completo en vivo bajo esta carga de
memoria puntual.

Esta investigación de recursos, de paso, expuso un hallazgo real
aparte: `ImageService`/`AudioService`/`STTService` (`kernel_bus/
services.py`) cargan su modelo perezosamente pero nunca lo descargan
— una vez generada una imagen, ese pipeline de varios GB queda en RAM
para siempre mientras viva el proceso. Motivó una propuesta del
usuario de un "Resource Broker" más amplio — evaluada, no
implementada todavía, ver memoria del proyecto.

## LLM en la nube como alternativa a Ollama local (2026-07-11)

El usuario recordó un principio de fondo del proyecto (ya confirmado
antes, ver "Confirmación explícita: kal es para uso general, no
personal" más arriba): kal se DISTRIBUYE a usuarios con hardware muy
distinto — el problema real de memoria que se acababa de encontrar
(Ollama con `qwen3-coder:30b` usando ~18.7GB de RAM) lo podría sufrir
cualquier otro usuario con menos RAM/VRAM que esta máquina de
desarrollo, y la aplicación debe estar preparada para eso desde ya,
no después. Pidió poder probar un modelo en la nube (Qwen, Grok/xAI,
u otro) como alternativa real a Ollama local.

**Lo que ya estaba construido y no hubo que rehacer**: el contrato
`LLMProvider` (F1) y `OpenAICompatibleClient` (F2, `agent_core/llm/
openai_compatible_client.py`) — ya soportaba `api_key` vía header
`Authorization: Bearer` desde el día que se escribió, solo nunca se
había probado contra un proveedor real en la nube (F2 lo validó
contra el propio endpoint OpenAI-compatible de Ollama, sin costo).

**Lo que faltaba, implementado ahora**: `utils/config.py::LLMConfig`
gana `provider: Literal["ollama", "openai_compatible"] = "ollama"` —
mismo patrón ya usado en `ImageGenConfig`/`AudioGenConfig`
(`backend: "local" | "api"`). Nueva fábrica
`agent_core/orchestrator.py::build_llm_client()`: con
`provider: "ollama"` (default) construye `OllamaClient()` exactamente
como antes, cero cambio de comportamiento; con
`provider: "openai_compatible"` construye `OpenAICompatibleClient`
apuntando a `settings.llm.base_url` (tiene que ser la URL COMPLETA que
pida el proveedor elegido, sin agregarle nada por detrás) con la key
de `LLM_API_KEY` (nuevo en `.env.example`). Fail-closed: sin la key
configurada, kal ni arranca, con un error claro — mismo criterio que
`IMAGE_GEN_API_KEY`/`AUDIO_GEN_API_KEY` en los adaptadores
multimodales, nunca intentar sin autenticación. `config/config.yaml`
documenta ejemplos reales de `base_url`/`default_model` para Qwen
(DashScope), Grok/xAI y OpenAI.

3 tests nuevos (`tests/test_llm_client_factory.py`): provider default
construye `OllamaClient`; `openai_compatible` sin `LLM_API_KEY` falla
cerrado con el mensaje claro; con la key, construye
`OpenAICompatibleClient` apuntando exactamente a la URL configurada.

**Pendiente real, no simulado**: el usuario eligió probar con
Grok/xAI en concreto — falta que configure su propia API key (no
compartida en esta conversación, por seguridad) y confirme para hacer
la prueba real en vivo (`/models`, `/status`, `/chat`) contra la API
de verdad, no solo contra dobles de prueba.

## Interfaz web para configurar el modelo (local o en la nube) (2026-07-11)

Seguimiento inmediato de lo anterior: el usuario pidió una interfaz
para que cualquier usuario cambie de proveedor sin editar
`config.yaml`/`.env` a mano — coherente con "kal se distribuye, no es
de uso personal".

**Implementado**: `agent_core/llm_settings.py` (nuevo) —
`get_llm_settings()` (nunca devuelve la API key en sí, solo
`has_api_key: bool`) y `update_llm_settings(provider, base_url=,
default_model=, api_key=)`. Persiste con reemplazo de texto DIRIGIDO
(regex ancorado a inicio de línea), nunca `yaml.dump()`/reescritura
completa — mismo criterio que `tool_integration/skills.py::
set_skill_enabled()`: `config.yaml` tiene comentarios reales
(ejemplos de `base_url` por proveedor) que un dump destruiría.
Verificado con un test que efectivamente busca que esos ejemplos
comentados sigan intactos después de un update. Si `.env` no existe
todavía, se crea a partir de `.env.example` antes de escribir la key
(no asume que ya existe).

Valida ANTES de escribir nada: `provider: "openai_compatible"` sin
`base_url` (o con el default de Ollama sin cambiar) rechaza con un
mensaje claro; sin ninguna API key (ni nueva ni ya guardada), también
— así nunca se deja `config.yaml` apuntando a un estado que después
haría fallar el arranque completo del proceso.

Dos endpoints nuevos en `orchestrator.py`: `GET /settings/llm` (sin
auth, nunca expone la key) y `POST /settings/llm` (gateado con el
token admin, mismo mecanismo que self-modification/VS Code). Un
update exitoso no solo persiste a disco — reconstruye el cliente real
(`build_llm_client()`) y lo re-inyecta en TODO lo que ya tenía una
referencia vieja (`orchestrator.llm`, `.agent.llm`,
`.planning_agent.planner.llm`, `.self_diagnosis.llm`) para que el
cambio tenga efecto de inmediato, sin reiniciar el proceso.

Nueva pestaña **"Modelo"** en la interfaz web (`frontend/index.html`/
`app.js`/`style.css`): selector de proveedor, URL base, modelo por
defecto, API key (nunca prellenada, solo un indicador de "ya
configurada"/"no configurada"). Al guardar, también refresca el
selector de modelo del chat (`loadModels()`) — depende del proveedor
recién activado.

**Verificado real, no solo con tests**: `GET /settings/llm` contra el
proceso real; `POST` sin token → 401; con token pero sin `base_url`
para `openai_compatible` → 400 con el mensaje claro, SIN tocar
`config.yaml`; `POST` con `provider: "ollama"` (no-op seguro, mismos
valores ya vigentes) → 200, confirmado con `grep` que `config.yaml`
sigue exactamente igual, comentarios/ejemplos incluidos. 12 tests
nuevos (9 en `test_llm_settings.py`, 3 en
`test_orchestrator_llm_settings.py`), más una entrada nueva sumada al
gate compartido ya existente de `test_orchestrator_admin_auth.py`
(sin agregar un test nuevo ahí, solo extiende la lista que ya recorren
los 3 tests de ese archivo) — sumado a los 3 de
`test_llm_client_factory.py` del ítem anterior, 15 tests nuevos en
total para todo el trabajo de LLM en la nube.

**Pendiente real, sigue igual**: la prueba en vivo contra Grok/xAI de
verdad (no simulada) sigue esperando que el usuario configure su
propia API key.

## Rediseño de la pestaña "Modelo": alcance correcto + bug real de UX (2026-07-11)

Probando la pestaña recién agregada, el usuario reportó dos problemas
reales (con capturas):

1. **Alcance mal pensado por mí**: la pestaña tenía `provider`/
   `base_url`/`default_model` como un formulario genérico — pero
   `default_model` es redundante con el selector de modelo que YA
   existe en la barra de chat (`#model-select`, alimentado por
   `GET /models`) — ese selector ya lista los modelos del proveedor
   ACTIVO en cada momento, sea local o en la nube. El usuario lo
   señaló explícitamente, y además recordó que la selección de modelo
   apropiado por tarea es justamente lo que se viene preparando para
   que decida kal mismo (ver `[[project_resource_broker_proposal]]`)
   — no algo para que el usuario tipee a mano en otro lado. Alcance
   correcto, dado explícitamente: esta pestaña debe tener SOLO (a)
   descargar un modelo Ollama nuevo, y (b) configurar la API key de un
   proveedor en la nube.
2. **Bug real de UX**: el campo de API key (`type="password"`)
   quedaba justo después de un campo de texto (`default_model`) en el
   mismo `<form>` — Firefox lo interpretó como un formulario de login
   real y ofreció "guardar la contraseña", usando el nombre del modelo
   como "usuario". Confirmado en la captura del usuario.

**Rediseño implementado**:
- `agent_core/llm_settings.py` gana `list_local_ollama_models()` (lista
  lo YA descargado, hablando siempre con el Ollama LOCAL fijo —
  `http://localhost:11434` — nunca con `settings.llm.base_url`, que
  podría apuntar a un proveedor en la nube si ese es el activo) y
  `pull_ollama_model(model)` (equivalente a `ollama pull`, vía la
  misma API HTTP que usa el CLI de Ollama, timeout generoso de 1 hora
  — una descarga real pesa varios GB).
- Dos endpoints nuevos: `GET /settings/llm/ollama/models` (sin auth,
  Ollama caído se informa como estado real —
  `ollama_available: false`—, nunca un 500) y
  `POST /settings/llm/ollama/pull` (gateado con token admin, mismo
  mecanismo que el resto).
- Pestaña "Modelo" reescrita: sección "Local (Ollama)" con la lista de
  modelos ya descargados + un campo para pedir uno nuevo (con link a
  ollama.com/library); sección "En la nube" con un selector de
  PRESETS (Qwen/Grok/xAI/OpenAI/Otro) que autocompleta la `base_url`
  correcta en vez de pedir que el usuario la tipee de memoria, más el
  campo de API key — ahora en su propio `<form>`, aislado, sin ningún
  campo de texto plano adyacente (elimina el patrón que confundía a
  Firefox), con un botón 👁 para mostrar/ocultar en vez de depender
  de que el navegador no intente "ayudar". Sin campo de
  `default_model`: guardar la config en la nube ya alcanza para que
  el selector de modelo de la barra de chat liste los modelos reales
  de ese proveedor.

**Verificado real, no solo con tests**: `GET /settings/llm/ollama/models`
contra el proceso real (5 modelos locales reales, incluido un
`glm-5.1:cloud` — confirma que Ollama Cloud ya es una opción real
soportada por el propio Ollama, aparte de este trabajo). Descarga real
de un modelo chico (`qwen2.5:0.5b`, ~400MB) vía
`POST /settings/llm/ollama/pull` con el token admin real — confirmado
con un segundo `GET` que el modelo nuevo aparece en la lista. 8 tests
nuevos (4 unitarios de `list_local_ollama_models`/`pull_ollama_model`
con `requests` mockeado, 4 de los endpoints nuevos), más una entrada
sumada al gate compartido de `test_orchestrator_admin_auth.py`.

**Nota sobre el bug de Firefox**: no hay forma 100% confiable de
evitar que un navegador ofrezca guardar un campo `type="password"`
como contraseña de sitio — es una heurística del navegador, no algo
que la página controle del todo. La combinación aplicada (sin campo
de texto adyacente + form propio + toggle mostrar/ocultar) resuelve
la causa concreta que se observó, pero no es una garantía absoluta
para cualquier navegador.

## Fricción real del token admin en el navegador + error HTTP sin cuerpo (2026-07-12)

Dos hallazgos reales probando la pestaña "Modelo" contra Grok/xAI de
verdad, con capturas del usuario:

1. **Fricción repetida con el token admin**: el usuario tropezó más de
   una vez con "Token administrativo inválido o ausente" al guardar,
   porque ese navegador/pestaña todavía no tenía el token en
   localStorage — hasta ahora, la única vía era visitar a mano
   `?admin_token=...` (impreso en el log al arrancar). Fix real:
   `frontend/app.js::api()` ahora detecta un 401, muestra un
   `prompt()` pidiendo el token, lo guarda, y reintenta la MISMA
   acción una sola vez (nunca en loop) — sin esto, la fricción iba a
   seguir repitiéndose cada vez que alguien probara desde un
   navegador/perfil nuevo.
2. **Bug cosmético de paso**: el campo "URL base de la API" (solo
   debería verse con el preset "Otro") quedaba visible con "Grok
   (xAI)" seleccionado — no afectaba lo que se guardaba de verdad
   (el submit usa el preset, ignora ese campo salvo con "Otro"), pero
   confundía. Se agregó un recálculo defensivo de `hidden` también en
   `refreshModelSettings()`, no solo en el evento "change" del select.

**Hallazgo más importante, investigando el error real de Grok**: una
vez resuelto el token, guardar la configuración de Grok funcionó, pero
el selector de modelo de la barra de chat mostró "ollama no
disponible" y la lámpara de LLM se puso roja. La causa NO era un bug
de kal — `agent_core/llm/openai_compatible_client.py` descartaba el
CUERPO de cualquier error HTTP (`str(HTTPError)` solo trae la línea de
estado, nunca el cuerpo, que es justo donde un proveedor real explica
QUÉ está mal). Sin verlo, el error era indiagnosticable a ciegas.

**Fix real**: nueva función `_response_detail()` en
`openai_compatible_client.py` — si la excepción trae un
`.response` real, agrega su cuerpo (truncado a 500 caracteres) al
mensaje de error. Aplicado a `chat()` y `list_models()`. Con esto,
apareció el error REAL de xAI: `GET /models` devolvía 403 con
`"Your newly created team doesn't have any credits or licenses
yet."` — una cuenta nueva de xAI sin facturación cargada, nada que
arreglar en kal. `POST /chat/completions` devolvía 400 con `"Model
not found: qwen3-coder:30b"` — consecuencia directa de lo anterior
(sin `/models` funcionando, el selector de modelo nunca se actualiza
con nombres reales de Grok y se queda con el default de Ollama). Una
vez que el usuario cargue facturación en su cuenta de xAI, ambos
deberían resolverse solos — no se necesita más cambio de código para
este caso puntual.

2 tests nuevos en `tests/test_openai_compatible_client.py`
confirmando que el cuerpo real aparece en el mensaje de error — el
`FakeResponse` de los tests existentes se actualizó para adjuntar
`response=self` al `HTTPError`, como hace `requests` de verdad
(sin eso, los tests no podrían haber detectado esto). El fix del
token admin (frontend) no tiene test automatizado — es interacción de
navegador (`prompt()`), mismo criterio ya aplicado a otras piezas
puramente de UI en este proyecto.

## Sin cuenta con créditos en Grok/xAI: kal quedaba SIN SALIDA, más confusión Groq≠Grok (2026-07-12)

El usuario planteó dos objeciones reales y correctas sobre el
diagnóstico anterior:

1. **"Eso no debe ocasionar que no se muestren los demás modelos... kal
   queda inhabilitado y no hay manera de seleccionar nuevamente un
   modelo local"** — tenía razón. El rediseño de la pestaña "Modelo"
   había quitado el selector de `provider` genérico (correcto, era
   redundante) pero sin querer también quitó la ÚNICA forma de volver
   a activar Ollama local una vez que se activaba un proveedor en la
   nube — si ese proveedor fallaba (como acá, sin créditos), no había
   ninguna salida desde la interfaz.
2. **"Tengo una API key de Grok que empieza con gsk_...¿la puedo
   usar?"** — esa key es de **Groq** (api.groq.com, el fabricante de
   chips de inferencia rápida), NO de **Grok/xAI** (api.x.ai) — dos
   empresas y APIs distintas con nombres casi idénticos. Las keys de
   xAI empiezan con `xai-...`, las de Groq con `gsk_...`. Confusión
   real y entendible, nunca aclarada hasta ahora.

**Implementado**:
- Botón nuevo "Usar Ollama local" en la sección local de la pestaña
  "Modelo" — un clic vuelve a `provider: "ollama"` sin pedir nada más,
  siempre disponible como salida de emergencia.
- Preset nuevo "Groq" en el selector de proveedores en la nube
  (`https://api.groq.com/openai/v1`), distinto y aclarado en el propio
  texto de la opción respecto de "Grok (xAI)".
- `frontend/app.js::loadModels()` ya no dice "ollama no disponible"
  a ciegas cuando falla — decía eso incluso con un proveedor en la
  nube activo, mintiendo sobre la causa. Ahora es genérico y manda a
  la pestaña Modelo.

**Bug real y más grave, encontrado probando el botón nuevo**:
`update_llm_settings(provider="ollama")` sin `base_url` explícito NO
reseteaba `base_url` — quedaba con el valor del proveedor en la nube
anterior. Confirmado en vivo: después de activar Grok y volver a
"ollama", `config.yaml` quedó con `provider: "ollama"` pero
`base_url: "https://api.x.ai/v1"` — `OllamaClient` intentaba pegarle a
`https://api.x.ai/v1/api/tags` (404), sin ninguna forma de
recuperación desde la interfaz. Fix: `update_llm_settings()` ahora
resetea `base_url` al default de Ollama automáticamente cuando
`provider == "ollama"` y no se pasa uno explícito (un `base_url`
explícito — p.ej. un puerto no estándar — sigue respetándose).

**Efecto secundario real encontrado**: el `config.yaml` REAL del
proyecto había quedado en ese estado corrupto por pruebas manuales
anteriores en esta misma sesión — y como `utils.config.settings` es
un singleton cargado una sola vez de ese archivo real al importar, la
suite de tests heredaba silenciosamente ese estado corrupto como
línea de base. `tests/test_llm_settings.py::_fake_paths` ahora fuerza
un estado conocido de `settings.llm` ANTES de cada test (no solo
restaura "lo que hubiera antes") — confirmado corriendo la suite con
el estado real deliberadamente corrompido primero, sigue pasando
igual.

4 tests nuevos (2 del reseteo de `base_url`, más el fixture de
aislamiento corregido). Corregido también el `config.yaml` real del
proyecto (vuelto a `http://localhost:11434`) y confirmado en vivo que
`/models` volvió a listar los modelos locales reales.

## Auto-provisión del token administrativo para loopback (2026-07-12)

Probando el preset "Groq" nuevo, el usuario primero eligió "Grok
(xAI)" por error (nombres muy parecidos, confirmado con el error real
de xAI: "Incorrect API key provided" — la key de Groq no sirve ahí).
Resuelto simplemente re-eligiendo el preset correcto.

El planteo de fondo fue otro, y más importante: **"no me parece
práctico que un usuario inexperto tenga que ingresar el token
administrativo copiándolo desde la terminal, debe haber otra
solución"**. Correcto — copiar un token de una terminal es una
fricción real e injustificada para el caso normal de uso.

**Análisis de seguridad antes de tocar nada**: el token existe para
un problema concreto (revisión de seguridad 2026-07-09): cualquiera
que alcance el puerto de kal, sin verificar identidad, podía aprobar
self-modification/herramientas. Pero ese riesgo es sobre acceso
**remoto** (LAN) — alguien que YA está en la misma máquina donde corre
kal podría leer `data/keys/admin_token` directamente del disco, así
que entregárselo por HTTP no le da ninguna capacidad nueva a un
atacante local. La distinción correcta no es "pedir el token siempre"
vs. "nunca pedirlo" — es **loopback vs. LAN real**.

**Implementado**: `GET /admin-token` (nuevo, sin token requerido) en
`agent_core/orchestrator.py` — responde con el token real SOLO si
`request.client.host` es `127.0.0.1`/`::1` (mismo criterio que
`docker-compose.yml`, que ya solo publica el puerto en loopback);
cualquier otra IP (el caso real que el token protege) recibe 403 sin
el token. `frontend/app.js::ensureAdminToken()` (nuevo) lo pide solo
al arrancar, únicamente si no hay ya un token guardado — si el
backend responde 403 (acceso no-loopback), no pasa nada, sigue
funcionando el `prompt()` de respaldo ya existente. Con esto, usar kal
desde la propia máquina (el caso normal) queda con CERO fricción de
token — nunca hay que copiar nada de una terminal.

**Detalle real de testing**: `TestClient` de Starlette simula por
default un peer `"testclient"`, no loopback — hubo que pasar
`client=("127.0.0.1", puerto)`/`client=("::1", puerto)` explícito para
poder probar de verdad el camino de loopback, y una IP de LAN real
(`192.168.1.50`) para confirmar que sigue bloqueado. 4 tests nuevos.
Verificado también en vivo contra el proceso real corriendo
(`curl http://127.0.0.1:8000/admin-token` devuelve el token real).

## Selector de modelo resiliente ante un proveedor roto (2026-07-12)

El usuario planteó una pregunta de diseño real y correcta: si el
proveedor activo falla (p.ej. una API key sin créditos, el caso real
que se venía dando con la key de Groq puesta por error contra xAI),
¿cómo elige un usuario alguno de sus otros modelos ya activados? Antes
de este fix, la respuesta era "no puede desde el selector de la barra
de chat" — `loadModels()` solo mostraba un mensaje de error genérico
si `/models` fallaba, dejando el selector totalmente inutilizable
hasta ir a la pestaña "Modelo" a mano.

**Implementado**: `loadModels()` (`frontend/app.js`), si `/models`
falla, en vez de solo mostrar un error, pide
`/settings/llm/ollama/models` (los modelos locales YA descargados,
independiente del proveedor activo roto) y los ofrece directo en el
mismo selector, marcados como "(local — activa Ollama)". Elegir
cualquiera de esos dispara un listener de `"change"` nuevo que
reactiva `provider: "ollama"` de inmediato (no recién al mandar el
próximo mensaje) y refresca el estado — recuperación de un clic, sin
pasar por la pestaña "Modelo" para nada.

**Verificado real, no solo en teoría**: reproducido el estado roto de
verdad (la key de Groq puesta contra el endpoint de xAI, error real
"Incorrect API key provided"), confirmado que
`/settings/llm/ollama/models` sigue funcionando con el proveedor
activo roto, y que la secuencia completa (activar `ollama` →
`/models` vuelve a andar) se comprueba en el backend real. Sin tests
automatizados nuevos (100% lógica de DOM/frontend, mismo criterio que
otras piezas de UI de este proyecto) — verificado por lectura +
llamadas reales a la API subyacente.

## Perfiles de proveedores en la nube guardados a la vez (2026-07-12)

El usuario pidió, correctamente, ir un paso más allá del fallback
solo-a-Ollama: **"en el selector de modelo activo no solo deben
mostrarse los modelos locales ollama, sino todos los modelos en la
nube correctamente activados"**. Hasta acá, kal solo recordaba UN
proveedor en la nube a la vez (una sola `base_url`/`LLM_API_KEY`) —
guardar uno nuevo pisaba el anterior sin dejar rastro.

**Decisión de alcance, confirmada con el usuario vía
`AskUserQuestion`**: guardar VARIOS perfiles a la vez, cada uno con su
propia API key persistida (opción recomendada, sobre la alternativa
de solo "recordar cuáles funcionaron antes" sin guardar las keys).

**Implementado**: `data/keys/cloud_profiles.json` (nuevo) — lista de
perfiles (`name`/`base_url`/`api_key_env`), gestionado 100% por kal
(a diferencia de `config.yaml`, no tiene comentarios de autor que
preservar, así que acá SÍ es seguro reescribirlo entero en cada
cambio). Cada perfil guarda su key en su PROPIA variable de entorno
(`LLM_API_KEY_<NOMBRE>`, p.ej. `LLM_API_KEY_GROQ`) — nunca se pisan
entre sí, ni con la del proveedor ACTIVO (`LLM_API_KEY`, sin cambios).

`agent_core/llm_settings.py` gana `save_cloud_profile()`,
`list_cloud_profiles()`, `activate_cloud_profile()` (activa un perfil
ya guardado sin volver a pedir la key) y `list_model_sources()` — el
corazón del pedido: junta Ollama local + CADA perfil guardado que
responda con éxito AHORA MISMO (arma un `OpenAICompatibleClient`
temporal por perfil y llama a `.list_models()` de verdad) — un perfil
guardado pero roto (sin crédito, key inválida) simplemente no
aparece, nunca se muestra a medias. `update_llm_settings()` gana
`profile_name`: guardar y activar un proveedor en la nube desde la
pestaña "Modelo" ahora también lo deja guardado como perfil reusable,
sin un paso separado.

Dos endpoints nuevos: `GET /settings/llm/sources` (sin auth, la lista
completa de arriba) y `POST /settings/llm/activate-profile` (admin-gated,
`{"name": ...}`, reconstruye y reinyecta el cliente real igual que
`/settings/llm`).

**Frontend**: el selector de modelo del chat (`loadModels()`) ahora
arma `<optgroup>` por fuente (Ollama local + cada perfil que
respondió bien), con el modelo por defecto del proveedor activo
preseleccionado si aparece en la lista. Elegir cualquier modelo activa
su fuente al instante (Ollama o el perfil correspondiente), sin ir a
la pestaña "Modelo". El formulario de la pestaña "Modelo" manda
`profile_name` — el nombre corto del preset elegido (Qwen/Grok xAI/
Groq/OpenAI) o, para "Otro", un campo nuevo pidiendo un nombre corto
para reconocer el perfil después.

**Verificado real, de punta a punta, no solo con tests**: perfil de
prueba apuntado al propio endpoint OpenAI-compatible de Ollama (sin
necesitar una key de verdad ni red externa) — guardado, confirmado en
`data/keys/cloud_profiles.json`, `/settings/llm/sources` lista AMBAS
fuentes (Ollama local + el perfil) con sus modelos reales,
`activate-profile` lo activa, y activar un perfil inexistente falla
limpio con 400 sin romper nada. Datos de prueba limpiados al terminar,
proveedor activo devuelto a "ollama". 13 tests nuevos (9 en
`test_llm_settings.py`, 4 en `test_orchestrator_llm_settings.py`),
más una entrada sumada al gate compartido de
`test_orchestrator_admin_auth.py` (sin necesitar mock: un perfil
inexistente ya falla barato, mismo criterio que self-modification).

## Tres bugs reales: Enter en VS Code sin efecto, index.html cacheado, extensión desactualizada (2026-07-12)

Tres reportes del usuario en un mismo mensaje, cada uno con causa
real distinta:

1. **"El botón enviar debe activarse al presionar Enter" (VS Code)**:
   el fix ya existía en el código fuente
   (`vscode-extension/media/chat.js`, commit de la sesión anterior),
   pero la extensión INSTALADA en su VS Code seguía siendo de antes de
   ese fix — nunca se había reinstalado después. Confirmado
   comparando el archivo fuente contra el de
   `~/.vscode/extensions/undefined_publisher.kal-vscode-0.1.0/media/
   chat.js` (todavía con `ev.ctrlKey || ev.metaKey`). Solución: NO fue
   un cambio de código, fue reinstalar de verdad vía
   `POST /integrations/vscode/install` — confirmado que la extensión
   reinstalada ya trae `!ev.shiftKey`. **Lección**: un fix en el
   repo no alcanza si la extensión empaquetada no se reinstala — a
   tener en cuenta después de cualquier cambio a `vscode-extension/`.

2. **"El selector de modelo activo... ya no reconoce ni a qwen local",
   con una key de Grok que "funciona en otra aplicación"**: investigado
   contra el backend real primero — `GET /settings/llm/sources`
   mostraba TODO bien (Ollama local con sus modelos reales, Y el
   perfil de Grok con su lista real de modelos de Groq, confirmando
   que la key sí era válida). El backend nunca tuvo el bug. La causa
   real era el frontend: `frontend/index.html` se servía CON caché
   normal del navegador (a diferencia de `style.css`/`app.js`, que ya
   tenían `Cache-Control: no-store` desde antes) — un `index.html`
   viejo cacheado, combinado con el `app.js` nuevo (ese sí siempre
   fresco), rompía en silencio: el JS nuevo esperaba elementos que el
   HTML viejo no tenía. La suposición original documentada en el
   código ("index.html no cambia tan seguido") dejó de ser cierta:
   ganó varias pestañas/campos nuevos en esta misma sesión. Fix: nueva
   ruta explícita `GET /` en `agent_core/orchestrator.py`
   (`serve_index_html()`, registrada antes del mount catch-all) con
   el mismo `Cache-Control: no-store` que ya tenían los otros dos
   archivos. Como el HTML viejo ya estaba en la caché del usuario
   ANTES de este fix, hace falta un refresh forzado una vez
   (Ctrl+Shift+R) para bajar la versión nueva — de ahí en más, las
   recargas normales ya siempre traen la versión actualizada.

3 tests nuevos (`tests/test_orchestrator_static_frontend.py`) —
de paso cubren también `style.css`/`app.js`, que nunca habían tenido
test para esta protección a pesar de ya existir.

## Selector de modelo: solo "listos para usar" + bug real de os.environ obsoleto (2026-07-12)

Dos pedidos del usuario en el mismo mensaje: que el selector de
modelo activo "solo muestre los modelos correctamente configurados y
listos para usar" (aparecía una lista grande de modelos que no
respondían), y que una key de Groq real y con crédito ("la uso en
otra aplicación y funciona sin problema") seguía sin ser reconocida
por kal, que además "ya no reconoce ni a qwen local".

**"Listos para usar" — dos casos reales encontrados, no hipotéticos**:

1. `GET /v1/models` de un proveedor real (Groq) devuelve TODOS sus
   modelos hospedados, no solo los de chat — `whisper-large-v3`
   (habla-a-texto), `llama-prompt-guard`/`gpt-oss-safeguard`
   (clasificadores de seguridad), `orpheus` (texto-a-voz), etc.
   aparecían mezclados con los modelos de chat de verdad, aunque
   nunca podrían responder a un `/chat` de kal. Fix: filtro heurístico
   por nombre (`_NON_CHAT_MODEL_KEYWORDS` en `agent_core/llm_settings.py`)
   — no es una garantía (no hay un campo "tipo" estándar en la
   respuesta), pero cubre los casos reales encontrados.
2. Los modelos Ollama con sufijo `:cloud` (confirmado con
   `ollama list | grep cloud` → `glm-5.1:cloud`) son en realidad un
   proxy al servicio en la nube DE OLLAMA MISMO, que necesita su
   propia sesión (`ollama signin`) sin relación con la configuración
   de kal — sin ella, devuelven 401 al primer uso. Excluidos de
   `list_model_sources()` (siguen apareciendo en la gestión de
   descargas locales, donde sí tiene sentido verlos).

**El bug real detrás de "no reconoce ni a Groq ni a Qwen local"**:
diagnosticado primero ampliando el manejo de errores de
`list_model_sources()` (atrapaba solo `ProviderError`, cualquier otra
excepción hacía desaparecer un perfil del selector sin rastro en los
logs) — eso reveló en `logs/agent.log` un 401 real de Groq:
`"Invalid API Key"`, con la MISMA key que un proceso Python nuevo y
aislado aceptaba sin problema contra la API real de Groq. Reproducido
de forma aislada:

```python
os.environ['LLM_API_KEY_GROQ'] = 'PLACEHOLDER'
from dotenv import load_dotenv
load_dotenv()
print(repr(os.environ.get('LLM_API_KEY_GROQ')))  # -> 'PLACEHOLDER'
```

`load_dotenv()` (se re-ejecuta en cada `--reload` de uvicorn) **nunca
sobreescribe una variable que ya esté seteada** en el proceso. En
algún momento de la sesión (una prueba anterior, un primer intento de
guardado con la key equivocada) un valor viejo quedó "pegado" en
`os.environ` del proceso vivo — ningún `--reload` posterior, ni que el
`.env` en disco tuviera después el valor correcto, lo iba a corregir
jamás. Mismo mecanismo de fondo que
[Caché del navegador](#interfaz-web-para-configurar-el-modelo-local-o-en-la-nube-2026-07-11):
una copia vieja sirviendo mientras la fuente de verdad ya está
arreglada — pero acá la "copia vieja" vive en memoria del proceso, no
en el navegador.

**Fix**: nuevo `read_llm_env_var(key)` en `agent_core/llm_settings.py`
que lee el valor SIEMPRE del archivo `.env` en disco primero (con
fallback a `os.environ` solo si la clave no está en el archivo en
absoluto) — nunca confía en `os.environ` como fuente de verdad para
estas keys. Reemplaza todos los `os.environ.get(...)` de lectura en
`llm_settings.py` (`get_llm_settings`, `update_llm_settings`,
`activate_cloud_profile`, `list_model_sources`) y también en
`agent_core/orchestrator.py::build_llm_client()` (mismo riesgo exacto
para el proveedor que esté activo al arrancar). Los `os.environ[key]
= value` de ESCRITURA (al guardar una key nueva) se mantienen sin
cambios — el problema era solo de lectura.

**Verificado en vivo, no solo con tests**: contra el proceso real de
kal (corriendo con `--reload`, key de Groq efectivamente "envenenada"
en memoria) — tras el fix, `GET /settings/llm/sources` pasó a listar
correctamente tanto Ollama local (5 modelos) como el perfil "Groq"
completo (10 modelos de chat reales, sin los que no lo son), sin
ningún 401 nuevo en `logs/agent.log`. 2 tests nuevos en
`tests/test_llm_settings.py` reproducen exactamente el escenario
("os.environ viejo, .env en disco correcto y más nuevo" y "clave
ausente del archivo, cae a os.environ").

**Tercer síntoma del mismo mensaje explicado — "después de mi primer
pedido ollama dejó de responder"**: al verificar el proceso real
después del fix de arriba, `GET /status` devolvía `llm_available:
false` — el proveedor ACTIVO del proceso real había quedado en
`provider: "openai_compatible"` con `base_url` de Groq, pero la key
GENÉRICA (`LLM_API_KEY`, la que usa el proveedor que esté activo en
cada momento, distinta de `LLM_API_KEY_GROQ` que guarda cada perfil)
seguía siendo el placeholder de Ollama
(`no-hace-falta-para-ollama`) — un resto de una investigación en vivo
anterior en esta misma sesión, de antes del fix de `read_llm_env_var`.
Confirmado disparando `/chat` de verdad: 401 "Invalid API Key" contra
Groq. **No es un bug nuevo de código** — es el mismo problema de fondo
de esta sección, capturado en un estado real a medio arreglar. Fix
inmediato: `POST /settings/llm {"provider": "ollama"}` (el botón
"Usar Ollama local" hace exactamente esto) — confirmado
`GET /status` → `llm_available: true` y un `/chat` real respondiendo
correctamente contra Ollama local.

## Resource Broker — Fase 1: liberar RAM de servicios multimedia inactivos (2026-07-12)

El usuario reportó inconsistencia real cambiando entre modelos locales
(GLM-4.7-flash vs Qwen) para generar imágenes — la misma duplicidad de
sujetos ya vista antes, y "después de mi primer pedido ollama dejó de
responder". Investigando `logs/agent.log`: justo después de cada
generación de imagen, Ollama queda **totalmente inalcanzable**
(`Connection refused`) durante 1-2 minutos, hasta reiniciarse solo.

Propuse inicialmente que era contención de GPU/VRAM — el usuario
corrigió: su máquina no usa GPU ni NPU para esto. Confirmado en el
código (`kernel_bus/services.py`): todo corre explícitamente en CPU
(`device="cpu"`, `use_cuda=False`). El mecanismo real es **RAM del
sistema**: `ImageService`/`AudioService`/`STTService` cargan su modelo
perezosamente pero nunca lo descargan — un pipeline de varios GB queda
en RAM para siempre tras el primer uso, compitiendo con Ollama (que ya
usa ~18.7GB de 27GB con `qwen3-coder:30b`, dato del OOM real
investigado antes en esta misma sesión). El reintento de
`OllamaClient` (ya existente) mitiga el síntoma (la tarea no aborta
del todo) pero no evita que el proceso de Ollama se caiga.

Esto conecta con una propuesta más amplia que el usuario ya había
hecho antes (ver memoria `project_resource_broker_proposal`, entonces
sin evidencia concreta): un "Model Lifecycle Manager" completo —
descubrimiento de modelos, routing automático por capacidad, memoria
compartida entre Skills, descarga por presión de memoria, preloading
por contexto, políticas por hardware. Con evidencia real ahora en
mano, se decidió (vía plan explícito, aprobado antes de tocar código)
implementar **solo** la pieza justificada por el bug real: liberar RAM
de servicios inactivos. El resto queda deliberadamente fuera de esta
fase (ver más abajo).

**Implementado**: `kernel_bus/resource_broker.py` (nuevo) —
`ResourceBroker.register(name, is_loaded, unload)` +
`mark_used(name)` + `evict_idle_and_pressured()`: libera cada recurso
cargado que lleve más de `idle_timeout_seconds` sin uso (default 300s,
`config.yaml: resource_broker.idle_timeout_seconds`), o **todos** de
inmediato si `psutil.virtual_memory().available` cae debajo de
`min_available_ram_mb` (default 2048MB) — evicción agresiva ante
presión real, no solo por reloj. Singleton al final del módulo, mismo
patrón que `tool_registry`/`audit_log`/`kernel_bus`.

`kernel_bus/services.py`: los 4 recursos ya existentes se registran en
`__init__` con closures sobre `self` — `image.generate`,
`image.inpaint` (dos pipelines distintos de `ImageService`),
`audio.synthesize`, `stt.transcribe`. Cada `_get_X()` llama
`mark_used()` antes de comprobar si ya está cargado; `unload()`
simplemente vuelve el campo a `None` (el GC libera la RAM real — nada
más los referencia en producción, confirmado que
`tool_integration/registry.py::_register_default_static_tools()` crea
una única instancia compartida de cada servicio).

`agent_core/llm/ollama_client.py::OllamaClient.chat()`: llama
`evict_idle_and_pressured()` justo antes de `_post_with_retry()` — es
el único lugar que de verdad compite por RAM local con estos servicios
(un proveedor en la nube no usa RAM de esta máquina, por eso el
enganche va acá y no en `OpenAICompatibleClient`). `resource_broker`
inyectable en el constructor (default: el singleton real), mismo
patrón DI que `post_fn`/`get_fn`/`sleep_fn` ya usado ahí mismo.

`psutil` agregado explícito a `requirements.txt` (ya estaba instalado
como dependencia transitiva, ninguna descarga nueva).

**Verificado real, de punta a punta**: 15 tests nuevos
(`tests/test_resource_broker.py`: registro/uso reciente no se libera/
idle pasado el timeout se libera/nunca libera algo no cargado/presión
de RAM libera todo de inmediato aunque nada llegó al timeout; más 1
test nuevo en `tests/test_ollama_client.py` confirmando que `chat()`
llama al broker inyectado antes de postear). Suite completa
`pytest tests/ -q`, 0 regresiones. Confirmado en el proceso real
corriendo: instanciar los 3 servicios registra los 4 recursos
(`image.generate`, `image.inpaint`, `audio.synthesize`,
`stt.transcribe`) con `is_loaded() == False` antes del primer uso.

**Fuera de alcance de esta fase, documentado explícitamente**:
routing automático de LLM por capacidad (sigue sin haber un segundo
caso de uso real — un solo modelo activo a la vez, elegido a mano),
preloading inteligente por contexto (sin heurística concreta
definida), políticas por hardware más allá de las dos perillas de
config ya agregadas (esta máquina confirmada 100% CPU, sin GPU que
detectar distinto), y descubrimiento de modelos multimedia (no aplica
hoy: imagen/audio/STT tienen un solo backend local cada uno).

## default_model quedaba pegado a Ollama al activar un proveedor en la nube — rompía el agente IDE de VS Code (2026-07-14)

El usuario reportó: "kal responde en la interfaz web pero no como
agente IDE en vscode". Revisé primero que la extensión instalada
coincidiera byte a byte con el código fuente actual (ya no era el bug
de "extensión desactualizada" de sesiones previas) y todo el flujo del
webview (CSP con nonce, `ChatViewProvider`, `chatWebviewHtml.ts`) sin
encontrar nada roto — necesité pedirle al usuario el error real
(`AskUserQuestion`) para seguir.

El error real: `https://api.groq.com/openai/v1 devolvió ... 404 ...
"The model \`deepseek-r1:14b\` does not exist"` — un nombre de modelo
de OLLAMA, contra la API de Groq. Confirmado contra `GET
/settings/llm`: `provider: "openai_compatible"` (Groq activo) con
`default_model: "deepseek-r1:14b"` (un modelo LOCAL). Causa real:
`default_model` es una perilla GLOBAL en `config.yaml`, no una por
proveedor — activar un proveedor en la nube (sea vía el selector de
modelo del chat o vía "Guardar y activar" en la pestaña Modelo) nunca
tocaba `default_model`, dejando pegado lo último que hubiera sido
válido para el proveedor ANTERIOR. La interfaz web no lo sufre porque
su selector de modelo siempre manda un `model` explícito en cada
`/chat` — pero el agente IDE de VS Code no tiene selector de modelo
propio (`kal.model` es una config de texto libre, vacía por defecto),
así que siempre depende de este default global, y ahí sí rompía.

**Fix**: `agent_core/llm_settings.py::update_llm_settings()` — si
`provider == "openai_compatible"` y el `base_url` efectivo CAMBIA
respecto al que ya estaba activo, y no se pidió un `default_model`
explícito, se elige automáticamente el primer modelo de chat real que
ese proveedor devuelva (`_first_chat_capable_model()`, reusa el mismo
filtro `_is_chat_capable_model_name()` de `list_model_sources()`). Si
el proveedor no responde, se deja `default_model` como estaba (no
peor que el estado actual). Mismo patrón ya usado para el bug análogo
de `base_url` no reseteándose al volver a Ollama.

**Verificado real, de punta a punta**: reproducido el estado exacto
del bug contra el proceso vivo (activar Groq sin modelo explícito),
confirmado que ahora elige un modelo real de Groq
(`meta-llama/llama-4-scout-17b-16e-instruct`) en vez de quedarse con
el nombre de Ollama, y un `/chat` con `client: "vscode"` (mismo cuerpo
que manda la extensión) respondiendo `status: "success"` de verdad.

De paso, corregidos 2 tests que dependían de comportamiento previo a
esta sesión: `tests/test_llm_client_factory.py` monkeypatcheaba
`os.environ` directamente sin aislar `agent_core.llm_settings._ENV_PATH`
— desde el fix de `read_llm_env_var` (antes en esta misma sesión), esos
tests quedaban enmascarados por el `.env` REAL del proyecto en disco;
y `test_list_model_sources_skips_a_profile_with_no_key_in_the_environment`
tenía el mismo problema (`save_cloud_profile()` ya escribe la key al
`.env` real de test, borrar solo `os.environ` no alcanzaba). 4 tests
nuevos en `tests/test_llm_settings.py` cubriendo la elección automática
de modelo (cambio de endpoint la dispara / mismo endpoint no la
dispara / un `default_model` explícito se respeta siempre / proveedor
roto no pisa el modelo anterior). Suite completa, 0 regresiones.

## Groq rompía cualquier tarea de más de un paso: dos bugs reales de interoperabilidad estricta del formato OpenAI (2026-07-14)

Con el default_model arreglado, el usuario probó de nuevo el agente
IDE de VS Code contra Groq y encontró DOS bugs reales más, cada uno en
un punto distinto del mismo flujo — ambos porque Groq valida el
formato OpenAI ESTRICTO, mientras que Ollama (contra el que se probó
todo originalmente) es tolerante y nunca los hizo notar.

**1. Un intento de tool-call mal formado tiraba la respuesta entera a
la basura**: "crea un proyecto html para un sitio web" devolvía un 400
de Groq: `code: "tool_use_failed"` — el modelo había intentado una
llamada a herramienta mal formada, pero el cuerpo del error YA incluye
en `failed_generation` la respuesta en texto plano que el modelo
quería dar antes de ese intento roto. Fix:
`agent_core/llm/openai_compatible_client.py::_tool_use_failed_fallback_content()`
detecta esta forma específica de error y usa `failed_generation` como
respuesta final en vez de propagar el 400 — el usuario recibe la
respuesta útil que el modelo sí tenía, solo se descarta el intento de
herramienta roto (irrecuperable de todos modos, no hay forma de saber
qué quiso llamar).

**2. `tool_calls[].function.arguments` como objeto, no como string**:
en cualquier turno DESPUÉS de una llamada a herramienta, Groq
rechazaba con 400 (`'arguments' : value must be a string`) —
`agent_core/llm/agent_loop.py` reconstruye el mensaje `assistant` con
`tool_calls` para el próximo turno, y mandaba `tc.arguments` (un dict
ya parseado) directo, sin `json.dumps()`. Ollama tolera un objeto ahí;
el formato OpenAI real exige un string con JSON adentro. Fix: serializar
con `json.dumps()` al reconstruir ese mensaje.

**3. Falta el 'id' de cada tool_call (y el 'tool_call_id' de su
respuesta)**: arreglado el punto 2, apareció un tercer 400:
`'tool_calls.0.id' : property 'id' is missing` — el formato OpenAI
exige un id único por tool_call en el mensaje `assistant`, correlacionado
con `tool_call_id` en el mensaje `role="tool"` que le responde. Ni
Ollama ni el fallback de texto plano (`_extract_fallback_tool_call`)
garantizan un id. Fix: `ToolCall` (contrato público en
`agent_core/llm/provider.py`) gana un campo `id: str | None = None`
(retrocompatible); ambos clientes (`OllamaClient`/`OpenAICompatibleClient`)
lo propagan si el proveedor lo manda; `agent_loop.py` genera uno
(`call_<hex>`) si falta, ANTES de construir los mensajes, y lo usa
consistente en `tool_calls[].id` (mensaje assistant) y `tool_call_id`
(mensaje tool).

**Verificado real, de punta a punta, los tres bugs juntos**: "ejecuta
este codigo: print(2+2)" (dispara el flujo de 2 pasos completo) y
"crea un proyecto html para un sitio web" (dispara tool_use_failed)
contra el proceso real con Groq activo — ambos ahora responden
`status: "success"` con la respuesta correcta, sin ningún 400. 7 tests
nuevos: 2 en `test_openai_compatible_client.py` (fallback de
tool_use_failed / un 400 distinto sigue propagándose), 2 en
`test_ollama_client.py` (id presente/ausente en el parseo), 2 en
`test_agent_loop.py` (arguments como string / id generado y
correlacionado), más una aserción nueva en un test ya existente de
`test_openai_compatible_client.py`. Suite completa, 0 regresiones.

## Permission Manager de filesystem del Kernel + creación real de archivos desde VS Code (2026-07-14)

El usuario notó que kal, como agente IDE, "entrega todo el código y da
instrucciones pero no crea automáticamente las carpetas ni los
archivos" — confirmado en el código: `CodeExecutionTool` prohíbe
`open()`/`import os` a propósito (sandbox aislado) y su propia
descripción le dice al modelo que genere el código en la respuesta
final, nunca que lo escriba; del lado de la extensión, la única
escritura real (`applyEdit.ts`) reemplaza un archivo ya abierto, nunca
crea archivos/carpetas nuevas.

En la discusión de diseño, el usuario planteó un "Permission Manager"
completo del Kernel — Skill + Recurso + Acción, con scopes de
aprobación (una vez/sesión/proyecto/skill), inspirado en el modelo de
confianza de carpetas de VS Code pero generalizado a cualquier Skill.
Explícitamente pidió diseñarlo COMPLETO ahora, no esperar a que otra
Skill lo necesite — kal se distribuye al público, no es de uso
personal, y hay que estar preparado para cualquier contingencia antes
de que un usuario real la reporte. Confirmado vía `AskUserQuestion`
por sobre la alternativa de escopar solo lo mínimo para VS Code.

**Límite arquitectónico real, no negociable**: el backend de Python
NUNCA sabe qué carpeta tiene abierta VS Code — solo la extensión lo
sabe. La escritura real al disco del proyecto SIEMPRE ocurre del lado
de la extensión (`vscode.workspace.fs`); el rol del Kernel es
política + auditoría, nunca ejecutar la escritura él mismo.

**Implementado — Kernel (nuevo, genérico, no solo para VS Code)**:
- `tool_integration/filesystem_permissions.py` (100% stdlib, mismo
  criterio de shipping que `permissions.py`): `FilesystemAction`
  (create/read/modify/delete/rename) × `FilesystemScope`
  (workspace/home/external).
- `tool_integration/filesystem_access_manager.py`:
  `FilesystemAccessManager.evaluate()` decide `auto_allowed` vs
  `requires_approval` por política de `config.yaml` (fail-safe: solo
  workspace+create/modify auto-permitido por default, todo lo demás
  requiere un humano) — consultando primero un store de concesiones ya
  otorgadas en 4 escalas tal como las planteó el usuario: `once`
  (nunca se persiste), `session` (memoria del proceso), `project`
  (persistido por recurso exacto), `skill` (persistido, cualquier
  recurso de esa skill). Toda decisión queda auditada
  (`audit/audit_log.py`, 4 `EventType` nuevos:
  `filesystem_access_requested/_granted/_denied/_escalated`). Para
  `requires_approval`, mismo patrón propose→pending→approve con token
  admin que ya existía para self-modification/herramientas dinámicas:
  `GET /filesystem-access`, `POST /filesystem-access/{id}/approve`
  (con el nivel de escala elegido), `POST /filesystem-access/{id}/deny`.

**Implementado — primer consumidor real (VS Code)**:
- `tool_integration/adapters/vscode_files.py::ProposeProjectFilesTool`
  (`propose_project_files`): el modelo propone `files: [{path,
  content}]` con rutas SIEMPRE relativas (rechaza absolutas y `..`,
  reforzado en la propia descripción de la herramienta al modelo);
  consulta `filesystem_access_manager.evaluate(scope=WORKSPACE,
  action=CREATE)` (auto-permitido por política default, pero deja
  auditoría) y devuelve la propuesta estructurada — nunca escribe nada
  ella misma. Excluida del toolset salvo `client == "vscode"` (mismo
  mecanismo que ya excluía herramientas multimedia PARA vscode, acá
  invertido: el cliente web no tiene ningún canal para aplicar una
  propuesta de archivos).
- `agent_core/llm/agent_loop.py::_artifact_to_observation()`: rama
  nueva para `modality="project_files"` — resumen en lenguaje natural
  para el modelo, NUNCA el contenido completo (la vista previa real la
  ve el usuario, del lado de la extensión).
- `agent_core/orchestrator.py::_step_artifact()`: antes solo
  serializaba `modality="image"` en la respuesta de `/chat` — se
  extiende para serializar `project_files` completo (request_id +
  archivos), de donde la extensión lo lee.
- `vscode-extension/src/projectFiles.ts` (nuevo): al recibir una
  respuesta de `/chat` con una propuesta, si no hay ninguna carpeta
  abierta ofrece "Abrir una carpeta..."; si hay workspace, modal con
  la lista de archivos + "Ver detalle" (documento virtual con todo el
  contenido) + Aplicar/Descartar (mismo patrón que
  `applyEdit.ts::runApplySuggestedEdit`, generalizado a varios
  archivos). Al aplicar: valida cada ruta (reusa
  `projectFilesFormat.ts::findFirstInvalidPath`, sin `import vscode`,
  testeable con Node normal — defensa en profundidad, aunque el
  backend ya validó lo mismo), avisa y pide confirmar si hay
  colisiones con archivos existentes (todo o nada, sin merge parcial),
  aborta TODO si algún path resuelto queda fuera de la raíz del
  workspace, y si todo está bien crea carpetas
  (`vscode.workspace.fs.createDirectory`) y escribe
  (`vscode.workspace.fs.writeFile`). Reporta el resultado real
  (escrito/descartado) a `POST /filesystem-access/{id}/report-outcome`
  (nuevo, deliberadamente SIN token admin — el Kernel ya auto-permitió
  esto por política, el endpoint solo audita qué pasó de verdad).

**Verificado real, de punta a punta, contra el proceso vivo**: pedido
real ("creá un index.html con un título que diga Hola Mundo, usando la
herramienta para proponer archivos de proyecto") con `client:
"vscode"` — el modelo llamó `propose_project_files`, la respuesta de
`/chat` trajo el `artifact` completo (`request_id` + archivos), y
`logs/audit.log` mostró la cadena real
`filesystem_access_requested` → `filesystem_access_granted`.
Confirmado también `POST /filesystem-access/{id}/report-outcome`
dejando el evento de auditoría correspondiente. Extensión reempaquetada
e instalada de nuevo (`POST /integrations/vscode/install` — lección ya
conocida: un cambio en `vscode-extension/` no alcanza sin esto),
confirmado que el `.vsix` instalado ya trae `projectFiles.js`/
`projectFilesFormat.js` y el método nuevo de `kalClient.js`. La
escritura real en un VS Code con GUI (fuera del alcance de este
entorno de desarrollo, sin pantalla) queda pendiente de confirmación
visual del usuario, mismo límite honesto que la integración de VS Code
original.

35 tests nuevos entre backend y extensión: `test_filesystem_access_manager.py`
(22, política + las 4 escalas de concesión + auditoría),
`test_propose_project_files_tool.py` (8, validación de paths + llamada
al Permission Manager), casos nuevos en `test_agent_loop.py` (exclusión
por cliente + rama de observación), `test_orchestrator_chat_project_files.py`
(serialización de `_step_artifact`), 2 nuevos en
`test_orchestrator_admin_auth.py` (gate de `/filesystem-access/*` +
`report-outcome` deliberadamente sin gate), y 8 en
`projectFilesFormat.test.ts` (validación de rutas, sin `vscode`).

**Fuera de alcance de esta fase, documentado explícitamente**:
autorizar/crear un workspace nuevo para una ruta EXTERNA (el escenario
"creá un proyecto en ~/Desktop/MiProyecto" que describió el usuario) —
el Kernel-side ya soporta scope HOME/EXTERNAL + aprobación admin-gated
para cualquier Skill futura, pero la UX específica de VS Code
("Crear nuevo workspace / Autorizar esta carpeta / Cancelar") no está
conectada — requiere que el modelo comunique una ruta absoluta de
forma confiable, sin canal bueno para eso hoy (parsear lenguaje natural
es frágil). Alternativa más simple para después: un comando nuevo con
selector nativo de carpeta (`vscode.window.showOpenDialog`) — la
elección explícita del usuario ES la autorización. Tampoco hay merge
parcial en colisiones (todo o nada), y las escalas `project`/`skill`
de concesión no las ejercita todavía VS Code de verdad (siempre
auto-permitido por política) — quedan listas para cuando haga falta.

## Tener la herramienta disponible no bastó: el modelo seguía sin usar propose_project_files (2026-07-14)

Probando la funcionalidad recién construida, el usuario pegó una
respuesta real de kal: seguía devolviendo el código en bloques de
texto y ofreciendo pegarlo a mano ("¿te gustaría que te proporcione un
script en Node.js que lo haga?") — exactamente el comportamiento
viejo, pese a que `propose_project_files` ya estaba registrada y
ofrecida al modelo para `client="vscode"`.

Causa real, encontrada en dos lugares: (1)
`agent_core/context_service.py::_VSCODE_CLIENT_INSTRUCTION` (inyectada
en CADA turno para el cliente VS Code) todavía decía literalmente "tu
respuesta final debe traer el código completo en bloques de código
**para que el usuario lo copie**" — una instrucción escrita ANTES de
que la herramienta existiera, ahora activamente contraproducente: le
decía al modelo, en cada turno, que el camino correcto era mostrar
texto, nunca mencionaba que ahora hay una herramienta real para
proponer archivos. (2) `agent_core/llm/agent_loop.py::SYSTEM_PROMPT`
tenía la misma laguna: "si el pedido requiere ese tipo de archivo, no
lo intentes escribir con run_code — es un error conocido, no algo
para reintentar de otra forma" — cierto sobre `run_code`, pero sin
redirigir a la alternativa real que ahora existe.

**Lección, coherente con un patrón ya visto varias veces en esta
sesión** (herramientas multimedia que había que EXCLUIR
estructuralmente del toolset porque una regla de prompt sola no
alcanzaba): acá el problema es el inverso — tener una herramienta
disponible en el toolset no es información suficiente para que el
modelo la prefiera sobre su hábito por defecto de responder solo en
texto, sobre todo si una instrucción vieja en el mismo prompt sigue
apuntando en la dirección contraria.

**Fix**: reescritas ambas — `_VSCODE_CLIENT_INSTRUCTION` ahora dice
explícitamente "IMPORTANTE: tenés disponible la herramienta
propose_project_files... usá SIEMPRE propose_project_files — no te
limites a mostrar el código en bloques y sugerir que lo copien"; el
bloque de `SYSTEM_PROMPT` sobre `run_code` ahora redirige a
`propose_project_files` cuando está disponible, y solo cae al
comportamiento viejo ("responder con el código completo en texto") si
no lo está — correcto para ambos clientes sin necesitar texto
condicional por cliente en el `SYSTEM_PROMPT` mismo (el toolset ya se
filtra por cliente en `agent_loop.py`, la instrucción solo necesita no
contradecir esa realidad).

**Verificado real, de punta a punta**: mismo pedido exacto que antes
generaba solo texto ("creá una página web simple para una barbería con
un título y un botón de reservar cita") contra el proceso real —
ahora la PRIMERA respuesta llama `propose_project_files` directamente,
sin ofrecer alternativas manuales. 1 test nuevo
(`test_context_service.py`) confirma que la instrucción de VS Code
menciona la herramienta por nombre.

## Multi-archivo (HTML+CSS+JS): seguía fallando a veces incluso con el fix del prompt (2026-07-14)

El usuario reportó "sigue igual" pegando un log real con
`tool_use_failed` — reveló un problema DISTINTO del anterior: el
modelo a veces SÍ intentaba llamar a `propose_project_files`, pero el
log solo decía "se usa la respuesta en texto plano" sin mostrar QUÉ
había intentado llamar — indiagnosticable a ciegas. Primer fix:
`openai_compatible_client.py` ahora loguea el `failed_generation` real
(truncado) en el warning.

Reproduciendo en vivo con la MISMA frase ("crea el código para una
página web para una barbería", pedido de 3 archivos: HTML+CSS+JS): el
PRIMER intento no llamó a la herramienta en absoluto — escribió los
tres archivos como bloques de código en la respuesta y, al final,
literalmente describió en texto cómo se vería la llamada a la
herramienta ("Para crear estos archivos... te sugiero: \`\`\`json
[{"path": "index.html", ...}]\`\`\`") sin ejecutarla de verdad. Los
siguientes 5 intentos con la misma frase SÍ llamaron a la herramienta
correctamente con los 3 archivos — confirmando que es variabilidad de
muestreo del modelo (Groq/llama-4-scout, cuya confiabilidad de
tool-calling ya se documentó como más débil que Ollama en
[[technical_openai_strict_tool_calling_format]]), no un bug
determinístico reproducible siempre.

**Fix (mitiga, no puede garantizar 100%)**: reforzada
`_VSCODE_CLIENT_INSTRUCTION` — instrucción explícita de llamar a la
herramienta UNA sola vez con TODOS los archivos juntos cuando el
proyecto tiene varios, y de nunca "describir en texto cómo se vería la
llamada" en vez de hacerla de verdad (el caso real observado).
Verificado con 9 pedidos reales seguidos de la misma frase: 8/9
llamaron a la herramienta correctamente (vs. la falla real reportada
por el usuario antes del refuerzo). El 9no dio `llm_error` — pero por
una causa totalmente distinta y esperable: rate limit real de Groq
(429, "tokens per minute" agotado) causado por las pruebas repetidas
en poco tiempo contra la cuenta gratuita — la herramienta SÍ se había
llamado bien en ese intento, el error fue en el turno de seguimiento.

**Límite honesto, no resuelto ni resoluble solo con prompt**: con un
modelo de tool-calling menos confiable (Groq) bajo carga (varios
archivos grandes en un mismo argumento), una falla ocasional sigue
siendo posible — el `tool_use_failed` fallback ya evita perder la
respuesta por completo, y reintentar el mismo pedido normalmente
funciona (confirmado empíricamente). Ollama local no tiene este
problema de confiabilidad de tool-calling (documentado desde antes),
así que es la alternativa más robusta si esto se vuelve frecuente en
el uso real.

## Proyectos distintos en la misma conversación mezclaban sus archivos (2026-07-14)

El usuario reportó que ahora sí funcionaba, pero "mezcla en el árbol
de archivos todos los archivos de los proyectos que se van creando" —
causa real: `propose_project_files` nunca tuvo instrucción sobre
organización de carpetas, así que dos pedidos distintos en la misma
conversación (p.ej. una página para una barbería y después otra para
una panadería) proponían archivos SUELTOS en la raíz del proyecto
(`index.html`, `estilos.css`, `script.js` para ambos) — el segundo
pedido pisaba/mezclaba con el primero, sin ninguna separación.

**Fix**: reforzada `_VSCODE_CLIENT_INSTRUCTION` — si el pedido es un
proyecto NUEVO y distinto de lo que se venía haciendo en la
conversación, todos sus archivos van dentro de una subcarpeta con
nombre corto y descriptivo derivado del pedido (p.ej.
`barberia-web/index.html`, nunca suelto en la raíz); si en cambio es
agregar/modificar el MISMO proyecto ya en curso, o el usuario pide una
ruta explícita, se respeta esa instrucción en lugar de crear una
subcarpeta nueva.

**Verificado real, de punta a punta**: dos pedidos distintos en la
MISMA sesión ("página para una barbería" seguido de "página para una
panadería") — el primero propuso `barberia-web/index.html` +
`barberia-web/estilos.css` + `barberia-web/script.js`, el segundo
`panaderia-web/index.html` + `panaderia-web/estilos.css` +
`panaderia-web/script.js` — cada proyecto en su propia subcarpeta, sin
mezclarse.

## "Fallo al crear un proyecto Android" + "todo el HTML en una línea": el mismo patrón de fondo, dos causas distintas (2026-07-15)

El usuario reportó ambos síntomas juntos. Investigando `logs/agent.log`
en detalle encontré que las DOS fallas eran manifestaciones del mismo
patrón ya conocido (el modelo "imita" la llamada a
`propose_project_files` como texto en vez de ejecutarla de verdad) —
pero con una causa técnica distinta en cada caso, ninguna cubierta por
el fallback existente (`_extract_fallback_tool_call`).

**Causa 1 — forma no reconocida**: `_extract_fallback_tool_call` (el
mecanismo que ya existía para detectar un tool call imitado como texto
plano) solo reconocía la forma `{"name": ..., "arguments": ...}` — pero
el modelo, para `propose_project_files` específicamente, a veces
imitaba un ARRAY crudo de archivos (`[{"path":..., "content":...}]`),
sin ese envoltorio. `extract_json_object()` (que `_extract_fallback_tool_call`
usa) ni siquiera intenta reconocer un array — devolvía `None` de
entrada, dejando el texto crudo (con los saltos de línea escapados
como `\n` literal) como respuesta final. Esto es lo que el usuario veía
como "todo el código en una línea": no estaba minificado, era el JSON
con sus escapes de texto sin interpretar, mostrado tal cual.

Fix: `agent_core/llm/json_extraction.py::extract_json_array()` (nueva,
misma lógica que `extract_json_object()` pero para arrays) +
`_extract_fallback_tool_call()` ahora también intenta esta forma,
armando un `ToolCall(name="propose_project_files", arguments={"files": ...})`
si el array tiene la forma esperada (`path`/`content` en cada
elemento) Y la herramienta está disponible (nunca para el cliente web).

**Causa 2 — JSON técnicamente inválido**: reproduciendo el pedido real
de un proyecto Android ("agenda personal"), con la causa 1 ya
arreglada el intento SEGUÍA sin detectarse — el modelo escribía código
Java/XML multilínea con saltos de línea LITERALES dentro del valor de
`"content"` en vez de escaparlos como `\n` (un error real y común al
armar JSON "a mano" en vez de generarlo con una librería) — técnicamente
inválido, `json.loads()` en modo estricto lo rechaza entero
(`JSONDecodeError: Invalid control character`) por un solo carácter
mal escapado, perdiendo la propuesta completa.

Fix: `json.loads(candidate, strict=False)` en ambos extractores —
`strict=False` permite caracteres de control (incluido un salto de
línea literal) dentro de un string JSON, exactamente el caso real. Sin
reimplementar un parser tolerante propio: es una opción ya integrada
de la librería estándar para exactamente este problema.

**Además**: reforzada `_VSCODE_CLIENT_INSTRUCTION` para proyectos
grandes (Android, con manifest/gradle/actividades/layouts en varias
carpetas) — proponer primero solo los archivos ESENCIALES para que el
proyecto funcione de forma mínima, en vez de intentar todo de una vez
y arriesgarse a que la respuesta se corte a la mitad; el resto se pide
en un pedido siguiente.

**Verificado real, de punta a punta**: el pedido EXACTO que antes
fallaba ("creá un proyecto Android para una agenda personal") ahora
responde `status: "success"` con `propose_project_files` llamada de
verdad (3 archivos: `MainActivity.java`, `activity_main.xml`,
`AndroidManifest.xml`, todos dentro de `agenda-personal/`). 5 tests
nuevos: 2 en `test_json_extraction.py` (`extract_json_array` +
tolerancia a salto de línea literal en ambos extractores), 3 en
`test_agent_loop.py` (array crudo detectado / ignorado sin la
herramienta ofrecida / salto de línea literal tolerado). Suite
relacionada completa, 0 regresiones.

## Dominios de assets habilitados + Playwright sync API rompía dentro del threadpool de FastAPI (2026-07-15)

El usuario pidió dominios seguros para descargar imágenes/sonidos/
plantillas web. Agregados a `config.yaml: browser.allowed_domains`
(vacío por defecto, deny-by-default): `unsplash.com`, `pexels.com`,
`pixabay.com` (imágenes), `freesound.org` (sonidos), `html5up.net` y
`startbootstrap.com` (plantillas) — todas licencias permisivas
(CC0/MIT/CC BY), sin necesitar login.

Probando en vivo (con el binario de Chromium de Playwright recién
instalado — no estaba antes, `playwright install chromium`, ~290MB),
apareció un bug real y distinto:
`BrowserTool` fallaba con "It looks like you are using Playwright Sync
API inside the asyncio loop. Please use the Async API instead." — un
error que **solo podía aparecer una vez que Chromium estuviera
instalado de verdad** (antes fallaba antes, con "executable doesn't
exist", escondiendo este problema).

Causa real: `PlaywrightBrowserDriver` (`tool_integration/adapters/browser.py`)
usa la API SYNC de Playwright, que no puede correr en un hilo con un
event loop de asyncio asociado — y el pool de threads que FastAPI/
Starlette usa para despachar `/chat` (`run_in_threadpool` vía anyio)
SÍ lo tiene, aunque el endpoint esté definido como `def` normal, no
`async def`.

Fix: todas las llamadas reales a Playwright (`_ensure_browser`,
`extract_text`, `extract_links`, `screenshot`, `close`) ahora corren
en un `ThreadPoolExecutor` propio de UN solo worker — un hilo crudo
del sistema operativo, nunca tocado por anyio, donde Playwright nunca
detecta un event loop. `max_workers=1` no es solo por simplicidad: los
objetos de Playwright (browser/page) quedan atados al hilo que los
creó, así que todas las llamadas de una misma instancia tienen que
caer siempre en el mismo hilo. Ningún otro archivo del pipeline de
herramientas (`Tool.execute()`, `agent_loop.py`, `orchestrator.py`)
cambió — sigue siendo síncrono de punta a punta, el aislamiento queda
contenido dentro del driver.

**Verificado real, de punta a punta**: navegar a `https://unsplash.com`
ahora devuelve texto real de la página (el banner de cookies) en vez
de fallar — confirmado tanto el permiso de dominio como el fix de
threading juntos. `tests/test_browser_tool.py` (usa un driver falso
inyectado, nunca ejercita `PlaywrightBrowserDriver` directamente) sigue
pasando sin cambios — 0 regresiones.

## VS Code: diálogos de vista previa de archivos se encolaban, mostrando siempre el más viejo (2026-07-15)

El usuario pegó una captura real: después de pedir un menú con fotos
(3 archivos) y luego, en un pedido SEPARADO, corregir la indentación
de `index.html` (1 archivo — la respuesta de texto en el chat lo
confirmaba correctamente: "Se prepararon 1 archivo(s)..."), el diálogo
de VS Code que aparecía en pantalla seguía mostrando los 3 archivos
del pedido ANTERIOR — desincronizado con lo que el chat ya mostraba.

Causa real: `media/chat.js::send()` nunca deshabilitaba el
input/botón de enviar — el usuario podía mandar un pedido nuevo
mientras la vista previa de archivos (`showInformationMessage`
modal) de un pedido ANTERIOR todavía esperaba una decisión. VS Code
encola varios diálogos nativos abiertos a la vez y los muestra de a
uno, EN ORDEN — así que el usuario seguía viendo el más viejo sin
resolver, sin importar cuántos pedidos nuevos hiciera después. De
paso, `handleAsk()` en `chatPanel.ts`/`chatViewProvider.ts` mandaba el
mensaje `"answer"` (que en el webview no deshabilitaba nada, pero de
todos modos) ANTES de esperar `maybeHandleProjectFiles()` — ningún
lado del sistema sabía que había que esperar a que la vista previa
se resolviera antes de aceptar un pedido nuevo.

**Fix**: `chat.js::send()` deshabilita `input`/`send` al mandar un
pedido; un mensaje nuevo `"ready"` los vuelve a habilitar — pero
`chatPanel.ts`/`chatViewProvider.ts::handleAsk()` solo lo mandan en un
`finally` que envuelve TODO el flujo, incluida
`await maybeHandleProjectFiles(...)` — así el usuario físicamente no
puede mandar un pedido nuevo hasta resolver (Aplicar/Descartar/Ver
detalle) la vista previa del actual, eliminando la posibilidad de que
se encolen diálogos desincronizados.

Extensión reempaquetada e instalada de nuevo (lección ya conocida:
un cambio en `vscode-extension/` no alcanza sin
`POST /integrations/vscode/install`). Sin test de UI para esto (la
lógica de deshabilitar/habilitar vive en `chat.js`, que corre dentro
de un webview real — fuera del alcance de `node --test`, mismo límite
que el resto de `media/`); `tsc` + los 29 tests existentes de la
extensión (lógica pura, sin `vscode`) siguen pasando sin cambios.

## Artifact Service (Fase 1): descarga real de imágenes desde sitios permitidos (2026-07-15)

El usuario preguntó cómo pedirle a kal que agregue fotos "descargadas"
a una página web. Investigando: no era posible — `BrowserTool` solo
extraía texto/enlaces/captura completa (nunca `<img src>` ni el
binario de una imagen), y `propose_project_files` solo maneja texto.
Lo único que funcionaba era referenciar la imagen por URL directa
(hotlink), sin copia local real.

En la discusión, el usuario propuso un "Artifact Service" del Kernel
completo (Import/Export/Download Manager, Registry de metadatos,
múltiples orígenes: URL/GitHub/Drive/Dropbox/clipboard, cualquier tipo
de binario). Confirmado explícitamente (`AskUserQuestion`, sobre mi
propuesta de escopar solo imágenes): diseñar el mecanismo genérico
completo AHORA — mismo criterio ya aplicado al Permission Manager de
filesystem (kal se distribuye al público, no espera demanda validada
para infraestructura de seguridad). Alcance acordado: el mecanismo es
genérico (`type` extensible), pero el ÚNICO tipo real implementado y
validado es `"image"` — otros orígenes/tipos quedan documentados como
extensión futura, sin construir (sin consumidor real todavía).

**Reuso real, no reinventado**: `tool_integration/malware_scan.py::scan_bytes()`
(ClamAV, fail-closed, ya construido para artefactos de skills) —
reusado tal cual para los bytes descargados. `filesystem_access_manager.evaluate()`
— misma decisión de política y auditoría que ya usa
`propose_project_files`. El mismo `Artifact(modality="project_files")`
— se extiende con un campo `encoding` (`"utf-8"`/`"base64"`) en vez de
un flujo de UI paralelo. El log de auditoría ya hash-encadenado sirve
como "Metadata Index" (nuevo `EventType`: `artifact_imported`, con
url/sha256/mime/tamaño) — no hace falta una base de datos nueva. La
protección contra DNS rebinding y el allowlist de dominios (ya
construidos en `browser.py`) se EXTRAEN a
`tool_integration/network_safety.py` — el download manager los
necesita igual, sin duplicar la lógica.

**Implementado**:
- `tool_integration/network_safety.py` (nuevo): `is_unsafe_ip()`/
  `is_domain_allowed()`, extraídas de `browser.py` (que ahora importa
  de acá en vez de tener su propia copia).
- `tool_integration/download_manager.py` (nuevo): `DownloadManager.download_and_validate(url, expected_type)`
  — fail-closed en cada paso: esquema (https siempre, http solo si
  `downloads.allow_http`), dominio (`downloads.allowed_domains`,
  deny-by-default), IP insegura (resuelve el host, rechaza
  privada/reservada — mismo límite conocido que `browser.py`: ventana
  de carrera entre resolución y conexión, aceptado, documentado),
  streaming con tope real de tamaño (`downloads.max_size_mb`, nunca
  descarga todo primero para recién ahí medir), escaneo ClamAV,
  validación real de imagen (Pillow `Image.verify()` — rechaza bytes
  basura con extensión de imagen), hash SHA-256.
- `config/config.yaml: downloads:` — nueva sección, deliberadamente
  SEPARADA de `browser:` (semántica distinta: sin JS/cookies, con tope
  de tamaño) aunque con los mismos dominios ya confiados
  (unsplash/pexels/pixabay/freesound/html5up/startbootstrap).
- `tool_integration/adapters/browser.py`: acción nueva `"images"`
  (`img[src]`, mismo patrón que `"links"` con `a[href]`) — para que el
  modelo consiga una URL de imagen REAL antes de importarla, en vez de
  inventar una a ciegas.
- `tool_integration/adapters/vscode_files.py::ImportResourceTool`
  (`import_resource`, nueva): descarga+valida, llama al Permission
  Manager (mismo `evaluate()` que `propose_project_files`), audita
  `artifact_imported`, y devuelve el archivo como
  `project_files`/`encoding: "base64"` — el mismo flujo de vista previa
  y Aplicar/Descartar ya construido, sin UI paralela.
- `vscode-extension/src/kalClient.ts`/`projectFiles.ts`: soporte de
  `encoding: "base64"` al escribir (`Buffer.from(content, "base64")`)
  y un placeholder (`[archivo binario, ~N KB]`) en "Ver detalle" en vez
  de volcar el blob base64 crudo.
- `agent_core/context_service.py::_VSCODE_CLIENT_INSTRUCTION`: nueva
  instrucción — navegar con `browser action='images'` primero para
  conseguir una URL real, y LLAMAR `import_resource` de verdad
  (reforzado tras un hallazgo real: la primera versión de la
  instrucción hizo que el modelo navegara bien pero después pusiera la
  URL encontrada directo en un `<img src="...">` del HTML — un hotlink,
  no una descarga real, exactamente lo que el pedido quería evitar).

**Verificado real, de punta a punta, contra el proceso vivo**: pedido
real ("agregá una foto real de comida descargada a la página web del
restaurante") — el modelo navegó con `browser action='images'`,
consiguió URLs reales de Unsplash, y llamó `import_resource` de
verdad. `logs/audit.log` muestra `artifact_imported` con la URL real,
`sha256`, `mime: "image/jpeg"`, y `size_bytes: 1974639` — una imagen
JPEG real de ~2MB, descargada, escaneada con ClamAV real (confirmado
instalado), validada como imagen real con Pillow, y hasheada. 29 tests
nuevos: 7 en `test_network_safety.py`, 10 en `test_download_manager.py`
(incluido un test con ClamAV real sin mockear, mismo criterio que
`test_malware_scan.py`), 7 en `test_import_resource_tool.py`, 2 en
`test_browser_tool.py` (acción `images`), 2 en `test_agent_loop.py`
(exclusión de `import_resource` para el cliente web), 1 en
`test_context_service.py` (instrucción de navegar antes de importar).
Suite completa sin regresiones.

**Fuera de alcance de esta fase, documentado explícitamente**: otros
orígenes de importación (GitHub, Google Drive, Dropbox, clipboard,
archivo local) y otros tipos de recurso (PDF, video, SVG, ZIP, modelos
3D) — el mecanismo (`type`/`url`/validación/auditoría) queda listo
para agregar cualquiera de estos, pero ninguno tiene un consumidor
real hoy; `type` rechaza cualquier valor sin validador implementado,
nunca acepta un binario sin poder confirmar de verdad qué es. Tampoco
hay un "Artifact Registry" como estructura de datos propia y
consultable (el log de auditoría cumple ese rol por ahora) ni un
Export Manager (sin pedido real de "exportar" nada todavía).

## Análisis de imágenes con modelo de visión — y una regresión real de Ollama descubierta probando en vivo (2026-07-19)

El usuario descargó `llama3.2-vision:latest` localmente y pidió poder
subir una imagen para que kal la analice/describa. La interfaz web ya
tenía subida de imágenes propias (botón 📎, `POST /uploads`), pero solo
para herramientas de EDICIÓN
(`tool_integration/adapters/image_editing.py`) — ningún componente
llamaba nunca a un modelo de visión: `OllamaClient.chat()` no soportaba
el campo `images` de la API de Ollama.

**Implementado, mismo patrón que `SpeechToTextTool`** (una herramienta
que devuelve texto, no un artefacto nuevo):
- `agent_core/llm/ollama_client.py::OllamaClient.chat()`: parámetro
  nuevo `images: list[str] | None` (base64), se adjunta al ÚLTIMO
  mensaje sin mutar la lista del llamador — formato real de `/api/chat`
  de Ollama para modelos de visión. Default `None`, cero cambio para
  los 3 call sites existentes.
- `utils/config.py`/`config/config.yaml`: `multimodal.vision` nuevo
  (`backend`, `model`, y un `base_url` PROPIO).
- `tool_integration/adapters/image_analysis.py::ImageAnalysisTool`
  (`analyze_image`, nueva): `image_path` + `question` → lee el
  archivo, base64, llama al modelo de visión, devuelve
  `Artifact(modality="text", metadata={"answer": ...})`. Fail-closed:
  archivo inexistente o error del proveedor nunca crashea. Registrada
  en `tool_integration/registry.py`, disponible para ambos clientes
  (sin restricción, a diferencia de `propose_project_files`/
  `import_resource`).

**Bug real encontrado probando en vivo (el primero, antes de tocar el
modelo)**: `OllamaClient()` sin argumentos toma `settings.llm.base_url`
por defecto — pero ese campo ahora apunta a Groq (perfil de nube activo
en esta sesión, ver "default_model quedaba pegado a Ollama..." arriba).
La primera corrida del smoke test le pegó a
`https://api.groq.com/openai/v1/api/chat` (404) en vez de al Ollama
local. Corregido con un `base_url` PROPIO en `VisionConfig`
(`http://localhost:11434`, fijo) — la capacidad de visión, como
`image_gen`/`audio_gen`/`speech_to_text`, tiene que hablar siempre con
su modelo local, sin importar qué proveedor use el "cerebro" del agente
para decidir qué herramienta llamar.

**Segundo bug real, mucho más serio — no era de este código**: con el
`base_url` ya corregido, la llamada seguía fallando: `500 Internal
Server Error: llama-server process has terminated ... unknown model
architecture: 'mllama'`. Confirmado con `ollama run llama3.2-vision`
directo desde la CLI (sin pasar por kal): falla igual. Investigado
(GitHub `ollama/ollama#16547`): Ollama ≥0.30.0 migró a un motor
`llama.cpp` unificado que NUNCA soportó de forma nativa la arquitectura
`mllama` de Llama 3.2 Vision — el soporte anterior era un parche
privado de Ollama, no upstream, y se perdió al migrar de motor. Sin
arreglo ni ETA de ningún lado (ni Ollama ni llama.cpp) al momento de
escribir esto. La versión instalada en esta máquina (0.31.1) está
afectada.

**Solución real**: en vez de esperar el fix de Ollama, se bajó
`llava:13b` (arquitectura CLIP, sí soportada de forma nativa) como
modelo de visión por defecto — decisión del usuario entre 3
alternativas presentadas (llava:13b/minicpm-v/moondream). Cero cambio
de código necesario: `multimodal.vision.model` ya era configurable.
Verificado real, de punta a punta: una imagen de prueba (círculo azul +
rectángulo amarillo generada con Pillow) → `analyze_image` real →
`llava:13b` real vía Ollama real → descripción correcta de forma y
colores. `llama3.2-vision:latest` queda descargado en la máquina pero
inutilizable hasta que Ollama o llama.cpp resuelvan la regresión —
documentado en el comentario de `VisionConfig.model`, no escondido.

4 tests nuevos en `test_ollama_client.py` (adjunta `images` al último
mensaje sin mutar la lista original, no agrega la clave si no se pasa),
5 en `test_image_analysis_tool.py` (archivo inexistente, éxito con
cliente falso, error del proveedor, manifest, `base_url` propio vs.
`llm.base_url`). Suite completa sin regresiones.

## Tercer bug real, mucho más grave: el fix de Groq para `arguments` rompía CUALQUIER conversación de más de un paso contra Ollama nativo (2026-07-19)

Al probar el feature de arriba en vivo (usuario cambió el modelo del
selector "Modelo" del chat), apareció un error nuevo y aparentemente
sin relación: `Ollama devolvió un error HTTP: 400 Client Error: Bad
Request` — hasta con un simple "hola" (que dispara `audio_generation`
como comportamiento default de la interfaz web) volvía a fallar en el
turno SIGUIENTE al de la llamada a la herramienta. Investigado en
vivo, con el body real de la respuesta de Ollama capturado (envolviendo
`OllamaClient._post` con un wrapper de depuración, ya que
`OllamaError` solo guarda `str(exc)`, sin el cuerpo): `{"error":"Value
looks like object, but can't find closing '}' symbol"}`.

Aislado con variantes mínimas contra el Ollama real de esta máquina:
la causa NO era el `content` (que en el camino de fallback trae texto
crudo con forma de JSON) sino `tool_calls[].function.arguments` — Ollama
nativo (`/api/chat`) exige que sea el OBJETO ya parseado, nunca un
string con JSON adentro. Ese string es exactamente lo que
`agent_core/llm/agent_loop.py` empezó a mandar SIEMPRE
(`json.dumps(tc.arguments)`) tras el fix de interoperabilidad con Groq
del 2026-07-14 (ver "Groq rompía cualquier tarea de más de un paso" más
arriba) — ese fix estaba documentado como algo que "Ollama tolera", pero
en la práctica Ollama no tolera el string, rechaza con 400 la plantilla
de su motor de chat al intentar renderizarlo. Como el `provider` activo
en esta sesión venía siendo `openai_compatible` (Groq) hasta hace poco,
esta regresión llevaba días sin manifestarse — recién se hizo visible
al volver a `provider: ollama` como parte de las pruebas de hoy.

**Corregido en la capa correcta**: `agent_loop.py` ahora arma
`tool_calls[].function.arguments` en formato CANÓNICO (el dict ya
parseado, sin `json.dumps`) — el núcleo del loop no debe conocer el
wire format de un proveedor concreto (mismo principio que ya documenta
`agent_core/llm/provider.py`). La necesidad real de un string
(Groq/OpenAI-strict) se resolvió DENTRO de
`OpenAICompatibleClient.chat()`
(`_with_stringified_tool_call_arguments()`, nueva): serializa
`arguments` a JSON string en el payload saliente, sin mutar la lista
`messages` del llamador (mismo criterio que `OllamaClient.chat()` con
`images`, ver más arriba). `OllamaClient` no necesitó ningún cambio —
ya reenviaba `messages` tal cual.

Además, un bug aparte encontrado en el camino (arreglado hoy mismo,
independiente): el modelo elegido en el selector "Modelo" de la web
(`llava:13b`, un modelo de VISIÓN sin soporte de tool-calling) había
quedado como `llm.default_model` — Ollama rechaza con 400
("does not support tools") CUALQUIER request con `tools` contra ese
modelo, rompiendo el chat de punta a punta con solo escribir "hola".
Restaurado a `qwen2.5-coder:14b` (con capacidad `tools` confirmada vía
`/api/show`) usando el propio endpoint `POST /settings/llm` del
servidor en vivo. El selector de modelo hoy no distingue entre modelos
con y sin soporte de herramientas — queda como deuda conocida, no
corregida en esta sesión (fuera del alcance del pedido original).

Verificado real, de punta a punta, contra el servidor vivo:
`ejecutá este código: print(sum(range(1,11)))` → llamó `run_code`,
ejecutó de verdad, devolvió "55", respuesta final correcta — el mismo
flujo de dos turnos que antes rompía con 400 en cuanto había una
herramienta de por medio. 1 test de `test_agent_loop.py` reescrito
(`test_reconstructed_tool_call_arguments_stay_as_a_dict_ollama_native_format`,
antes asumía el comportamiento viejo) + 1 test nuevo en
`test_openai_compatible_client.py`
(`test_chat_stringifies_outgoing_tool_call_arguments_before_sending`).
Suite completa sin regresiones.

## Dos bugs reales más probando analyze_image en vivo: el modelo no conectaba la herramienta, y su respuesta se perdía en el camino (2026-07-19)

Con los bugs de arriba corregidos, el usuario probó el flujo real:
generó una imagen ("generame una imagen de un león") y después pidió
"describe esta imagen". Primera vuelta: kal respondió "Lo siento, pero
no puedo ver o analizar imágenes en este entorno" — ni siquiera
INTENTÓ llamar a `analyze_image`, pese a tenerla disponible y pese a
que el artefacto activo (con su path real) ya se anunciaba en el
contexto. Mismo patrón que ya documentó
[[technical_vscode_client_tool_restriction]] y otros hallazgos de esta
sesión: tener la herramienta disponible, y hasta mencionar el path del
artefacto activo, no alcanza para que el modelo conecte un pedido
conversacional ("describe esta imagen") con la llamada real — sin una
instrucción explícita, cae en su respuesta genérica de "no tengo
visión".

**Corregido**: `agent_core/context_service.py::_build_session_context()`
ahora agrega, específicamente cuando el artefacto activo es
`modality="image"`, una instrucción explícita: si piden describir/
analizar/identificar contenido de la imagen, llamar a `analyze_image`
con `image_path` igual al artefacto activo — nunca responder que no
se pueden ver imágenes.

Con eso corregido, apareció un SEGUNDO bug real en la misma prueba: el
modelo SÍ llamó a `analyze_image` con el path correcto, pero la
`observation` que le llegó de vuelta fue literalmente `"(sin salida)"`
— la respuesta real de `llava:13b` se perdía por completo.
Investigado: `agent_core/llm/agent_loop.py::_artifact_to_observation()`
tiene una convención de dos ramas para `modality="text"`: si
`"status"` está en `metadata`, asume la forma de `run_code` (espera
`"stdout"`); si no, y hay `"summary"`, lo muestra tal cual (la
convención que ya usa `speech_to_text.py`). `ImageAnalysisTool` había
usado `{"status": "success", "answer": ...}` — cayó en la rama
equivocada, buscando una clave `"stdout"` que nunca existía. Corregido
adoptando la convención de `"summary"` (sin `"status"` en el caso de
éxito; el caso de error sigue usando `"status": "error"` +
`"stderr"`, que sí toma la rama correcta).

Verificado real, de punta a punta, en una sola sesión sin reinicios de
por medio: "generame una imagen de un gato" → "describe esta imagen"
→ `analyze_image` real, con el path correcto, devolvió una
descripción real y detallada (correctamente notó que era una foto
díptico de un gato, con detalles de la postura y el entorno) — ni
placeholder ni "no puedo ver imágenes". 4 tests nuevos
(`test_context_service.py`: 2 sobre la instrucción nueva;
`test_agent_loop.py`: 1 sobre la convención `"summary"` de
`_artifact_to_observation`; `test_image_analysis_tool.py`: actualizado
a la nueva convención). Suite completa (742 tests) sin regresiones.

## El selector de modelo dejaba elegir un modelo sin tool-calling y rompía TODO el chat — corregido de raíz (2026-07-19)

El usuario volvió a cambiar el modelo del selector web a `llava:13b`
(esta vez ya con el flujo generar+describir imagen funcionando bien
antes del cambio) y el chat "dejó de responder". Mismo error de fondo
que ya se había visto y "resuelto a mano" horas antes (restaurando
`default_model` vía `POST /settings/llm`): Ollama rechaza con 400
(`"llava:13b does not support tools"`) CUALQUIER mensaje con `tools`
en el payload — y kal SIEMPRE manda `tools`, así que cualquier modelo
sin esa capacidad como `default_model` rompe el chat entero, hasta un
simple "hola". Esta vez, en vez de dejarlo como "deuda conocida" (como
se documentó horas antes), se corrigió de raíz: nada impedía
elegirlo, ni en el selector ni en el backend.

**Corregido en dos capas**:
1. `agent_core/llm_settings.py::_ollama_model_supports_tools()`
   (nueva): consulta `POST /api/show` de Ollama (la MISMA fuente de
   verdad ya usada para diagnosticar este bug, `capabilities` incluye
   `"tools"` o no) — a diferencia de `_is_chat_capable_model_name()`
   (heurística por palabras clave, la única opción para proveedores en
   la nube sin API de capacidades), acá SÍ hay una respuesta real y
   confiable. Fail-closed: si Ollama no responde, el modelo no aparece
   (mismo criterio que un perfil de nube roto).
2. `list_model_sources()` ahora filtra los modelos Ollama locales por
   esta capacidad — `llava:13b` (y cualquier otro modelo de solo
   visión) ya NO aparece en el selector del chat.
3. `update_llm_settings()` valida lo mismo ANTES de escribir nada (ya
   prometía esto en su docstring) — defensa en profundidad por si se
   pide un modelo sin soporte de tools por fuera del selector (llamada
   directa al endpoint): rechaza con un `LLMSettingsError` claro en vez
   de aceptar un estado roto.

Nota real encontrada de paso: `llama3.2-vision:latest` SÍ reporta
`"tools"` en sus capabilities (arquitectónicamente cierto), pese a
estar roto por la regresión de `mllama` documentada más arriba — ese
es un fallo de CARGA del modelo (500, recién al intentar usarlo),  no
de capacidad declarada, así que este filtro no lo detecta; ya estaba
documentado como inutilizable en el comentario de `VisionConfig.model`
y no se resuelve acá.

Verificado en vivo contra el servidor real: `POST /settings/llm` con
`default_model: "llava:13b"` ahora devuelve 400 con el mensaje claro,
sin tocar la config; `GET /settings/llm/sources` ya no incluye
`llava:13b` en la lista de modelos locales. 6 tests nuevos
(`test_llm_settings.py`): 3 sobre `_ollama_model_supports_tools()`
(lee capabilities, true/false, fail-closed), 1 sobre el filtro en
`list_model_sources()`, 2 sobre la validación en
`update_llm_settings()` (rechaza/acepta). Suite completa sin
regresiones.

## Explicar, no solo bloquear: capacidades visibles + ventana con motivo real (2026-07-19)

El usuario probó de nuevo el mismo cambio de modelo problemático
("¿tendré problemas si necesito un modelo en la nube?" — no, el filtro
es específico de `provider: "ollama"`) y después pidió, para el caso de
elegir un modelo de visión como cerebro: "que salte una ventana con una
explicación". El filtro de la sección anterior ya lo IMPIDE (llava:13b
ni aparece en el selector), pero eso deja dos huecos reales: (1) el
usuario no entiende POR QUÉ un modelo que sí ve en "modelos locales
descargados" no aparece arriba en el selector del chat, y (2) el
listener de "change" del selector no tenía ningún `try/catch` — si el
backend llegara a rechazar el cambio por cualquier motivo (este u
otro), la falla quedaba silenciosa (promesa sin manejar), sin ningún
aviso visible.

**Corregido**:
- `agent_core/llm_settings.py::get_ollama_model_capabilities()`
  (nueva, extraída de `_ollama_model_supports_tools()` sin duplicar la
  llamada a `/api/show`): devuelve la lista real de capacidades de un
  modelo (`["completion", "tools"]`, `["completion", "vision"]`, etc.),
  no solo un booleano.
- `GET /settings/llm/ollama/models` ahora incluye
  `capabilities: {modelo: [...]}` junto a la lista de modelos.
- `frontend/app.js::refreshModelSettings()`: cada modelo en la lista
  de "modelos locales" de la pestaña Modelo ahora se anota con lo que
  puede hacer ("puede ser el cerebro del chat" / "solo visión, no
  soporta herramientas") — así el usuario entiende por qué falta del
  selector de arriba SIN necesitar que nada falle primero.
- `model-select` (listener de "change"): ahora envuelto en
  `try/catch` — cualquier rechazo del backend (mismo mensaje claro que
  ya arma `update_llm_settings()`) dispara una ventana (`alert()`) con
  la explicación real, y restaura el selector al modelo que sigue
  activo de verdad (mismo patrón que ya existía para el caso
  `:cloud`, ahora generalizado a cualquier error).

Verificado en vivo: `GET /settings/llm/ollama/models` devuelve
`capabilities` reales para los 5 modelos locales de esta máquina
(`llava:13b` → `["completion", "vision"]`, `qwen2.5-coder:14b` →
`["completion", "tools", "insert"]`, etc.); `node --check` sobre
`app.js` sin errores de sintaxis. 2 tests nuevos
(`get_ollama_model_capabilities`: devuelve la lista real / vacía si
Ollama no responde) + 1 test de endpoint actualizado a la nueva forma
de la respuesta. Suite completa sin regresiones.

## Access Manager genérico: Permission Manager unificado, Fase 1 (Filesystem + Network) (2026-07-19)

El usuario propuso una evolución grande de arquitectura (kernel/ como
módulo independiente, SDK oficial, Permission Manager unificado,
Knowledge Service evolucionado, Integration Manager). Relevamiento
completo del código real antes de diseñar: hoy NO hay un sistema de
permisos disperso, hay TRES mecanismos ORTOGONALES —
`PermissionCascade` (¿puede esta herramienta pedir esta CAPACIDAD en
absoluto?, por nivel de confianza), `FilesystemAccessManager` (el más
maduro: política + escalamiento humano + 4 escalas de concesión
persistentes + auditoría) y Red (`network_safety.py`/`download_manager.py`
— hoy solo una allowlist ESTÁTICA, sin ningún camino de escalar a un
humano). Acordado con el usuario: Knowledge Service e Integration
Manager siguen pospuestos (sin nueva evidencia); de los tres restantes
(kernel/, SDK, Permission Manager), arrancar por Permission Manager —
menor riesgo, mayor valor inmediato.

**Decisión de diseño explícita del usuario** (la más importante de
esta fase): NO extraer/generalizar `FilesystemAccessManager` tratando
a Network como un caso derivado. En cambio, construir un motor
`AccessManager` GENÉRICO e independiente de recurso, del que Filesystem
y Network sean los dos primeros ADAPTADORES — para que un futuro
adaptador de Terminal o Modelos se sienta como reusar el componente
que siempre fue para arbitrar acceso a cualquier recurso, no como
"adaptar un gestor de archivos".

**Implementado**:
- `tool_integration/access_manager.py` (nuevo): motor genérico —
  `scope`/`action` como `str` libres (no un enum específico), política
  inyectada vía callback `is_auto_allowed(scope, action, resource_key)`
  (a diferencia del `_is_policy_auto_allowed(scope, action)` viejo de
  filesystem, que ignoraba `resource_key` — Network SÍ necesita mirar
  el dominio concreto), 4 escalas de concesión (once/session/project/skill),
  auditoría con `event_type_prefix` parametrizado. Sin ningún `import`
  de utils.config — el core no sabe qué consumidor lo usa.
- `tool_integration/filesystem_access_manager.py` reescrito como
  ADAPTADOR delgado sobre el motor — API pública IDÉNTICA
  (`evaluate()`, `create_pending_request()`, `list_pending()`,
  `approve()`, `deny()`, `PendingFilesystemAccess`,
  `FilesystemAccessError`), cero cambios para sus consumidores
  actuales (`vscode_files.py`, endpoints `/filesystem-access/*`, la
  extensión de VS Code). Los 22 tests existentes pasan SIN
  modificación — prueba de que el refactor no cambió comportamiento
  observable.
- `tool_integration/network_permissions.py` +
  `tool_integration/network_access_manager.py` (nuevos): segundo
  adaptador real. `resource_key` es el hostname (no la URL completa);
  reusa la política YA existente (`downloads.allowed_domains`) — sin
  ninguna config nueva. `NetworkAction.BROWSE` declarado pero sin
  conectar todavía (mismo criterio que `FilesystemAction.DELETE/RENAME`:
  taxonomía completa, sin consumidor real aún).
- `tool_integration/network_safety.py`: extraído `is_hostname_allowed()`
  (la lógica de matching pura); `is_domain_allowed()` pasa a ser un
  wrapper delgado, sin cambiar su comportamiento público.
- `tool_integration/adapters/vscode_files.py::ImportResourceTool`:
  gate de red ANTES de descargar — dominio no permitido ahora crea una
  solicitud pendiente real (`Artifact` con `status: "requires_approval"`,
  `resource_kind: "network"`) en vez de fallar con un error inmediato
  sin salida.
- `agent_core/orchestrator.py`: endpoints `/network-access/*`
  (`GET` lista pendientes, `POST .../approve` y `.../deny` con token
  admin) — mismo patrón que `/filesystem-access/*`, SIN el equivalente
  a `report-outcome` (una descarga sucede enteramente dentro del
  backend, que ya sabe el resultado real sin que nadie se lo reporte).
- `audit/audit_log.py`: 4 `EventType` nuevos
  (`network_access_requested/granted/denied/escalated`).

**Bug real encontrado probando el flujo completo en vivo (aprobar un
dominio nuevo y reintentar)**: tras aprobar, la descarga SEGUÍA
fallando — `download_manager.py` tenía SU PROPIO chequeo de allowlist
de dominios (`is_domain_allowed` contra `settings.downloads.allowed_domains`
estático), una SEGUNDA fuente de verdad que no sabía nada de la
concesión recién otorgada por `network_access_manager`. Corregido
quitando ese chequeo de `download_manager.py` — el gate de dominio
pasa a ser responsabilidad exclusiva de quien llama (`ImportResourceTool`,
que ya gatea vía `network_access_manager` ANTES de descargar). El
resto de las validaciones de `download_manager` (IP segura, tamaño,
malware, contenido real) siguen intactas.

Verificado real, de punta a punta: URL de un dominio no listado →
`requires_approval` con `request_id` real; `network_access_manager.approve(id, level="once")`
→ el siguiente intento del MISMO dominio vuelve a pedir aprobación
(once nunca se recuerda); `approve(id, level="project")` → el
siguiente intento pasa el gate de red y llega hasta el paso real
siguiente (resolución DNS) — confirmando que la concesión tiene efecto
real, no solo en el gate sino en la descarga de verdad. 27 tests
nuevos (`test_access_manager.py`: 16, motor genérico;
`test_network_access_manager.py`: 11, adaptador de red) + tests
existentes actualizados (`test_import_resource_tool.py`: nuevo caso de
`requires_approval` de red; `test_download_manager.py`: quitado el
test del chequeo de dominio ahora removido; `test_network_safety.py`:
`is_hostname_allowed`; `test_orchestrator_admin_auth.py`: gate de
token en `/network-access/*`). Suite completa sin regresiones.

**Fuera de alcance de esta fase, documentado explícitamente**:
`BrowserTool` (`adapters/browser.py`) sigue con su chequeo de
allowlist directo, sin escalamiento — el mecanismo genérico queda
listo para que lo adopte después, evitando duplicar el riesgo de
tocar sus dos puntos de chequeo (pre-navegación + destino tras
redirect) en la misma pasada que construye el motor nuevo.
`PermissionCascade` sin cambios (capa aparte y complementaria).
Terminal/Modelos como nuevos "resource_kind" — pospuestos, sin
consumidor real todavía. Reestructuración a `kernel/` y SDK oficial —
próximos pasos, fuera de esta fase.

## BrowserTool adopta el Access Manager de red — segundo consumidor real (2026-07-20)

Siguiendo lo pospuesto explícitamente en la fase anterior:
`tool_integration/adapters/browser.py::BrowserTool` reemplaza su
rechazo duro de dominio (`is_domain_allowed()` directo, sin ningún
camino de escalar) por el mismo `network_access_manager` que ya usa
`ImportResourceTool` — con las mismas 4 escalas de concesión y
auditoría. Dos puntos de chequeo migrados: el gate PRE-navegación
(antes de llamar a Playwright) y el chequeo POST-redirect
(`_reject_if_unsafe_destination`, que valida el destino REAL tras
seguir cualquier redirect — ver "BUG REAL ENCONTRADO EN HARDENING F5"
en el docstring del módulo). El chequeo de IP insegura (DNS rebinding,
Fase E6) queda intacto, sin relación con este cambio.

`NetworkAction.BROWSE` (declarada pero sin conectar en la fase
anterior) ahora tiene una fuente de política real:
`network_access_manager.py::_is_policy_auto_allowed()` reusa
`settings.browser.allowed_domains` para BROWSE (mismo criterio que
DOWNLOAD con `downloads.allowed_domains`) — sin ninguna config nueva.
Nuevo `BROWSER_SKILL_NAME = "browser"` (mismo patrón que
`VSCODE_INTEGRATION_SKILL_NAME` de `vscode_files.py`) — genérico
porque `BrowserTool` la usan ambos clientes (web y VS Code), no solo
uno.

**Bug real de aislamiento de tests encontrado en el camino**: un test
nuevo (aprobar un dominio con `level="project"` y confirmar que un
reintento ya no escala) usaba el singleton REAL de
`network_access_manager` — que persiste concesiones en
`data/keys/network_grants.json`, un archivo real en disco, NO aislado
entre corridas de test. La primera corrida del test pasaba (creaba la
concesión real); la segunda corrida del MISMO test fallaba (`KeyError:
'request_id'`) porque el dominio ya estaba auto-permitido por la
concesión que la corrida ANTERIOR había persistido de verdad —
confirmado con `cat data/keys/network_grants.json` mostrando el grant
real. Corregido inyectando una instancia propia de
`NetworkAccessManager` con `grants_path` en `tmp_path` (mismo patrón
de aislamiento que ya usan `test_filesystem_access_manager.py` y
`test_network_access_manager.py`), vía
`monkeypatch.setattr(browser_module, "network_access_manager", ...)`
— el archivo real contaminado (con entradas de este mismo test y de
smoke tests manuales anteriores) se eliminó (`data/keys/` está en
`.gitignore`, solo estado local de desarrollo).

Verificado en vivo contra el servidor real: `BrowserTool().execute(url="https://sitio-no-permitido.../")`
devuelve `status: "requires_approval"` con un `request_id` real que
aparece en `network_access_manager.list_pending()`. Suite del área (92
tests) corrida DOS veces seguidas para confirmar idempotencia real
(sin el fix, la segunda corrida fallaba) — ambas veces sin fallos.
Tests nuevos/actualizados: 4 en `test_browser_tool.py` (2 casos
existentes migrados a `requires_approval`, 2 nuevos: pending request
real + ciclo aprobar→reintentar), 1 en `test_network_access_manager.py`
(BROWSE ya conectado, reemplaza el test viejo de "sin política
todavía"). Suite completa sin regresiones.

**Fuera de alcance, sin cambios**: `PermissionCascade`, Terminal/Modelos
como `resource_kind`, reestructuración a `kernel/` y SDK oficial —
siguen siendo los próximos pasos acordados, todavía no abordados.

## kernel/ como módulo independiente + SDK oficial (2026-07-20)

Cierre de la evolución de arquitectura: tras el Permission Manager
unificado (Access Manager genérico + BrowserTool como segundo
adaptador de red), el usuario pidió terminar con los dos puntos
restantes — reestructurar a `kernel/` y construir el SDK oficial.
Relevamiento previo (conteo real de consumidores por grep, no
estimación): ~90 archivos únicos importaban algo de
`tool_integration.{permissions,permission_cascade,access_manager,
filesystem_*,network_*,registry,skills,sandboxed_skill,versioning,
signing,skill_market,skill_signing,base_tool,kernel_client}`,
`kernel_bus.*` o `sandbox.*`.

**Hallazgo clave que motivó el diseño**: el SDK YA EXISTÍA en forma
embrionaria, sin nombrarse como tal —
`tool_integration/sandboxed_skill.py::_kal_runtime_files()` ya copiaba
literal `base_tool.py`/`permissions.py`/`kernel_client.py` dentro de
cada contenedor de skill, y `kernel_client.py` se autodescribía en su
propio docstring como "el SDK minúsculo que la skill usa del otro
lado". El problema real ("una Skill conoce demasiados detalles
internos") era concreto y verificable:
`skills/qr_code/tool.py` hacía
`from tool_integration.base_tool import Artifact, Tool` — un import
directo a una ruta interna del kernel.

**Decisión de diseño explícita del usuario** (confirmada antes de
implementar): NO extraer/generalizar módulos existentes tratando al
resto como derivado — construir `sdk/` como la base PURA (Tool,
ToolManifest, Artifact, Permission, 100% stdlib) de la que `kernel/`
DEPENDE (nunca al revés), y reorganizar TODO lo genérico
(`tool_integration.{permission*,access_manager,filesystem_*,network_*,
registry,skills,sandboxed_skill,versioning,signing,skill_market,
skill_signing}`, `kernel_bus/*`, `sandbox/*`) bajo `kernel/` con una
estructura de 6 subpaquetes: `api/` (protocolo+bus+socket_server+
sandbox_api), `services/` (ImageService/AudioService/STTService),
`broker/` (Resource Broker), `registry/` (alta/baja de herramientas y
Skills), `permissions/` (Permission Manager unificado), `lifecycle/`
(ejecución aislada: Docker runner/executor/skill_runner/skill_image_builder,
Dockerfile, scripts eBPF). Sin `kernel/scheduler/` — mismo criterio ya
aplicado a Terminal/Modelos: sin ningún candidato real hoy.
`tool_integration/` queda reducido a lo que siempre fue realmente
concreto: `adapters/`, `download_manager.py`, `malware_scan.py`.

**Ejecución**: movimiento con `git mv` (preserva historia) en 5
etapas (permisos → registro → lifecycle → api/services/broker →
recorte de tool_integration), seguido de un script Python que migró
~101 archivos de una sola pasada (imports dotted + referencias de
prosa estilo `tool_integration/registro.py` en docstrings/comentarios,
para que la documentación quedara consistente con el código real).
Corte limpio sin shims de compatibilidad, confirmado explícitamente
con el usuario antes de empezar (la alternativa — dejar
`tool_integration/base_tool.py` como re-export — habría dejado
conviviendo dos rutas de import, justo lo que se quería evitar).

**Varios bugs reales del reemplazo mecánico, encontrados y corregidos
uno por uno** (ninguno cambia comportamiento intencional, todos son
consecuencia de mover código sin tocar lógica):
1. Un regex que separaba `from tool_integration.base_tool import X, Y`
   en dos imports (`sdk.skill`/`sdk.artifacts`) rompió 2 archivos de
   prosa que YO MISMO escribí (`sdk/__init__.py`, `kernel/__init__.py`)
   citando ese import como ejemplo dentro de un string — el reemplazo
   ciego no distingue "código real" de "texto que menciona código".
   Corregido a mano.
2. El mismo patrón rompió 6 ocurrencias en `tests/test_sandboxed_skill.py`
   donde el import viejo vivía DENTRO de un string literal de una sola
   línea (código de prueba usado como fixture) — el reemplazo insertó
   un salto de línea REAL adentro de un string comillado, rompiendo la
   sintaxis. Detectado con un chequeo de sintaxis (`ast.parse`) sobre
   TODO el repo — encontró también 2 casos más
   (`test_tool_versioning.py`, `test_tool_registry.py`) donde el
   import quedó indentado incorrectamente (una línea con 4 espacios,
   la siguiente en columna 0) dentro de una función.
3. Un fallback "bare word" (`kernel_bus` -> `kernel`, para prosa
   suelta) hizo un reemplazo de SUBSTRING, no de palabra completa —
   corrompió el nombre real del singleton del bus
   (`kernel_bus = _build_default_bus()` pasó a `kernel = ...`, y
   `default_kernel_bus` pasó a `default_kernel`) en 2 archivos
   (`kernel/api/bus.py`, `kernel/registry/sandboxed_skill.py`,
   `kernel/registry/registry.py`). Funcionalmente seguía siendo
   consistente (definición y todos los usos coincidían), pero el
   nombre `kernel` colisionaba confusamente con el propio paquete que
   lo contiene — renombrado a `kernel_service_bus` para claridad, y
   quedó UN bug real de verdad en el camino: una referencia a
   `default_kernel` que mi propio Edit anterior había dejado sin
   actualizar (variable inexistente, `NameError` en tiempo de
   ejecución si `kernel_bus_instance` es `None`).
4. `_kal_runtime_files()` (la función que arma los archivos a copiar
   al contenedor de una skill) quedó con las CLAVES del diccionario ya
   migradas (`"sdk/skill.py"`, etc., por el reemplazo de texto) pero
   los VALORES seguían leyendo de `_TOOL_INTEGRATION_DIR / "base_tool.py"`
   — un directorio/archivo que ya no existía tras borrar
   `tool_integration/base_tool.py`. Reescrita para leer los 5 archivos
   reales de `sdk/` (antes copiaba solo 3). `_RUNNER_PATH` (ruta
   `__file__`-relativa a `skill_runner.py`) también apuntaba mal tras
   el movimiento de directorio (`kernel/registry/` en vez de la vieja
   `tool_integration/`, con `skill_runner.py` ahora en
   `kernel/lifecycle/` en vez de `sandbox/`) — único otro caso de este
   tipo de bug en todo el repo (confirmado por grep de `__file__`).
5. `Dockerfile`s y scripts shell (`.sh`, no `.py` — el script de
   migración solo tocó `.py`) con rutas hardcodeadas
   (`COPY sandbox/`, `WORKDIR /app/sandbox`,
   `CMD ["uvicorn", "sandbox.sandbox_api:app", ...]`,
   `docker-compose.yml: dockerfile: sandbox/Dockerfile`) — corregidos
   a mano uno por uno. El Dockerfile del sandbox_runner también ganó
   `COPY sdk/` (antes no hacía falta copiar nada de eso porque
   `sandbox_api.py`/`executor.py` no dependían de `Permission`
   directamente por ese camino — ahora `executor.py` importa
   `sdk.permissions`).
6. **El más sutil**: firmar las 6 skills reales con
   `scripts/sign_skill.py` (necesario porque migrar sus `tool.py` a
   `sdk.*` invalida la firma existente — `verify_skill_signature()` es
   fail-closed, una skill con firma inválida NO se registra) tiene que
   pasar DESPUÉS de terminar TODOS los demás cambios de contenido — 3
   de las 6 quedaron "tampered" de nuevo porque las firmé, y RECIÉN
   DESPUÉS corregí referencias de prosa obsoletas
   (`kernel_bus/__init__.py`) en sus propios `skill.yaml` (que SÍ
   forma parte de lo firmado, a propósito — para que nadie pueda subir
   permisos en el manifiesto sin invalidar la firma). Encontrado
   comparando a mano el manifiesto canónico actual contra el firmado
   (`_canonical_manifest()`); solucionado firmando una segunda vez,
   ahora sí como paso verdaderamente final.

**Verificado real, de punta a punta**: `python -c "import
agent_core.orchestrator"` limpio; las 6 skills reales cargan con
`status: "loaded"` y `signature_status: "verified"`; ejecución REAL de
`qr_code` dentro de un contenedor Docker real (reusando la imagen
`kal-skill-qr-code` ya construida) generó un PNG real de 551 bytes en
`data/artifacts/skills/qr_code/` — confirma que el `sdk/` copiado
dentro del contenedor (5 archivos: `__init__.py`, `skill.py`,
`artifacts.py`, `permissions.py`, `context.py`) importa y funciona de
verdad, no solo en teoría. Verificación de sintaxis (`ast.parse`)
sobre los ~2000+ archivos `.py` del repo: 0 errores. Grep final de
cualquier referencia residual a las rutas viejas (imports Python,
YAML, shell, Dockerfiles): 0 resultados fuera de una mención histórica
intencional en `sdk/__init__.py`. Suite completa de pytest, 0
regresiones.

**Fuera de alcance de esta fase, documentado explícitamente**:
verificación de build real de `docker-compose.yml` (el subcomando
`docker compose` no está disponible en este entorno de desarrollo —
validado el YAML sintácticamente y revisado el Dockerfile a mano en
su lugar); renombrar las claves de `config/config.yaml`
(`tool_integration:`, `permissions:`, etc.) — son namespaces de
configuración independientes del layout de carpetas, sin beneficio
real de renombrarlas ahora.

## Dos bugs reales encontrados en uso justo después de la reestructuración (2026-07-20)

El usuario pidió "crea una naranja (solo una)" al servidor real y
recibió `Error: NetworkError when attempting to fetch resource.` en el
frontend. El log completo (no solo el fragmento inicial que compartió)
reveló DOS problemas reales, independientes entre sí.

**Bug 1 — `--reload` de uvicorn vigilaba `data/`**: mientras el
usuario probaba el servidor en vivo, la suite de tests corría en
paralelo (parte de la verificación final de la reestructuración a
kernel/) y escribió archivos reales bajo `data/tool_versions/` (los
tests de versionado de herramientas dinámicas persisten versiones de
verdad). `uvicorn --reload`, sin restricciones, vigila TODO el árbol
del proyecto — detectó esos cambios y reinició el servidor completo A
MITAD de la conversación del usuario, cortando la respuesta con el
`NetworkError` que vio. Corregido en `scripts/run_kal.sh`: agregados
`--reload-exclude` para `data/*`, `logs/*`, `docs/*`, `tests/*`,
`*.log` — ninguno es código fuente que deba disparar un reload, así
que esto no esconde ningún cambio real, solo deja de reaccionar a
efectos secundarios de ejecutar la app o los tests.

**Bug 2, más importante — el modelo analizaba su propia imagen recién
generada y la regeneraba**: tras el reinicio, el pedido original
("crea una naranja (solo una)") siguió corriendo en segundo plano
(`uvicorn` espera tareas en curso al apagarse) y el log completo
mostró la secuencia real: `image_generation` (éxito, imagen real
generada) → `analyze_image` sobre esa MISMA imagen recién creada →
`image_generation` DE NUEVO (otra imagen real generada) →
`analyze_image` de nuevo → intento de generar una TERCERA vez,
rechazado por `max_tool_repeats` → agotó `max_agent_steps=8` sin
ninguna respuesta final. El límite estructural (`max_tool_repeats`,
ver `technical_agent_image_overgeneration` en memoria) funcionó
exactamente como se diseñó — evitó una cuarta y quinta generación real
— pero el usuario terminó sin ninguna respuesta pese a que la imagen
YA se había generado bien la primera vez.

Causa: `analyze_image` (agregado en una sesión posterior a la regla
de "generá exactamente lo pedido" del `SYSTEM_PROMPT`) no estaba
mencionado en esa regla — el modelo, tras generar con éxito, decidía
por su cuenta "revisar" lo que había creado llamando a `analyze_image`
sobre su propio resultado, y la descripción que volvía lo empujaba a
generar de nuevo en vez de simplemente responder. Corregido con dos
reglas nuevas en `agent_core/llm/agent_loop.py::SYSTEM_PROMPT`: (1) la
regla existente de "no encadenes herramientas extra" ahora menciona
explícitamente `analyze_image` como una de esas herramientas extra no
pedidas; (2) regla nueva y explícita: nunca llamar `analyze_image`
sobre una imagen generada en el MISMO turno para "confirmar" que salió
bien — esa herramienta es solo para cuando el usuario pide describir/
analizar una imagen (propia o ya existente), nunca como autochequeo.

Verificado real, de punta a punta: el MISMO pedido exacto
("crea una naranja (solo una)") contra `AgentLoop.run()` real (mismo
modelo, mismo Ollama) ahora genera UNA sola imagen (1 paso) y responde
directo con la ruta del archivo — sin `analyze_image`, sin
regeneración. `tests/test_agent_loop.py` (45 tests) y
`tests/test_self_modification.py` (17 tests, por el fix de
`CORE_PATHS_HARDCODED` de la fase anterior) sin regresiones.

## Autochequeo acotado (1 revisión + 1 reintento), no prohibición total, con aviso honesto (2026-07-20)

El usuario, revisando las tres naranjas generadas por el bug anterior,
notó algo importante: NINGUNA mostraba una sola naranja — todas eran
grupos. Hipótesis correcta: el modelo probablemente regeneraba porque
`analyze_image` SÍ detectaba el desajuste (no era un loop sin sentido)
— pero sin límite, nunca llegaba a avisar la limitación, solo agotaba
pasos. Confirmado revisando `kernel/services/services.py`: el prompt
que kal le mandaba a SDXL-Turbo SÍ decía "una sola naranja" cada vez —
el generador de imágenes en sí (2 pasos, optimizado para velocidad) es
el que no respeta cantidades exactas de forma confiable, una
limitación real y conocida de los modelos de difusión rápidos, no un
error de razonamiento de kal.

Dado esto, la corrección anterior (prohibir `analyze_image` sobre la
propia generación) era demasiado tajante — el usuario pidió en cambio
un término medio: permitir la auto-revisión, pero acotada a UN solo
reintento, con aviso honesto si el resultado sigue sin coincidir.

**Implementado, estructural (no solo texto de prompt — mismo criterio
que `max_tool_repeats` general, que ya demostró que las instrucciones
de prompt solas no alcanzan)**: `AgentLoop.run()` ahora rastrea
`artifact_paths_this_turn` (uri del artefacto -> nombre de la
herramienta que lo generó) y `self_checked_tools` (qué herramientas
generativas ya se autochequearon con `analyze_image` en este turno,
detectado comparando el `image_path` que recibe `analyze_image` contra
esa tabla). Una herramienta marcada como autochequeada queda con un
tope de `min(2, max_tool_repeats)` — la original + un solo reintento —
en vez del `max_tool_repeats` configurado en general (que sigue
aplicando sin cambios a todo lo demás). El mensaje de rechazo, cuando
se corta por este tope MÁS estricto, le pide al modelo explícitamente
que responda YA y que sea honesto si el resultado no coincide
exactamente ("los modelos de generación de imágenes no siempre
respetan cantidades exactas, reintentar más no lo garantiza").
`SYSTEM_PROMPT` actualizado en el mismo sentido (autochequeo permitido
pero acotado, en vez de prohibido).

2 tests nuevos en `tests/test_agent_loop.py`: confirma que el tope se
endurece a 2 SOLO cuando `analyze_image` miró un artefacto de ESTE
turno (no una ruta cualquiera, como una imagen subida por el usuario),
y que sigue rechazando un 3er intento aunque `max_tool_repeats`
configurado sea mayor. Verificado en vivo contra el servidor real
(mismo pedido: "crea una naranja (solo una)") — generó, se autorevisó
una vez, reintentó una sola vez más, y esta vez SÍ llegó a una
respuesta final (a diferencia de antes, que agotaba los 8 pasos sin
responder nada). Suite completa de `test_agent_loop.py` (47 tests) sin
regresiones.

## Deuda de seguridad de la revisión 2026-07-09: los 5 hallazgos menores restantes, más el bug de "quién sos" (2026-07-20)

Pedido explícito del usuario: cerrar los hallazgos menores documentados
como "deuda aceptada" en la revisión de seguridad del 9 de julio (ver
sección más arriba y [[project_security_review_2026_07_09]]) — de los 6
originales, ya quedaba corregido el límite de línea del Kernel Bus
(2026-07-11); quedaban 5 — y de paso, el bug ya diagnosticado de
"quién sos" disparando `system_info` sin necesidad (ver
[[technical_agent_overeager_tool_calling_on_identity_questions]]), cuyo
fix ya estaba identificado pero nunca aplicado a propósito.

Las rutas de todos estos hallazgos cambiaron con la reestructuración a
`kernel/`+`sdk/` (`kernel_bus/` -> `kernel/api/`+`kernel/services/`,
`sandbox/` -> `kernel/lifecycle/`) — se verificó el código real de cada
uno antes de tocar nada, no se asumió nada de la memoria de la sesión
anterior.

**1. Sin lock sobre los pipelines compartidos.** `ImageService`/
`AudioService`/`STTService` (`kernel/services/services.py`) exponen un
único pipeline de PyTorch/piper/faster-whisper por proceso, invocable
tanto por el adaptador de primera parte como por cualquier cantidad de
skills concurrentes vía el bus — sin ninguna sincronización. Fix: un
`threading.Lock()` por pipeline (no uno solo por servicio — `generate()`
e `inpaint()` usan pipelines DISTINTOS, un solo lock los serializaría
sin necesidad). En `STTService.transcribe()`, importante: el generador
que devuelve `faster-whisper` es perezoso — el lock tiene que envolver
también su consumo (`" ".join(...)`), si no la sincronización sería un
espejismo (el cómputo real seguiría ocurriendo fuera de la sección
protegida).

**2. Errores internos del kernel bus se devolvían crudos a la skill.**
`kernel/api/socket_server.py::_handle_line()` capturaba cualquier
`Exception` de `bus.dispatch()` y devolvía `str(e)` tal cual por el
socket — un servicio real puede fallar de formas que revelan detalles
del host (p.ej. una ruta real ya resuelta desde un `artifact://` de
entrada, mensajes de librerías de terceros). Si esa misma skill
también tiene permiso de red, es una vía de exfiltración. Fix: los
errores de protocolo del propio bus (`ServiceNotFoundError`/
`ActionNotFoundError`/`ArtifactNotFoundError`, cuyo mensaje solo cita
strings que la skill misma pasó como parámetro) se siguen devolviendo
tal cual — son seguros por construcción. Cualquier otra excepción
ahora devuelve un mensaje genérico (`"el servicio '{method}' falló
procesando el pedido"`); el detalle completo se sigue registrando
server-side (`logger.warning` + auditoría) para diagnóstico, solo deja
de cruzar el socket.

**3. `dispatch()` sin allowlist explícito de acciones por servicio.**
Resolvía la acción con `getattr` genérico sobre el objeto del
servicio — cualquier método público quedaba invocable como "acción" del
bus, no solo los pensados como tal. Inofensivo hoy (cada servicio solo
tiene los métodos que ya son sus acciones reales), pero frágil a
futuro: un método público agregado más adelante para otro propósito
quedaría expuesto por accidente. Fix: `ALLOWED_ACTIONS` (frozenset)
explícito en cada clase de servicio
(`ImageService`/`AudioService`/`STTService`), chequeado en
`KernelServiceBus.dispatch()` antes de resolver el `getattr`. Test
nuevo (`test_dispatch_rejects_a_public_method_not_in_allowed_actions`)
agrega un método público deliberadamente fuera de la allowlist a un
servicio de prueba y confirma que se rechaza igual que uno inexistente.

**4. Directorio de trabajo del sandbox en 0777.**
`kernel/lifecycle/docker_runner.py::_prepare_workdir()` hardcodeaba el
contenedor a correr como UID/GID 1000:1000 y, para que el bind mount
fuera legible pese a que el proceso host casi nunca corre con ese mismo
UID, abría el árbol entero con `chmod 0777` — legible y ESCRIBIBLE por
CUALQUIER usuario del sistema mientras el contenedor corría, no solo un
riesgo teórico en un host compartido (no de un solo usuario). Fix real,
no solo un chmod más angosto: en vez de hardcodear el UID del
contenedor y compensar del lado del host, el contenedor ahora corre
con `user=f"{os.getuid()}:{os.getgid()}"` — el MISMO UID/GID que el
proceso que lo lanza, sea cual sea. Sin mismatch que compensar, ya no
hace falta abrir ningún permiso: los defaults de
`tempfile.TemporaryDirectory()` (0700) y `write_text`/`mkdir` alcanzan
porque el dueño real y el usuario del contenedor son la misma cuenta.
Eliminadas las constantes `SANDBOX_UID`/`SANDBOX_GID` (sin otro uso en
el repo) y todos los `os.chmod` que compensaban el mismatch. Verificado
con Docker real: los 16 tests de `test_sandbox_integration.py` pasan
sin cambios (incluidos los de `output_dir`/`workspace_files`, que
dependían de esos permisos).

**5. `_artifact_url()` no era `..`-safe por sí sola.**
`agent_core/orchestrator.py` comparaba con `Path(uri).relative_to(
'data/artifacts')` SIN resolver antes — un `uri` armado como
`"data/artifacts/../../etc/passwd"` tiene `('data', 'artifacts')` como
prefijo literal de sus partes (relative_to no resuelve ".." antes de
comparar), así que la función lo aceptaba igual, dependiendo
enteramente de que Starlette bloqueara el traversal real al servir el
archivo después. Hoy no hay ningún llamador que pase un `uri`
controlado por un tercero, pero la función debe ser segura POR SÍ
SOLA. Fix: `Path(uri).resolve()` antes de `relative_to(_ARTIFACTS_DIR)`
— un intento de escape termina en una ruta absoluta fuera del
directorio real y se rechaza de verdad, no solo en apariencia. 4 tests
nuevos en `tests/test_orchestrator_artifact_url.py`, incluido uno que
reproduce exactamente el escape que antes pasaba desapercibido.

**Bug de "quién sos" disparando `system_info` — fix de prompt aplicado
(el ya planeado, no el estructural de la sobregeneración de
imágenes).** `SYSTEM_PROMPT` (`agent_core/llm/agent_loop.py`) ya tenía
una regla contra esto, pero redactada pensando específicamente en "no
generar audio" — el modelo, muy probablemente, interpretó que llamar a
`system_info` no la violaba (no es audio). Generalizada la regla
existente para decir explícitamente "sin llamar a NINGUNA herramienta
(ni audio, ni system_info, ni ninguna otra)", agregando el caso real de
`system_info` como segundo ejemplo concreto — mismo patrón que ya
funcionó para el resto de esta lista de ejemplos. Cambio de texto de
prompt únicamente, sin tests nuevos (mismo criterio que el fix
equivalente para la sobregeneración de imágenes).

**Verificación**: `test_sandbox_integration.py` (16, Docker real),
`test_sandboxed_skill.py` + `test_skills.py` (56, Docker real,
incluidos los 3 tests end-to-end del Kernel Service Bus actualizados
con `ALLOWED_ACTIONS`), `test_kernel_bus.py` + `test_kernel_bus_socket_server.py`
+ `test_orchestrator_artifact_url.py` (23) — todos verdes antes de
correr la suite completa.

## orchestrator.py deja de ser un god-file: 44 endpoints repartidos en routers por dominio (2026-07-20)

Pedido explícito del usuario tras una revisión de arquitectura propia
(7 observaciones, ver más abajo el resto de la lista pendiente):
`agent_core/orchestrator.py` había crecido a 879 líneas con los 44
endpoints HTTP del proyecto declarados directamente con
`@app.get`/`@app.post`, importando prácticamente todos los subsistemas
(memoria, self-mod, sesiones, diagnóstico, permisos de FS y red,
registry, VS Code, audit...). Funcionaba, pero cualquier cambio tocaba
ese archivo, y el acoplamiento por import dificultaba razonar sobre qué
depende de qué.

**Refactor mecánico, sin cambios de comportamiento**: 11 `APIRouter`
nuevos bajo `agent_core/routers/` (health, llm_settings, chat, tasks,
tools, memory, self_modification, permissions, diagnostics,
vscode_integration, audit), cada uno con sus propios modelos Pydantic y
endpoints, importando desde `agent_core.orchestrator` solo lo que
necesita compartir: el singleton `orchestrator`, `require_admin_token`,
`_artifact_url`, `_reinject_llm_client`. `agent_core/orchestrator.py`
queda en 260 líneas — construye el singleton `Orchestrator`, arma la
app de FastAPI, el token administrativo, sirve el frontend estático, y
hace `app.include_router(...)` por cada dominio.

**Orden de imports deliberado para evitar un import circular real**:
los routers hacen `from agent_core.orchestrator import orchestrator,
require_admin_token, ...`, y `agent_core/orchestrator.py` a su vez hace
`from agent_core.routers import (chat, tasks, ...)` para incluirlos —
un ciclo real entre los dos módulos. Se resuelve con ORDEN: todo lo que
los routers necesitan importar (`orchestrator`, `require_admin_token`,
`_artifact_url`, `_reinject_llm_client`) se define PRIMERO en
`orchestrator.py`, y el `from agent_core.routers import ...` va
DESPUÉS — cuando Python ejecuta ese import y entra a cada archivo de
router, el módulo `agent_core.orchestrator` ya está en `sys.modules`
(parcialmente ejecutado, pero con esos nombres ya definidos), así que
la resolución funciona sin re-ejecutar nada.

**Bug real encontrado verificando el refactor (no de lógica, de
versión de dependencia)**: contar `len(app.routes)` antes/después de
cada `app.include_router()` para confirmar que cada router aportaba
sus endpoints mostraba solo +1 por router en vez de +3, +6, etc. — casi
se interpreta como un bug del refactor. Investigado con una
reproducción mínima aislada (`FastAPI()` + `APIRouter()` con 3 rutas
sueltas, sin nada más del proyecto): FastAPI 0.139 cambió su
representación interna de `app.routes` — `include_router()` ahora
agrega un único objeto `_IncludedRouter` envolviendo las rutas
incluidas, en vez de aplanarlas como antes. Nada roto: confirmado
haciendo pedidos HTTP reales vía `TestClient` contra cada endpoint
migrado (todos 200), no contando la estructura interna de `app.routes`
(que cambió de forma en esta versión de FastAPI y ya no es un proxy
confiable de "cuántos endpoints hay").

**Bug real de test-double, no de código de producción**: 3 archivos de
test (`test_orchestrator_admin_auth.py`, `test_orchestrator_llm_settings.py`,
`test_orchestrator_vscode_integration.py`) mockeaban funciones
(`update_llm_settings`, `pull_ollama_model`, `list_local_ollama_models`,
`activate_cloud_profile`, `get_llm_settings`, `list_model_sources`,
`get_ollama_model_capabilities`, `get_vscode_status`,
`install_extension`) con `monkeypatch.setattr(orchestrator, "nombre",
...)` — apuntando al módulo `agent_core.orchestrator`, que es donde
esas funciones se importaban ANTES del refactor. Al mover los
endpoints que las llaman a sus routers nuevos (que hacen su PROPIO
`from agent_core.llm_settings import ...`/`from
agent_core.vscode_integration import ...`), el mock dejó de tener
efecto — cada nombre se resuelve en el namespace del módulo que lo
importó, no en el del módulo que originalmente lo reexportaba. Corregido
retargeteando esos `monkeypatch.setattr(...)` a
`agent_core.routers.llm_settings`/`agent_core.routers.vscode_integration`.
`build_llm_client` es la excepción: se queda apuntando a
`orchestrator` porque esa función NUNCA se movió (la sigue llamando
`_reinject_llm_client()`, que tampoco se movió).

Verificado: 34 tests de los 6 archivos `test_orchestrator_*.py` +
`test_llm_client_factory.py` en verde, más la suite completa (790
passed, 0 regresiones, 19:24).

## Correlation ID: de /chat hasta el log de la skill y el audit log (2026-07-20)

Punto 6 de la revisión de arquitectura del usuario (después del punto 1,
ver más arriba): sin esto, reconstruir qué pasó en un pedido real
significaba cruzar `logs/agent.log` y `logs/audit.log` a mano — patrón
ya repetido varias veces en esta sesión (p.ej. investigando los
archivos de audio generados por tests, o el bug de la naranja).

**Corrección de premisa antes de diseñar**: el usuario mencionó "con el
structlog que utilizamos" — pero `structlog` está en `requirements.txt`
(línea "logging estructurado") SIN usarse en ningún lado del código;
`utils/logger.py` es stdlib `logging` puro, con un formatter de texto
plano. No se migró a structlog para este cambio (alcance mucho mayor,
reescribir cada call site) — se resolvió con lo que ya hay:
`contextvars` + un `logging.Filter`.

**Diseño**: `utils/correlation.py` nuevo — un `contextvars.ContextVar`
con `new_id()` (12 hex), `set_correlation_id()`/`get_correlation_id()`.
Deliberadamente NO se pasa el id como parámetro explícito por cada
función de la cadena `AgentLoop -> tool_registry -> SandboxedSkillTool
-> SandboxExecutor -> DockerSandboxRunner` (~30+ call sites, incluida
la interfaz `Tool.execute()` que implementan 36+ herramientas) — toda
esa cadena corre en el MISMO thread que originó el pedido HTTP
(Starlette corre cada `def` sync en un thread de su pool, pero un único
pedido nunca salta de thread a mitad de camino), así que un solo
`set_correlation_id()` al principio de `/chat`
(`agent_core/routers/chat.py`) ya es visible en toda la cadena sin
tocar ninguna firma intermedia.

**Propagación automática, sin tocar call sites existentes**:
- `utils/logger.py`: un `logging.Filter` nuevo inyecta
  `record.correlation_id` (o `"-"` si nada lo seteó) en cada
  `LogRecord` — TODOS los `logger.info(...)`/`warning(...)` ya
  existentes en el proyecto lo muestran automáticamente, sin editar
  ninguno.
- `audit/audit_log.py::AuditLog.record()`: inyecta
  `event.context["correlation_id"]` automáticamente si hay uno seteado
  y el llamador no puso ya uno explícito — cubre los ~15 call sites de
  `audit_log.record(...)` repartidos por el proyecto sin tocarlos.

**Excepción real que si necesitó código explícito**:
`kernel/api/socket_server.py::KernelBusSocketServer` sirve el socket
Unix en un `threading.Thread` de background propio — un `ContextVar`
NUNCA cruza automáticamente a un thread nuevo. Se captura el valor en
el thread ORIGINAL (dentro de
`kernel/registry/sandboxed_skill.py::SandboxedSkillTool.execute()`,
antes de lanzar el socket) y se pasa explícito
(`correlation_id=get_correlation_id()`); `_serve()` hace
`set_correlation_id(self.correlation_id)` como primera línea, así que
todo lo que loguea/audita desde ese thread (incluida cada llamada real
de la skill al Kernel Service Bus) queda etiquetado igual.

**Hasta dentro del contenedor**: `kernel/lifecycle/docker_runner.py::run()`
ahora pasa `KAL_CORRELATION_ID` como variable de entorno al contenedor
(leído de `get_correlation_id()` — corre en el mismo thread que originó
el pedido, mismo razonamiento que arriba) — una skill de terceros
PUEDE leerlo e incluirlo en lo que imprime, sin que sea obligatorio.
Verificado con Docker real: `os.environ.get("KAL_CORRELATION_ID")`
dentro del contenedor devuelve el valor exacto seteado del lado del
host.

`POST /chat` genera un id nuevo por pedido, lo loguea al recibir el
`goal`, y lo devuelve en la respuesta JSON (`correlation_id`) — ante un
fallo real alcanza con ese valor para grep-ear ambos logs, sin
reconstruir nada a mano.

**Verificado en vivo, de punta a punta**: llamando directamente a la
skill real `qr_code` (Docker real) con un correlation_id de prueba
seteado, la línea de log "Ejecutando skill de terceros: 'qr_code'" Y la
entrada de auditoría `sandbox_execution` que genera
`SandboxExecutor.execute_trusted()` muestran el mismo id — mientras que
entradas de auditoría de ANTES de setear ninguno (`skill_loaded`, del
arranque del proceso) siguen sin él, confirmando que no hay
contaminación retroactiva. Un `POST /chat` real con "hola" confirma el
mismo id en la respuesta JSON y en `logs/agent.log`.

12 tests nuevos: `tests/test_correlation.py` (el módulo en sí),
3 en `tests/test_audit_log.py` (inyección automática, sin pisar uno
explícito, sin agregar la key si no hay ninguno seteado), 1 en
`tests/test_kernel_bus_socket_server.py` (cruce real al thread de
background), 2 en `tests/test_sandbox_integration.py` (Docker real: la
env var llega, y está ausente si no hay id seteado). Suite completa
verificada sin regresiones.

## Skill Creator: el agente propone Skills nuevas, un humano las aprueba (2026-07-20)

Primer punto de una segunda ronda de sugerencias del usuario (análisis
competitivo contra otros agentes locales tipo local-skills-agent) —
priorizado explícitamente por el usuario por encima del resto.

**Diseño**: `agent_core/skill_creator.py` (`SkillCreatorManager`),
mismo espíritu que `self_modification.py` (proponer -> validar barato
-> humano decide) pero para el caso que ese pipeline excluye a
propósito: crear archivos que no existían, no modificar uno existente.

- `propose()` NUNCA escribe bajo `skills/` — solo bajo
  `data/proposed_skills/<id>/`, invisible para
  `kernel/registry/skills.py::load_skills()` (que solo mira `skills/`).
  Validación deliberadamente barata: nombre válido (snake_case, sin
  colisión con una skill real ni con otra propuesta pendiente), nombre
  de clase válido, permisos declarados existen de verdad
  (`sdk.permissions.Permission`), y el código es sintácticamente válido
  Python (`ast.parse`). A diferencia de `self_modification.py`, el
  código NUNCA pasa por el denylist AST — una Skill legítima necesita
  `os`/`subprocess`/etc. para hacer algo útil (mismo criterio ya
  documentado en `kernel/registry/skills.py`: la barrera real es el
  aislamiento Docker, no un filtro estático).
- `approve()` copia la propuesta a `skills/<name>/` y la firma (Ed25519
  propio, identidad separada en `data/keys/agent_generated_skills/` —
  distinguible de `data/keys/kal_project`, usada para las skills
  escritas por el propio proyecto) — pero `enabled` queda en `false`
  siempre. Habilitarla de verdad es un SEGUNDO gate independiente
  (`scripts/enable_skill.py`, sin tocar), no algo que aprobar la
  propuesta haga solo.
- `reject()` borra el staging sin dejar rastro en `skills/`.
- Nueva Tool `propose_skill` (`tool_integration/adapters/skill_creator_tool.py`),
  registrada como herramienta estática de primera parte (no
  sandboxeada — no ejecuta el código propuesto, solo lo escribe a
  disco para revisión, mismo criterio que `propose_project_files`).
- Nuevo router `/skill-proposals/*`
  (`agent_core/routers/skill_creator.py`): listar (resumen), ver detalle
  completo (CÓDIGO incluido — un humano tiene que poder leerlo entero
  antes de decidir), aprobar/rechazar (gateados con el token
  administrativo, igual que self-modification).

**Bug real, pre-existente, encontrado probando el flujo completo**:
habilitar una skill YA FIRMADA (`set_skill_enabled()`, lo mismo que usa
`scripts/enable_skill.py`) invalidaba su propia firma en el acto —
`enabled` vive dentro de `skill.yaml`, y la firma cubre el archivo
entero. Nunca se había disparado en la práctica porque las 6 skills
existentes siempre se firmaron con `enabled` ya en su valor final; el
diseño de dos gates independientes del Skill Creator (aprobar ≠
habilitar) fue el primero en de verdad ejercer esa secuencia. Fix en
`kernel/registry/skill_signing.py::_canonical_manifest()`: `enabled`
se normaliza a un valor fijo antes de hashear skill.yaml — el resto del
manifiesto (permissions/requirements/kernel_services/entry_point/etc.,
que SÍ son decisión del autor) sigue cubierto por la firma tal cual.
`verify_skill_signature()` ampliado para tratar un YAML corrupto como
"tampered" (fail closed), ya que ahora sí parsea el archivo en vez de
solo hashear bytes crudos.

Como este cambio altera qué bytes se firman de verdad, invalidó las
firmas de las 6 skills reales existentes — se re-firmaron con
`scripts/sign_skill.py` (mismo `data/keys/kal_project`, mismo
fingerprint de autor, confirmando que es la misma identidad, solo
re-firmada bajo el algoritmo corregido).

**Verificado en vivo, de punta a punta**: llamando a la Tool real
`propose_skill` (sin pasar por el LLM) se generó una propuesta real en
`data/proposed_skills/`, con su `skill.yaml` (`enabled: false`) y
`tool.py` legibles; `reject()` la limpió sin dejar rastro. Por
separado, un test de integración confirma que aprobar sin habilitar
deja la skill en estado "disabled" para `load_skills()` real (ni
una línea de su código se ejecuta), y que habilitarla aparte
(`set_skill_enabled`) recién ahí la deja "loaded" con firma "verified".

31 tests nuevos: `tests/test_skill_creator.py` (23, el manager +
end-to-end con el loader real), `tests/test_orchestrator_skill_creator.py`
(9, el router), 2 en `tests/test_skill_signing.py` (regresión del bug
de `enabled` + que otros cambios en skill.yaml sigan detectándose), 2
entradas nuevas en la lista de endpoints gateados de
`tests/test_orchestrator_admin_auth.py`. Suite completa verificada sin
regresiones.
