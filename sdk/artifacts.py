"""
Artifact — resultado tipado de cualquier herramienta (de primera parte
o Skill de terceros). Parte del SDK público (ver sdk/__init__.py): una
Skill nunca necesita saber de dónde viene este tipo, solo que su
Tool.execute() debe devolver uno.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Artifact:
    """Resultado de una herramienta que genera contenido (imagen/audio/video/etc)."""
    modality: str          # "image" | "audio" | "video" | "text" | ...
    uri: str                # referencia en almacenamiento de objetos, no el binario en sí
    metadata: dict[str, Any] = field(default_factory=dict)
