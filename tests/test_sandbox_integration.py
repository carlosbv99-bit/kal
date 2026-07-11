"""
Tests de integración del sandbox contra un daemon Docker real.

Se saltan automáticamente si Docker no está disponible en el entorno
(p.ej. este mismo entorno de desarrollo de Claude no lo tiene). Ejecutar
en una máquina con Docker instalado:

    pytest tests/test_sandbox_integration.py -v

Cada test corresponde a una garantía de seguridad concreta del sandbox,
no solo a "funciona". Si alguno falla, es una regresión de seguridad,
no solo un bug funcional.
"""
from __future__ import annotations

from tests.conftest import requires_docker

pytestmark = requires_docker


def test_successful_execution_returns_stdout(runner):
    result = runner.run("print('hola desde el sandbox')")
    assert result.status == "success"
    assert "hola desde el sandbox" in result.stdout
    assert result.exit_code == 0


def test_runtime_error_is_captured_not_raised(runner):
    result = runner.run("raise ValueError('fallo esperado')")
    assert result.status == "error"
    assert "ValueError" in result.stderr
    assert result.exit_code != 0


def test_network_is_blocked_by_default(runner):
    """
    Garantía de seguridad crítica: sin network_mode=none, esto podría
    exfiltrar datos. Debe fallar al intentar conectar, no tener éxito.
    """
    code = (
        "import socket\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.settimeout(3)\n"
        "s.connect(('8.8.8.8', 53))\n"
        "print('CONEXION_EXITOSA')"  # si esto se imprime, es una fuga de seguridad
    )
    result = runner.run(code)
    assert "CONEXION_EXITOSA" not in result.stdout
    assert result.status != "success"


def test_execution_timeout_is_enforced(runner):
    """
    Garantía de seguridad: un bucle infinito no debe colgar el sistema
    indefinidamente, debe cortarse al llegar al timeout configurado.
    """
    result = runner.run("while True: pass")
    assert result.status == "timeout"


def test_filesystem_is_read_only_outside_workspace(runner):
    """
    Garantía de seguridad: el código no debe poder escribir fuera de
    /workspace, ni siquiera en directorios típicamente escribibles.
    """
    code = (
        "try:\n"
        "    with open('/etc/malicious', 'w') as f:\n"
        "        f.write('x')\n"
        "    print('ESCRITURA_EXITOSA')\n"
        "except Exception as e:\n"
        "    print('BLOQUEADO:', type(e).__name__)\n"
    )
    result = runner.run(code)
    assert "ESCRITURA_EXITOSA" not in result.stdout
    assert "BLOQUEADO" in result.stdout


def test_workspace_itself_is_writable(runner):
    """Verifica que /workspace SÍ es escribible (no es un falso positivo del test anterior)."""
    code = (
        "with open('/workspace/test_output.txt', 'w') as f:\n"
        "    f.write('ok')\n"
        "print('ESCRITURA_WORKSPACE_OK')\n"
    )
    result = runner.run(code)
    assert "ESCRITURA_WORKSPACE_OK" in result.stdout
    assert result.status == "success"


def test_memory_limit_kills_process(runner):
    """
    Garantía de seguridad: un proceso que intenta consumir memoria muy
    por encima del límite configurado debe ser terminado por el OOM
    killer, no colgar el host.
    """
    code = (
        "data = []\n"
        "while True:\n"
        "    data.append(b'0' * 10_000_000)\n"  # ~10MB por iteración
    )
    result = runner.run(code)
    assert result.status in ("resource_limit_exceeded", "timeout", "error")
    assert result.status != "success"


def test_fork_bomb_is_contained(runner):
    """
    Garantía de seguridad: pids_limit debe evitar que un fork bomb
    agote los recursos del host.
    """
    code = (
        "import os\n"
        "while True:\n"
        "    os.fork()\n"
    )
    result = runner.run(code)
    assert result.status != "success"


# --- output_dir / output_files (agregado para el aislamiento real de skills) ---


def test_output_dir_files_are_read_back(runner):
    code = (
        "with open('/workspace/output/result.txt', 'w') as f:\n"
        "    f.write('contenido generado dentro del sandbox')\n"
    )
    result = runner.run(code, output_dir="output")

    assert result.status == "success"
    assert result.output_files == {"result.txt": b"contenido generado dentro del sandbox"}


def test_output_dir_supports_binary_and_nested_paths(runner):
    code = (
        "import os\n"
        "os.makedirs('/workspace/output/nested', exist_ok=True)\n"
        "with open('/workspace/output/nested/binary.bin', 'wb') as f:\n"
        "    f.write(bytes([0, 1, 2, 255]))\n"
    )
    result = runner.run(code, output_dir="output")

    assert result.status == "success"
    assert result.output_files == {"nested/binary.bin": bytes([0, 1, 2, 255])}


def test_no_output_dir_requested_means_no_output_files(runner):
    result = runner.run("print('sin output_dir')")
    assert result.output_files == {}


def test_workspace_files_supports_binary_content_and_subdirectories(runner):
    code = (
        "with open('/workspace/skill/data.bin', 'rb') as f:\n"
        "    print('LEIDO:', f.read())\n"
    )
    result = runner.run(code, workspace_files={"skill/data.bin": bytes([9, 8, 7])})

    assert result.status == "success"
    assert "LEIDO: b'\\t\\x08\\x07'" in result.stdout


# --- extra_mounts (agregado para el Kernel Service Bus: montar el socket
# Unix del bus, que vive en un directorio aparte del workdir principal) ---


def test_extra_mounts_are_bind_mounted_into_the_container(tmp_path, runner):
    (tmp_path / "marker.txt").write_text("contenido del host", encoding="utf-8")

    code = (
        "with open('/workspace/.kal/marker.txt') as f:\n"
        "    print('LEIDO:', f.read())\n"
    )
    result = runner.run(code, extra_mounts={str(tmp_path): "/workspace/.kal"})

    assert result.status == "success"
    assert "LEIDO: contenido del host" in result.stdout


def test_without_extra_mounts_the_path_does_not_exist(runner):
    code = (
        "import os\n"
        "print('EXISTE' if os.path.exists('/workspace/.kal') else 'NO_EXISTE')\n"
    )
    result = runner.run(code)

    assert "NO_EXISTE" in result.stdout


# --- timeout_seconds (agregado para el Kernel Service Bus: una skill que
# llama a un servicio real como "image.generate" puede tardar bastante
# más que el timeout por defecto del sandbox) ---


def test_timeout_seconds_override_allows_longer_execution(runner):
    """Código que duerme más que el timeout por defecto (30s, ver
    config.yaml) pero menos que el override explícito debe terminar
    bien, no cortarse por timeout."""
    result = runner.run("import time; time.sleep(2); print('listo')", timeout_seconds=60)
    assert result.status == "success"
    assert "listo" in result.stdout


def test_timeout_seconds_override_still_enforces_a_shorter_limit(runner):
    result = runner.run("import time; time.sleep(10)", timeout_seconds=2)
    assert result.status == "timeout"
