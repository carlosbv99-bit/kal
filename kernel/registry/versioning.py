"""
Persistencia versionada de herramientas dinámicas.

Antes de esto, una herramienta dinámica activada solo existía como un
string `source_code` en memoria de proceso (ver PendingTool/
DynamicSandboxedTool en registry.py) — nada llegaba a disco, y por
tanto no había manera de "volver a la versión anterior" ni de firmar
algo persistente. Cada activación (inicial o re-propuesta con código
nuevo) queda como un archivo `<name>_v<N>.py` inmutable — nunca se
sobreescribe una versión ya escrita, igual espíritu que el audit log
append-only.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

DEFAULT_VERSIONS_DIR = Path("data/tool_versions")


class ToolVersionStore:
    def __init__(self, base_dir: Path | str = DEFAULT_VERSIONS_DIR):
        self.base_dir = Path(base_dir)

    def _tool_dir(self, name: str) -> Path:
        tool_dir = self.base_dir / name
        tool_dir.mkdir(parents=True, exist_ok=True)
        return tool_dir

    def list_versions(self, name: str) -> list[int]:
        tool_dir = self.base_dir / name
        if not tool_dir.exists():
            return []
        versions = []
        for path in tool_dir.glob(f"{name}_v*.py"):
            suffix = path.stem.rsplit("_v", 1)[-1]
            if suffix.isdigit():
                versions.append(int(suffix))
        return sorted(versions)

    def latest_version(self, name: str) -> int | None:
        versions = self.list_versions(name)
        return versions[-1] if versions else None

    def next_version(self, name: str) -> int:
        return (self.latest_version(name) or 0) + 1

    def save_version(
        self, name: str, version: int, source_code: str, manifest_dict: dict, signature: str
    ) -> None:
        """
        `version` se calcula previamente (ver next_version) y se pasa
        explícito en vez de recalcularse aquí, porque el llamador
        (ToolRegistry._activate) necesita ese mismo número para firmar
        el contenido ANTES de escribirlo — firmar y persistir deben
        usar el mismo número de versión, no dos cálculos independientes.
        """
        tool_dir = self._tool_dir(name)
        (tool_dir / f"{name}_v{version}.py").write_text(source_code, encoding="utf-8")
        (tool_dir / f"{name}_v{version}.manifest.json").write_text(
            json.dumps(
                {
                    "manifest": manifest_dict,
                    "signature": signature,
                    "version": version,
                    "created_at": time.time(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def read_version(self, name: str, version: int) -> tuple[str, dict]:
        tool_dir = self.base_dir / name
        source_path = tool_dir / f"{name}_v{version}.py"
        manifest_path = tool_dir / f"{name}_v{version}.manifest.json"
        if not source_path.exists() or not manifest_path.exists():
            raise FileNotFoundError(f"No existe la versión {version} de la herramienta '{name}'")
        source_code = source_path.read_text(encoding="utf-8")
        sidecar = json.loads(manifest_path.read_text(encoding="utf-8"))
        return source_code, sidecar


tool_version_store = ToolVersionStore()
