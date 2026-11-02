"""
Tests de kernel/lifecycle/docker_runner.py::DockerSandboxRunner.run() —
sandbox.workdir_root (B-3, auditoría externa 2026-09-27).

BUG REAL ENCONTRADO EN AUDITORÍA EXTERNA: el workdir temporal de cada
ejecución usaba SIEMPRE tempfile.gettempdir() implícito, sin forma de
cambiarlo. Si el daemon de Docker vive en otro mount namespace que este
proceso (Docker rootless, Docker Desktop, DOCKER_HOST remoto), el bind
mount apunta a un directorio que el daemon no ve — TODA ejecución
fallaba con un error que parece un bug de la skill, no lo que es: un
problema de topología entre este proceso y el daemon.
"""
from __future__ import annotations

import docker
from docker.errors import DockerException

from kernel.lifecycle.docker_runner import DockerSandboxRunner, SandboxResult
from tests.conftest import requires_docker


class _RecordingContainers:
    """
    Doble de prueba: registra los volumes con los que se llamó
    containers.run(), sin tocar Docker real. Lanza DockerException (no
    un tipo de excepción arbitrario) para que run() la atrape con su
    manejo normal de errores y devuelva un SandboxResult de "error" en
    vez de propagar — no hace falta simular un contenedor real que
    responda a wait()/logs() para lo que este test verifica.
    """

    def __init__(self):
        self.calls: list[dict] = []

    def run(self, *args, **kwargs):
        self.calls.append(kwargs)
        raise DockerException("no se necesita un contenedor real para este test")


class _FakeClient:
    def __init__(self, containers):
        self.containers = containers


def test_workdir_is_created_under_the_configured_workdir_root(tmp_path, monkeypatch):
    recording = _RecordingContainers()
    monkeypatch.setattr(docker, "from_env", lambda: _FakeClient(recording))
    runner = DockerSandboxRunner()
    # runner.cfg es settings.sandbox, el singleton global (ver
    # DockerSandboxRunner.__init__) — mutarlo directo filtraría a
    # cualquier otro test/runner del mismo proceso. monkeypatch lo
    # restaura solo al terminar este test.
    monkeypatch.setattr(runner.cfg, "workdir_root", str(tmp_path))

    runner.run("print('hola')")

    assert len(recording.calls) == 1
    mounted_workdir = next(iter(recording.calls[0]["volumes"]))
    assert mounted_workdir.startswith(str(tmp_path))


def test_workdir_root_none_keeps_the_default_system_tempdir(tmp_path, monkeypatch):
    """None (el default) preserva el comportamiento de siempre —
    tempfile.gettempdir(), nunca tmp_path de este test específico."""
    recording = _RecordingContainers()
    monkeypatch.setattr(docker, "from_env", lambda: _FakeClient(recording))
    runner = DockerSandboxRunner()
    assert runner.cfg.workdir_root is None

    runner.run("print('hola')")

    mounted_workdir = next(iter(recording.calls[0]["volumes"]))
    assert not mounted_workdir.startswith(str(tmp_path))


@requires_docker
def test_real_docker_still_works_with_an_explicit_workdir_root(tmp_path, monkeypatch):
    """De punta a punta con Docker real: apuntar workdir_root a un
    directorio explícito no rompe el camino feliz."""
    runner = DockerSandboxRunner()
    monkeypatch.setattr(runner.cfg, "workdir_root", str(tmp_path))

    result = runner.run("print('funciona')", timeout_seconds=30)

    assert result.status == "success"
    assert "funciona" in result.stdout


def _resultado_workdir_vacio() -> SandboxResult:
    return SandboxResult(
        status="error",
        stdout="",
        stderr="python: can't open file '/workspace/main.py': [Errno 2] No such file or directory",
        exit_code=2,
    )


def test_el_diagnostico_aparece_solo_si_la_prueba_confirma_que_el_daemon_no_ve_el_workdir(
    tmp_path, monkeypatch
):
    """
    B-3: el síntoma `can't open file '/workspace/main.py'` parece un bug de la
    skill y en realidad es topología (el daemon no ve el workdir). El
    diagnóstico solo se afirma si la prueba con centinela lo CONFIRMA.
    """
    runner = DockerSandboxRunner()
    monkeypatch.setattr(runner.cfg, "workdir_root", str(tmp_path))
    monkeypatch.setattr(runner, "_daemon_ve_el_workdir", lambda: False)
    auditados = []
    monkeypatch.setattr(
        "kernel.lifecycle.docker_runner.audit_log.record",
        lambda evento: auditados.append(evento),
    )

    resultado = runner._diagnosticar_workdir_invisible(_resultado_workdir_vacio(), tmp_path / "w")

    assert "daemon de Docker NO ve el directorio de trabajo" in resultado.stderr
    assert "sandbox.workdir_root" in resultado.stderr
    assert "TMPDIR" in resultado.stderr
    # La salida original se conserva: el diagnóstico se agrega, no reemplaza.
    assert "can't open file" in resultado.stderr
    assert auditados and auditados[0].event_type == "sandbox_workdir_no_visible"


def test_sin_confirmacion_no_se_inventa_ningun_diagnostico(tmp_path, monkeypatch):
    """La otra mitad, y la que más importa: si la prueba dice que el daemon SÍ
    ve el workdir (o no se pudo determinar), el stderr queda INTACTO."""
    runner = DockerSandboxRunner()

    for veredicto in (True, None):
        monkeypatch.setattr(runner, "_daemon_ve_el_workdir", lambda v=veredicto: v)
        original = _resultado_workdir_vacio()
        resultado = runner._diagnosticar_workdir_invisible(original, tmp_path / "w")
        assert resultado.stderr == original.stderr


def test_una_ejecucion_exitosa_no_se_toca(tmp_path, monkeypatch):
    runner = DockerSandboxRunner()
    monkeypatch.setattr(runner, "_daemon_ve_el_workdir", lambda: False)
    original = SandboxResult(status="success", stdout="hola", stderr="", exit_code=0)

    assert runner._diagnosticar_workdir_invisible(original, tmp_path / "w") is original
