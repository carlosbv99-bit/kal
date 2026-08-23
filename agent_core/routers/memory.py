"""
Memoria en tres niveles: /memory/*.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent_core.orchestrator import orchestrator

router = APIRouter(prefix="/memory", tags=["Memoria"])


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


@router.delete("/{tier}/{item_id}")
def forget_memory(tier: str, item_id: str):
    """Derecho al olvido, un item puntual (mid_term/long_term, mismo
    alcance que verify()/pin() — corto plazo no tiene identidad estable
    fuera de la tarea activa). Idempotente: borrar un id que ya no
    existe no es un error."""
    try:
        orchestrator.memory.forget(item_id, tier)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"deleted": item_id, "tier": tier}


@router.delete("")
def forget_matching_memory(
    keyword: str | None = None,
    tier: str | None = None,
    classification: str | None = None,
    before: float | None = None,
    after: float | None = None,
):
    """Derecho al olvido, masivo con filtros — exige al menos uno
    (ver MemoryManager.forget_matching()), nunca borra todo sin
    condición. Sin `tier`, aplica a los tres niveles."""
    try:
        deleted = orchestrator.memory.forget_matching(
            keyword=keyword, tier=tier, classification=classification, before=before, after=after,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"deleted_count": deleted}
