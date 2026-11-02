# Qué se trabaja en cada repositorio

Este archivo es el **autoritativo para kal**. Lo que hay que hacer en `kal-in` se anota en
`kal-in/docs/PENDIENTE.md`, y lo de Likay-OS en el repo de Likay: cada espacio lleva su
propia lista para que no haya dos copias que se desincronicen.

## Lo que corresponde a kal (acá)

| Ámbito | Archivos |
|---|---|
| El kernel | `kernel/` (registry, sandbox, permisos, lifecycle, api), `sdk/`, `audit/`, `code_analysis/` |
| Herramientas del kernel | `scripts/install_from_market.py`, firma de skills, `kernel/permissions/` |
| Skills compartidas con kal-in | `skills/<nombre>/` cuando el nombre existe en los dos repos |

## Lo que NO se hace acá

- `agent_core/` (la ruta `/chat`, el cliente del LLM, el catálogo de tools, las sesiones):
  es del host, o sea de `kal-in`.
- `scripts/run_kal.sh` y el arranque del servidor: son del host.
- Política de producto de Likay-OS (su UI, su pin, qué modelos permite).

## Cómo llega el trabajo a este repo

Al revés de lo habitual en la última sesión: varios fixes **ya están en `kal-in`** y hay que
traerlos acá **en su forma de kernel** (sin `agent_core`), corriendo los tests y el lint de
*este* repo por separado. Después de cada uno: portar de vuelta a `kal-in` citando el hash
del commit de acá, como pide `kal-in/CONTRIBUTING.es.md`.

## Pendiente en kal, en orden

1. **`deny_pending_tool()` + `POST /tools/{name}/deny` + evento `tool_denied`.**
   En `kal-in` existe (`kernel/registry/registry.py`, `audit/audit_log.py`); acá no.
   Sin esto la interfaz es asimétrica: un humano puede aprobar una herramienta pendiente
   pero no rechazarla, y la entrada queda en `_pending` para siempre.
2. **`deactivate_tool()` + `POST /tools/{name}/deactivate` + evento `tool_deactivated`.**
   `_active_tools` solo se escribe: la única forma de sacar una herramienta de circulación
   es reemplazarla por otra versión con `rollback_tool()`. Para una herramienta comprometida,
   "no se puede apagar" es un hueco real. Las Skills sí tienen el equivalente
   (`set_skill_enabled()` + `--disable`).
3. **`verify_tool_integrity()` tiene que auditar lo que detecta.**
   Hoy devuelve True/False en silencio, mientras `rollback_tool()` sí audita
   `tool_tamper_detected`. Es la única detección de manipulación del sistema sin rastro, y
   encima es on-demand (`GET /tools/{name}/verify`): nadie la sondea. En `kal-in` ya audita,
   con `detected_by: "verify_tool_integrity"`. El camino feliz **no** audita, a propósito.
4. **B-3: diagnóstico de workdir invisible.**
   `DockerSandboxRunner._workdir_visible`, `_diagnosticar_workdir_invisible()`,
   `_MARCADOR_WORKDIR_VACIO` y su llamada en `run()`. Si el daemon de Docker vive en otro
   mount namespace, hoy toda ejecución falla con un error que parece un bug del código de la
   skill (`can't open file '/workspace/main.py'`). En `kal-in` está.
5. **`_ALLOWED_EXTRA_MOUNT_ROOTS` parametrizado** (opcional, robustez).
   kal hardcodea `/workspace`; `kal-in` usa la allowlist `("/workspace", "/project")` porque
   self-modification monta el proyecto en `/project`. Adoptar la forma parametrizada con solo
   `/workspace` deja los dos repos con el mismo mecanismo (no cambia ninguna protección: las
   dos son allowlists angostas).
6. **Allowlist de claves de autor para el market (primitiva nueva).**
   `verify_skill_signature()` verifica contra la clave **embebida en el propio `skill.sig`**:
   prueba integridad, no autoría (hallazgo M-8). `install_from_market.py` acepta cualquier
   clave autofirmada. Acá va la primitiva (un conjunto de claves de autor confiables que el
   instalador exige) y el evento de auditoría del rechazo por clave desconocida; la
   **política** (qué claves) queda en cada consumidor — en `kal-in` primero.
8. **`allowed_domains` se declara y nunca se aplica (M-6).**
   `ToolManifest.allowed_domains` (y el campo equivalente en `skill.yaml`) promete
   una restricción de destinos que hoy no existe: con `Permission.NETWORK`
   concedido, el contenedor sale con `network_mode="bridge"` — internet completo,
   sin allowlist ni proxy de egreso. El campo se serializa y viaja por todos lados
   (`sdk/skill.py`, `kernel/registry/registry.py`), así que hoy es una promesa
   falsa, que es peor que no tenerlo. Dos salidas, ninguna barata: implementarlo
   de verdad (proxy de egreso, o `iptables`/`nft` dentro del contenedor) o sacarlo
   del manifest y documentar que la red es todo-o-nada por nivel de confianza.
   Mientras tanto, la única barrera real es el techo de `permission_cascade` en
   `config.yaml` (tier `skill`, hoy solo con `filesystem_read`).

7. **Tipo de evento de auditoría para la huella de la plantilla de chat** (si se decide
   hacerla): `audit/audit_log.py` es compartido, así que el tipo nuevo nace acá y después
   `kal-in` agrega la llamada a `/api/show` + hash por sesión.

## Nota sobre Likay-OS

Likay-OS consume kal por **submódulo fijado a un commit** (`vendor/kal`). Un fix acá **no
llega solo** a ninguna ISO: el bump del pin es un commit aparte, en Likay, y su mensaje
debería decir qué se está llevando y hasta qué commit.
