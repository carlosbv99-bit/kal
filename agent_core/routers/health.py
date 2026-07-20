"""
Estado general del agente: /health, /status, /models — sin
dependencias de ningún dominio específico (memoria, self-mod,
permisos...), por eso viven separados del resto.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agent_core.llm.provider import ProviderError
from agent_core.orchestrator import orchestrator
from audit.audit_log import audit_log
from error_handling.circuit_breaker import circuit_breaker
from utils.config import settings

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/status")
def status():
    """
    Estado de las garantías de seguridad del sistema, usado por la
    franja de estado del frontend — no decoración, son las propiedades
    reales que hacen que kal sea seguro de usar.
    """
    pending_tools = len(orchestrator.tools.list_pending())
    pending_selfmod = sum(1 for p in orchestrator.self_modification.list_proposals() if p.status == "pending_human_approval")
    return {
        "audit_chain_verified": audit_log.verify_chain(),
        "sandbox_network_mode": settings.sandbox.network_mode,
        "pending_tool_approvals": pending_tools,
        "pending_self_modification_approvals": pending_selfmod,
        "open_circuit_breakers": circuit_breaker.open_circuit_count(),
        "llm_available": orchestrator.llm.is_available(),
    }


@router.get("/models")
def list_models():
    try:
        return {"models": orchestrator.llm.list_models(), "default": settings.llm.default_model}
    except ProviderError as e:
        raise HTTPException(status_code=503, detail=str(e))
