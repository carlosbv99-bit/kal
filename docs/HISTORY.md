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
