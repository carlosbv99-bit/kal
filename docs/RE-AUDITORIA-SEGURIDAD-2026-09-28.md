# Re-auditoría de seguridad — kal (kernel puro)

**Fecha:** 2026-09-28
**Alcance:** verificación de los 3 commits de remediación
(`b7de7f0`, `7e89e0a`, `9755f2a`) contra los 19 hallazgos de
`docs/AUDITORIA-SEGURIDAD-2026-09-27.md` (1 alto, 8 medios, 10 bajos),
más revisión del código nuevo introducido por esos fixes.

> **Corrección de mi propio informe anterior:** su resumen ejecutivo
> decía "1 alto, 8 medios y 9 bajos" — eran **10 bajos** (B-1 a B-10),
> 19 en total, como en la tabla detallada de ese mismo documento. El
> error fue solo del resumen.
**Método:** el mismo de la primera ronda — leer el diff completo, correr
la suite, y **re-ejecutar cada PoC** además de atacar el código nuevo.
Cada afirmación marcada ✅ está respaldada por un comando que corrí en
este entorno.

---

## 1. Veredicto

La respuesta a la auditoría fue **seria y de buena calidad**: de los 19
hallazgos, **14 quedaron cerrados de verdad** (con test de regresión y,
en los casos importantes, con verificación contra Docker real), 3
quedaron **parciales**, 1 se **difirió con justificación**, 1 se
**aceptó y documentó**, y 1 (M-8) se cerró en la parte que importa.

El nivel de la remediación es alto y en dos puntos notable:

- **M-7 verificado por mí con un build y ejecución reales**: la imagen
  compila, corre como `sandbox` (uid 999) y la app importa. El bug que
  encontraron *al verificar su propio fix* (`USER sandbox` sin `chown`
  rompía el arranque) es exactamente el tipo de rigor que se pide.
- **La crítica de proceso de la ronda anterior fue atendida**: los tests
  nuevos de M-1 ya no prueban la función pura, ejecutan
  `DynamicSandboxedTool.execute()` y afirman que el sandbox **nunca se
  llama**. Ese test está bien escrito (parchea el nombre en el namespace
  correcto).

Pero **el patrón que señalé como debilidad estructural reapareció dentro
de esta misma remediación**, y esta vez en el hallazgo que *trataba sobre
ese patrón*: B-1 se corrigió solo para `builtins`, sin barrer los módulos
hermanos (`posix`, `_socket`, `_io`, `pty`, `platform`) ni la variante
`__builtins__['eval']`. Y **M-5 introdujo un control que no hace lo que
su propio docstring y `docs/HISTORY.md` afirman**: verifiqué con Docker
real que se puede evadir y escribir en un directorio del host.

**Hallazgos nuevos: 1 medio, 4 bajos.** Ninguno es una vulnerabilidad
explotable sin un llamador que hoy no existe en el repo; el medio es un
control de seguridad que no controla.

---

## 2. Estado de los 19 hallazgos anteriores

