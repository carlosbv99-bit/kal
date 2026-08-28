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


def test_vscode_only_tool_names_includes_android_build_and_screenshot():
    assert "android_build_and_screenshot" in _VSCODE_ONLY_TOOL_NAMES


def test_create_text_file_is_available_to_both_clients():
    """
    A diferencia de propose_project_files (exclusiva de VS Code,
    escribe recién del lado de la extensión), CreateTextFileTool sí
    escribe un archivo real en el backend — tiene sentido para ambos
    clientes (web, que hasta ahora no tenía NINGUNA forma de entregar
    un archivo; y VS Code, como alternativa liviana cuando no hace
    falta escribir dentro del workspace abierto).
    """
    assert "create_text_file" not in _MULTIMEDIA_TOOL_NAMES
    assert "create_text_file" not in _VSCODE_ONLY_TOOL_NAMES


def test_vscode_instruction_tells_the_model_never_to_claim_the_android_build_already_finished():
    """
    Pedido explícito del usuario (2026-07-30): monitorear visualmente el
    progreso de una app Android en un dispositivo conectado. El trabajo
    real (compilar/instalar/capturar) es asincrónico del lado de la
    extensión — el modelo nunca ve el resultado, así que su respuesta
    final no puede dar la tarea por terminada ni inventar cómo se ve.
    """
    assert "android_build_and_screenshot" in _VSCODE_CLIENT_INSTRUCTION
    assert "NUNCA digas que ya se" in _VSCODE_CLIENT_INSTRUCTION


def test_vscode_instruction_tells_the_model_not_to_call_android_build_automatically_after_creating_a_project():
    """
    BUG REAL ENCONTRADO EN USO (2026-08-23): "crea un proyecto de agenda
    para android" (sin pedir ver el progreso visual) llamó igual a
    android_build_and_screenshot después de propose_project_files, un
    paso que el usuario nunca pidió sobre archivos que ni siquiera se
    habían aplicado todavía. Debe llamarse SOLO cuando el pedido pide
    explícitamente ver/monitorear/mostrar el progreso visual.
    """
    assert "NUNCA se llama automáticamente después de crear/proponer" in _VSCODE_CLIENT_INSTRUCTION


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
