"""
Orchestrator: punto de coordinación central del agente.

Responsabilidades:
  - Exponer la API del agente (FastAPI, puerto 8000)
  - Coordinar memoria, ejecución de tareas, herramientas y reparación
  - Exponer el loop de razonamiento (agent_core/llm/agent_loop.py) vía
    /chat — esto es lo que conecta a kal con Ollama y lo hace utilizable
    desde el frontend, no solo desde llamadas API de bajo nivel.
  - Delegar self-modification a agent_core/self_modification.py, que
    tiene su propio pipeline de validación (copia aislada del proyecto,
    comparación de tests antes/después, aprobación humana obligatoria
    antes de tocar disco real). Ver ese módulo para el detalle — este
    orquestador solo expone la API HTTP sobre él.
"""
from __future__ import annotations

import secrets
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent_core.llm.agent_loop import AgentLoop
from agent_core.llm.ollama_client import OllamaClient
from agent_core.llm.planner import PlanningAgentLoop
from agent_core.llm.provider import ProviderError
from agent_core.memory.manager import MemoryManager
from agent_core.self_diagnosis import INVARIANT_CHECKS, SelfDiagnosisAgent
from agent_core.self_modification import self_modification_manager
from agent_core.sessions import session_manager
from audit.audit_log import audit_log
from error_handling.circuit_breaker import circuit_breaker
from task_execution.executor import TaskExecutor
from tool_integration.base_tool import Artifact
from tool_integration.permissions import Permission
from tool_integration.registry import tool_registry
from utils.admin_token import get_or_create_admin_token
from utils.config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class Orchestrator:
    def __init__(self):
        self.memory = MemoryManager()
        self.tasks = TaskExecutor()
        self.tools = tool_registry
        self.self_modification = self_modification_manager
        self.sessions = session_manager
        self.llm = OllamaClient()
        self.agent = AgentLoop(llm_client=self.llm, task_executor=self.tasks, memory=self.memory)
        self.planning_agent = PlanningAgentLoop(self.agent)
        self.self_diagnosis = SelfDiagnosisAgent(llm_client=self.llm)

    def run_consolidation_cycle(self) -> dict:
        """Job periódico: corto->mediano, luego evalúa promoción mediano->largo."""
        consolidated = self.memory.consolidate_short_to_mid()
        promoted = self.memory.promote_mid_to_long()
        return {"consolidated": consolidated, "promoted": promoted}


orchestrator = Orchestrator()

# --- API HTTP ---
app = FastAPI(title="Kal")

# Segunda capa de defensa (la primera es que docker-compose ya solo
# publica este puerto en 127.0.0.1, ver docker-compose.yml) para las
# acciones que hoy hacen de facto de "aprobación humana": self-
# modification y aprobación/rollback de herramientas. Sin esto,
# `approved_by` era un string que el propio cliente elegía — no
# verificaba ninguna identidad real. Token persistido en disco (ver
# utils/admin_token.py), no en el código ni en config.yaml.
_ADMIN_TOKEN = get_or_create_admin_token()
logger.info(
    "Token administrativo generado/leído para self-modification y aprobación de "
    "herramientas. Para usar esas acciones desde el frontend, abrilo una vez como "
    f"http://localhost:8000/?admin_token={_ADMIN_TOKEN}"
)


def require_admin_token(x_kal_admin_token: str | None = Header(default=None)) -> None:
    if x_kal_admin_token is None or not secrets.compare_digest(x_kal_admin_token, _ADMIN_TOKEN):
        raise HTTPException(
            status_code=401,
            detail="Token administrativo inválido o ausente (header X-Kal-Admin-Token).",
        )


class TaskRequest(BaseModel):
    description: str


class ChatRequest(BaseModel):
    goal: str
    model: str | None = None
    use_planner: bool | None = None  # None = usar el default de config.yaml (llm.planning_enabled)
    session_id: str | None = None  # None = sesión nueva (ver agent_core/sessions.py)
    # Override de la cascada de permisos para esta sesión (ver
    # tool_integration/permissions.py::PermissionCascade). None = no tocar
    # lo que ya había (default); [] = limpiar cualquier restricción previa;
    # una lista = REEMPLAZA el override completo (no se acumula turno a
    # turno, para que nunca quede algo bloqueado "para siempre" sin que el
    # usuario lo vea venir).
    deny_permissions: list[str] | None = None


class SelfModProposeRequest(BaseModel):
    target_path: str
    proposed_source: str
    justification: str


class SelfModApplyRequest(BaseModel):
    proposal_id: str
    approved_by: str


class ToolApproveRequest(BaseModel):
    approved_by: str


class ToolRollbackRequest(BaseModel):
    to_version: int
    approved_by: str


class MemoryVerifyRequest(BaseModel):
    verified_by: str


class SelfDiagnosisRequest(BaseModel):
    model: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
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


@app.get("/models")
def list_models():
    try:
        return {"models": orchestrator.llm.list_models(), "default": settings.llm.default_model}
    except ProviderError as e:
        raise HTTPException(status_code=503, detail=str(e))


