"""
SDK minúsculo para que una skill le pida algo a un servicio del kernel
(p.ej. generar una imagen) sin tener que cargar ella misma un modelo
pesado — ver kernel_bus/__init__.py para el porqué completo.

IMPORTANTE — igual que tool_integration/base_tool.py y
tool_integration/permissions.py, este archivo se copia TAL CUAL dentro
de cada contenedor de skill (ver
tool_integration/sandboxed_skill.py::_kal_runtime_files()). Por eso
debe seguir siendo 100% stdlib (`socket`, `json`) — nunca importa nada
de `kernel_bus` en sí: la skill solo habla el protocolo (JSON-RPC 2.0
sobre un socket Unix), nunca recibe una referencia a un objeto Python
del kernel.
"""
from __future__ import annotations

import json
import socket
from typing import Any

# Ruta fija dentro del contenedor — sandbox/skill_runner.py y
# tool_integration/sandboxed_skill.py se ponen de acuerdo en este mismo
# valor (el segundo monta el socket ahí antes de arrancar el contenedor).
SOCKET_PATH = "/workspace/.kal/kernel.sock"


class KernelError(Exception):
    """Un llamado al Kernel Service Bus falló — método no declarado
    para esta skill, servicio/acción inexistente, o la acción misma
    falló del lado del kernel (ver kernel_bus/socket_server.py)."""


def call(method: str, **params: Any) -> dict[str, Any]:
    """
    Le pide algo a un servicio del kernel:

        from tool_integration.kernel_client import call
        result = call("image.generate", prompt="un castillo medieval")
        result["artifact"]  # "artifact://image/<uuid>"

    `method` debe estar declarado en el `kernel_services` de
    skill.yaml — si no, el kernel rechaza el pedido antes de tocar
    nada real.
    """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(SOCKET_PATH)
        request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
        line = _read_line(sock)
    finally:
        sock.close()

    if line is None:
        raise KernelError("el kernel no respondió (conexión cerrada sin datos)")

    response = json.loads(line)
    if "error" in response:
        raise KernelError(response["error"]["message"])
    return response["result"]


def _read_line(sock: socket.socket) -> str | None:
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            return None
        buf += chunk
    line, _, _ = buf.partition(b"\n")
    return line.decode("utf-8")
