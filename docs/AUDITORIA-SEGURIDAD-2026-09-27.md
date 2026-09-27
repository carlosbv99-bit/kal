# Auditoría de seguridad — kal (kernel puro)

**Fecha:** 2026-09-27
**Alcance:** todo el repo (`kernel/`, `sdk/`, `audit/`, `code_analysis/`,
`utils/`, `scripts/`, `skills/`, `config/`, `tests/`, CI).
**Tipo:** auditoría de código con verificación empírica (PoC ejecutados),
no sólo revisión de lectura.
**Método:** lectura completa del código de producción (~4.500 LOC sin
tests), ejecución de la suite, análisis estático (`ruff`, `pip-audit`),
grep dirigido de patrones peligrosos y **reproducción real** de cada
hallazgo relevante. Cada hallazgo marcado ✅ fue verificado con un PoC
que corrió en este entorno.

---

## 1. Resumen ejecutivo

El proyecto tiene una arquitectura de seguridad **mejor que la media**:
el modelo de amenaza está explícito, las defensas son de capas
independientes, el sandbox de Docker está endurecido de verdad (lo
verifiqué ejecutando contenedores reales) y las decisiones de diseño
incómodas están documentadas en lugar de escondidas (`docs/HISTORY.md`).

Dicho eso, la auditoría encontró **1 hallazgo alto, 8 medios y 9 bajos**.
Dos de ellos son especialmente importantes porque **contradicen garantías
que el propio repo declara**:

1. **ALTA — `scripts/install_from_market.py` permite path traversal en
   `skill_name`** y escribe/habilita una skill fuera de `skills/`
   (PoC ejecutado). Es exactamente la clase de bug que el repo ya
   corrigió dos veces en otros módulos (K-1/K-6) y quedó sin corregir en
   el instalador.
2. **MEDIA — la cascada de permisos no se aplica a las herramientas
   dinámicas**: con `network` en `globally_denied` (documentado como
   *"techo del sistema entero… pase lo que pase"*), una herramienta
   dinámica igual ejecuta con red (PoC ejecutado). El test que "ancla"
   ese default sólo prueba la función pura, no ningún camino de
   ejecución — da una falsa sensación de cobertura.

