"""
Formato de mensaje del Kernel Service Bus: JSON-RPC 2.0 (subconjunto),
sobre líneas newline-delimited — mismo formato que ya usa LSP (Language
Server Protocol) para el mismo problema (proceso aislado hablando con
un host de confianza), en vez de inventar un esquema propio. Da gratis
una convención de códigos de error y un campo `id` para matchear
pedido/respuesta.

Funciones puras acá — nada de sockets, para poder testear el formato
de los mensajes sin Docker ni un servidor real.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

JSONRPC_VERSION = "2.0"

# Códigos de error estilo JSON-RPC 2.0 (rango reservado -32000 a -32099
# para errores definidos por la aplicación, el resto son los estándar).
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32000
PERMISSION_DENIED = -32001


class ProtocolError(Exception):
    """Un mensaje no se pudo parsear como un pedido JSON-RPC válido."""


@dataclass
class Request:
    id: int | str
    method: str  # "<servicio>.<acción>", p.ej. "image.generate"
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def service(self) -> str:
        return self.method.partition(".")[0]

    @property
    def action(self) -> str:
        return self.method.partition(".")[2]


def parse_request(line: str) -> Request:
    try:
        data = json.loads(line)
    except json.JSONDecodeError as e:
        raise ProtocolError(f"línea no es JSON válido: {e}") from e

    if not isinstance(data, dict):
        raise ProtocolError("el mensaje debe ser un objeto JSON")
    if data.get("jsonrpc") != JSONRPC_VERSION:
        raise ProtocolError(f"jsonrpc debe ser '{JSONRPC_VERSION}'")
    if "id" not in data:
        raise ProtocolError("falta 'id'")
    method = data.get("method")
    if not isinstance(method, str) or "." not in method:
        raise ProtocolError("'method' debe ser un string '<servicio>.<acción>'")
    params = data.get("params", {})
    if not isinstance(params, dict):
        raise ProtocolError("'params' debe ser un objeto")

    return Request(id=data["id"], method=method, params=params)


def success_response(request_id: int | str, result: dict[str, Any]) -> str:
    return json.dumps({"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result})


def error_response(request_id: int | str | None, code: int, message: str) -> str:
    return json.dumps(
        {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": {"code": code, "message": message}}
    )
