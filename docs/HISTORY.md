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

**Hallazgo aparte, resuelto en esta misma sesión**: el chequeo también
reportó que `kernel/security/malware_scan.py` (y su `__init__.py`) no
tenían equivalente en kal-in, porque ahí ese mismo módulo todavía vivía
en `tool_integration/malware_scan.py`. No era una vulnerabilidad —
ambos repos escaneaban malware igual — era una diferencia de
organización que kal-in arrastraba de antes del split. Con
confirmación del usuario, se migró en kal-in (`git mv` + imports
actualizados) — ver `docs/HISTORY.md` de kal-in para el detalle.

## Auditoría externa completa de kal-in aplicada a kal: 3 hallazgos más, todos reales (2026-09-27)

Al revisar el contenido de la carpeta vieja de kal-in (pedido del
usuario: "mira los dos pendientes"), apareció `docs/SECURITY-AUDIT-2026-09-26.md`
— una auditoría de seguridad externa completa (5 críticos + 10 altos +
12 medios + 6 bajos) que nunca se había mencionado en esta sesión hasta
ahora. La mayoría de los hallazgos son específicos de kal-in (agente,
LLM, memoria, frontend, extensión VS Code) y no aplican acá — pero
varios SÍ son del kernel puro, y kal los tenía sin corregir porque este
repo se extrajo antes de que existiera esa auditoría:

- **A-1 (relacionado a K-2)**: `kernel/registry/sandboxed_skill.py::_collect_skill_files()`
  usaba `path.is_file()` (sigue symlinks) sobre `rglob("*")` — mismo
  patrón que K-2 en `docker_runner.py`, pero del lado de ENTRADA: un
  symlink dentro de `skills/<x>/` apuntando a un archivo del HOST
  (una clave de firma, `.env`, `/etc/passwd`) hacía que el proceso
  HOST lo leyera y lo empaquetara en `workspace_files` — exfiltrable
  si la skill declara `Permission.NETWORK`. Mismo fix en dos capas que
  K-2: `os.lstat` + descartar no-regulares + chequeo de que la ruta
  real resuelva dentro de `skill_dir`. 2 tests nuevos (symlink a
  archivo, symlink a subdirectorio — Python ≥3.13 sigue symlinks a
  directorios en `rglob`).
- **C-3 (CRÍTICO en el informe original)**: `kernel/api/sandbox_api.py::/execute`
  ejecutaba código arbitrario SIN NINGUNA autenticación, alcanzable
  desde cualquier proceso en la misma red que `sandbox_runner` — el
  único freno era el denylist AST (heurístico, no exhaustivo, por su
  propio docstring) más el aislamiento de Docker. Fix: token
  compartido vía header (`SANDBOX_API_TOKEN` en el entorno,
  `secrets.compare_digest` comparado como BYTES — ver M-6 del mismo
  informe: comparar como `str` no-ASCII lanza `TypeError` sin atrapar,
  un 500 alcanzable sin auth) + límite de tamaño de body (1 MiB,
  rechazado por `Content-Length` antes de que Pydantic lea el body
  completo). Fail-closed: sin `SANDBOX_API_TOKEN` configurado, TODO
  pedido se rechaza. Primer test de este archivo en todo el repo (7
  tests nuevos) — hizo falta agregar `httpx2` a `requirements-dev.txt`
  (requerido por `fastapi.testclient.TestClient`, mismo paquete que ya
  usa kal-in).
- **A-10 #2**: `audit/audit_log.py::_read_last_hash()` hacía
  `json.loads()` sobre la última línea SIN try/except — una línea
  corrupta (escritura parcial por un crash/`kill -9` a mitad de
  `record()`, el propio docstring de la clase documenta múltiples
  escritores concurrentes) hacía que ESA excepción se propagara sin
  atrapar, y TODO evento posterior fallaba igual: el sistema quedaba
  SIN auditoría de ahí en más, silenciosamente. Mismo patrón encontrado
  además en `tail()` y `diagnose_chain()` (ninguno de los dos estaba
  en el informe original, pero comparten la misma causa) — las tres
  funciones ahora atrapan `JSONDecodeError`, loguean fuerte con la
  línea cruda, y siguen funcionando (nueva cadena a partir de la
  corrupción, en vez de romperse por completo). 3 tests nuevos.