Además, la afirmación de seguridad más visible del proyecto (**"firma
verificada"**) prueba *integridad interna*, no autoría: cualquiera puede
firmar con su propia clave y el resultado dice "verified" (PoC
ejecutado). El código lo documenta con honestidad, pero el mensaje que
ve el usuario (instalador, página de market, `enable_skill.py`) no.

**Estado de la suite de tests:** 403 tests. Con el `TMPDIR` por defecto
de este entorno: **369 pasan / 34 fallan** — las 34 fallas son
*ambientales* (el daemon de Docker no ve el `/tmp` de esta sesión), no
del código: con `TMPDIR` dentro del workspace pasan 394/403, y las 9
restantes fallan por longitud máxima de path AF_UNIX (artefacto del
`TMPDIR` que yo mismo elegí, ver B-4). **Ninguna falla de test
corresponde a un bug funcional no detectado.** Ese comportamiento, igual,
es un hallazgo (B-3).

---

## 2. Tabla de hallazgos

| ID | Sev | Título | Archivo principal |
|----|-----|--------|-------------------|
| **A-1** | 🔴 Alta | Path traversal en `skill_name` del instalador de market → escribe/habilita fuera de `skills/` | `scripts/install_from_market.py` |
| **M-1** | 🟠 Media | La cascada de permisos no se aplica en ejecución a herramientas dinámicas (tier `agent`) | `kernel/registry/registry.py` |
| **M-2** | 🟠 Media | `Content-Length` no numérico rompe el middleware de `/execute` (pre-auth) y el límite es evadible | `kernel/api/sandbox_api.py` |
| **M-3** | 🟠 Media | `verify_chain()`/`diagnose_chain()` revientan con una línea JSON sin las claves esperadas | `audit/audit_log.py` |
| **M-4** | 🟠 Media | Grants persistidos se parsean sin validación; `data/keys/` escribible por grupo | `kernel/permissions/access_manager.py` |
| **M-5** | 🟠 Media | `extra_mounts` monta rutas arbitrarias del host sin validar | `kernel/lifecycle/docker_runner.py` |
| **M-6** | 🟠 Media | `allowed_domains` nunca se aplica: `Permission.NETWORK` = internet completo; `is_unsafe_ip` es código muerto | `sdk/skill.py`, `kernel/permissions/network_safety.py` |
| **M-7** | 🟠 Media | `sandbox_runner` corre como **root** teniendo el socket Docker del host | `kernel/lifecycle/Dockerfile` |
| **M-8** | 🟠 Media | Firma de skills: "verified" no prueba autoría y borrar `skill.sig` degrada a "unsigned" | `kernel/registry/skill_signing.py` |
| **B-1** | 🟡 Baja | Denylist AST evadible en una línea (`builtins.__import__('os')`, alias de `eval`) | `code_analysis/ast_validator.py` |
| **B-2** | 🟡 Baja | `_skill_files()` (firma) sigue symlinks — el fix A-1 no se aplicó acá | `kernel/registry/skill_signing.py` |
| **B-3** | 🟡 Baja | El sandbox depende de que Docker vea `tempfile.gettempdir()`; el fallo es engañoso y sin diagnóstico | `kernel/lifecycle/docker_runner.py` |
| **B-4** | 🟡 Baja | Path del socket Unix sin chequeo de longitud ni limpieza del tempdir | `kernel/registry/sandboxed_skill.py` |
| **B-5** | 🟡 Baja | Si kal corre como root, el sandbox corre como root (sin chequeo) | `kernel/lifecycle/docker_runner.py` |
| **B-6** | 🟡 Baja | `.gitignore` sin `.env`; `logs/` y `data/keys/` escribibles por grupo | `.gitignore`, permisos |
| **B-7** | 🟡 Baja | `bus.artifact_paths`: mapa global sin límite ni scoping por skill | `kernel/api/bus.py` |
| **B-8** | 🟡 Baja | El audit log se relee entero en cada evento (O(n²), sin rotación) | `audit/audit_log.py` |
| **B-9** | 🟡 Baja | Restos y artefactos desactualizados (tool_versions, docs/index.html ausente, claims de tests) | varios |
| **B-10** | 🟡 Baja | Inyección de opciones en `git clone` vía `--market`; pins incompletos (Dockerfiles, CI) | `kernel/registry/skill_market.py`, Dockerfiles |

---

## 3. Hallazgos detallados

### 🔴 A-1 — Path traversal en el instalador de market (ALTA)

**Ubicación:** `scripts/install_from_market.py:80` (y `:87`, `:117`)

```python
local_dest = DEFAULT_SKILLS_DIR / args.skill_name      # sin sanitizar
...
fetch_skill_from_market(args.market, args.skill_name, staging_dir, ref=args.ref)
...
shutil.copytree(staging_dir, local_dest)               # escritura fuera de skills/
set_skill_enabled(local_dest, True)                    # y además la habilita
```

`args.skill_name` viene de la línea de comandos y **no pasa por ninguna
validación** — a diferencia de `manifest.name`, que sí está validado por
`_validate_skill_name()` (`kernel/registry/skills.py`) y
`is_valid_tool_name()` (`versioning.py`) precisamente por esta razón
(K-1 / K-6, `docs/HISTORY.md` 2026-09-27).

**PoC ejecutado (✅ reproducido en este entorno):** construí un repo
"market" local con un paquete firmado con una clave **de atacante** y
corrí:

```
python3 scripts/install_from_market.py "../.audit_pwned" --market <repo-atacante> --yes
```

Resultado real:

```
Skill: pwned (v0.1.0)
Firma: verificada (el paquete no cambió desde que su autor lo firmó)
'pwned' instalada y habilitada.
```

y el paquete quedó escrito y **habilitado** en `<repo>/.audit_pwned/`,
fuera de `skills/`. Con una ruta elegida a propósito (`--skill-name
"../../.venv/lib/python3.14/site-packages/<algo>"`) se llega al escenario
de **RCE diferido** que el propio `docs/HISTORY.md` describe para K-1
(el `local_dest.exists()` sólo impide *pisar* un directorio ya existente,
no impide crear uno nuevo en cualquier ruta donde el usuario tenga
permiso de escritura).

**Impacto:** una skill de un market controlado por un atacante escribe
contenido arbitrario fuera del único directorio que el sistema considera
"instalable", con la aprobación humana reducida a "instalar la skill X", y
la deja `enabled: true` y auditada como instalación legítima.

**Remediación:**
1. Validar `args.skill_name` con el mismo `_VALID_SKILL_NAME` de
   `kernel/registry/skills.py` **antes** de tocar el filesystem
   (una sola fuente de verdad, no una tercera regex).
2. Segunda capa en `fetch_skill_from_market()`/`install_from_market`:
   comprobar `local_dest.resolve().is_relative_to(DEFAULT_SKILLS_DIR.resolve())`
   y rechazar (mismo patrón que `SandboxedSkillTool.__init__` y
   `ToolVersionStore._tool_dir`).
3. No usar `--yes` en documentación de CI/automatización hasta arreglar (1) y (2).

---

### 🟠 M-1 — La cascada de permisos no se aplica a las herramientas dinámicas

**Ubicación:** `kernel/registry/registry.py:108-126`
(`DynamicSandboxedTool.execute`) vs. `kernel/registry/sandboxed_skill.py:169`
(`SandboxedSkillTool.execute`)

`SandboxedSkillTool.execute()` consulta `permission_cascade.missing_permissions(..., "skill")`
(K-4). `DynamicSandboxedTool.execute()` **no consulta la cascada en
absoluto**: deriva `network_mode` únicamente de
`manifest.permissions` y llama a `SandboxExecutor.execute()`.

**PoC ejecutado (✅):** con una cascada que deniega `network`
globalmente —

```python
# PermissionCascade(globally_denied=["network"])
DynamicSandboxedTool(manifest_with_network, "print(1)", sandbox=fake).execute()
# -> network_mode = 'bridge'
```

Verificado también por inspección: `"permission_cascade" in
inspect.getsource(DynamicSandboxedTool.execute)` → `False`.

**Impacto:** `config/config.yaml` documenta `globally_denied` como
*"Techo del sistema entero: nadie por debajo puede otorgar un permiso
listado acá, pase lo que pase — ni siquiera el tier system"*. Para
herramientas dinámicas eso es hoy **falso**: endurecer la config no
cambia su comportamiento. El único control que queda es
`require_human_approval_for` (que sí se evalúa al proponer), así que no
hay escalada directa, pero sí **pérdida de un control de defensa en
profundidad que el operador cree tener**. Es el mismo tipo de hueco que
K-4 (`docs/HISTORY.md`) declaró cerrado, sólo que para el otro wrapper.

**Cobertura de tests engañosa:** el test que "ancla" este default
(`tests/test_permission_cascade.py::test_default_config_denies_the_highest_impact_permissions_globally`)
sólo ejercita `missing_permissions()` (función pura). Ningún test
comprueba que un `Tool.execute()` real obedezca la cascada.

**Remediación:** mover la comprobación a un único punto que cubra los dos
wrappers (por ejemplo dentro de `SandboxExecutor.execute()` /
`execute_trusted()`, recibiendo el `trust_tier`, o un `_assert_cascade`
compartido), y agregar un test que ejecute `DynamicSandboxedTool.execute()`
con una cascada restrictiva y verifique `network_mode is None` + artefacto
de error.

---

### 🟠 M-2 — Middleware de tamaño de body: crash pre-auth y límite evadible

**Ubicación:** `kernel/api/sandbox_api.py:38-59`

```python
content_length = headers.get(b"content-length")
if content_length is not None and int(content_length) > self.max_bytes:
```

**PoC ejecutado (✅):**

```
middleware CRASH for [(b'content-length', b'not-a-number')]:
    ValueError: invalid literal for int() with base 10: b'not-a-number'
```

Un `Content-Length` no numérico produce una excepción **antes** de la
autenticación (el middleware corre antes de las dependencias), es decir
un 500/aborto de conexión alcanzable por cualquiera que pueda llegar al
puerto. Además:
- `dict(scope["headers"])` colapsa headers duplicados (dos
  `Content-Length` → gana el último).
- El límite es evadible con `Transfer-Encoding: chunked` o con un
  `Content-Length` mentido — el propio docstring lo admite
  ("deny-by-default en el caso común, no una defensa exhaustiva"), pero
  el cliente que evade *no* pasó la autenticación todavía: el comentario
  da a entender que la autenticación ya ocurrió cuando eso es falso.
- El límite grande (`int` de 26 dígitos) **no** es un overflow en Python
  (verificado): no hay hallazgo ahí.

**Remediación:** envolver el `int()` en `try/except (TypeError, ValueError)`
tratando el valor inválido como `413`/`400`; usar
`starlette.middleware.trustedhost`/un contador real de bytes sobre
`receive` (no `Content-Length`) para el límite efectivo; no afirmar en el
comentario que la autenticación ya ocurrió.

---

### 🟠 M-3 — El verificador de la cadena de auditoría revienta con entrada malformada

**Ubicación:** `audit/audit_log.py:282-291` (`diagnose_chain`)

`json.loads` está protegido (fix A-10#2), pero los accesos
`entry["prev_hash"]`, `entry["event_type"]`, etc. **no**. Una línea que
sea JSON válido pero no tenga esas claves (tampering manual, línea de
otra herramienta, escritura parcial que casualmente parsea) produce un
`KeyError` sin capturar.

**PoC ejecutado (✅):**

```
valid chain: True
CRASH verify_chain(): KeyError 'prev_hash'
tail(): 3        # tail() sí sobrevive
record() OK      # record() sí sobrevive (_read_last_hash captura KeyError)
```

**Impacto:** la herramienta con la que un humano investigaría una
manipulación del log es justamente la primera que deja de funcionar. El
`record()` sigue escribiendo (bien), así que no se pierde auditoría — se
pierde la **capacidad de verificarla**, que es el punto del hash-chain.

**Remediación:** encapsular el acceso a claves obligatorias con
`entry.get(...)` + registro de ruptura (igual que ya se hace para
`JSONDecodeError`), y agregar tests para "JSON válido sin claves",
"claves con tipo equivocado" y "event_hash con longitud inválida".

---

### 🟠 M-4 — Grants persistidos sin validación + directorio de claves escribible por grupo

**Ubicación:** `kernel/permissions/access_manager.py:174-184`

```python
raw = json.loads(self._grants_path.read_text(encoding="utf-8"))
return [_Grant(**g) for g in raw]
```

Sin `try/except`: JSON corrupto → `JSONDecodeError` sin capturar dentro de
`evaluate()` (PoC ✅: `CRASH in evaluate(): JSONDecodeError ...`); un campo
extra o faltante → `TypeError`. Un archivo ilegible/incompleto deja el
motor de decisión inutilizable (fail-closed por excepción, pero rompe en
lugar de degradar con auditoría).

Además:
- `_GRANTS_PATH = Path("data/keys/filesystem_grants.json")` (y el de red)
  viven en un directorio con permisos `0775` y el archivo se crea con el
  umask del proceso (`0664` típico). En un host compartido, **otro
  usuario del grupo puede escribir sus propias concesiones** — incluida
  una con `"resource_key": null`, que concede *cualquier* recurso para esa
  skill/scope/acción (`_grant_matches`, `access_manager.py:66-69`).
- Ninguno de los dos adaptadores (`filesystem_access_manager`,
  `network_access_manager`) tiene hoy un consumidor in-repo: son
  plumbing de política sin punto de enforcement en este repo (ver §5).

**Remediación:** `try/except (OSError, JSONDecodeError, TypeError)` con
auditoría de la anomalía; validar el esquema de cada grant con un modelo
(igual que `utils/config.py` hace con pydantic); mover los grants a un
archivo `0600` fuera de `data/keys` (o endurecer el directorio a `0700`).

---

### 🟠 M-5 — `extra_mounts` sin validación (la defensa de K-2/A-1 no lo cubre)

**Ubicación:** `kernel/lifecycle/docker_runner.py:223-225`

```python
volumes = {str(workdir): {"bind": "/workspace", "mode": "rw"}}
for host_path, container_path in (extra_mounts or {}).items():
    volumes[str(host_path)] = {"bind": container_path, "mode": "rw"}
```

`workspace_files` y `output_dir` sí pasan por `_join_within()` (fix
"footgun latente" documentado en `docs/HISTORY.md`), pero `extra_mounts`
—que es **la clave del diccionario**: una ruta del host— no pasa por
ningún control, y se monta `rw`. El único llamador real es interno
(`sandboxed_skill.py` monta un `mkdtemp` propio del socket), así que hoy
no es explotable in-repo; pero `DockerSandboxRunner`/`SandboxExecutor`
son explícitamente la superficie pública que consumen kal-in y Likay-OS,
y la firma invita a pasar mounts dinámicos.

**Remediación:** validar que cada `host_path` esté dentro de una raíz
permitida (configurable), rechazar `container_path` absolutos fuera de
`/workspace`/una raíz declarada, y montar `ro` por defecto salvo
justificación explícita.

---

### 🟠 M-6 — `allowed_domains` no se aplica: NETWORK = internet completo

**Ubicación:** `sdk/skill.py:28` (declaración), `kernel/registry/sandboxed_skill.py:208`
(consumo), `kernel/registry/registry.py:109`

```python
network_mode = "bridge" if Permission.NETWORK in self.manifest.permissions else None
```

`ToolManifest.allowed_domains` se declara, se serializa
(`registry.py:59/72`) y **nunca se aplica** para una skill o herramienta
sandboxeada: `Permission.NETWORK` concede la red `bridge` completa (sin
allowlist, sin proxy, sin `--dns` restringido, sin `iptables`). Basta con
que un humano apruebe `network` una vez.

Relacionado: `kernel/permissions/network_safety.py::is_unsafe_ip()`
(protección anti-DNS-rebinding) **no tiene ningún llamador** en el repo
(verificado con grep). El docstring del módulo afirma que se comparte con
`tool_integration/adapters/browser.py` y `download_manager.py`, que no
existen acá; el único consumidor real es `network_access_manager`, que usa
`is_hostname_allowed` (allowlist) pero **no** `is_unsafe_ip`. La
protección anti-SSRF que el README presenta como parte del kernel es, en
este repo, código muerto.

**Remediación:** o bien (a) no prometer `allowed_domains` hasta que exista
enforcement (proxy de egreso / `iptables` en el contenedor), o (b)
implementarlo; y llamar `is_unsafe_ip()` en el punto donde se resuelve el
destino, o marcar explícitamente el helper como "para consumidores
externos" en el docstring.

---

### 🟠 M-7 — El servicio con acceso al socket Docker corre como root

**Ubicación:** `kernel/lifecycle/Dockerfile:8, 30-32`

```dockerfile
RUN groupadd -r sandbox && useradd -r -g sandbox sandbox
...
EXPOSE 9000
CMD ["uvicorn", "kernel.api.sandbox_api:app", "--host", "0.0.0.0", "--port", "9000"]
```

El usuario `sandbox` se crea y **nunca se usa**: no hay `USER sandbox`.
`sandbox_runner` es, por diseño, el único componente con el socket de
Docker del host — y corre como root. Cualquier RCE en el proceso FastAPI
(cuyo `/execute` ejecuta código, con un denylist evadible, B-1) pasa de
"contenedor comprometido" a "root con el socket de Docker", es decir root
del host.

Además, la imagen instala dependencias **sin pinear** (`pip install
--no-cache-dir docker fastapi "uvicorn[standard]"`), a diferencia de
`requirements-core.txt` que sí se pineó en la misma sesión (M-9) — la
imagen más privilegiada del sistema es la que quedó con superficie de
supply-chain abierta. Tampoco hay `docker-compose.yml` en el repo (ver
B-10).

**Remediación:** agregar `USER sandbox` (y el GID del socket como grupo
suplementario vía `--group-add`, que es para lo que sirve el usuario
creado), fijar versiones en el Dockerfile, y sumar el build de la imagen
a CI.

---

### 🟠 M-8 — Firma de skills: "verified" no prueba autoría y es degradable

**Ubicación:** `kernel/registry/skill_signing.py:174-206`, `kernel/registry/skills.py:243-257`

Tres hechos verificados (✅):

1. `verify_skill_signature()` valida la firma contra
   `data["author_public_key"]`, **la clave pública que viene dentro del
   propio `skill.sig`**. Cualquiera puede generar un keypair, firmar su
   skill y obtener `"verified"`:

   ```
   after deleting skill.sig:              unsigned
   after re-signing with an attacker key: verified
   ```

2. **Borrar `skill.sig` degrada a `"unsigned"`**, y `load_skills()`
   acepta `unsigned` (decisión de compatibilidad, documentada). Con
   permiso de escritura sobre `skills/`, la verificación se evita
   simplemente borrando el archivo (la re-verificación por ejecución de
   K-5 no ayuda si no hay firma que verificar).

3. El mensaje que ve el humano **no refleja ese alcance**: el instalador
   imprime `"Firma: verificada (el paquete no cambió desde que su autor lo
   firmó)"` (que implica autoría) y la página de market dice *"Every skill
   listed here is signature-verified before install"*.

El código documenta honestamente la limitación ("integridad, NUNCA
autoridad"), pero la UI no. Combinado con A-1, el modelo "el market sólo
instala paquetes firmados y verificados" no frena a un market hostil.

**Remediación:** (a) cambiar los mensajes a "integridad verificada
(firmado con la clave X; el autor no está autenticado)"; (b) exponer el
fingerprint de la clave en el resumen de instalación para que el humano
pueda compararlo con el anunciado por el autor; (c) decidir
explícitamente si `unsigned` debe seguir cargándose (hoy sí) y auditarlo
como tal.

---

### 🟡 B-1 — Denylist AST evadible (documentado como heurístico, pero es el gate de auto-activación)

**Ubicación:** `code_analysis/ast_validator.py:37-40`, `code_analysis/denylist.py`

`visit_Call` sólo mira `ast.Name`; `visit_Attribute` sólo mira nombres de
atributo literales; `visit_Import` mira el módulo raíz. PoC ejecutados
(✅):

| Entrada | Resultado |
|---|---|
| `eval('1+1')` | bloqueado |
| `import os` | bloqueado |
| `import builtins; builtins.eval('1+1')` | **pasa** |
| `import builtins; builtins.__import__('os').system('id')` | **pasa** |
| `f = eval; f('1+1')` | **pasa** |
| `import io; io.open('/etc/passwd')` | **pasa** |

El docstring del denylist es explícito en que no es la garantía (la
garantía es Docker) y `tests/test_sandbox_escape_resistance.py` lo
justifica bien. El problema es de **enmarcado**: `propose_dynamic_tool()`
usa `validate_code()` como gate real (si pasa y no pide permisos
sensibles, la herramienta se **auto-activa**) y `scripts/verify_sandbox.sh`
presenta "import os prohibido se rechaza" como una verificación de
seguridad. Un atacante que controle el prompt del LLM propone una
herramienta con una línea de `builtins` y pasa el gate.

**Remediación:** no cambiar la naturaleza heurística, sino (a) dejar de
apoyarse en el denylist para decidir auto-activación (exigir aprobación
humana para toda herramienta dinámica, o confirmar identidad del autor),
y (b) aclarar en `verify_sandbox.sh` y en el docstring que es un filtro
de higiene, no un control.

---

### 🟡 B-2 — `_skill_files()` sigue symlinks (el fix A-1 quedó a medias)

`kernel/registry/skill_signing.py:59-65` usa `p.is_file()` (sigue
symlinks) sobre `rglob("*")`, mientras que
`SandboxedSkillTool._collect_skill_files()` —el mismo patrón— sí se
corrigió con `os.lstat` (A-1). Verificado: firmar una skill con
`link.py -> /etc/hostname` incluye el archivo del host en el manifiesto
canónico.

**Impacto:** sólo se calcula el SHA-256 del contenido del host (no hay
exfiltración ni bypass de firma, verificado); el efecto real es que un
paquete con symlinks "firma" contenido fuera de `skills/` y puede volverse
`tampered` si el archivo externo cambia. Inconsistencia con la defensa ya
adoptada en el módulo hermano.

**Remediación:** usar `os.lstat`/`S_ISREG` + comprobación
`resolve().is_relative_to(skill_dir.resolve())`, igual que
`_collect_skill_files()`.

---

### 🟡 B-3 — El sandbox depende de que Docker pueda montar `tempfile.gettempdir()`

`DockerSandboxRunner.run()` crea el workdir con
`tempfile.TemporaryDirectory()` y lo bind-mountea. Si el daemon de Docker
vive en otro mount namespace (rootless Docker, Docker Desktop, snap,
`DOCKER_HOST` remoto), el workdir **no existe** desde el daemon y **toda**
ejecución falla con:

```
python: can't open file '/workspace/main.py': [Errno 2] No such file or directory
```

Es exactamente lo que ocurrió en este entorno (verificado: el daemon ve
`/tmp` distinto que la sesión; `docker run -v /tmp/kaltest:/x` muestra el
directorio vacío). Síntoma engañoso: parece un bug del código de la skill,
no de la topología. Reproduje las garantías del sandbox poniendo
`TMPDIR` dentro del workspace: **25/25 tests de integración + escape
resistance pasan** (read-only rootfs, cap_drop, no-root, sin red, sin
socket Docker, sin fuga de env).

**Remediación:** exponer `sandbox.workdir_root` en config (default
`tempfile.gettempdir()`), documentar el requisito "debe ser
bind-mountable por el daemon" y devolver un error explícito cuando el
workdir no es visible (por ejemplo, un `main.py` marcador verificado con
un `docker run` de sonda, una vez).

---

### 🟡 B-4 — Path del socket Unix sin validación y con fuga de tempdir

`kernel/registry/sandboxed_skill.py:213-227`: el `socket_tempdir` se crea
y `socket_server.start()` se llama **fuera** del `try/finally` que limpia.
Si `tempfile.gettempdir()` es largo, el path supera el límite de
`sockaddr_un` (108 bytes) y el `bind()` lanza `OSError: AF_UNIX path too
long` (✅ verificado con un path de 129 bytes). Consecuencias: la excepción
se propaga cruda fuera de `execute()` (no se convierte en `Artifact` de
error) y el `mkdtemp` queda sin borrar.

**Remediación:** mover la creación del socket dentro del `try`, convertir
`OSError` en un `Artifact` de error auditado y, si el path excede el
límite, usar un directorio alternativo corto (`/tmp/kal-<uuid>`) con un
mensaje claro.

---

### 🟡 B-5 — Sandbox root si kal corre como root

`docker_runner.py:254` fija `user=f"{os.getuid()}:{os.getgid()}"`. Es una
buena decisión (evita el chmod 0777 histórico), pero si el proceso
principal corre como `uid 0`, el contenedor también. No hay ninguna
comprobación ni advertencia. `cap_drop=ALL`, `no-new-privileges` y
`read_only` reducen mucho el impacto, pero conviene fallar ruidosamente
(o al menos auditar) cuando `os.getuid() == 0`.

---

### 🟡 B-6 — Higiene de secretos en disco

- `.gitignore` **no incluye `.env`**, aunque `utils/config.py:20` llama a
  `load_dotenv()`. El repo nunca tuvo un `.env` (confirmado con
  `git log --all`), pero el día que alguien cree uno con secretos está a
  un `git add -A` de commitearlo. Agregar `.env`, `.env.*`, `*.pem`,
  `*.key`.
- `logs/` es `0775` y `logs/audit.log` `0664`: cualquier miembro del grupo
  puede reescribir el registro de auditoría (el hash-chain detecta la
  manipulación, pero no la impide — M-12 lo reconoce). `data/keys/` es
  `0775`: los archivos privados están en `0600` (bien), pero el
  directorio permite a un miembro del grupo *reemplazar* la clave (y
  entonces las firmas nuevas son del atacante) y escribir grants (M-4).
  Recomendado: `0700` para `data/keys` y `logs`.

---

### 🟡 B-7 — `bus.artifact_paths`: mapa global, sin límite ni scoping

`kernel/api/bus.py:39, 84-90`. El mapa `artifact://` → ruta real crece
indefinidamente (nunca se limpia al terminar una ejecución) y no está
scopeado por skill: una skill que adivine u obtenga el UUID de un
artefacto generado por otra puede pasarlo como entrada a un método
declarado en su propio `kernel_services` y obtener la ruta real de host
(`_resolve_input_artifacts`). En este repo no hay servicios registrados
(no hay `ALLOWED_ACTIONS` en el árbol), así que hoy es teórico; en kal-in
(Los servicios reales sí existen) es alcanzable.

**Remediación:** mapa por ejecución (pasado al `KernelBusSocketServer`),
límite de entradas, y TTL/acceso por skill; devolver el contenido del
artefacto en lugar de la ruta cuando sea posible.

---

### 🟡 B-8 — Coste O(n) por evento en el audit log

`AuditLog._read_last_hash()` hace `f.read()` del archivo entero en cada
`record()` bajo lock exclusivo (para resolver la carrera entre procesos,
que es correcta). Con un log que sólo crece (339 KB hoy, sin rotación),
el coste total es cuadrático y **el lock serializa a todos los
escritores** mientras lee. Una skill puede generar hasta 20 eventos por
ejecución (`max_requests`) de forma barata.

**Remedación:** mantener el hash del último evento en un sidecar pequeño
(`audit.log.head`), o leer sólo el final del archivo
(`seek(-N, SEEK_END)`), conservando la lectura desde disco (no un caché en
memoria) que fue la corrección original.

---

### 🟡 B-9 — Restos, artefactos y afirmaciones desactualizadas

- `data/tool_versions/herramienta_de_prueba/` (120 archivos, ~60
  versiones) son restos de tests, firmados con una clave que
  `docs/HISTORY.md` reconoce como perdida. No se cargan en el arranque
  (verificado: nada lista `tool_versions` al importar), pero ensucian el
  estado y harían fallar `verify_tool_integrity()` si alguna se activara.
- `scripts/generate_market_page.py` escribe `docs/index.html`, que **no
  existe** en el repo (y el README/HISTORY lo presentan como la página
  publicada en GitHub Pages).
- `_badge_for_signature()` muestra `"unsigned"` para el estado
  `"tampered"`: un paquete **alterado** se muestra igual que uno sin
  firmar. Confunde la señal de seguridad.
- `docs/HISTORY.md` afirma "367/403 tests passed" sin especificar el
  entorno; en un entorno con Docker accesible pero `/tmp` no compartido
  fallan 34 (B-3). Convendría registrar el requisito de entorno en
  `CONTRIBUTING.md`.

---

### 🟡 B-10 — Inyección de opciones en `git clone` y pins incompletos

- `kernel/registry/skill_market.py:39-42`: `market_url` se pasa como
  argumento posicional a `git clone ... <market_url> <dest>`. Si el valor
  comienza con `-` (p. ej. `--upload-pack=<cmd>`), git lo interpreta como
  opción. El valor lo provee el humano que corre el script, así que es de
  severidad baja, pero el arreglo es trivial: `git clone ... -- <url>` o
  rechazar URLs que empiecen con `-`.
- Pins incompletos: `kernel/lifecycle/Dockerfile` (M-7) y
  `.github/workflows/validate-skills.yml:21`
  (`pip install pyyaml python-dotenv pydantic cryptography`, sin
  versiones) quedaron fuera del barrido M-9 que sí pineó
  `requirements-*.txt` y las actions por SHA.
- `pip-audit` en CI es informativo (`|| true`): aceptable como decisión,
  pero significa que una vulnerabilidad nueva no bloquea nada.

---

## 4. Verificado como correcto (no son hallazgos)

Para que el informe también sirva de evidencia positiva, esto se revisó y
**está bien**:

- **Aislamiento de Docker** (`docker_runner.py:237-259`): `read_only=True`,
  `tmpfs /tmp` con `noexec,nosuid,size=64m`, `cap_drop=["ALL"]`,
  `security_opt=["no-new-privileges"]`, `user` = UID/GID del proceso,
  límites de memoria/swap/CPU/pids, `network_mode="none"` por defecto,
  sin variables de entorno del host (sólo `KAL_CORRELATION_ID`), sin el
  socket de Docker, contenedor efímero eliminado con `force=True`.
  Confirmado ejecutando los tests reales (25/25 con TMPDIR adecuado).
- **K-2 y A-1** (lectura arbitraria de host por symlinks en el bind mount
  de salida y de entrada): ambos fixes presentes y funcionando —
  `_collect_output_files` y `_collect_skill_files` usan `os.lstat` +
  `S_ISREG` + `resolve().is_relative_to(raíz)`. Verifiqué que un symlink a
  `/etc/hostname` **no** se recolecta.
- **K-5** (re-verificación de firma en cada `execute()`) presente.
- **K-1/K-6** (nombres de skill/herramienta validados con una única regex
  en dos capas: `load_skills()` + `SandboxedSkillTool.__init__`,
  `propose_dynamic_tool()` + `ToolVersionStore._tool_dir()`) presentes.
- **K-4** (cascada exigida por el kernel para skills) presente — el hueco
  es sólo para el tier `agent` (M-1).
- **`kernel/api/sandbox_api.py` / C-3**: sin `SANDBOX_API_TOKEN` todo
  pedido a `/execute` es 401 (fail-closed, verificado); comparación con
  `secrets.compare_digest` sobre bytes, sin `TypeError` con input
  no-ASCII (verificado); `/health` sin autenticar pero sin datos
  sensibles.
- **Audit log**: append-only real, `fcntl.flock` correcto, lectura del
  último hash **desde disco** (no caché), `record()` y `tail()`
  resilientes a línea corrupta, `prev_hash`/`event_hash` bien calculados,
  no se avanza con el hash recomputado (permite detectar rupturas
  posteriores).
- **`sdk/` 100% stdlib** y separación correcta entre
  `sdk/permissions.py` (se copia al contenedor) y
  `permission_cascade.py` (nunca sale del host).
- **`code_analysis`** bloquea correctamente los vectores clásicos
  (`eval`, `exec`, `import os`, `__subclasses__`, `getattr`, `pathlib`).
- **`network_safety.is_hostname_allowed`**: deny-by-default con lista
  vacía, matching exacto o subdominio.
- **Sin secretos en el historial de git** (escaneé todos los blobs
  alcanzables); claves privadas fuera de git (`/data/` ignorado) y en
  `0600`; `admin_token` con `secrets.token_urlsafe(32)`.
- **`ruff check .` (regla completa): limpio.** `pip-audit
  -r requirements-core.txt`: "No known vulnerabilities found".
- **YAML alias-bomb probado** contra `parse_manifest()` y contra el
  hashing de firma: PyYAML reutiliza referencias, no hay expansión
  exponencial (no es un DoS).
- `DockerSandboxRunner` con conexión perezosa (un Docker caído no impide
  arrancar el proceso) y el fix del pull implícito con timeout +
  limpieza del contenedor huérfano vía `add_done_callback`.

---

## 5. Observaciones de alcance (importante para el informe final)

1. **La capa "Access Manager" no tiene punto de enforcement en este
   repo.** `filesystem_access_manager`, `network_access_manager`,
   `get_or_create_admin_token` y `resource_broker` no tienen ningún
   consumidor dentro de `kernel/`/`sdk/`/`audit/`/`code_analysis/`/
   `scripts/` (verificado con grep, excluyendo tests y comentarios). Son
   primitivas que exporta el kernel para kal-in/Likay-OS. La frase del
   README *"tiered, deny-by-default access to filesystem and network, con
   aprobación humana explícita"* describe **la intención del mecanismo**,
   no una garantía aplicada dentro de kal. Todo lo que kal realmente
   impone hoy es: aislamiento de Docker + `network_mode` derivado del
   manifiesto + cascada para el tier `skill` + aprobación humana en la
   propuesta de herramientas dinámicas.
2. **Las 7 skills del repo están todas `enabled: true`.** El docstring de
   `kernel/registry/skills.py` dice *"cada skill.yaml trae enabled: false
   … hasta que un humano edita el manifiesto a mano"*; el estado que se
   entrega **no** cumple eso (7/7 habilitadas). Se mitiga porque ahora se
   ejecutan aisladas y su tier no tiene red, pero la afirmación
   "deny-by-default a nivel de manifiesto" no es lo que el repo
   distribuye. Convendría alinear el docstring con la realidad (o
   entregar `enabled: false` y dejar que el humano habilite).
3. **No hay `docker-compose.yml`** en el repo, pese a que
   `docker_runner.py`, `kernel/__init__.py`, `event_consumer.py`,
   `sandbox_api.py` y `docs/HISTORY.md` lo citan como la pieza que
   (a) publica el puerto sólo en `127.0.0.1` y (b) provee
   `SANDBOX_API_TOKEN`. Un operador que siga la documentación no tiene
   ese archivo. Además `scripts/verify_sandbox.sh` quedó **roto** desde el
   fix C-3: hace `POST /execute` sin el header `X-Sandbox-Token`, así que
   siempre recibe 401 y el script aborta (`set -euo pipefail`). Añadir el
   compose y arreglar el script (o borrarlo) es parte de cerrar C-3.

---

## 6. Priorización recomendada

**Ahora (esta semana):**
1. A-1 — validar `skill_name` + contención de ruta en el instalador, con
   test de regresión para `../`, absolutos y `nested/deep`.
2. M-1 — aplicar la cascada en `DynamicSandboxedTool.execute()` (o en un
   punto único) + test que ejecute de verdad.
3. M-2 y M-3 — los dos crasheos triviales (`int(Content-Length)`,
   `KeyError` en `diagnose_chain`).

**Corto plazo:**
4. M-7 (`USER sandbox` + pins en el Dockerfile del servicio privilegiado)
   y `docker-compose.yml` + arreglar `verify_sandbox.sh`.
5. M-8 (mensajes de firma honestos) y M-4 (validación + permisos).
6. M-5/M-6 (validar `extra_mounts`; decidir el destino de
   `allowed_domains`/`is_unsafe_ip`).

**Higiene:**
7. B-1 a B-10, y alinear `docs/HISTORY.md`/docstrings con lo que el repo
   realmente garantiza (skills `enabled`, Access Manager sin enforcement,
   conteo de tests por entorno).

---

## 7. Metodología y limitaciones

- **Leí** todos los módulos de producción, los 7 `skill.yaml`/`tool.py`,
  los `Dockerfile`, los workflows de CI, `pyproject.toml`,
  `requirements-*.txt`, `.gitignore`, `docs/HISTORY.md`, `README*.md`.
- **Reproduje** cada hallazgo marcado ✅ con código ejecutado en este
  entorno (no inferencia): los PoC se corrieron y se limpiaron; el árbol
  quedó sin cambios (`git status` limpio).
- **Ejecuté** la suite completa (403 tests) en dos configuraciones de
  `TMPDIR`, `ruff check .` y `pip-audit`.
- **No pude** verificar el flujo completo con los servicios reales del
  Kernel Service Bus (`image.generate`, etc.): no existen en este repo
  (`kernel/services/` fue removido en el split). Los hallazgos B-7 y M-6
  se evaluaron sobre el código del kernel y su contrato, no contra un
  servicio real.
- **No pude** verificar el despliegue con `docker-compose` (no existe) ni
  el enforcement de `AccessManager` de punta a punta (no hay consumidor).
- Las versiones del manifiesto (`pydantic==2.13.5`, `fastapi==0.141.1`,
  `httpx2`, etc.) y las fechas del repo son las declaradas por el propio
  proyecto; `pip-audit` reportó "No known vulnerabilities found" contra
  el set instalado.
