"""
Taxonomía de acciones y alcances de filesystem — acción
(create/read/modify/delete/rename) × alcance (workspace/home/external),
ortogonal al modelo de permisos estilo Android de permissions.py
(FILESYSTEM_READ/FILESYSTEM_WRITE siguen siendo el gate de "puede pedir
tocar el filesystem en absoluto"; esto es "qué exactamente, y dónde").

IMPORTANTE — mismo criterio que permissions.py: 100% stdlib, sin
ningún import de utils.config ni de nada que no exista dentro de un
contenedor de skill, para poder copiarse tal cual si una skill en
Docker necesita conocer esta taxonomía. La lógica de DECISIÓN (política
configurable, concesiones persistidas, auditoría) vive aparte, en
kernel/permissions/filesystem_access_manager.py, que NUNCA se envía a un
contenedor — mismo motivo que separa permission_cascade.py de
permissions.py.
"""
from __future__ import annotations

from enum import Enum


class FilesystemAction(str, Enum):
    CREATE = "create"
    READ = "read"
    MODIFY = "modify"
    DELETE = "delete"
    RENAME = "rename"


class FilesystemScope(str, Enum):
    # El workspace/proyecto actualmente abierto (VS Code) o el
    # artifact_dir propio de una skill — el caso común, de menor riesgo.
    WORKSPACE = "workspace"
    # La carpeta home del usuario, fuera de cualquier workspace/artifact_dir.
    HOME = "home"
    # Cualquier otra ruta absoluta fuera de las dos anteriores.
    EXTERNAL = "external"
