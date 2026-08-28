"""
Tests de tool_integration/adapters/text_file.py::CreateTextFileTool.

HALLAZGO REAL EN USO (2026-08-26): un pedido de "crear un .txt con un
poema" desde el cliente web no tenía ninguna herramienta que lo
pudiera cumplir — kal respondió correctamente que no podía, pero la
capacidad en sí no existía. Este tool la agrega, reusando el mismo
mecanismo de artifacts (data/artifacts/, servido vía /artifacts) que ya
usan imagen/audio/video.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tool_integration.adapters.text_file import CreateTextFileTool
from utils.config import settings


@pytest.fixture
def tool(tmp_path, monkeypatch):
    monkeypatch.setattr(settings.text_files, "artifact_dir", str(tmp_path / "text_files"))
    return CreateTextFileTool()


def test_writes_a_real_txt_file_with_the_given_content(tool):
    artifact = tool.execute(content="Línea 1\nLínea 2\n", filename="poema")

    assert artifact.modality == "document"
    path = Path(artifact.uri)
    assert path.exists()
    assert path.suffix == ".txt"
    assert path.read_text(encoding="utf-8") == "Línea 1\nLínea 2\n"


def test_metadata_includes_filename_and_length(tool):
    artifact = tool.execute(content="hola", filename="notas")

    assert artifact.metadata["filename"].startswith("notas-")
    assert artifact.metadata["filename"].endswith(".txt")
    assert artifact.metadata["length_chars"] == 4


def test_filename_with_txt_extension_does_not_get_it_duplicated(tool):
    """
    BUG REAL ENCONTRADO EN USO (2026-08-26): el modelo a veces manda el
    nombre CON extensión ("poema.txt") — sin este chequeo, el archivo
    terminaba llamándose "poema.txt-<id>.txt".
    """
    artifact = tool.execute(content="x", filename="poema.txt")

    assert artifact.metadata["filename"].startswith("poema-")
    assert artifact.metadata["filename"].count(".txt") == 1


def test_missing_filename_falls_back_to_default(tool):
    artifact = tool.execute(content="contenido sin nombre")

    assert artifact.metadata["filename"].startswith("documento-")


@pytest.mark.parametrize("bad_filename", ["../../etc/passwd", "a/b", "a\\b", ""])
def test_unsafe_filename_falls_back_to_default_instead_of_failing(tool, bad_filename):
    artifact = tool.execute(content="x", filename=bad_filename)

    assert artifact.modality == "document"
    assert artifact.metadata["filename"].startswith("documento-")
    # Nunca escribe fuera del artifact_dir configurado.
    assert Path(artifact.uri).parent == Path(settings.text_files.artifact_dir)


def test_content_over_the_configured_limit_is_rejected(tool):
    monkeypatch_max = 10
    tool.cfg.max_length_chars = monkeypatch_max

    artifact = tool.execute(content="x" * (monkeypatch_max + 1))

    assert artifact.modality == "text"
    assert artifact.metadata["status"] == "error"
    assert "supera el máximo" in artifact.metadata["stderr"]


def test_two_calls_with_the_same_filename_do_not_collide(tool):
    first = tool.execute(content="uno", filename="poema")
    second = tool.execute(content="dos", filename="poema")

    assert first.uri != second.uri
    assert Path(first.uri).exists()
    assert Path(second.uri).exists()
