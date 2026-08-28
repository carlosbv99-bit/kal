"""
Adaptador para crear un archivo de texto/documento real y descargable
(poemas, notas, listas) — pieza que faltaba para que el cliente WEB
pudiera "entregar" un archivo, algo que hasta ahora solo existía para
VS Code vía propose_project_files (que nunca escribe nada del lado del
backend: la extensión aplica la propuesta). Este tool SÍ escribe un
archivo real en disco, bajo data/artifacts/text_files/, servido después
por el mismo mount /artifacts de solo lectura que ya usan imagen/audio/
video (ver agent_core/orchestrator.py::_artifact_url).

HALLAZGO REAL EN USO (2026-08-26): un usuario pidió "creá un .txt en
Documentos con un poema" desde el cliente web — kal respondió (correcto
en ese momento) que no podía, porque run_code no tiene acceso al
filesystem del host y propose_project_files es exclusiva de VS Code.
No había ninguna forma de entregar un archivo de texto simple al
cliente web. Este tool cierra ese hueco.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from sdk.artifacts import Artifact
from sdk.skill import Tool, ToolManifest
from utils.config import settings

# El modelo elige un nombre corto (p.ej. "poema"), nunca una ruta —
# esto rechaza cualquier separador de directorio o carácter que rompa
# el mount estático; un nombre inválido cae al default en vez de fallar.
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._ -]+$")
_DEFAULT_FILENAME = "documento"
_MAX_FILENAME_LENGTH = 80


class CreateTextFileTool(Tool):
    manifest = ToolManifest(
        name="create_text_file",
        description=(
            "Crea un archivo de texto real (.txt) descargable con el contenido dado — para poemas, "
            "notas, listas o cualquier documento simple que el usuario se quiera llevar. Para un "
            "proyecto de código con varios archivos, usar propose_project_files en cambio (solo VS Code)."
        ),
        requires_network=False,
        created_by="system",
        parameters_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Contenido completo del archivo de texto."},
                "filename": {
                    "type": "string",
                    "description": "Nombre del archivo sin extensión ni ruta (p.ej. 'poema'). Opcional.",
                },
            },
            "required": ["content"],
        },
    )

    def __init__(self):
        self.cfg = settings.text_files
        Path(self.cfg.artifact_dir).mkdir(parents=True, exist_ok=True)

    def execute(self, content: str, filename: str | None = None, **kwargs) -> Artifact:
        if len(content) > self.cfg.max_length_chars:
            return self._error(
                f"El contenido pedido ({len(content)} caracteres) supera el máximo permitido "
                f"({self.cfg.max_length_chars})."
            )
        safe_name = self._safe_filename(filename)
        artifact_id = uuid.uuid4().hex[:8]
        path = Path(self.cfg.artifact_dir) / f"{safe_name}-{artifact_id}.txt"
        path.write_text(content, encoding="utf-8")
        return Artifact(
            modality="document",
            uri=str(path),
            metadata={"filename": path.name, "length_chars": len(content)},
        )

    @staticmethod
    def _safe_filename(filename: str | None) -> str:
        if not filename:
            return _DEFAULT_FILENAME
        candidate = filename.strip()
        # BUG REAL ENCONTRADO EN USO (2026-08-26): el modelo a veces
        # manda el nombre CON extensión ("poema.txt") — sin esto, el
        # ".txt" que este método siempre agrega abajo quedaba duplicado
        # ("poema.txt-<id>.txt").
        if candidate.lower().endswith(".txt"):
            candidate = candidate[: -len(".txt")]
        candidate = candidate.strip()[:_MAX_FILENAME_LENGTH]
        if not candidate or not _SAFE_FILENAME_RE.match(candidate):
            return _DEFAULT_FILENAME
        return candidate

    @staticmethod
    def _error(message: str) -> Artifact:
        return Artifact(modality="text", uri="", metadata={"status": "error", "stderr": message})
