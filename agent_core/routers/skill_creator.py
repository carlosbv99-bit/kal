"""
Skill Creator: /skill-proposals/* — revisión y aprobación humana de
Skills nuevas propuestas por el agente (ver agent_core/skill_creator.py
para el pipeline completo).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent_core.orchestrator import require_admin_token
from agent_core.skill_creator import skill_creator_manager

router = APIRouter(prefix="/skill-proposals")


class SkillProposalRejectRequest(BaseModel):
    reason: str = ""


class SkillProposalApproveRequest(BaseModel):
    approved_by: str


def _summary(p) -> dict:
    return {
        "id": p.id, "name": p.name, "description": p.description,
        "justification": p.justification, "status": p.status,
    }


@router.get("")
def list_skill_proposals():
    return [_summary(p) for p in skill_creator_manager.list_proposals()]


@router.get("/{proposal_id}")
def get_skill_proposal(proposal_id: str):
    """
    Detalle completo, INCLUIDO el código propuesto — un humano tiene que
    poder leerlo entero antes de decidir si aprueba o rechaza, no solo
    ver un resumen.
    """
    proposal = skill_creator_manager.get(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="No existe esa propuesta de skill")
    return {
        **_summary(proposal),
        "class_name": proposal.class_name,
        "entry_point": proposal.entry_point,
        "code": proposal.code,
        "permissions": proposal.permissions,
        "requirements": proposal.requirements,
        "kernel_services": proposal.kernel_services,
        "parameters_schema": proposal.parameters_schema,
        "detail": proposal.detail,
    }


@router.post("/{proposal_id}/approve", dependencies=[Depends(require_admin_token)])
def approve_skill_proposal(proposal_id: str, req: SkillProposalApproveRequest):
    try:
        proposal = skill_creator_manager.approve(proposal_id, approved_by=req.approved_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": proposal.id, "name": proposal.name, "status": proposal.status, "detail": proposal.detail}


@router.post("/{proposal_id}/reject", dependencies=[Depends(require_admin_token)])
def reject_skill_proposal(proposal_id: str, req: SkillProposalRejectRequest):
    try:
        proposal = skill_creator_manager.reject(proposal_id, reason=req.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": proposal.id, "name": proposal.name, "status": proposal.status}
