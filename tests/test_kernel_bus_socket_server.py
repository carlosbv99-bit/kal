"""
Tests de kernel_bus/socket_server.py::KernelBusSocketServer — la
plomería del socket Unix en sí (permisos declarados, auditoría,
límites), con un cliente de socket real pero SIN Docker (el contenedor
solo le agrega una frontera de proceso/filesystem al mismo socket, la
lógica de arriba es independiente de eso — ver
tests/test_sandboxed_skill.py para el caso con Docker real de punta a
punta).
"""
from __future__ import annotations

import json
import socket
import tempfile
from pathlib import Path

import pytest

from kernel_bus.bus import KernelServiceBus
from kernel_bus.socket_server import KernelBusSocketServer


class FakeService:
    def echo(self, text):
        return {"echoed": text}

    def boom(self):
        raise RuntimeError("boom interno")


@pytest.fixture
def bus():
    b = KernelServiceBus()
    b.register("test", FakeService())
    return b


@pytest.fixture
def socket_path(tmp_path):
    return tmp_path / "kernel.sock"


def _send(sock_path: Path, message: dict) -> dict:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(3)
    sock.connect(str(sock_path))
    sock.sendall((json.dumps(message) + "\n").encode("utf-8"))
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
    sock.close()
    line, _, _ = buf.partition(b"\n")
    return json.loads(line.decode("utf-8"))


def test_allowed_method_dispatches_successfully(bus, socket_path):
    server = KernelBusSocketServer(bus, allowed_methods=["test.echo"], socket_path=socket_path, skill_name="prueba")
    server.start()
    try:
        response = _send(socket_path, {"jsonrpc": "2.0", "id": 1, "method": "test.echo", "params": {"text": "hola"}})
    finally:
        server.stop()

    assert response == {"jsonrpc": "2.0", "id": 1, "result": {"echoed": "hola"}}


def test_method_not_declared_is_rejected_before_touching_the_bus(bus, socket_path):
    server = KernelBusSocketServer(bus, allowed_methods=["test.echo"], socket_path=socket_path, skill_name="prueba")
    server.start()
    try:
        response = _send(socket_path, {"jsonrpc": "2.0", "id": 1, "method": "test.boom", "params": {}})
    finally:
        server.stop()

    assert response["error"]["code"] == -32001  # PERMISSION_DENIED
    assert "no está declarado" in response["error"]["message"]


def test_action_exception_becomes_clear_error_response(bus, socket_path):
    server = KernelBusSocketServer(bus, allowed_methods=["test.boom"], socket_path=socket_path, skill_name="prueba")
    server.start()
    try:
        response = _send(socket_path, {"jsonrpc": "2.0", "id": 1, "method": "test.boom", "params": {}})
    finally:
        server.stop()

    assert response["error"]["code"] == -32000  # INTERNAL_ERROR
    assert "boom interno" in response["error"]["message"]


def test_calls_and_denials_are_audited(bus, socket_path, monkeypatch, tmp_path):
    from audit.audit_log import audit_log

    monkeypatch.setattr(audit_log, "path", tmp_path / "audit.log")
    server = KernelBusSocketServer(bus, allowed_methods=["test.echo"], socket_path=socket_path, skill_name="auditada")
    server.start()
    try:
        _send(socket_path, {"jsonrpc": "2.0", "id": 1, "method": "test.echo", "params": {"text": "x"}})
        _send(socket_path, {"jsonrpc": "2.0", "id": 2, "method": "test.no_declarado", "params": {}})
    finally:
        server.stop()

    entries = audit_log.tail(5)
    event_types = {e["event_type"] for e in entries}
    assert "kernel_service_call" in event_types
    assert "kernel_service_denied" in event_types


def test_max_requests_stops_accepting_after_the_limit(bus, socket_path):
    server = KernelBusSocketServer(
        bus, allowed_methods=["test.echo"], socket_path=socket_path, skill_name="prueba",
        max_requests=1, idle_timeout=2,
    )
    server.start()
    try:
        first = _send(socket_path, {"jsonrpc": "2.0", "id": 1, "method": "test.echo", "params": {"text": "1"}})
        assert first["result"] == {"echoed": "1"}

        with pytest.raises(ConnectionRefusedError):
            _send(socket_path, {"jsonrpc": "2.0", "id": 2, "method": "test.echo", "params": {"text": "2"}})
    finally:
        server.stop()
