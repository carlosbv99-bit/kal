"""
Auditoría: /audit/tail.
"""
from __future__ import annotations

from fastapi import APIRouter

from audit.audit_log import audit_log

router = APIRouter(prefix="/audit")


@router.get("/tail")
def audit_tail(n: int = 50):
    return {"verified": audit_log.verify_chain(), "entries": audit_log.tail(n)}
