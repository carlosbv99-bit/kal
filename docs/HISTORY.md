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
