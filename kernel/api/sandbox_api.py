"""
API interna del servicio sandbox_runner.

El agente principal (agent_core) llama a este servicio vía HTTP en vez
de invocar Docker directamente, para que solo este proceso aislado
tenga acceso al socket de Docker del host (ver docker-compose.yml).
"""
from __future__ import annotations

import os
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from kernel.lifecycle.executor import SandboxExecutor

# VULNERABILIDAD REAL ENCONTRADA EN AUDITORÍA EXTERNA (C-3, 2026-09-26):
# /execute ejecutaba código arbitrario SIN NINGUNA autenticación,
# alcanzable desde cualquier proceso en la misma red que sandbox_runner
# — el único freno era el denylist AST (code_analysis/), que su propio
# docstring ya declara heurístico, no exhaustivo, más el aislamiento de
# Docker (real, pero no debería ser la ÚNICA capa para un endpoint de
# "ejecutá este código"). Fail-closed por diseño, mismo criterio que el
# resto del proyecto (sandbox.network_mode="none", browser.allowed_domains
# vacío, etc.): sin SANDBOX_API_TOKEN configurado en el entorno, TODO
# pedido a /execute se rechaza — nunca "abierto por default" mientras
# alguien se olvida de configurar el secreto.
SANDBOX_API_TOKEN = os.environ.get("SANDBOX_API_TOKEN")

# Mismo hallazgo (C-3): sin límite de tamaño de body. 1 MiB es de sobra
# para el código fuente real de una skill/herramienta dinámica — un
# body más grande no tiene ningún caso de uso legítimo hoy.
_MAX_BODY_BYTES = 1024 * 1024


class _MaxBodySizeMiddleware:
    """
    Rechaza temprano por `Content-Length` declarado, antes de que
    FastAPI/Pydantic lean el body completo a memoria. Corre ANTES que
    cualquier dependencia de la ruta (incluida `_verify_token` de abajo)
    — un middleware ASGI siempre corre antes del routing/las
    dependencias, nunca después — así que esto es una defensa PRE-AUTH,
    alcanzable por cualquiera que llegue al puerto, no solo por quien ya
    tiene el token. No cubre un cliente que mienta el header o
    transmita en streaming sin Content-Length — deny-by-default en el
    caso común, no una defensa exhaustiva.
    """

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            content_length = headers.get(b"content-length")
            if content_length is not None:
                # BUG REAL ENCONTRADO EN AUDITORÍA EXTERNA (M-2,
                # 2026-09-27): un Content-Length no numérico (p.ej.
                # b"not-a-number") hacía que int() lanzara ValueError
                # SIN ATRAPAR acá — un crash alcanzable por cualquiera
                # que llegue al puerto, ANTES de la autenticación (ver
                # el comentario de arriba). Tratado igual que un body
                # demasiado grande: rechazo limpio, nunca un 500.
                try:
                    declared_size = int(content_length)
                except ValueError:
                    response = JSONResponse({"detail": "Content-Length inválido"}, status_code=400)
                    await response(scope, receive, send)
                    return
                if declared_size > self.max_bytes:
                    response = JSONResponse({"detail": "Body demasiado grande"}, status_code=413)
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


app = FastAPI(title="Sandbox Runner")
app.add_middleware(_MaxBodySizeMiddleware, max_bytes=_MAX_BODY_BYTES)
executor = SandboxExecutor()


def _verify_token(x_sandbox_token: str | None = Header(default=None)) -> None:
    # BUG REAL ENCONTRADO EN LA MISMA AUDITORÍA (M-6): secrets.compare_digest
    # lanza TypeError con un string no-ASCII — comparar como bytes (la
    # codificación UTF-8 nunca falla) evita ese 500 sin capturar, que
    # además saltearía la autenticación en vez de rechazarla si no se
    # atrapara la excepción.
    expected = (SANDBOX_API_TOKEN or "").encode("utf-8")
    provided = (x_sandbox_token or "").encode("utf-8")
    if not SANDBOX_API_TOKEN or not x_sandbox_token or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Token de sandbox_runner inválido o no configurado")


class ExecuteRequest(BaseModel):
    source_code: str
    context: dict = Field(default_factory=dict)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/execute", dependencies=[Depends(_verify_token)])
def execute(req: ExecuteRequest):
    result = executor.execute(req.source_code, req.context)
    return {
        "status": result.status,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "resource_usage": result.resource_usage,
    }