| ID | Sev origen | Estado | Verificación mía |
|----|-----------|--------|------------------|
| **A-1** path traversal en instalador | Alta | ✅ **Cerrado** | `../.audit_pwned`, `/tmp/x`, `nested/deep`, `UPPER`, 65 chars → rechazados por CLI; segunda capa de contención presente; 2 tests nuevos |
| **M-1** cascada no aplicada a tools dinámicas | Media | ✅ **Cerrado** | ✅ Con `network` en `globally_denied`: `network_mode=None`, artefacto de error, sandbox no invocado |
| **M-2** `Content-Length` no numérico | Media | ✅ **Cerrado** | ✅ `not-a-number` → 400; `999999999` → 413; `10` → pasa |
| **M-3** `diagnose_chain` con JSON sin claves | Media | ✅ **Cerrado** | ✅ Ya no revienta; reporta la ruptura y sigue |
| **M-4** grants corruptos + permisos | Media | ✅ **Cerrado** | ✅ JSON roto / lista con campo extra / no-lista → `requires_approval` sin excepción; `data/keys` y `logs` en `0700` |
| **M-5** `extra_mounts` sin validar | Media | ⚠️ **Parcial (bypass)** | ❌ **Ver §3.1** — `/workspace/../<x>` evade el chequeo; `host_path` sigue sin cota |
| **M-6** `allowed_domains` sin enforcement | Media | ➖ **Aceptado y documentado** | Docstrings honestos en `sdk/skill.py`/`network_safety.py`/`registry.py`. El hueco técnico sigue (NETWORK = internet completo) |
| **M-7** `sandbox_runner` como root | Media | ✅ **Cerrado** (código) | ✅ Build real: `whoami` → `sandbox`, uid 999, import OK. ⚠️ El prerequisito operativo (`--group-add`) no se entrega (ver §4) |
| **M-8** firma ≠ autoría | Media | ✅ **Cerrado** (mensajes) | Fingerprint expuesto y texto correcto en instalador, `enable_skill` y página del market. `unsigned` sigue cargándose silenciosamente (documentado, sin cambio) |
| **B-1** denylist evadible | Baja | ⚠️ **Parcial** | ❌ `builtins`/`__builtins__.<attr>` bloqueados, pero **7+ evasiones siguen pasando** (§3.2) |
| **B-2** `_skill_files` sigue symlinks | Baja | ✅ **Cerrado** | ✅ Symlink fuera del set; las 7 firmas del repo siguen verificando (`validate_all_skills()` → sin errores) |
| **B-3** workdir dependiente de TMPDIR | Baja | ⚠️ **Parcial** | `sandbox.workdir_root` configurable ✅; falta el diagnóstico explícito cuando el daemon no ve el workdir |
| **B-4** path AF_UNIX largo | Baja | ✅ **Cerrado** | ✅ Con TMPDIR de 151 chars: `Artifact` de error auditado, sin excepción cruda, **sin tempdir huérfano** |
| **B-5** sandbox root si kal es root | Baja | ✅ **Cerrado** | Warning una vez por instancia (verificado en el código; el test lo cubre) |
| **B-6** `.env` + permisos | Baja | ✅ **Cerrado** | ✅ `.env`/`*.pem`/`*.key` en `.gitignore`; `0700` en `data/keys` y `logs` |
| **B-7** `artifact_paths` global | Baja | ✅ **Cerrado** | ✅ Scoping por skill + tope 200 FIFO; 4 tests incluida la aislamiento cruzado |
| **B-8** audit log O(n) por evento | Baja | ➖ **Diferido (documentado)** | Justificación correcta: el comportamiento es correcto, solo lento. Sin cambio de código |
| **B-9** restos y artefactos | Baja | ✅ **Cerrado** | `docs/index.html` generado y commiteado; badge `tampered` propio; aclaración del "367/403" en HISTORY |
| **B-10** opciones de `git clone` + pins | Baja | ✅ **Cerrado** | ✅ `git clone --depth 1 --branch main -- <url> <dest>` funciona; CI de skills ahora instala `requirements-core.txt`; Dockerfile pinea |

**Resultado: 14 cerrados (M-8 en lo esencial), 3 parciales (M-5, B-1, B-3), 2 aceptados/diferidos (M-6, B-8).**

---

## 3. Hallazgos nuevos

### 3.1 🟠 M-5-incompleto — el chequeo de contención de `extra_mounts` es evadible (MEDIO)

**Ubicación:** `kernel/lifecycle/docker_runner.py::_validate_extra_mounts()`

```python
container_posix = PurePosixPath(container_path)
if not container_posix.is_absolute() or not container_posix.is_relative_to("/workspace"):
    raise ValueError(...)
```

`PurePosixPath` **no normaliza `..`** y `is_relative_to()` compara
componentes sin resolverlos, así que `/workspace/../<x>` pasa el filtro.
Docker **sí** normaliza la ruta destino, así que el mount termina donde
el atacante pidió.

**PoC ejecutado con Docker real (✅):**

```
runner.run("...open('/esc/PWNED','w')...", extra_mounts={<host_dir>: "/workspace/../esc"})
→ status: success
→ 'PWNED' apareció en <host_dir> del HOST
→ extra_mounts={"/etc": "/workspace/etc_from_host"} → aceptado (monta /etc rw)
```

Tabla de la validación nueva (✅):

| container_path | resultado |
|---|---|
| `/workspace/.kal` | aceptado (correcto) |
| `/etc`, `/`, `/workspacefoo` | rechazado (correcto) |
| `/workspace/../etc` | **aceptado** ❌ |
| `/workspace/x/../../etc` | **aceptado** ❌ |
| `/workspace/./../root` | **aceptado** ❌ |

Además, el otro lado del hallazgo original sigue abierto: `host_path`
solo se valida como "absoluto y existente" — `/etc`, `/`, `/home`
cualquiera se monta **rw** dentro de un contenedor que ejecuta código no
confiable. Mi recomendación era confinarlo a una raíz permitida y montar
`ro` por defecto.

