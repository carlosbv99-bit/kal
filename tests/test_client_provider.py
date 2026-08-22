"""
Tests de contrato de agent_core/client_provider.py — mismo espíritu
que tests/test_llm_provider.py: confirman que ClientProvider se
sostiene contra las DOS implementaciones reales (VSCodeClientProvider,
WebClientProvider), y que get_client_provider() es el único lugar que
compara `client` contra un string literal.
"""
from __future__ import annotations

from agent_core.client_provider import (
    _MULTIMEDIA_TOOL_NAMES,
    _VSCODE_CLIENT_INSTRUCTION,
    _VSCODE_ONLY_TOOL_NAMES,
    ClientProvider,
    VSCodeClientProvider,
    WebClientProvider,
    get_client_provider,
)


def test_vscode_client_provider_satisfies_the_client_provider_protocol():
    assert isinstance(VSCodeClientProvider(), ClientProvider)


def test_web_client_provider_satisfies_the_client_provider_protocol():
    assert isinstance(WebClientProvider(), ClientProvider)


def test_get_client_provider_returns_vscode_provider_for_vscode():
    assert isinstance(get_client_provider("vscode"), VSCodeClientProvider)


def test_get_client_provider_returns_web_provider_for_none():
    assert isinstance(get_client_provider(None), WebClientProvider)


def test_get_client_provider_returns_web_provider_for_web():
    assert isinstance(get_client_provider("web"), WebClientProvider)


def test_vscode_provider_system_prompt_addendum_is_the_vscode_instruction():
    assert get_client_provider("vscode").system_prompt_addendum() == _VSCODE_CLIENT_INSTRUCTION


def test_web_provider_system_prompt_addendum_is_none():
    assert get_client_provider("web").system_prompt_addendum() is None


def test_vscode_provider_excludes_multimedia_tools():
    assert get_client_provider("vscode").excluded_tool_names() == _MULTIMEDIA_TOOL_NAMES


def test_vscode_instruction_tells_the_model_never_to_claim_files_are_already_saved():
    """
    BUG REAL ENCONTRADO EN USO (2026-07-30): tras propose_project_files
    exitoso, el modelo dijo "creé los archivos" — el usuario entendió
    que ya estaban guardados, cuando en realidad la escritura real
    depende de que apruebe un diálogo aparte de VS Code (fácil de no
    notar). La instrucción debe pedir explícitamente "propuse"/
    "preparé" en vez de "creé"/"guardé", y avisar del diálogo pendiente.
    """
    assert '"creé"' in _VSCODE_CLIENT_INSTRUCTION
    assert "propuse" in _VSCODE_CLIENT_INSTRUCTION
    assert "diálogo que apareció en VS Code" in _VSCODE_CLIENT_INSTRUCTION


def test_web_provider_excludes_vscode_only_tools():
    assert get_client_provider("web").excluded_tool_names() == _VSCODE_ONLY_TOOL_NAMES
