"""
API interna del servicio sandbox_runner.

El agente principal (agent_core) llama a este servicio vía HTTP en vez
de invocar Docker directamente, para que solo este proceso aislado
tenga acceso al socket de Docker del host (ver docker-compose.yml).
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from kernel.lifecycle.executor import SandboxExecutor

app = FastAPI(title="Sandbox Runner")
executor = SandboxExecutor()


class ExecuteRequest(BaseModel):
    source_code: str
    context: dict = {}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/execute")
def execute(req: ExecuteRequest):
    result = executor.execute(req.source_code, req.context)
    return {
        "status": result.status,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "resource_usage": result.resource_usage,
    }
