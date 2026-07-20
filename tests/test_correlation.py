"""
Tests de utils/correlation.py — el ContextVar en sí, sin ninguna
dependencia de logging/audit/Docker (esos casos de uso están cubiertos
en tests/test_audit_log.py, tests/test_kernel_bus_socket_server.py y
tests/test_sandbox_integration.py respectivamente).
"""
from __future__ import annotations

import re

from utils.correlation import get_correlation_id, new_id, set_correlation_id


def test_new_id_is_a_short_hex_string():
    value = new_id()
    assert re.fullmatch(r"[0-9a-f]{12}", value)


def test_new_id_is_different_each_time():
    assert new_id() != new_id()


def test_get_correlation_id_defaults_to_none():
    set_correlation_id(None)
    assert get_correlation_id() is None


def test_set_then_get_roundtrips():
    set_correlation_id("abc123")
    try:
        assert get_correlation_id() == "abc123"
    finally:
        set_correlation_id(None)
