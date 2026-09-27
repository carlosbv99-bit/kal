# Contribuir con Kal

🇬🇧 [English](CONTRIBUTING.md) | 🇪🇸 Español

> Este repo es **kal**, el microkernel de seguridad puro — sin agente,
> sin LLM, sin ML incluido. Todo lo que decide *qué hace un agente*
> (el loop de razonamiento, las herramientas concretas, la memoria)
> vive en [kal-in](https://github.com/carlosbv99-bit/kal-in), el
> agente de referencia de kal construido sobre este kernel — ver la
> nota al principio de [README.es.md](README.es.md).

## Contribuir código

1. Forkeá el repo y clonalo localmente.
2. Armá un virtualenv e instalá las dependencias:
   ```
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements-core.txt -r requirements-dev.txt
   ```
   Esa es toda la superficie de dependencias — sin librerías de ML,
   sin cliente de LLM, nada multimodal. Si tu cambio necesita algo más
   pesado que eso, casi seguro pertenece a kal-in, no acá.
3. Corré los tests:
   ```
   python -m pytest tests/ -q
   ```
   Es el mismo comando que corre la CI (367 tests hoy). Un puñado
   necesita Docker corriendo (`requires_docker` en `tests/conftest.py`)
   — esos se saltan solos automáticamente cuando no está disponible.
4. Lint (el mismo chequeo que aplica la CI — errores reales, no una
   opinión de estilo):
   ```
   python -m ruff check --select=E9,F .
   ```
5. Abrí un pull request contra `main`.

**Dónde vive cada cosa**, si no estás seguro dónde entra un cambio:
- `kernel/` — sandboxing, permisos, el registro de Skills, el Kernel
  Bus, el resource broker. Infraestructura de seguridad pura: sin LLM,
  sin ML, sin lógica de agente. Cero dependencia de nada específico de
  agente — es deliberado, mantenelo así (verificado con grep, no solo
  por convención: `import agent_core`/`import tool_integration` fallan
  acá con `ModuleNotFoundError`).
- `sdk/` — la API pública que importa una Skill (`Tool`,
  `ToolManifest`, `Artifact`, `Permission`, `call()`). 100% stdlib a
  propósito: este paquete se copia tal cual dentro del contenedor
  Docker de cada Skill (ver `kernel/registry/sandboxed_skill.py`), así
  que nunca puede ganar una dependencia que no esté ya dentro del
  contenedor.
- `audit/` — el log de auditoría con hash-chain, a prueba de
  alteraciones, donde escribe cada acción sensible del kernel.
- `code_analysis/` — validación estática a nivel AST de código de
  herramienta propuesto dinámicamente, antes de que llegue a un
  sandbox.
- `skills/` — un puñado de Skills de primera parte incluidas junto
  con el kernel (información del sistema, códigos QR, y envoltorios
  finos sobre Kernel Services para imagen/audio/descarga) — mayormente
  implementaciones de referencia y fixtures de tests de integración,
  no un catálogo de producto. El Skill Market real, en crecimiento,
  vive en kal-in.
- `tests/` — refleja el módulo que testea (`test_docker_runner_*.py`
  → `kernel/lifecycle/docker_runner.py`, etc.). Un test
  `requires_docker` necesita Docker corriendo y se saltea solo si no
  está.

Un PR que cambia comportamiento debería venir con un test que hubiera
fallado antes del cambio — `docs/HISTORY.md` de este repo es un
registro de bugs reales encontrados en uso real (la mayoría heredados
de la propia historia de kal-in antes del split, algunos encontrados
acá después), cada uno con el test que ahora lo cubre; ese es el
estándar que se espera de una contribución nueva, no cobertura del
100% por sí misma.

Si tu cambio es chico y bien acotado, buscá un issue etiquetado
**good first issue** — están elegidos para entenderse sin tener que
leer todo el código primero.

## Reportar un problema de seguridad

Este es un kernel de seguridad — si encontrás una forma de escapar
del sandbox, saltear un chequeo de permisos, o de cualquier otra
manera lograr que el kernel haga algo que se supone que impide, por
favor abrí un issue describiéndolo. Todavía no hay un canal de
divulgación privada dedicado al tamaño actual de este proyecto —
tratalo como un hueco conocido, no como un motivo para quedarte
callado.
