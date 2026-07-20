"""
Tests de agent_core/orchestrator.py::_artifact_url — hallazgo de la
revisión de seguridad 2026-07-09: la función debe ser segura contra
path traversal POR SÍ SOLA, sin depender únicamente de que Starlette
bloquee el traversal real al servir el archivo después.
"""
from __future__ import annotations

from pathlib import Path

from agent_core.orchestrator import _ARTIFACTS_DIR, _artifact_url


def test_a_real_artifact_path_resolves_to_its_url():
    real_path = _ARTIFACTS_DIR / "images" / "algo.png"
    assert _artifact_url(str(real_path)) == "/artifacts/images/algo.png"


def test_a_path_outside_artifacts_dir_returns_none():
    assert _artifact_url("/etc/passwd") is None


def test_a_traversal_attempt_disguised_as_a_prefix_match_is_rejected():
    """
    Antes de este fix, Path("data/artifacts/../../etc/passwd").relative_to(
    "data/artifacts") tenía éxito (sin resolver ".." primero), devolviendo
    una URL "/artifacts/../../etc/passwd" — el escape real dependía
    enteramente de que Starlette lo bloqueara después. Con resolve()
    antes de comparar, esto debe rechazarse acá mismo.
    """
    traversal_uri = str(_ARTIFACTS_DIR / ".." / ".." / "etc" / "passwd")
    assert _artifact_url(traversal_uri) is None


def test_a_relative_uri_under_the_real_artifacts_dir_still_resolves():
    relative_uri = str(Path("data", "artifacts", "audio", "algo.wav"))
    assert _artifact_url(relative_uri) == "/artifacts/audio/algo.wav"
