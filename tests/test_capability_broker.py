"""
Tests de agent_core/capability_broker.py — el mapeo capacidad -> nombres
de herramientas reales. No hay ninguna lógica de "elegir entre varios
proveedores" todavía (no existe ese caso real) — solo une los conjuntos
de herramientas para las capacidades pedidas.
"""
from __future__ import annotations

from agent_core.capability_broker import CapabilityBroker


def test_tool_names_for_a_single_known_capability():
    broker = CapabilityBroker()

    result = broker.tool_names_for(["image-generation"])

    assert "image_generation" in result
    assert "image_via_kernel" in result
    assert "qr_code" in result


def test_tool_names_for_merges_multiple_capabilities():
    broker = CapabilityBroker()

    result = broker.tool_names_for(["coding", "image-generation"])

    assert "run_code" in result
    assert "image_generation" in result


def test_tool_names_for_unknown_capability_contributes_nothing():
    broker = CapabilityBroker()

    result = broker.tool_names_for(["esto-no-existe"])

    assert result == frozenset()


def test_tool_names_for_empty_list_is_empty():
    broker = CapabilityBroker()

    assert broker.tool_names_for([]) == frozenset()


def test_conversation_capability_unlocks_nothing():
    broker = CapabilityBroker()

    assert broker.tool_names_for(["conversation"]) == frozenset()


def test_coding_and_vscode_only_tools_never_leak_into_multimedia_unlock():
    # coding mapea a herramientas VS-Code-only (propose_project_files,
    # read_workspace_file) — esto es correcto en sí (ver diseño), pero
    # la barrera de seguridad real vive en agent_loop.py (intersección
    # con _MULTIMEDIA_TOOL_NAMES), no acá — este test solo confirma que
    # el broker en sí devuelve esos nombres tal cual, sin filtrar nada.
    broker = CapabilityBroker()

    result = broker.tool_names_for(["coding"])

    assert "propose_project_files" in result
    assert "read_workspace_file" in result