**Impacto:** hoy no es explotable dentro del repo (el único llamador
pasa un `mkdtemp` propio), igual que antes del fix. Lo que cambió es que
ahora **hay un control que parece cerrar el hueco y no lo cierra**, y
`docs/HISTORY.md` afirma *"`container_path` debe estar confinado a
`/workspace/`"* — una garantía que el código no da. Es el mismo tipo de
problema que la primera auditoría señaló para M-6 (afirmar un control
inexistente), reintroducido en el fix de M-5.

**Remediación:** normalizar antes de comparar
(`posixpath.normpath(container_path)`, o rechazar explícitamente
cualquier componente `..`), usar el mismo enfoque que `_join_within()`
(que ya resuelve/normaliza), agregar los casos `/workspace/../x` a
`tests/test_docker_runner_path_containment.py` (los 7 tests nuevos no
incluyen ninguno con `..`) y decidir explícitamente el destino de
`host_path`.

### 3.2 🟡 B-1-incompleto — el barrido de hermanos volvió a faltar (BAJO)

`import builtins` y `__builtins__.<attr>` quedaron bloqueados (✅), pero
la clase de bug no se barrió. Batería re-ejecutada (✅):

| Entrada | Resultado |
|---|---|
| `import builtins; builtins.eval(...)` | bloqueado ✅ |
| `__builtins__.eval('1')` | bloqueado ✅ |
| `e = eval; e('1+1')` | **pasa** (documentado como hueco conocido) |
| `x = __builtins__; x['eval']('1+1')` | **pasa** ❌ (misma familia que se acaba de tocar: `Subscript`, no `Attribute`) |
| `import io; io.open('/etc/passwd')` | **pasa** ❌ |
| `import posix; posix.system('id')` | **pasa** ❌ (alias directo de `os`, que sí está bloqueado) |
| `import _socket` | **pasa** ❌ (el módulo real detrás de `socket`, que sí está bloqueado) |
| `import _io` | **pasa** ❌ |
| `import pty` | **pasa** ❌ |
| `import platform; platform.os.system('id')` | **pasa** ❌ |
| `import gc` | **pasa** ❌ |

No es una vulnerabilidad (el docstring es claro en que este módulo no es
la garantía; el aislamiento real es Docker y
`test_sandbox_escape_resistance.py` lo prueba). El problema es de
proceso: **es la tercera vez en la sesión** que se corrige una instancia
y no la clase (A-1 vs `_skill_files`; K-4 vs `DynamicSandboxedTool`;
ahora `builtins` vs `posix`/`_socket`/`_io`). Si el objetivo del
validador es higiene, alcanza con documentarlo; si se lo va a seguir
usando como gate de auto-activación en `propose_dynamic_tool()`, la
lista de imports prohibidos necesita derivarse de una fuente
(`sys.builtin_module_names` + alias conocidos) o el gate necesita dejar
de ser el denylist.

### 3.3 🟡 `tool_permission_denied` no está en `EventType` (BAJO)

El fix de M-1 agrega `audit_log.record(AuditEvent(event_type="tool_permission_denied", ...))`
en `kernel/registry/registry.py:133`, pero `"tool_permission_denied"` **no
existe** en el `Literal` `EventType` de `audit/audit_log.py` — el mismo
commit que agregó correctamente `skill_execution_socket_error`,
`skill_permission_denied`, `skill_execution_signature_invalid` y
`kernel_invalid_encoding`. Verificado con un chequeo automático de
"event_type usados vs declarados": el único no declarado es
`tool_permission_denied`. A runtime no rompe (el `Literal` no se valida),
pero el vocabulario de auditoría es el contrato del log y ya quedó
desalineado.

### 3.4 🟡 `KernelServiceBus.artifact_paths` cambió de nombre sin deprecación (BAJO)

El fix de B-7 renombró el atributo **público** `artifact_paths` a
`_artifacts_by_skill` y cambió la firma de `resolve_artifact()`. El
scoping está bien hecho y testeado, pero el kernel se declara consumido
por terceros (kal-in, Likay-OS): un consumidor que leyera
`bus.artifact_paths` se rompe sin aviso. Bajo, pero es un cambio de
contrato, no un detalle interno.

### 3.5 🟡 Higiene: `logs/` inconsistente y archivo ajeno en la raíz (BAJO)