# --- Chat / agente ---


def _artifact_url(uri: str) -> str | None:
    """
    Traduce una ruta de archivo real (uri de un Artifact) a la URL
    servida por el mount /artifacts (solo lectura, ver más abajo) para
    que el frontend pueda mostrarla en <img src=...>. None si la ruta
    no está bajo data/artifacts/ (no se puede servir).
    """
    try:
        return f"/artifacts/{Path(uri).relative_to('data/artifacts')}"
    except ValueError:
        return None


@app.post("/chat")
def chat(req: ChatRequest):
    session = orchestrator.sessions.get_or_create(req.session_id)
    use_planner = req.use_planner if req.use_planner is not None else settings.llm.planning_enabled

    if req.deny_permissions is not None:
        try:
            denied = frozenset(Permission(p) for p in req.deny_permissions)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Permiso inválido en deny_permissions: {e}")
        orchestrator.sessions.update_denied_permissions(session, denied)

    try:
        result = orchestrator.planning_agent.run(
            req.goal, model=req.model, use_planner=use_planner,
            history=session.history_messages(), session_context=session.context_message(),
            denied_permissions=session.denied_permissions,
        )
    except ProviderError as e:
        raise HTTPException(status_code=503, detail=str(e))

    orchestrator.sessions.record_turn(session, req.goal, result.final_answer)
    all_steps = [s for step_result in result.step_results for s in step_result.result.steps]
    for step in all_steps:
        if step.artifact is not None and step.artifact.modality != "text":
            orchestrator.sessions.update_active_artifact(session, step.artifact)

    def _step_artifact(step) -> dict | None:
        if step.artifact is None or step.artifact.modality != "image":
            return None
        url = _artifact_url(step.artifact.uri)
        if url is None:
            return None
        return {"modality": step.artifact.modality, "url": url, "path": step.artifact.uri}

    return {
        "session_id": session.id,
        "goal": result.goal,
        "final_answer": result.final_answer,
        "status": result.status,
        "plan": [s.description for s in result.plan.steps],
        "steps": [
            {
                "tool": s.tool_name, "arguments": s.arguments, "observation": s.observation,
                "artifact": _step_artifact(s),
            }
            for s in all_steps
        ],
    }


# --- Subida de imágenes propias ---

_ALLOWED_UPLOAD_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp"}


@app.post("/uploads")
async def upload_image(file: UploadFile = File(...), session_id: str | None = Form(None)):
    """
    Sube una imagen propia del usuario (no generada por kal) y la
    convierte en el artefacto activo de la sesión — así el siguiente
    mensaje ("quitale el fondo") no necesita repetir ninguna ruta.

    Acción DIRECTA del usuario (como escribir un mensaje de chat), no
    una decisión autónoma del agente — no pasa por el pipeline de
    permisos/aprobación ni se audita, mismo criterio que /chat en sí
    (ver audit/audit_log.py: solo se registran ahí acciones SIN
    intervención humana directa).
    """
    if file.content_type not in _ALLOWED_UPLOAD_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de archivo no soportado: '{file.content_type}' (solo imágenes: png/jpeg/webp)",
        )

    cfg = settings.multimodal.uploads
    upload_dir = Path(cfg.artifact_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "").suffix or ".png"
    dest_path = upload_dir / f"{uuid.uuid4()}{suffix}"
    max_bytes = cfg.max_size_mb * 1024 * 1024

    size = 0
    with open(dest_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                f.close()
                dest_path.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail=f"Archivo demasiado grande (máx {cfg.max_size_mb}MB)")
            f.write(chunk)

    session = orchestrator.sessions.get_or_create(session_id)
    artifact = Artifact(
        modality="image", uri=str(dest_path),
        metadata={"uploaded_by_user": True, "original_filename": file.filename},
    )
    orchestrator.sessions.update_active_artifact(session, artifact)

    return {
        "session_id": session.id,
        "path": str(dest_path),
        "url": _artifact_url(str(dest_path)),
    }


# --- Tareas ---

@app.post("/tasks")
def create_task(req: TaskRequest):
    task = orchestrator.tasks.submit(req.description)
    return {"task_id": task.id, "status": task.status}


@app.get("/tasks")
def list_tasks():
    return [
        {"id": t.id, "description": t.description, "status": t.status, "created_at": t.created_at, "error": t.error}
        for t in orchestrator.tasks.list_tasks()
    ]


@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    task = orchestrator.tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# --- Herramientas ---

@app.get("/tools")
def list_tools():
    return {"active": orchestrator.tools.list_active(), "pending": orchestrator.tools.list_pending()}


@app.post("/tools/{name}/approve", dependencies=[Depends(require_admin_token)])
def approve_tool(name: str, req: ToolApproveRequest):
    try:
        orchestrator.tools.approve_pending_tool(name, approved_by=req.approved_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"name": name, "status": "active"}


@app.get("/skills")
def list_skills():
    return {"skills": orchestrator.tools.list_skills()}


