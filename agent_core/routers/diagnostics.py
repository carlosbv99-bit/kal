"""
Auto-diagnóstico: /diagnostics, /diagnostics/{invariant}/self-repair.

Bajo demanda únicamente: nunca se dispara solo, ni siquiera cuando un
invariante está mal — alguien tiene que pedirlo explícitamente acá.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent_core.orchestrator import orchestrator, require_admin_token
from agent_core.self_diagnosis import INVARIANT_CHECKS

router = APIRouter(prefix="/diagnostics")


class SelfDiagnosisRequest(BaseModel):
    model: str | None = None


@router.get("")
def list_diagnostics():
    return {name: vars(check()) for name, check in INVARIANT_CHECKS.items()}


@router.post("/{invariant}/self-repair", dependencies=[Depends(require_admin_token)])
def self_repair(invariant: str, req: SelfDiagnosisRequest):
    try:
        result = orchestrator.self_diagnosis.diagnose_and_propose_fix(invariant, model=req.model)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "invariant": result.invariant,
        "status": result.status,
        "diagnosis": result.diagnosis,
        "proposal": (
            {"id": result.proposal.id, "status": result.proposal.status, "detail": result.proposal.detail}
            if result.proposal else None
        ),
    }
