"""
Herramientas y skills: /tools, /tools/{name}/*, /skills.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent_core.orchestrator import orchestrator, require_admin_token

router = APIRouter()


class ToolApproveRequest(BaseModel):
    approved_by: str


class ToolRollbackRequest(BaseModel):
    to_version: int
    approved_by: str


@router.get("/tools")
def list_tools():
    return {"active": orchestrator.tools.list_active(), "pending": orchestrator.tools.list_pending()}


@router.post("/tools/{name}/approve", dependencies=[Depends(require_admin_token)])
def approve_tool(name: str, req: ToolApproveRequest):
    try:
        orchestrator.tools.approve_pending_tool(name, approved_by=req.approved_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"name": name, "status": "active"}


@router.get("/skills")
def list_skills():
    return {"skills": orchestrator.tools.list_skills()}


@router.get("/tools/{name}/versions")
def list_tool_versions(name: str):
    return {"name": name, "versions": orchestrator.tools.list_versions(name)}


@router.get("/tools/{name}/verify")
def verify_tool(name: str):
    return {"name": name, "signature_valid": orchestrator.tools.verify_tool_integrity(name)}


@router.post("/tools/{name}/rollback", dependencies=[Depends(require_admin_token)])
def rollback_tool(name: str, req: ToolRollbackRequest):
    try:
        orchestrator.tools.rollback_tool(name, req.to_version, approved_by=req.approved_by)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"name": name, "version": req.to_version, "status": "active"}
