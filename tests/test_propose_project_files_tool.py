"""
Tests de tool_integration/adapters/vscode_files.py::ProposeProjectFilesTool
— nunca escribe nada a disco (eso es responsabilidad de la extensión de
VS Code, el backend no conoce el workspace real), solo valida rutas y
consulta al Permission Manager del Kernel.
"""
from __future__ import annotations

import pytest

from tool_integration.adapters.vscode_files import ProjectFilesRejectedError, ProposeProjectFilesTool


def test_proposes_files_when_access_is_auto_allowed(monkeypatch):
    import tool_integration.adapters.vscode_files as module

    monkeypatch.setattr(module.filesystem_access_manager, "evaluate", lambda **kwargs: "auto_allowed")
    tool = ProposeProjectFilesTool()

    artifact = tool.execute(files=[{"path": "index.html", "content": "<html></html>"}])

    assert artifact.modality == "project_files"
    assert artifact.metadata["status"] == "proposed"
    assert artifact.metadata["files"] == [{"path": "index.html", "content": "<html></html>"}]
    assert artifact.metadata["request_id"]


def test_calls_the_permission_manager_with_the_expected_arguments(monkeypatch):
    import tool_integration.adapters.vscode_files as module

    calls = []
    monkeypatch.setattr(
        module.filesystem_access_manager, "evaluate",
        lambda **kwargs: calls.append(kwargs) or "auto_allowed",
    )
    tool = ProposeProjectFilesTool()

    tool.execute(files=[{"path": "a.txt", "content": "x"}])

    assert calls[0]["skill_name"] == "vscode_integration"
    assert calls[0]["scope"].value == "workspace"
    assert calls[0]["action"].value == "create"


def test_fails_closed_when_access_requires_approval(monkeypatch):
    import tool_integration.adapters.vscode_files as module

    monkeypatch.setattr(module.filesystem_access_manager, "evaluate", lambda **kwargs: "requires_approval")
    tool = ProposeProjectFilesTool()

    artifact = tool.execute(files=[{"path": "index.html", "content": "<html></html>"}])

    assert artifact.metadata["status"] == "requires_approval"
    assert artifact.metadata["files"] == []


def test_rejects_an_empty_files_list():
    tool = ProposeProjectFilesTool()
    with pytest.raises(ProjectFilesRejectedError, match="'files'"):
        tool.execute(files=[])


def test_rejects_an_absolute_path():
    tool = ProposeProjectFilesTool()
    with pytest.raises(ProjectFilesRejectedError, match="absoluta"):
        tool.execute(files=[{"path": "/etc/passwd", "content": "x"}])


def test_rejects_a_path_that_escapes_with_dotdot():
    tool = ProposeProjectFilesTool()
    with pytest.raises(ProjectFilesRejectedError, match="\\.\\."):
        tool.execute(files=[{"path": "../../etc/passwd", "content": "x"}])


def test_rejects_an_empty_path():
    tool = ProposeProjectFilesTool()
    with pytest.raises(ProjectFilesRejectedError, match="vacía"):
        tool.execute(files=[{"path": "", "content": "x"}])


def test_accepts_a_relative_path_with_subfolders(monkeypatch):
    import tool_integration.adapters.vscode_files as module

    monkeypatch.setattr(module.filesystem_access_manager, "evaluate", lambda **kwargs: "auto_allowed")
    tool = ProposeProjectFilesTool()

    artifact = tool.execute(files=[{"path": "css/estilos.css", "content": "body {}"}])

    assert artifact.metadata["files"][0]["path"] == "css/estilos.css"