- `utils/logger.py:20` sigue con `LOG_DIR.mkdir(exist_ok=True)` (0775).
  `audit/audit_log.py` lo corrige a `0700`, pero solo si se importa
  `audit`. Todo entrypoint real lo importa, así que el estado final
  verificado es `0700`; queda la inconsistencia (el módulo que *crea* el
  directorio no es el que lo protege).
- `audio_controls.py` en la raíz (código Qt de otro proyecto, sintaxis
  inválida) hace que `ruff check .` **falle** en el árbol de trabajo:
  verificado, los 2 únicos errores de ruff son de ese archivo. El kernel
  (`ruff check kernel sdk audit utils code_analysis scripts tests`) pasa
  limpio. HISTORY lo menciona como excluido a mano; el riesgo es que un
  `git add -A` lo commitee y rompa `ci.yml` (`--select=E9,F` incluye
  invalid-syntax). Moverlo fuera del repo o agregarlo a `.gitignore`.

---

## 4. Puntos de alcance de la ronda anterior: siguen abiertos

No formaban parte de la tabla de 18, así que quedaron sin tocar:

1. **`scripts/verify_sandbox.sh` sigue roto** (✅ verificado: no manda
   `X-Sandbox-Token`): con `SANDBOX_API_TOKEN` configurado recibe 401 en
   todos los checks y aborta por `set -euo pipefail`. Es el script que
   "verifica el sandbox de punta a punta" — hoy no verifica nada.
2. **`docker-compose.yml` sigue sin existir**, y ahora es más relevante:
   el fix de M-7 (`USER sandbox`) hace que el contenedor **no pueda usar
   el socket de Docker** sin `--group-add <GID>`, un prerequisito que
   solo está documentado en un comentario del Dockerfile y que
   `docs/HISTORY.md` deriva a "el equivalente `group_add:` en
   docker-compose.yml" — archivo que no está en el repo. La mejora de
   seguridad es real y verificada, pero el despliegue documentado quedó
   incompleto.
3. **Afirmaciones de docstring vs. estado entregado** (skills 7/7
   `enabled: true`, contra "cada skill.yaml trae enabled: false") y
   **Access Manager sin consumidor in-repo**: ninguna de las dos se
   ajustó.

---

## 5. Verificación positiva (lo que probé y funciona)

- **Suite completa: 447 tests, cero fallas genuinas.** Verificado por
  triangulación: con `TMPDIR` por defecto de este entorno → 412 pasan /
  35 fallan (todas dependen de Docker y el daemon no ve el `/tmp` de la
  sesión); con `TMPDIR` dentro del workspace → 438 / 9 (las 9 son
  `test_kernel_bus_socket_server.py` por longitud `AF_UNIX`, artefacto de
  mi propio `TMPDIR` largo); esas 9 pasan 12/12 con `TMPDIR=/tmp/kalt`.
  Los 16 archivos de test nuevos o modificados (excluyendo los que
  ejercitan Docker): 169 de 170 pasan, y el único que falla es
  `test_docker_runner_workdir_root.py::test_real_docker_still_works_with_an_explicit_workdir_root`
  (marcado `@requires_docker`, misma razón de visibilidad del `TMPDIR`).
  **Ninguna falla por un defecto de código.**
- **Tests nuevos que valen**: los de M-1 ejecutan el camino de
  enforcement y afirman que el sandbox no se invoca; los de B-7 prueban
  aislamiento cruzado entre skills; los de A-1 reproducen el PoC real
  con un market git local (sin red); los de B-4 cubren el path AF_UNIX
  largo; los de B-10 reproducen el error exacto de git sin el `--`.
- **M-2/M-3/M-4**: los tres se comportan de forma fail-safe (400/413,
  ruptura reportada y diagnóstico que continúa, grants inválidos
  descartados uno por uno cayendo a `requires_approval`), no de forma
  fail-crash. Bien resuelto.
- **A-1**: rechazo temprano, antes de red y de filesystem, con una sola
  fuente de verdad (`validate_skill_name()` reutilizada) y segunda capa
  de contención. Exactamente lo pedido.
