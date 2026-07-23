"""
kernel/: toda la infraestructura genérica de kal — el "microkernel" del
que agent_core/ es un CONSUMIDOR, nunca el dueño. Reestructurado
(2026-07-20) a partir de lo que antes vivía repartido entre
tool_integration/, kernel_bus/ y sandbox/ — mismo código, ninguna
lógica nueva, solo un lugar de verdad único por responsabilidad:

  - api/         — el protocolo/superficie por la que un contenedor
                    aislado (Skill) o un proceso externo (sandbox_runner)
                    habla con el kernel: protocol.py (JSON-RPC 2.0,
                    funciones puras), bus.py (registro de servicios +
                    despacho por nombre), socket_server.py (expone el
                    bus a un contenedor vía socket Unix), sandbox_api.py
                    (API HTTP propia del proceso aislado con acceso al
                    socket de Docker, ver docker-compose.yml).
  - services/    — los servicios reales que un Kernel Service Bus
                    despacha (hoy: ImageService/AudioService/STTService,
                    modelos pesados que se cargan una vez y se
                    mantienen calientes entre llamadas).
  - broker/      — ciclo de vida de recursos pesados (Resource Broker):
                    libera RAM de servicios inactivos bajo presión, para
                    que el modelo de lenguaje del agente (Ollama) no
                    compita por la misma RAM que las herramientas
                    multimedia.
  - registry/    — alta/baja de herramientas: registro de Tools de
                    primera parte y dinámicas (registry.py), descubrimiento
                    y carga de Skills instaladas (skills.py), el puente
                    que convierte una Skill descubierta en una Tool
                    ejecutable de forma aislada (sandboxed_skill.py),
                    versionado/firma de herramientas dinámicas
                    (versioning.py/signing.py), y el mecanismo de
                    marketplace de Skills de terceros (skill_market.py/
                    skill_signing.py).
  - permissions/ — Permission Manager unificado: PermissionCascade
                    (¿puede esta herramienta pedir esta CAPACIDAD en
                    absoluto?, por nivel de confianza) + AccessManager
                    genérico (¿esta acción concreta sobre este recurso
                    concreto se auto-permite o requiere aprobación
                    humana?, con 4 escalas de concesión), y sus dos
                    adaptadores reales: filesystem y red.
  - lifecycle/   — ejecución aislada de código no confiable: el
                    SandboxExecutor + el runner de Docker real
                    (docker_runner.py), el proceso que corre DENTRO del
                    contenedor de una Skill (skill_runner.py), y la
                    construcción de la imagen Docker derivada por Skill
                    (skill_image_builder.py) — incluye el Dockerfile
                    base y los scripts de observación eBPF.

`kernel/permissions/` y el resto de este paquete DEPENDEN de `sdk/`
(nunca al revés) — `Permission`/`Tool`/`ToolManifest`/`Artifact` viven
en `sdk/` como fuente única, la misma que se copia dentro de cada
contenedor de Skill (ver
kernel/registry/sandboxed_skill.py::_kal_runtime_files()).

Sin `kernel/scheduler/` todavía — deliberado, sin ningún candidato real
hoy (mismo criterio que Terminal/Modelos en el Permission Manager: se
construye cuando exista una necesidad real de planificación de tareas,
no antes).

---

Docstring original del Kernel Service Bus (kernel_bus/__init__.py, el
paquete de donde viene todo esto), preservado porque documenta el
porqué de api/+services/+broker/:

Kernel Service Bus: protocolo genérico por el que una skill AISLADA
(corriendo dentro de un contenedor Docker efímero, sin red, sin
memoria compartida con el proceso principal) puede pedirle algo a un
servicio de confianza que vive en el proceso principal — sin nunca
importar código del kernel, sin nunca recibir una referencia a un
objeto Python real.

Por qué esto existe: 4 de las 6 herramientas de primera parte
(image_gen, image_editing, audio_gen, speech_to_text) cargan un modelo
pesado de forma perezosa (hasta 14GB) y lo mantienen caliente en
memoria entre llamadas — posible hoy porque viven en un proceso que
nunca muere. Una skill aislada corre en un contenedor EFÍMERO (uno
nuevo por llamada) — sin este bus, cada llamada de una skill que
necesite ese modelo tendría que recargarlo entero desde disco cada vez.

Analogía de diseño (no un patrón inventado para este proyecto): mismo
principio que LSP (Language Server Protocol, JSON-RPC sobre stdio) o
el extension host de VS Code — un proceso aislado habla con el host
SOLO por mensajes estructurados, nunca por memoria compartida.

Alcance actual (deliberado, no una limitación no revisada): un solo
servicio real, `image.generate` (más audio/STT/inpaint, agregados
después con el mismo patrón). Browser/OCR/Antivirus (mencionados en la
visión de plataforma) quedan documentados como extensión futura —
ninguno existe todavía como capacidad real en kal, construirles bus
ahora sería infraestructura sin demanda real.
"""
