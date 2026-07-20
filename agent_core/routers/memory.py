"""
Memoria en tres niveles: /memory/*.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent_core.orchestrator import orchestrator

router = APIRouter(prefix="/memory")


class MemoryVerifyRequest(BaseModel):
    verified_by: str


@router.get("/search")
def search_memory(q: str, top_k: int = 5):
    results = orchestrator.memory.recall(q, top_k=top_k)
    return {
        tier: [
            {"id": i.id, "content": i.content, "metadata": i.metadata, "confidence": i.confidence.value}
            for i in items
        ]
        for tier, items in results.items()
    }


@router.post("/consolidate")
def consolidate():
    return orchestrator.run_consolidation_cycle()


@router.post("/{tier}/{item_id}/verify")
def verify_memory(tier: str, item_id: str, req: MemoryVerifyRequest):
    try:
        item = orchestrator.memory.verify(item_id, tier, verified_by=req.verified_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": item.id, "confidence": item.confidence.value}


@router.post("/{tier}/{item_id}/pin")
def pin_memory(tier: str, item_id: str):
    try:
        item = orchestrator.memory.pin(item_id, tier)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": item.id, "confidence": item.confidence.value}
