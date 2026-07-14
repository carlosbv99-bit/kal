"""
Herramienta para que el agente IDE de VS Code cree archivos/carpetas
REALES en el proyecto del usuario — hasta ahora, kal solo devolvía el
código como texto en la respuesta final (ver
tool_integration/adapters/core_tools.py::CodeExecutionTool, que
explícitamente prohíbe escribir archivos "que el usuario se lleve"),
dejando que el usuario copie/pegue a mano.

Límite arquitectónico real: este backend de Python NUNCA sabe qué
carpeta tiene abierta VS Code — solo la extensión lo sabe. Por eso esta
Tool NUNCA escribe nada a disco ella misma: solo propone la lista de
archivos (rutas relativas + contenido), consulta al Permission Manager
del Kernel (tool_integration/filesystem_access_manager.py) para dejar
auditoría y confirmar que la acción está permitida, y devuelve la
propuesta estructurada — la escritura real ocurre del lado de la
extensión (vscode.workspace.fs), tras que el usuario la apruebe en una
vista previa (ver vscode-extension/src/projectFiles.ts).
"""
from __future__ import annotations

from pathlib import PurePosixPath
from uuid import uuid4

from tool_integration.base_tool import Artifact, Tool, ToolManifest
from tool_integration.filesystem_access_manager import filesystem_access_manager
from tool_integration.filesystem_permissions import FilesystemAction, FilesystemScope

# Nombre estable usado como skill_name ante el Permission Manager y
# como filtro de exclusión del toolset para clientes que no son VS Code
# (ver agent_core/llm/agent_loop.py::_VSCODE_ONLY_TOOL_NAMES) — el
# cliente web no tiene forma de escribir un archivo real, ofrecerle
# esta herramienta ahí solo generaría una propuesta que nadie puede
# aplicar nunca.
VSCODE_INTEGRATION_SKILL_NAME = "vscode_integration"


class ProjectFilesRejectedError(Exception):
    """Alguno de los paths propuestos no es válido — nunca se llega a proponer nada."""


def _validate_relative_path(path: str) -> None:
    if not path or not path.strip():
        raise ProjectFilesRejectedError("Un archivo propuesto tiene una ruta vacía.")
    pure = PurePosixPath(path.replace("\\", "/"))
    if pure.is_absolute():
        raise ProjectFilesRejectedError(
            f"'{path}' es una ruta absoluta — usá siempre rutas RELATIVAS al proyecto abierto."
        )
    if ".." in pure.parts:
        raise ProjectFilesRejectedError(f"'{path}' intenta salir de la carpeta del proyecto ('..') — no permitido.")


class ProposeProjectFilesTool(Tool):
    manifest = ToolManifest(
        name="propose_project_files",
        description=(
            "Propone crear uno o más archivos/carpetas NUEVOS en el proyecto real que el "
            "usuario tiene abierto en su editor (una página web, un proyecto con varios "
            "archivos, etc.) — a diferencia de run_code, esto SÍ termina en archivos "
            "reales que el usuario se lleva. El usuario ve una vista previa y decide si "
            "aplicarla, nunca se escribe nada sin su aprobación explícita. "
            "'path' de cada archivo tiene que ser SIEMPRE una ruta RELATIVA a la raíz del "
            "proyecto (p.ej. 'index.html', 'css/estilos.css') — nunca una ruta absoluta "
            "(como '/home/...' o 'C:\\...') ni un path con '..'; esos se rechazan."
        ),
        created_by="system",
        requires_filesystem_write=True,
        parameters_schema={
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "description": "Lista de archivos a proponer",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Ruta RELATIVA al proyecto, p.ej. 'index.html'"},
                            "content": {"type": "string", "description": "Contenido completo del archivo"},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            "required": ["files"],
        },
    )

    def execute(self, files: list[dict], **kwargs) -> Artifact:
        if not files:
            raise ProjectFilesRejectedError("'files' es requerido, con al menos un archivo.")
        for f in files:
            _validate_relative_path(f.get("path", ""))

        decision = filesystem_access_manager.evaluate(
            skill_name=VSCODE_INTEGRATION_SKILL_NAME,
            scope=FilesystemScope.WORKSPACE,
            action=FilesystemAction.CREATE,
            resource_key="workspace",
        )

        if decision != "auto_allowed":
            # Fail-closed: sin un canal síncrono de aprobación humana a
            # mitad de un turno de chat, no se puede simplemente esperar
            # — mismo criterio que self-modification/tools dinámicos,
            # nunca se procede como si el permiso ya estuviera dado.
            return Artifact(
                modality="project_files",
                uri="",
                metadata={"status": "requires_approval", "files": []},
            )

        return Artifact(
            modality="project_files",
            uri="",
            metadata={
                "status": "proposed",
                "request_id": str(uuid4()),
                "files": [{"path": f["path"], "content": f["content"]} for f in files],
            },
        )
