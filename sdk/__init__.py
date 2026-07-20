"""
SDK oficial de kal: la ÚNICA superficie pública que una Skill (propia
o de terceros) debería importar. Nunca `kernel.*` ni `agent_core.*` —
esos son detalles internos del proceso principal que una Skill
aislada, corriendo en su propio contenedor Docker efímero, jamás toca
directamente.

100% stdlib en los 4 módulos (skill.py, artifacts.py, permissions.py,
context.py) — es justamente lo que permite copiar el paquete completo
dentro de cada contenedor de Skill (ver
kernel/registry/sandboxed_skill.py::_kal_runtime_files()) sin arrastrar
ninguna dependencia pesada ni de red.

Antes de este paquete, una Skill hacía
`from tool_integration.base_tool import Artifact, Tool` — un import a
una ruta interna del kernel, no a una API pública nombrada y
versionada. `kernel/` (el resto de la infraestructura: registro,
permisos, sandbox, bus de servicios) DEPENDE de este paquete, nunca al
revés — `Permission`/`Tool`/`ToolManifest`/`Artifact` viven acá como
fuente ÚNICA.
"""
from __future__ import annotations

from sdk.artifacts import Artifact
from sdk.context import KernelError, call
from sdk.permissions import Permission
from sdk.skill import Tool, ToolManifest

__all__ = ["Artifact", "KernelError", "Permission", "Tool", "ToolManifest", "call"]
