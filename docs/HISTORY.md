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
