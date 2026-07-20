"""
Taxonomía de acciones y alcances de red — segundo adaptador de
kernel/permissions/access_manager.py::AccessManager (el primero es
kernel/permissions/filesystem_permissions.py). Mismo criterio: 100%
stdlib, sin ningún import de utils.config, para poder copiarse tal
cual a un contenedor de skill si alguna vez lo necesita.
"""
from __future__ import annotations

from enum import Enum


class NetworkAction(str, Enum):
    BROWSE = "browse"      # tool_integration/adapters/browser.py::BrowserTool
    DOWNLOAD = "download"  # tool_integration/adapters/vscode_files.py::ImportResourceTool


class NetworkScope(str, Enum):
    # Único valor hoy — a diferencia de filesystem (workspace/home/
    # external, con riesgo creciente real), la red no tiene todavía un
    # alcance de menor/mayor riesgo definido. Deja lugar para agregar
    # uno (p.ej. "dominios conocidos" vs. "internet abierto") sin tener
    # que cambiar la forma del resto del mecanismo.
    INTERNET = "internet"
