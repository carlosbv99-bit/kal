"""
Tests de kernel/lifecycle/docker_runner.py::DockerSandboxRunner._join_within()
— defensa en profundidad contra `workspace_files`/`output_dir` con
claves tipo "../../etc/algo" (footgun latente señalado en la auditoría
externa del 2026-09-26, relacionado a A-1): hoy ningún llamador real
alimenta esto con input no confiable, pero un llamador futuro o un
refactor sí podría.
"""
from __future__ import annotations

import pytest

from kernel.lifecycle.docker_runner import DockerSandboxRunner


def test_a_normal_relative_path_is_allowed(tmp_path):
    result = DockerSandboxRunner._join_within(tmp_path, "sub/archivo.txt")
    assert result == (tmp_path / "sub" / "archivo.txt").resolve()


def test_path_traversal_via_dotdot_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="fuera del workdir"):
        DockerSandboxRunner._join_within(tmp_path, "../../../../etc/passwd")


def test_an_absolute_path_that_escapes_base_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="fuera del workdir"):
        DockerSandboxRunner._join_within(tmp_path, "/etc/passwd")


def test_prepare_workdir_rejects_a_workspace_files_key_that_escapes(tmp_path):
    with pytest.raises(ValueError, match="fuera del workdir"):
        DockerSandboxRunner._prepare_workdir(
            tmp_path, "print('hola')", {"../../fuera_del_workdir.txt": "contenido"}
        )


def test_run_rejects_an_output_dir_that_escapes_the_workdir(monkeypatch):
    """
    No hace falta Docker real para este chequeo: la validación de
    output_dir corre ANTES de tocar containers.run().
    """
    runner = DockerSandboxRunner()

    result = runner.run("print('hola')", output_dir="../../fuera_del_workdir")

    assert result.status == "error"
    assert "fuera del workdir" in result.stderr
