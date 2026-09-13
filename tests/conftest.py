"""
Fixtures compartidos — Docker real para los tests de integración de
sandbox (test_sandbox_integration.py, test_sandbox_escape_resistance.py).

El fixture que neutralizaba el Conversation Engine (agent_core, kal-in)
se retiró acá — no existe ese módulo en el kernel puro. Ver
tests/conftest.py de kal-in para esa parte.
"""
from __future__ import annotations

import docker
import pytest
from docker.errors import DockerException

from kernel.lifecycle.docker_runner import DockerSandboxRunner


def docker_available() -> bool:
    try:
        docker.from_env().ping()
        return True
    except DockerException:
        return False


requires_docker = pytest.mark.skipif(
    not docker_available(), reason="Docker no disponible en este entorno"
)


@pytest.fixture(scope="session")
def runner():
    return DockerSandboxRunner()