**Hallazgo propio, no del informe — "footgun latente" que el informe sí
mencionó de pasada para A-1** ("`_prepare_workdir`/`output_dir` aceptan
claves con `../` sin normalizar"): agregado `DockerSandboxRunner._join_within()`,
un helper compartido que rechaza cualquier `workspace_files`/`output_dir`
que resuelva fuera del workdir temporal. Hoy ningún llamador real pasa
input no confiable acá (rutas fijas de primera parte), así que no era
explotable in situ — pero es exactamente el tipo de defensa en
profundidad que ya se aplicó en K-1/K-6 de sesiones anteriores. 5 tests
nuevos.

**M-9 (dependencias)**: ambos workflows de CI (`ci.yml`,
`validate-skills.yml`) pineaban `actions/checkout`/`actions/setup-python`
por tag mutable (`@v4`/`@v5`) en vez de SHA — corregido, SHAs
verificados con `git ls-remote` contra los tags reales (`v4.4.0`,
`v5.6.0` — casualmente los mismos que Likay-OS ya había verificado en
su propia re-auditoría). Además, `requirements-core.txt`/`requirements-dev.txt`
pasaron de rangos abiertos (`>=`) a versiones EXACTAS — pineadas a lo
que ya estaba instalado y ya verificado contra la suite completa en
este mismo cambio (cero riesgo de comportamiento nuevo). De paso,
sacado `pydantic-settings`: nunca se usó en ningún módulo del kernel
(verificado con grep) — `utils/config.py` usa `pydantic.BaseModel`
puro, dead weight desde la extracción inicial.

Verificado con un venv completamente nuevo instalando SOLO las
versiones exactas recién pineadas: 400 tests passed (383 anteriores +
17 nuevos), 0 failed. `ruff check .` (regla completa) limpio.

**Un hallazgo más, revisado aparte por tocar un DEFAULT de config
compartido**: A-5 ("la cascada de permisos es un no-op para casi todo
el toolset real") — verificado que en kal específicamente el ÚNICO
llamador real de `missing_permissions()` es el de tier "skill" (el fix
de K-4 de hoy mismo); no hay ningún llamador para tier "system"/"agent"
dentro de este repo (esa decisión vive en `agent_loop.py`, que no
existe acá). Pero `trust_tier_caps.system` sí incluye los 9 permisos
por diseño (documentado así desde la extracción), lo que hace que
`globally_denied` sea la ÚNICA capa real de contención para ese tier —
y estaba vacío por defecto. Corregido en `config/config.yaml`:
`docker`/`clipboard`/`camera`/`microphone` denegados globalmente por
defecto (los 4 de mayor impacto de un abuso silencioso, sin motor de
enforcement propio más allá de esta cascada — ver
`RUNTIME_ENFORCED` en `sdk/permissions.py`). `network`/
`filesystem_write`/`gpu`/`browser` quedan fuera a propósito: tienen
casos de uso legítimos frecuentes y ya están acotados por
`trust_tier_caps` según nivel de confianza. Test nuevo que ancla este
default contra la config REAL (no un fake), para que no se vuelva a
vaciar sin que alguien note el motivo. Suite completa: 401 passed
(1 test de `test_kernel_bus_socket_server.py` resultó flaky en una
corrida — no relacionado, confirmado pasando 3/3 en aislamiento y en
una segunda corrida completa limpia), 0 failed.

**Un último hallazgo (B-4, BAJO en el informe original, pero
kernel/api/socket_server.py SÍ es de este repo)**: `_read_line()` hacía
`line.decode("utf-8")` sin try/except — bytes que no son UTF-8 válido
(una skill con un bug propio, o a propósito) hacían que
`UnicodeDecodeError` matara el THREAD ENTERO de `_serve()`, no solo esa
conexión puntual: el resto de la sesión de esa skill con el Kernel
Service Bus quedaba inutilizable (`ECONNREFUSED` en cualquier pedido
siguiente), aunque `max_requests` todavía tuviera cupo. Mismo patrón ya
establecido para `LineTooLongError`: nueva excepción propia
(`InvalidEncodingError`), auditada (`kernel_invalid_encoding`), la
conexión se corta pero el thread sigue vivo para las siguientes. 2
tests nuevos (unit test directo de `_read_line`, más uno de punta a
punta con un socket Unix real confirmando que una skill hostil no
puede tumbar el resto de su propia sesión). Suite completa: 403
passed, 0 failed.

Con esto, se agotaron los hallazgos de `docs/SECURITY-AUDIT-2026-09-26.md`
que aplican al kernel puro (`kernel/`, `sdk/`, `audit/`,
`code_analysis/`) — el resto (C-1/C-2/C-4/C-5, A-2/A-3/A-4/A-6/A-7/
A-8/A-9, la mayoría de los M-*/B-*) son de `agent_core/`,
`tool_integration/`, `frontend/` o la extensión de VS Code, ninguno de
los cuales existe en este repo. **Aceptado, no resuelto, decisión
consciente de alcance**: M-12 (el hash-chain del log de auditoría es
SHA-256 sin clave — íntegro contra errores/carreras, no auténtico
contra quien pueda escribir el archivo) pide firmarlo con HMAC, lo que
implica decidir una estrategia de gestión de esa clave nueva (dónde
vive, cómo se rota) — un cambio de diseño real, no una corrección
mecánica, que queda para una decisión explícita aparte.

## Segunda auditoría externa, independiente — 4 hallazgos más, 3 en fixes de HOY MISMO (2026-09-27)

**Corrección importante sobre la sección anterior**: "se agotaron los
hallazgos que aplican al kernel puro" era una conclusión apurada. El
usuario trajo `docs/AUDITORIA-SEGURIDAD-2026-09-27.md`, una auditoría
externa completamente independiente de todo lo de arriba — con
verificación empírica (PoC ejecutados, no solo lectura) — y encontró
1 alto, 8 medios y 9 bajos. Antes de tocar código, se verificó cada
hallazgo relevante contra el repo real (reproducción propia, no
confianza ciega en el informe): los 5 que se intentaron reproducir
(A-1, M-1, M-2, M-3, M-6) se confirmaron exactamente como se
describen. Se corrigieron los 4 primeros en esta sesión:

- **A-1 (ALTA)**: `scripts/install_from_market.py` nunca validaba
  `args.skill_name` (input de línea de comandos) — mismo patrón EXACTO
  que K-1/K-6, esta vez en el instalador de market en vez de en el
  registry. PoC propio reproducido: sin el fix, `--skill-name
  "../.audit_pwned"` escribe y HABILITA una skill fuera de `skills/`.
  Fix: `validate_skill_name()` (renombrada, pública — antes
  `_validate_skill_name()`, mismo criterio que `is_valid_tool_name` en
  versioning.py: una sola fuente de verdad para dos llamadores) +
  segunda capa de contención antes de `copytree`. 2 tests nuevos.
- **M-1**: `DynamicSandboxedTool.execute()` (tier "agent") nunca
  consultaba la cascada de permisos — a diferencia de
  `SandboxedSkillTool.execute()` (tier "skill", K-4, arreglado
  hoy más temprano en ESTA MISMA sesión). Reparé solo la mitad
  del problema en K-4: el otro wrapper que existe en el mismo
  archivo se quedó sin el chequeo. `globally_denied` documentado
  como "pase lo que pase" era falso para herramientas dinámicas
  hasta este fix. 2 tests nuevos.
- **M-2**: el middleware de tamaño de body de `sandbox_api.py`
  (agregado HOY MISMO como parte del fix de C-3) crasheaba con
  `ValueError` sin atrapar ante un `Content-Length` no numérico —
  alcanzable ANTES de la autenticación, por cualquiera que llegue al
  puerto. Corregido con `try/except`; también se corrigió el
  docstring, que daba a entender (incorrectamente) que este
  middleware corre después de la autenticación. 2 tests nuevos — uno
  de ellos ancla explícitamente contra la regresión que casi se
  introduce al arreglar esto (un `return` mal ubicado habría rechazado
  TODO pedido con `Content-Length` presente, incluidos los legítimos;
  se detectó corriendo los tests existentes antes de dar el fix por
  terminado).
- **M-3**: `diagnose_chain()` (agregado HOY MISMO como parte del fix de
  A-10 #2) atrapaba `JSONDecodeError` pero no `KeyError` — una línea
  que ES JSON válido pero le faltan las claves esperadas seguía
  reventando exactamente la herramienta que un humano usaría para
  investigar una manipulación del log. `tail()` no necesitó el mismo
  fix: nunca accede a claves específicas, solo devuelve el dict tal
  cual. 1 test nuevo.

**Lección explícita**: 3 de los 4 hallazgos corregidos son gaps en
código que esta misma sesión escribió HOY, no deuda técnica vieja —
un caso borde no testeado (Content-Length no numérico), una simetría
rota (arreglar un wrapper y no el otro), y un catch demasiado angosto
(JSONDecodeError sin KeyError). Ninguno se habría encontrado con más
tests "obvios" — hizo falta una segunda revisión independiente,
adversarial, con PoCs reales. Suite completa: 410 passed, 0 failed.
`ruff check .` limpio.

## Segunda auditoría externa, continuación — M-4/M-5/M-7/M-8 (2026-09-27/28)

Siguiendo el mismo informe (`docs/AUDITORIA-SEGURIDAD-2026-09-27.md`),
se corrigieron los 4 hallazgos MEDIOS que quedaban pendientes.

- **M-4**: `_load_persisted_grants()` (`kernel/permissions/access_manager.py`)
  hacía `json.loads()` sin try/except — un archivo de grants corrupto
  (disco lleno a mitad de escritura) inutilizaba el motor de decisión
  ENTERO, no solo el grant afectado. Fail-safe: ante cualquier problema
  de lectura/parseo se trata como "sin grants persistidos" (la
  dirección segura — sin grants, `evaluate()` cae a
  `requires_approval`, nunca a `auto_allowed`), y un grant individual
  con forma inválida se descarta solo a él. Además: `data/keys/`
  (claves de firma, token admin, grants persistidos) quedaba con lo
  que diera el umask del proceso — **verificado en este entorno real:
  0775, escribible por grupo** — cualquier otro usuario del mismo
  grupo podía reemplazar una clave privada o escribir sus propios
  grants (incluido uno con `resource_key: null`, que autoriza
  CUALQUIER recurso). Nuevo helper compartido
  `utils/secure_dir.py::ensure_private_dir()` (fuerza 0700, sea que el
  directorio se acabe de crear o ya existiera de una instalación
  anterior) aplicado en `signing.py`, `skill_signing.py`,
  `access_manager.py`, `audit_log.py` (`logs/`) y `admin_token.py` — 5
  módulos que creaban directorios sensibles sin este chequeo. 12 tests
  nuevos.
- **M-5**: `extra_mounts` (`docker_runner.py`) montaba `host_path` ->
  `container_path` sin ninguna validación — a diferencia de
  `workspace_files`/`output_dir`, que ya usan `_join_within()` desde
  la limpieza anterior. Nuevo `_validate_extra_mounts()`: `host_path`
  debe ser absoluto y existir de verdad, `container_path` debe estar
  confinado a `/workspace/`. Verificado que el único llamador real
  (el socket del Kernel Service Bus en `sandboxed_skill.py`) sigue
  funcionando con Docker real (6/6 tests end-to-end). **Confirmado en
  vivo, sin el fix**: montar `/etc` como `extra_mounts` funcionaba de
  verdad contra Docker real (el test que lo prueba falla con
  `'success' == 'error'` al revertir el fix, no con un error de
  Docker). 7 tests nuevos.
- **M-7**: `kernel/lifecycle/Dockerfile` creaba el usuario `sandbox`
  pero nunca lo activaba (`USER sandbox` ausente) — el único servicio
  con acceso al socket de Docker del host corría como root. **Bug real
  encontrado verificando el fix**: agregar solo `USER sandbox` sin más
  rompía el servicio por completo (`/app` quedaba `root:root` por los
  `COPY` previos, `utils/logger.py` crea `logs/` al importarse y
  fallaba con `PermissionError`) — confirmado construyendo la imagen
  de verdad y corriéndola. Fix completo: `chown -R sandbox:sandbox
  /app` antes de `USER sandbox`. Verificado de punta a punta con un
  build y `docker run` reales: `whoami` → `sandbox`, `GET /health` →
  200. De paso, el `pip install` ad-hoc y sin pinear (`docker fastapi
  "uvicorn[standard]"`) se reemplazó por `COPY requirements-core.txt`
  + instalar desde ahí — una sola fuente de verdad con el resto del
  proyecto (mismo espíritu que M-9), en vez de una lista paralela que
  podía desalinearse. Sin test de pytest (es un Dockerfile, no código
  Python) — verificación fue build+run reales, documentada acá.
- **M-8**: el mensaje "Firma: verificada (el paquete no cambió desde
  que **su autor** lo firmó)" (`install_from_market.py`,
  `enable_skill.py`) implica que se verificó LA IDENTIDAD del autor —
  falso: "verified" solo prueba que el contenido no cambió desde que
  ALGUIEN (cualquiera puede generar su propio keypair) lo firmó con
  ESA clave. Nuevo `signer_fingerprint()` en `skill_signing.py` + los
  dos scripts ahora muestran el fingerprint y aclaran explícitamente
  que la firma NO confirma autoría — un humano puede comparar ese
  fingerprint contra lo que el autor real haya publicado en otro
  canal. Mismo ajuste en la tagline de `generate_market_page.py`. 4
  tests nuevos, incluido uno que reproduce el escenario exacto de A-1
  (re-firmar con una clave de atacante da "verified" igual, pero el
  fingerprint expuesto permite notar que cambió).

Suite completa: 430 passed, 0 failed. `ruff check .` limpio (excluido
`audio_controls.py` en la raíz del repo — código Qt no relacionado con
este proyecto, sintaxis inválida, no es parte de este trabajo).

Quedan del mismo informe, sin empezar: M-6 (verificado: `is_unsafe_ip`
es código muerto, cero llamadores reales — decisión pendiente: usarlo
o documentar el gap), y B-1 a B-10 (todos BAJOS).
