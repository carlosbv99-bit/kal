"""
Tareas asíncronas: /tasks, /tasks/{task_id}.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent_core.orchestrator import orchestrator

router = APIRouter(prefix="/tasks")


class TaskRequest(BaseModel):
    description: str


@router.post("")
def create_task(req: TaskRequest):
    task = orchestrator.tasks.submit(req.description)
    return {"task_id": task.id, "status": task.status}


@router.get("")
def list_tasks():
    return [
        {"id": t.id, "description": t.description, "status": t.status, "created_at": t.created_at, "error": t.error}
        for t in orchestrator.tasks.list_tasks()
    ]


@router.get("/{task_id}")
def get_task(task_id: str):
    task = orchestrator.tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