@app.get("/tools/{name}/versions")
def list_tool_versions(name: str):
    return {"name": name, "versions": orchestrator.tools.list_versions(name)}


@app.get("/tools/{name}/verify")
def verify_tool(name: str):
    return {"name": name, "signature_valid": orchestrator.tools.verify_tool_integrity(name)}


@app.post("/tools/{name}/rollback", dependencies=[Depends(require_admin_token)])
def rollback_tool(name: str, req: ToolRollbackRequest):
    try:
        orchestrator.tools.rollback_tool(name, req.to_version, approved_by=req.approved_by)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"name": name, "version": req.to_version, "status": "active"}


# --- Memoria ---

@app.get("/memory/search")
def search_memory(q: str, top_k: int = 5):
    results = orchestrator.memory.recall(q, top_k=top_k)
    return {
        tier: [
            {"id": i.id, "content": i.content, "metadata": i.metadata, "confidence": i.confidence.value}
            for i in items
        ]
        for tier, items in results.items()
    }


@app.post("/memory/consolidate")
def consolidate():
    return orchestrator.run_consolidation_cycle()


@app.post("/memory/{tier}/{item_id}/verify")
def verify_memory(tier: str, item_id: str, req: MemoryVerifyRequest):
    try:
        item = orchestrator.memory.verify(item_id, tier, verified_by=req.verified_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": item.id, "confidence": item.confidence.value}


@app.post("/memory/{tier}/{item_id}/pin")
def pin_memory(tier: str, item_id: str):
    try:
        item = orchestrator.memory.pin(item_id, tier)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": item.id, "confidence": item.confidence.value}


# --- Self-modification ---

@app.post("/self-modification/propose", dependencies=[Depends(require_admin_token)])
def propose_self_modification(req: SelfModProposeRequest):
    proposal = orchestrator.self_modification.propose(req.target_path, req.proposed_source, req.justification)
    return {"proposal_id": proposal.id, "status": proposal.status, "detail": proposal.detail}


@app.post("/self-modification/apply", dependencies=[Depends(require_admin_token)])
def apply_self_modification(req: SelfModApplyRequest):
    try:
        proposal = orchestrator.self_modification.apply(req.proposal_id, req.approved_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"proposal_id": proposal.id, "status": proposal.status}


@app.get("/self-modification")
def list_self_modifications():
    return [
        {"id": p.id, "target_path": p.target_path, "justification": p.justification, "status": p.status, "detail": p.detail}
        for p in orchestrator.self_modification.list_proposals()
    ]


@app.get("/self-modification/{proposal_id}")
def get_self_modification(proposal_id: str):
    proposal = orchestrator.self_modification.get(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


# --- Auto-diagnóstico ---
# Bajo demanda únicamente: nunca se dispara solo, ni siquiera cuando un
# invariante está mal — alguien tiene que pedirlo explícitamente acá.

@app.get("/diagnostics")
def list_diagnostics():
    return {name: vars(check()) for name, check in INVARIANT_CHECKS.items()}


@app.post("/diagnostics/{invariant}/self-repair", dependencies=[Depends(require_admin_token)])
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


# --- Auditoría ---

@app.get("/audit/tail")
def audit_tail(n: int = 50):
    return {"verified": audit_log.verify_chain(), "entries": audit_log.tail(n)}


# --- CSS/JS del frontend, servidos SIN cache ---
# BUG REAL ENCONTRADO EN USO: StaticFiles (más abajo) deja que el
# navegador cachee style.css/app.js con su heurística por defecto — al
# iterar rápido sobre el frontend en esta sesión, varios cambios de CSS
# no se veían ni con un hard refresh manual. Estas dos rutas explícitas
# (registradas ANTES del mount catch-all, así que Starlette las
# resuelve primero) fuerzan Cache-Control: no-store — el navegador
# nunca sirve una copia vieja de estos dos archivos.
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/style.css")
def serve_style_css():
    return FileResponse(_FRONTEND_DIR / "style.css", media_type="text/css", headers={"Cache-Control": "no-store"})


@app.get("/app.js")
def serve_app_js():
    return FileResponse(_FRONTEND_DIR / "app.js", media_type="application/javascript", headers={"Cache-Control": "no-store"})


# --- Artefactos (imágenes/audio/video generados o subidos) ---
# Solo lectura: sirve lo que ya hay en data/artifacts/ para que el
# frontend pueda mostrar <img src="/artifacts/..."> — sin esto, no hay
# forma de que el navegador vea una vista previa de lo subido/generado.
_ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "data" / "artifacts"
_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=str(_ARTIFACTS_DIR)), name="artifacts")

# --- Frontend estático ---
# Mount catch-all en "/" — tiene que ser el ÚLTIMO mount registrado,
# cualquier ruta/mount nuevo va ANTES de este. index.html sí puede
# cachearse (no cambia tan seguido y no tiene el mismo impacto que un
# CSS/JS desactualizado) — solo style.css/app.js tienen la ruta
# explícita sin cache de arriba.
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
