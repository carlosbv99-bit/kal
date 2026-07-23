"""
Configuración del LLM (local u en la nube): /settings/llm/*.

kal se distribuye a usuarios con hardware muy distinto (ver
docs/HISTORY.md) — esto deja elegir Ollama local o cualquier proveedor
compatible con OpenAI (Qwen, Grok/xAI, OpenAI...) desde la interfaz,
sin editar config.yaml/.env a mano. Ver agent_core/llm_settings.py.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent_core.llm_settings import (
    LLMSettingsError,
    activate_cloud_profile,
    get_llm_settings,
    get_ollama_model_capabilities,
    list_local_ollama_models,
    list_model_sources,
    pull_ollama_model,
    update_llm_settings,
)
from agent_core.orchestrator import _reinject_llm_client, require_admin_token

router = APIRouter(prefix="/settings/llm")


class LLMSettingsUpdateRequest(BaseModel):
    provider: str
    base_url: str | None = None
    default_model: str | None = None
    api_key: str | None = None  # None = no tocar la que ya está guardada
    # Si se pasa junto con provider="openai_compatible", además de
    # activarlo lo guarda como perfil reusable (ver
    # agent_core/llm_settings.py::save_cloud_profile) — así vuelve a
    # aparecer en el selector de modelo más adelante sin volver a
    # pedir la key.
    profile_name: str | None = None


class ActivateCloudProfileRequest(BaseModel):
    name: str


class OllamaPullRequest(BaseModel):
    model: str


@router.get("")
def get_llm_settings_endpoint():
    return get_llm_settings()


@router.post("", dependencies=[Depends(require_admin_token)])
def update_llm_settings_endpoint(req: LLMSettingsUpdateRequest):
    try:
        update_llm_settings(
            provider=req.provider, base_url=req.base_url,
            default_model=req.default_model, api_key=req.api_key,
            profile_name=req.profile_name,
        )
    except LLMSettingsError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _reinject_llm_client()
    return get_llm_settings()


@router.get("/sources")
def list_model_sources_endpoint():
    """
    Modelos de TODAS las fuentes conocidas (Ollama local + cada perfil
    en la nube guardado que responda con éxito ahora mismo) — a
    diferencia de /models (solo el proveedor ACTIVO), esto es lo que
    alimenta el selector de modelo resiliente del chat.
    """
    return {"sources": list_model_sources()}


@router.post("/activate-profile", dependencies=[Depends(require_admin_token)])
def activate_cloud_profile_endpoint(req: ActivateCloudProfileRequest):
    try:
        activate_cloud_profile(req.name)
    except LLMSettingsError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _reinject_llm_client()
    return get_llm_settings()


@router.get("/ollama/models")
def list_local_ollama_models_endpoint():
    """
    Modelos YA descargados en el Ollama local — independiente de cuál
    proveedor esté ACTIVO ahora mismo (a diferencia de /models, que
    lista los del proveedor activo). Ollama caído no es un error del
    endpoint, es un estado real y esperable: se informa como lista
    vacía + un aviso, no como 500.

    `capabilities`: un mapa {modelo: ["tools", "vision", ...]} — para
    que la interfaz explique POR QUÉ un modelo como llava:13b no
    aparece en el selector de modelo del agente (sin soporte de
    "tools"), en vez de dejarlo como una ausencia sin explicación.
    """
    try:
        models = list_local_ollama_models()
        capabilities = {m: get_ollama_model_capabilities(m) for m in models}
        return {"models": models, "capabilities": capabilities, "ollama_available": True}
    except LLMSettingsError as e:
        return {"models": [], "capabilities": {}, "ollama_available": False, "detail": str(e)}


@router.post("/ollama/pull", dependencies=[Depends(require_admin_token)])
def pull_ollama_model_endpoint(req: OllamaPullRequest):
    try:
        pull_ollama_model(req.model)
    except LLMSettingsError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"model": req.model, "status": "downloaded"}
