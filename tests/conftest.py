"""
Fixtures compartidos para los tests de integración que requieren un
daemon Docker real (test_sandbox_integration.py y
test_sandbox_escape_resistance.py).

Centralizar aquí evita crear un cliente Docker por archivo de test y
mantiene la lógica de "saltar si no hay Docker" en un solo lugar.
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