- **B-2**: no rompe compatibilidad — las 7 firmas ya commiteadas siguen
  verificando (`scripts/validate_skills.py` → "Todas las skills
  verificadas correctamente").
- **M-7**: build real, `whoami` → `sandbox`, `id` → uid 999, import de
  `kernel.api.sandbox_api` OK.
- **B-4/B-6/B-7**: los tres verificados con PoC propios, incluida la
  ausencia de tempdir huérfano y los permisos `0700` reales en disco.
- **`ruff check`** (regla completa) limpio en todo el árbol trackeado.
- El **manejo del propio error del fix** (M-7 sin `chown`) y la
  **autocrítica explícita en HISTORY** ("reparé solo la mitad del
  problema en K-4", "conclusión apurada") son señales de proceso
  maduras, no de fachada.

---

## 6. Nueva calificación

**7.5/10** (antes 7.0). El detalle:

| Dimensión | Antes | Ahora | Comentario |
|---|---|---|---|
| Arquitectura / modelo de amenaza | 9.0 | **9.0** | Sin cambios; el scoping de artefactos por skill mejora el aislamiento entre skills |
| Sandbox | 8.5 | **8.5** | M-7 (no-root) y B-4 suman; M-5-incompleto (control evadible) resta |
| Documentación del *porqué* | 9.0 | **9.0** | Tres secciones nuevas, honestas, con la lección explícita |
| Tests | 7.5 | **8.5** | +44 tests que ejercitan caminos reales, no funciones puras |
| Coherencia afirmación ↔ código | 5.0 | **6.0** | Firma/allowlist/index.html alineadas; sigue el hueco de M-6, el `verify_sandbox.sh` roto, el compose ausente y ahora la afirmación de M-5 |
| Supply chain / higiene | 6.0 | **7.5** | Pins en CI y Dockerfile, `.env`, `0700`, `git clone --` |
| Estado de release | 5.0 | **6.5** | Imagen no-root verificada, `index.html`; falta compose y el script de verificación está roto |
| **Proceso (barrido de clases de bug)** | 6.0 | **6.5** | Mejoró en tests e intención, pero **el patrón reapareció 2 veces dentro de la propia remediación** (B-1 y M-5) |

**Por qué no un 8:** una ronda de remediación que cierra 14/19 hallazgos
con tests y verificación real merece crédito, y lo tiene. Pero el techo
lo sigue poniendo lo mismo que la vez pasada, y ahora con evidencia más
dura: **el proyecto arregla instancias, no clases.** B-1 trataba sobre
evasiones del denylist y se cerró la mitad de las evasiones; M-5 trataba
sobre un montaje sin validar y se agregó una validación evadible. Ninguno
de los dos es explotable hoy, pero ambos dejan documentada una garantía
que el código no cumple — que es el riesgo que más me preocupa en un
proyecto que se presenta como *microkernel de seguridad*.

**Por qué no menos:** no hay ninguna vulnerabilidad nueva explotable,
todos los fixes que tocaron el aislamiento real están verificados en vivo,
y los dos ítems abiertos más serios (M-5, B-1) son de defensa en
profundidad con la barrera real intacta.

**Qué lo llevaría a 9:** (1) cerrar M-5 normalizando el path y acotando
`host_path`; (2) decidir B-1 de una vez — o el denylist deja de ser gate
de auto-activación, o las listas se derivan de una fuente en vez de
enumerarse a mano; (3) arreglar `verify_sandbox.sh` y entregar el
`docker-compose.yml` (con `group_add`), que es lo que hace aplicable el
fix de M-7; (4) una regla operativa simple para que no vuelva a pasar:
**cada hallazgo se cierra con un grep de su clase, no con un test de su
instancia** — buscar todos los `p.is_file()`/`mkdir`/`subprocess`/
`PurePath` del repo, no solo el sitio reportado.

---

## 7. Limitaciones de esta re-auditoría

- El `TMPDIR` por defecto de este entorno no es visible para el daemon de
  Docker, así que los 35 tests de Docker fallan acá por topología (mismo
  hallazgo B-3, que el fix de `workdir_root` ahora permite sortear). Los
  validé corriendo la suite con `TMPDIR` dentro del workspace: 438/447,
  y las 9 restantes son el límite `AF_UNIX` de mi propio path largo
  (12/12 con `TMPDIR` corto).
- No verifiqué el flujo completo del Kernel Service Bus con servicios
  reales (`kernel/services/` no existe en este repo); el scoping de
  artefactos se validó con los tests del bus y con dobles.
- La afirmación de `docs/HISTORY.md` "447 passed, 0 failed" no es
  reproducible tal cual en este entorno; sí lo es la conclusión de que
  no hay fallas de código.
- El PoC de M-5 se ejecutó con Docker real y **escribió un archivo en un
  directorio del host**; lo limpié y el árbol quedó en
  `git status` limpio (solo `audio_controls.py`, preexistente y ajeno).
