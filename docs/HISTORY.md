# Historial de ingeniería de kal (kernel puro)

Este repo se extrajo de [kal-in](https://github.com/carlosbv99-bit/kal-in)
en septiembre de 2026 — kal-in es, hasta esa fecha, el mismo código
que este repo hoy llama "kal-in" con toda su historia previa. Para la
historia técnica completa de cómo se construyó el kernel (Access
Manager, sandbox, audit log, Kernel Service Bus, etc.) ANTES de esta
extracción, ver `docs/HISTORY.md` en kal-in — cada archivo movido acá
conserva su propio historial de commits (`git log --follow`), pero
este archivo específico empieza de cero: era una única bitácora
compartida entre kernel y agente, y no tenía sentido partirla línea
por línea entre los dos repos nuevos.

De acá en adelante, este archivo documenta solo cambios del kernel
puro — sin agente, sin LLM, sin ML.

---

## Extracción inicial desde kal-in (2026-09-13)

Motivo: kal-in (entonces solo "kal") era un híbrido kernel+agente. Se
confirmó por código (no solo por diseño) que `kernel/`+`sdk/`+`audit/`+
`code_analysis/`+`utils/` no dependen de `agent_core/`/`tool_integration/`
— la única dependencia real cruzada era `tool_integration/malware_scan.py`
(escaneo ClamAV para skills sandboxeadas, sin ninguna librería de ML,
solo `shutil`/`subprocess`/`tempfile`), movida acá a
`kernel/security/malware_scan.py`.

Extraído vía `git filter-repo` sobre un clon nuevo de kal-in (nunca
sobre el remoto compartido), preservando la historia de cada path
conservado: `kernel/`, `sdk/`, `audit/`, `code_analysis/`, `utils/`,
`config/`, `skills/`, `tests/`, y los scripts de firma/mercado de
skills (`scripts/sign_skill.py`, `scripts/enable_skill.py`,
`scripts/install_from_market.py`, `scripts/generate_market_page.py`,
`scripts/validate_skills.py`, `scripts/verify_sandbox.sh`,
`scripts/build_sandbox_image.sh`).

Se descartaron ~79 archivos de test que solo tenían sentido para el
agente (`agent_core.*`, `tool_integration.adapters.*`) — incluyendo 8
que "pasaban" por accidente en la suite completa de kal-in: usaban
`pytest.importorskip("diffusers"/"piper"/etc.)` ANTES de importar el
módulo de agente real, así que sin esas librerías de ML instaladas
nunca llegaban a ejecutar la línea que habría fallado con
`ModuleNotFoundError`. Confirmado corriendo la suite en un venv nuevo,
sin esas librerías: 367 tests, todos genuinamente pasando (0 skips),
donde antes de sacarlos había 10 skips enmascarando ese problema.

`requirements-core.txt` se recortó a lo que el kernel realmente usa
(verificado con grep, no supuesto) — se sacaron `chromadb`/`sqlalchemy`
(memoria del agente), `Pillow`/`tenacity`/`structlog`/`python-multipart`
(sin un solo uso real en `kernel/`/`sdk/`/`audit/`/`utils/`/
`code_analysis/`/`scripts/`). Verificado con un venv limpio instalando
solo la lista recortada: 367/367 tests pasan igual.

Agregado `pyproject.toml` (paquete `kal`, instalable en modo editable)
— verificado con `pip install -e .` desde un venv nuevo e import
exitoso desde fuera del directorio del repo.

`docs/HISTORY.md` y `README.md` reescritos desde cero (ver nota al
principio de este archivo); `.gitignore` nuevo.

## Limpieza de `utils/config.py`/`config/config.yaml`: capacidades de agente removidas del kernel (2026-09-27)

Pregunta directa del usuario al revisar el repo recién extraído: ¿es
correcto que las capacidades de audio/video estén en el kernel, o
deberían estar en kal-in? La extracción inicial (arriba, 2026-09-13)
ya había recortado `requirements-*.txt` a lo que el kernel realmente
usa, pero **nunca se hizo el mismo ejercicio con el esquema de
config** — `utils/config.py`/`config/config.yaml` seguían siendo una
copia literal, sin editar, de la config completa de kal-in.

Verificado con grep real (no supuesto) qué secciones de `Settings`
consulta de verdad algo en `kernel/`/`sdk/`/`audit/`/`code_analysis/`/
`scripts/`: solo `sandbox`, `tool_integration`, `permissions`,
`filesystem_access`, `resource_broker`, `downloads`, `browser`,
`signing`. Cero usos de `llm`, `memory`, `multimodal` (imagen/audio/
video/STT/visión/edición/composición/uploads), `conversation_engine`,
`context`, `text_files`, `agent`, `runtimes`, `error_handling`,
`self_modification` — todas estas son configuración de kal-in (el
agente), nunca del kernel. `self_modification` en particular es un
caso límite interesante: el kernel sí tiene un mecanismo real
relacionado (`kernel/lifecycle/selfmod_test_image_builder.py`, la
imagen Docker para correr tests de una auto-modificación propuesta,
más el vocabulario de eventos de auditoría en `audit/audit_log.py`),
pero la DECISIÓN de si una auto-modificación se permite
(`SelfModificationConfig.enabled/scope/is_core_path()`) es pura lógica
de agente (`agent_core/self_modification.py`/`agent_core/orchestrator.py`
en kal-in) — el kernel ofrece el primitivo aislado, no decide cuándo
usarlo.

Eliminadas de `utils/config.py`: `LLMConfig`, `RuntimeSlotConfig`,
`RuntimesConfig`, `ShortTermConfig`, `MidTermConfig`, `PromotionConfig`,
`LongTermConfig`, `MemoryConfig`, `ErrorHandlingConfig`,
`ImageGenConfig`, `AudioGenConfig`, `VideoGenConfig`, `STTConfig`,
`VisionConfig`, `ImageEditingConfig`, `ImageCompositionConfig`,
`UploadsConfig`, `MultimodalConfig`, `ConversationEngineConfig`,
`SelfModificationConfig`, `TextFileConfig`, `AgentConfig`,
`ContextConfig` — y los campos correspondientes de `Settings`. Mismo
recorte aplicado a `config/config.yaml` (las secciones `llm`,
`runtimes`, `memory`, `error_handling`, `multimodal`,
`conversation_engine`, `context`, `self_modification`, `text_files`,
`agent` ya no existen ahí). De paso, se corrigieron comentarios/
docstrings que referenciaban rutas de kal-in que no existen en este
repo (`tool_integration/services.py`, `agent_core/orchestrator.py`,
etc.) para que no confundan a quien lea este repo de forma aislada.

Verificado: `settings = load_settings()` carga sin error contra el
`config.yaml` recortado; `ruff check --select=E9,F .` (el chequeo real
de CI) y `ruff check utils/config.py config/` (regla completa, solo en
los archivos tocados) pasan limpio; suite completa sin cambios,
367/367 passed — nada en `kernel/`/`sdk/`/`audit/`/`code_analysis/`/
`scripts/`/`tests/` dependía de ninguno de estos campos, confirmando
que era puro resto sin terminar de limpiar de la extracción inicial,
no una dependencia real oculta.

Nota aparte, no corregida en esta sesión (fuera de alcance de esta
pregunta puntual): este repo recién clonado nunca pasó por un
`ruff check .` de regla completa (solo el `--select=E9,F` angosto de
CI) — a diferencia de kal-in, que sí tuvo ese pase (ver
`docs/HISTORY.md` de kal-in, 2026-09-27). Queda pendiente como parte
de la auditoría externa de este repo todavía sin hacer.

## Revisión y limpieza completa para una auditoría externa (2026-09-27)

Mismo pase que ya se le hizo a kal-in: lint completo, triage de
seguridad, `CONTRIBUTING.md`, `pip-audit`, revisión de docs — con un
hallazgo real y grave en el medio.

**Vulnerabilidad real encontrada y corregida — `kernel/lifecycle/docker_runner.py`
estaba desactualizado respecto a kal-in en DOS fixes de seguridad
reales**, porque este repo se extrajo (2026-09-13) antes de que
existieran:
- **kal-in issue #4 (2026-09-21)**: `containers.run()` dispara un pull
  IMPLÍCITO de la imagen si no está cacheada — sin red (o con red
  caída a mitad de pull), esa llamada podía colgar SIN NINGÚN
  timeout propio; `container.wait(timeout=...)` solo acota la espera
  de un contenedor que YA arrancó, nunca esta llamada. Confirmado en
  un entorno real de Likay-OS sin red: varios minutos sin respuesta ni
  error visible. Este repo todavía tenía la versión SIN el fix — el
  mismo hueco, sin corregir, desde la extracción.
- **K-2, auditoría externa Likay-OS (2026-09-26)**: `_collect_output_files()`
  usaba `p.is_file()` (sigue symlinks) + `rglob("*")` sin restricción
  sobre el bind mount de salida — escribible por el código NO
  CONFIABLE que corre dentro del contenedor. Ese código podía crear un
  symlink apuntando a cualquier archivo del HOST (una clave de firma,
  un token, `/proc/self/environ`) y el proceso host lo seguía sin
  darse cuenta: **lectura arbitraria de archivos del host por un
  agente hostil**, explotable de verdad en este repo hasta ahora.

Portados ambos fixes completos desde el `origin/main` actual de
kal-in (incluida una tercera mejora, encontrada y corregida en la
sesión de auditoría de kal-in de hoy mismo: el thread de fondo de
`containers.run()` puede completar DESPUÉS de que ya se devolvió el
timeout, dejando un contenedor huérfano sin quien lo mate/remueva —
ahora se limpia vía `future.add_done_callback()`), junto con sus 7
tests de regresión (`tests/test_docker_runner_pull_timeout.py`,
`tests/test_docker_runner_output_collection.py`, antes inexistentes
acá). Los 12 tests de `docker_runner.py` pasan, incluido el que corre
contra Docker real.

**Lint amplio (`ruff check .`) — de 87 hallazgos a 0**: 74
auto-corregibles (mismas categorías que kal-in: imports desordenados,
`noqa` obsoletos, modernización de tipos), 13 triados a mano —
6 `BLE001` (todos fail-open/fail-safe ya deliberados, documentados con
`# noqa` + motivo, sin cambio de comportamiento), 2 `PLW1510`
(`check=False` explícito, el returncode ya se interpretaba a mano),
1 `RUF015`, 2 `C408` mecánicos. Mismos archivos, casi línea por línea,
que los ya triados en kal-in — tiene sentido: son las mismas skills y
la misma infraestructura de market, copiadas en el split.

**Bug real de firmas, y una pérdida real de una clave privada**: el
`ruff --fix` de arriba tocó los 7 `skills/*/tool.py` (reordenamiento
de imports) — mismo bug que ya se había encontrado en kal-in hoy: sin
volver a firmar, `validate_all_skills()` reportaba las 7 con "firma
tampered". Al intentar re-firmar con la MISMA identidad de siempre
(`data/keys/kal_project/` para 6, `data/keys/` para
`download_via_kernel`), se confirmó que esas claves privadas ya no
existen en ningún lado accesible: vivían solo en el directorio de
trabajo que se reemplazó por el clon fresco de este mismo repo, más
temprano en esta sesión (ver la sección de arriba) — un archivo
untracked/gitignored no sobrevive ese reemplazo, a diferencia del
propio historial de git. Impacto real, acotado: ninguna firma YA
hecha se invalida (la verificación solo necesita la clave PÚBLICA, que
queda embebida en cada `skill.sig` ya commiteado) — el único costo es
que estas 7 skills no pueden re-firmarse bajo la misma identidad de
autor de acá en más. Con confirmación del usuario, se generaron
keypairs nuevas (mismos dos `--key-dir` de siempre, para mantener la
misma separación organizativa) y se re-firmaron las 7; `validate_all_skills()`
vuelve a devolver `[]`.

**`CONTRIBUTING.md`/`CONTRIBUTING.es.md` — no existían, creados desde
cero** (a diferencia de kal-in, que solo estaban desactualizados).
Mismo formato/estructura que los de kal-in, pero con la sección "Dónde
vive cada cosa" recortada a lo que este repo realmente tiene
(`kernel/`, `sdk/`, `audit/`, `code_analysis/`, `skills/`, `tests/` —
sin `agent_core/`/`tool_integration/`, que no existen acá). Enlazados
desde README.md/README.es.md ("Get involved"/"Cómo colaborar"), que no
los mencionaban.

**`pip-audit` agregado a CI** — corrido en vivo antes de agregarlo:
"No known vulnerabilities found" contra `requirements-core.txt` +
`requirements-dev.txt` (el dependency set chico del kernel puro ayuda
acá — sin chromadb ni el resto del stack ML de kal-in). No bloqueante,
mismo criterio que kal-in: para que una vulnerabilidad nueva no pase
desapercibida, sin bloquear el build por una sin fix disponible.

**Decisiones tomadas sin cambio de código, documentadas**:
- Sin script de empaquetado tipo `create_package.py` (el de kal-in):
  este repo pesa 2.5MB sin `.venv`/`.git`, no tiene `.env`, no tiene
  `node_modules` ni ningún directorio pesado que excluir — `git
  archive` alcanza tal cual para entregárselo a un auditor externo.
  Construir un script dedicado acá sería una abstracción sin un
  problema real que resolver.
- Dependencias con rangos abiertos (`>=`) en `requirements-*.txt`,
  nunca versiones exactas — mismo patrón y misma decisión ya tomada en
  kal-in: pinnear es un cambio de política más grande, con riesgo real
  de romper algo, fuera de alcance de esta limpieza.
- Sin `.env` en el historial de git (confirmado, este repo nunca tuvo
  uno para empezar — no hay claves de proveedores en un kernel sin
  LLM).

Suite completa corrida después de todos los cambios (docker_runner.py,
socket_server.py, skill_market.py, skills.py, malware_scan.py,
generate_market_page.py, validate_skills.py) — ver el commit para el
resultado exacto.

## 4 vulnerabilidades reales más, encontradas construyendo un chequeo de drift (2026-09-27)

Al construir (en kal-in) un chequeo automático que compara la copia
embebida del kernel en kal-in contra el estado real de este repo —
para acortar el tipo de ventana que dejó pasar el hallazgo de
`docker_runner.py` de la sección anterior — el chequeo encontró
inmediatamente que faltaban 4 fixes MÁS de la misma auditoría externa
("5 vulnerabilidades reales de kernel/sandbox", Likay-OS 2026-09-26),
nunca portados a este repo:

- **K-1**: `manifest.name` de una skill (`skill.yaml`) se usaba SIN
  sanitizar para armar `SandboxedSkillTool.artifact_dir` — un `name`
  tipo `"../../../../.venv/lib/pythonX.Y/site-packages"` permitía
  crear directorios FUERA de `data/artifacts/skills/`, path traversal
  que combinado con una escritura posterior ahí es RCE diferido al
  próximo arranque del intérprete. Corregido en dos capas:
  `kernel/registry/skills.py::load_skills()` rechaza el nombre
  temprano (nunca activa la skill), `SandboxedSkillTool.__init__`
  valida de nuevo por si algún otro llamador la instancia directo.
- **K-4**: la cascada de permisos (`PermissionCascade`, "más
  restrictivo gana") solo se aplicaba en el LLAMADOR
  (`agent_loop.py`, que no existe en este repo) — el kernel mismo
  nunca la exigía, así que cualquier otro consumidor de
  `SandboxedSkillTool` heredaba cero cascada. Ahora
  `SandboxedSkillTool.execute()` la exige directamente, tier `skill`
  hardcodeado (estructuralmente siempre ese tier, no hace falta
  preguntarle a `trust_tier_for()`).
- **K-5**: la firma de una skill solo se verificaba UNA VEZ, al cargar
  (tiempo de arranque) — pero el contenido de `skills/<x>/` se relee
  del disco en CADA `execute()` posterior. Quien pudiera escribir ahí
  entre la carga y una ejecución posterior (el proceso no tiene por
  qué reiniciarse) corría código nunca verificado, mientras la
  auditoría seguía diciendo "verified". Ahora se re-verifica en cada
  `execute()`, fresco contra el disco real.
- **K-6**: mismo patrón que K-1 pero para el NOMBRE de una herramienta
  dinámica propuesta por el agente (`ToolRegistry.propose_dynamic_tool()`),
  usado sin sanitizar en `ToolVersionStore._tool_dir()`. Corregido en
  dos capas igual que K-1: `registry.py` rechaza temprano,
  `versioning.py::_tool_dir()` valida de nuevo para cualquier otro
  llamador de esa clase.

Los 4 fixes + sus tests de regresión se portaron completos desde el
`origin/main` actual de kal-in (`kernel/registry/registry.py`,
`sandboxed_skill.py`, `skills.py`, `versioning.py` + los 4 archivos de
test correspondientes), con un solo ajuste real: la ruta de
`malware_scan` se mantuvo en `kernel/security/malware_scan.py` (la
ubicación correcta en este repo) en vez de
`tool_integration/malware_scan.py` (kal-in todavía no reorganizó ese
módulo hacia el kernel — ver el hallazgo de "FALTA en kal-in" más
abajo). Suite completa: 383 passed, 0 failed.

**Corrección importante sobre el hallazgo anterior**: la sección previa
de este mismo archivo dio a entender que "kal está al día" tras portar
el fix de `docker_runner.py` — eso fue incompleto. Solo se revisó ese
archivo puntual (el que motivó la sesión), nunca un diff sistemático
del resto de `kernel/`. Este chequeo de drift es, en parte, la
corrección de ese proceso: de acá en más, un fix real que no se porta
se detecta solo, no depende de que alguien piense en revisarlo a mano.

**Hallazgo aparte, sin resolver todavía — decisión pendiente, no un
bug**: el chequeo también reporta que `kernel/security/malware_scan.py`
(y su `__init__.py`) no tienen equivalente en kal-in, porque ahí ese
mismo módulo todavía vive en `tool_integration/malware_scan.py`. No es
una vulnerabilidad — ambos repos escanean malware igual — es una
diferencia de organización que kal-in arrastra de antes del split.
Migrar `tool_integration/malware_scan.py` a `kernel/` en kal-in es un
cambio real (mover el módulo, actualizar sus imports) que no se hizo
en esta sesión — decisión del usuario, ver conversación.
