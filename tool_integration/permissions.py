"""
Modelo de permisos granulares por herramienta, estilo Android: cada
herramienta declara qué capacidades necesita, y kal solo le otorga
esas capacidades durante su propia ejecución — nunca acceso implícito
a nada que no haya declarado.

De estos 9 permisos, hoy solo NETWORK tiene un motor real que lo
aplica de forma diferenciada (network_mode en sandbox/docker_runner.py).
Los demás (GPU/CAMERA/MICROPHONE/CLIPBOARD/BROWSER/DOCKER) se pueden
declarar y quedan sujetos al mismo pipeline de aprobación, pero
SandboxExecutor los rechaza explícitamente en tiempo de ejecución
(ver RUNTIME_ENFORCED más abajo) hasta que exista el motor
correspondiente — mejor negar con un error claro que fingir un
permiso que no se puede confinar de verdad.

IMPORTANTE — este archivo se copia TAL CUAL dentro de cada contenedor
de skill (ver tool_integration/sandboxed_skill.py::_kal_runtime_files(),
toda skill necesita `Permission` a través de `base_tool.py`). Por eso
debe seguir siendo 100% stdlib, sin ningún import de utils.config ni de
nada que no exista dentro del contenedor — la cascada de permisos que sí
necesita settings.permissions vive aparte, en
tool_integration/permission_cascade.py, que NUNCA se envía a un
contenedor (solo lo usa el proceso principal, en agent_loop.py).
"""
from __future__ import annotations

from enum import Enum


class Permission(str, Enum):
    FILESYSTEM_READ = "filesystem_read"
    FILESYSTEM_WRITE = "filesystem_write"
    NETWORK = "network"
    GPU = "gpu"
    CAMERA = "camera"
    MICROPHONE = "microphone"
    CLIPBOARD = "clipboard"
    BROWSER = "browser"
    DOCKER = "docker"


# Permisos que el sandbox puede efectivamente aplicar/confinar hoy.
# FILESYSTEM_READ es implícito (todo el workspace es legible) y NETWORK
# se traduce en network_mode real. El resto no tiene motor todavía.
RUNTIME_ENFORCED: frozenset[Permission] = frozenset({
    Permission.FILESYSTEM_READ,
    Permission.NETWORK,
    Permission.FILESYSTEM_WRITE,
})

# Permisos declarables pero sin motor de aplicación real todavía.
# Ver docstring del módulo: una herramienta que los pida se rechaza en
# tiempo de ejecución, nunca se ejecuta como si el permiso no existiera.
UNSUPPORTED_RUNTIME_PERMISSIONS: frozenset[Permission] = frozenset(
    p for p in Permission if p not in RUNTIME_ENFORCED
)
