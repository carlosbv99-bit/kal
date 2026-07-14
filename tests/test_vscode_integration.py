"""
Tests de agent_core/vscode_integration.py — instalación de la
extensión de kal en VS Code (v1: no instala VS Code mismo, ver
docstring del módulo).

Todo lo que llamaría a un binario real (code/npm/npx) está
mockeado — estos tests no dependen de tener VS Code/Node instalados
en la máquina que corre la suite. El smoke test manual real (con
binarios de verdad) se documenta aparte, en docs/HISTORY.md.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_core import vscode_integration
from agent_core.vscode_integration import (
    VSCodeIntegrationError,
    get_status,
    install_extension,
    is_code_cli_available,
    is_extension_installed,
)


def _ok(stdout: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def _fail(stderr: str = "boom") -> SimpleNamespace:
    return SimpleNamespace(returncode=1, stdout="", stderr=stderr)


# ---------- is_code_cli_available / is_extension_installed / get_status ----------

def test_is_code_cli_available_false_when_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert is_code_cli_available() is False


def test_is_extension_installed_false_when_code_cli_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert is_extension_installed() is False


def test_is_extension_installed_true_when_listed(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/code")
    monkeypatch.setattr(
        vscode_integration.subprocess, "run",
        lambda *a, **k: _ok(stdout="ms-python.python\nundefined_publisher.kal-vscode\n"),
    )
    assert is_extension_installed() is True


def test_is_extension_installed_false_when_not_listed(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/code")
    monkeypatch.setattr(vscode_integration.subprocess, "run", lambda *a, **k: _ok(stdout="ms-python.python\n"))
    assert is_extension_installed() is False


def test_get_status_combines_both_checks(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/code")
    monkeypatch.setattr(vscode_integration.subprocess, "run", lambda *a, **k: _ok(stdout="undefined_publisher.kal-vscode"))
    assert get_status() == {"code_cli_available": True, "installed": True}


# ---------- install_extension ----------

def test_install_extension_raises_when_code_cli_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    with pytest.raises(VSCodeIntegrationError, match="'code' no está en el PATH"):
        install_extension()


def test_install_extension_raises_when_npm_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/code" if name == "code" else None)
    with pytest.raises(VSCodeIntegrationError, match="npm no está instalado"):
        install_extension()


def test_install_extension_raises_when_a_step_fails(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/whatever")
    monkeypatch.setattr(vscode_integration, "_EXTENSION_DIR", tmp_path)

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["npm", "install"]:
            return _ok()
        if cmd[:3] == ["npm", "run", "compile"]:
            return _fail("compile error de prueba")
        return _ok()

    monkeypatch.setattr(vscode_integration.subprocess, "run", fake_run)

    with pytest.raises(VSCodeIntegrationError, match="npm run compile.*compile error de prueba"):
        install_extension()

    # No debería haber llegado a intentar empaquetar/instalar después del fallo.
    assert not any(c[:2] == ["code", "--install-extension"] for c in calls if len(c) > 1)


def test_install_extension_success_runs_all_steps_in_order(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/whatever")
    monkeypatch.setattr(vscode_integration, "_EXTENSION_DIR", tmp_path)

    calls = []
    monkeypatch.setattr(vscode_integration.subprocess, "run", lambda cmd, **k: (calls.append(cmd), _ok())[1])

    message = install_extension()

    assert "instalada" in message
    assert calls[0][:2] == ["npm", "install"]
    assert calls[1][:3] == ["npm", "run", "compile"]
    assert "@vscode/vsce" in calls[2]
    assert calls[3][:2] == ["code", "--install-extension"]
    # El .vsix temporal se limpia después de instalar, no queda residuo.
    assert list(tmp_path.glob("*.vsix")) == []


def test_install_extension_audits_success(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/whatever")
    monkeypatch.setattr(vscode_integration, "_EXTENSION_DIR", tmp_path)
    monkeypatch.setattr(vscode_integration.subprocess, "run", lambda cmd, **k: _ok())

    recorded = []
    monkeypatch.setattr(vscode_integration.audit_log, "record", lambda event: recorded.append(event))

    install_extension()

    assert len(recorded) == 1
    assert recorded[0].event_type == "vscode_extension_installed"
    assert recorded[0].outcome == "success"


def test_install_extension_audits_failure(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)

    recorded = []
    monkeypatch.setattr(vscode_integration.audit_log, "record", lambda event: recorded.append(event))

    with pytest.raises(VSCodeIntegrationError):
        install_extension()

    assert len(recorded) == 1
    assert recorded[0].event_type == "vscode_extension_installed"
    assert recorded[0].outcome == "failure"
