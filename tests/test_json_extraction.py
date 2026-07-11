"""Tests de agent_core/llm/json_extraction.py."""
from __future__ import annotations

from agent_core.llm.json_extraction import extract_json_object


def test_extracts_bare_json():
    assert extract_json_object('{"name": "run_code", "arguments": {}}') == {
        "name": "run_code", "arguments": {},
    }


def test_extracts_json_wrapped_in_markdown_fence():
    content = 'Voy a hacer esto:\n```json\n{"steps": ["uno", "dos"]}\n```'
    assert extract_json_object(content) == {"steps": ["uno", "dos"]}


def test_extracts_json_embedded_in_surrounding_text():
    content = 'Claro, aquí tenés: {"steps": ["uno"]} espero que sirva'
    assert extract_json_object(content) == {"steps": ["uno"]}


def test_returns_none_for_empty_content():
    assert extract_json_object("") is None
    assert extract_json_object("   ") is None


def test_returns_none_for_plain_text_without_json():
    assert extract_json_object("No necesito ninguna herramienta para responder esto.") is None


def test_returns_none_for_non_object_json():
    assert extract_json_object("[1, 2, 3]") is None


def test_returns_none_for_malformed_json():
    assert extract_json_object("{esto no es json valido") is None


def test_falls_back_to_embedded_json_when_fence_has_no_object_inside():
    content = '```json\nno es json\n```\npero esto sí: {"steps": ["a"]}'
    assert extract_json_object(content) == {"steps": ["a"]}
