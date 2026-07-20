"""
Tests de kernel/api/protocol.py — formato de mensaje (JSON-RPC 2.0
sobre líneas newline-delimited). Funciones puras, sin socket.
"""
from __future__ import annotations

import json

import pytest

from kernel.api.protocol import (
    ProtocolError,
    Request,
    error_response,
    parse_request,
    success_response,
)


def test_parse_request_extracts_service_and_action():
    request = parse_request('{"jsonrpc": "2.0", "id": 1, "method": "image.generate", "params": {"prompt": "x"}}')

    assert request == Request(id=1, method="image.generate", params={"prompt": "x"})
    assert request.service == "image"
    assert request.action == "generate"


def test_parse_request_defaults_params_to_empty_dict():
    request = parse_request('{"jsonrpc": "2.0", "id": 1, "method": "image.generate"}')
    assert request.params == {}


def test_parse_request_rejects_non_json():
    with pytest.raises(ProtocolError):
        parse_request("esto no es json")


def test_parse_request_rejects_wrong_jsonrpc_version():
    with pytest.raises(ProtocolError):
        parse_request('{"jsonrpc": "1.0", "id": 1, "method": "image.generate"}')


def test_parse_request_rejects_missing_id():
    with pytest.raises(ProtocolError):
        parse_request('{"jsonrpc": "2.0", "method": "image.generate"}')


def test_parse_request_rejects_method_without_dot():
    with pytest.raises(ProtocolError):
        parse_request('{"jsonrpc": "2.0", "id": 1, "method": "generate"}')


def test_parse_request_rejects_non_dict_params():
    with pytest.raises(ProtocolError):
        parse_request('{"jsonrpc": "2.0", "id": 1, "method": "image.generate", "params": [1, 2]}')


def test_success_response_shape():
    response = json.loads(success_response(1, {"artifact": "artifact://image/x"}))
    assert response == {"jsonrpc": "2.0", "id": 1, "result": {"artifact": "artifact://image/x"}}


def test_error_response_shape():
    response = json.loads(error_response(1, -32001, "no autorizado"))
    assert response == {"jsonrpc": "2.0", "id": 1, "error": {"code": -32001, "message": "no autorizado"}}
