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

import os
import secrets
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent_core.context_service import ContextService, EditorContextSignals
from agent_core.llm.agent_loop import AgentLoop
from agent_core.llm.ollama_client import OllamaClient
from agent_core.llm.openai_compatible_client import OpenAICompatibleClient
from agent_core.llm.planner import PlanningAgentLoop
from agent_core.llm.provider import LLMProvider, ProviderError
from agent_core.llm_settings import (
    LLMSettingsError,
    activate_cloud_profile,
    get_llm_settings,
    list_local_ollama_models,
    list_model_sources,
    pull_ollama_model,
    read_llm_env_var,
    update_llm_settings,
)
from agent_core.memory.manager import MemoryManager
from agent_core.self_diagnosis import INVARIANT_CHECKS, SelfDiagnosisAgent
from agent_core.self_modification import self_modification_manager
from agent_core.sessions import session_manager
from agent_core.vscode_integration import VSCodeIntegrationError, get_status as get_vscode_status, install_extension
from audit.audit_log import AuditEvent, audit_log
from error_handling.circuit_breaker import circuit_breaker
from task_execution.executor import TaskExecutor
from tool_integration.base_tool import Artifact
from tool_integration.filesystem_access_manager import FilesystemAccessError, filesystem_access_manager
from tool_integration.permissions import Permission
from tool_integration.registry import tool_registry
from utils.admin_token import get_or_create_admin_token
from utils.config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def build_llm_client() -> LLMProvider:
    """
    Fábrica del LLMProvider real según settings.llm.provider — kal se
    distribuye a usuarios con hardware muy distinto (ver
    docs/HISTORY.md), así que el cerebro del agente no puede quedar
    hardcodeado a Ollama local. "ollama" (default) no cambia nada del
    comportamiento de siempre. "openai_compatible" sirve tanto para un
    proveedor real en la nube (Qwen/DashScope, Grok/xAI, OpenAI,
    OpenRouter...) como para el propio endpoint OpenAI-compatible de
    Ollama (ya validado en F2, ver agent_core/llm/openai_compatible_client.py).

    Fail-closed: sin LLM_API_KEY configurada, kal ni arranca — mismo
    criterio que IMAGE_GEN_API_KEY/AUDIO_GEN_API_KEY en los adaptadores
    multimodales (tool_integration/adapters/image_gen.py), nunca
    intentar sin autenticación y fallar tarde con un error confuso.
    """
    if settings.llm.provider == "openai_compatible":
        api_key = read_llm_env_var("LLM_API_KEY")
        if not api_key:
            raise RuntimeError(
                "LLM_API_KEY no configurada — completá .env (ver .env.example) "
                "para usar llm.provider: openai_compatible."
            )
        return OpenAICompatibleClient(base_url=settings.llm.base_url, api_key=api_key)
    return OllamaClient()


class Orchestrator:
    def __init__(self):
        self.memory = MemoryManager()
        self.tasks = TaskExecutor()
        self.tools = tool_registry
        self.self_modification = self_modification_manager
        self.sessions = session_manager
        self.context_service = ContextService()
        self.llm = build_llm_client()
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


_LOOPBACK_ADDRESSES = frozenset({"127.0.0.1", "::1"})


@app.get("/admin-token")
def get_admin_token_endpoint(request: Request):
    """
    Fricción real encontrada en uso: pedirle a un usuario no-programador
    que copie el token administrativo de una terminal para poder usar
    la interfaz web era impracticable. Esto se lo entrega automáticamente
    al FRONTEND (nunca al agente ni a una skill: no es un tool, no hay
    forma de que el LLM llegue a esto) — pero SOLO si la conexión viene
    de loopback (mismo criterio que docker-compose.yml: 127.0.0.1). Quien
    accede desde la propia máquina donde corre kal ya podría leer
    data/keys/admin_token directamente del disco — esto no le da a un
    atacante remoto ninguna capacidad nueva, solo evita que el usuario
    legítimo tenga que ir a buscarlo a mano. Alguien conectándose desde
    otra máquina en la LAN (el caso real que este token protege) sigue
    sin poder obtenerlo por acá.
    """
    if request.client is None or request.client.host not in _LOOPBACK_ADDRESSES:
        raise HTTPException(status_code=403, detail="Solo disponible desde la misma máquina donde corre kal.")
    return {"token": _ADMIN_TOKEN}


class TaskRequest(BaseModel):
    description: str


class EditorContextRequest(BaseModel):
    """
    Señal cruda del editor (ver agent_core/context_service.py) — el
    frontend (extensión de VS Code) NUNCA manda texto ya formateado
    acá, solo estos 4 campos. El Context Service decide cómo se ve en
    el mensaje final al LLM.
    """
    relative_path: str
    language_id: str
    text: str
    is_selection: bool


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
    editor_context: EditorContextRequest | None = None
    # None/"web" = interfaz web (default: genera imagen/audio/video). "vscode" =
    # extensión de VS Code (ver agent_core/context_service.py::_VSCODE_CLIENT_INSTRUCTION) —
    # ahí "página web"/"app"/"script" es un pedido de código, no de imágenes.
    client: str | None = None


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


class FilesystemAccessApproveRequest(BaseModel):
    # "once" | "session" | "project" | "skill" — ver
    # tool_integration/filesystem_access_manager.py::GrantLevel.
    level: str = "once"


class FilesystemAccessOutcomeRequest(BaseModel):
    # Reportado por la extensión de VS Code después de que el usuario
    # decide en la vista previa — el Kernel ya auto-permitió la acción
    # por política, esto deja constancia de qué pasó DE VERDAD (auditoría
    # con datos reales, no solo "se permitió").
    outcome: str  # "written" | "discarded"
    files_written: list[str] = Field(default_factory=list)


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


# --- Configuración del LLM (local u en la nube) ---
# kal se distribuye a usuarios con hardware muy distinto (ver
# docs/HISTORY.md) — esto deja elegir Ollama local o cualquier
# proveedor compatible con OpenAI (Qwen, Grok/xAI, OpenAI...) desde la
# interfaz, sin editar config.yaml/.env a mano. Ver agent_core/llm_settings.py.

class LLMSettingsUpdateRequest(BaseModel):
    provider: str
    base_url: str | None = None
    default_model: str | None = None
    api_key: str | None = None  # None = no tocar la que ya está guardada
    # Si se pasa junto con provider="openai_compatible", además de
    # activarlo lo guarda como perfil reusable (ver
    # agent_core/llm_settings.py::save_cloud_profile) — así vuelve a
    # aparecer en el selector de modelo más adelante sin volver a
    # pedir la key.
    profile_name: str | None = None


def _reinject_llm_client() -> None:
    """
    Reconstruye el cliente real y lo re-inyecta en todo lo que ya
    tenía una referencia — sin esto, cambiar el proveedor/perfil activo
    no tendría efecto hasta reiniciar el proceso entero.
    """
    orchestrator.llm = build_llm_client()
    orchestrator.agent.llm = orchestrator.llm
    orchestrator.planning_agent.planner.llm = orchestrator.llm
    orchestrator.self_diagnosis.llm = orchestrator.llm


@app.get("/settings/llm")
def get_llm_settings_endpoint():
    return get_llm_settings()


@app.post("/settings/llm", dependencies=[Depends(require_admin_token)])
def update_llm_settings_endpoint(req: LLMSettingsUpdateRequest):
    try:
        update_llm_settings(
            provider=req.provider, base_url=req.base_url,
            default_model=req.default_model, api_key=req.api_key,
            profile_name=req.profile_name,
        )
    except LLMSettingsError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _reinject_llm_client()
    return get_llm_settings()


class ActivateCloudProfileRequest(BaseModel):
    name: str


@app.get("/settings/llm/sources")
def list_model_sources_endpoint():
    """
    Modelos de TODAS las fuentes conocidas (Ollama local + cada perfil
    en la nube guardado que responda con éxito ahora mismo) — a
    diferencia de /models (solo el proveedor ACTIVO), esto es lo que
    alimenta el selector de modelo resiliente del chat.
    """
    return {"sources": list_model_sources()}


@app.post("/settings/llm/activate-profile", dependencies=[Depends(require_admin_token)])
def activate_cloud_profile_endpoint(req: ActivateCloudProfileRequest):
    try:
        activate_cloud_profile(req.name)
    except LLMSettingsError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _reinject_llm_client()
    return get_llm_settings()


class OllamaPullRequest(BaseModel):
    model: str


@app.get("/settings/llm/ollama/models")
def list_local_ollama_models_endpoint():
    """
    Modelos YA descargados en el Ollama local — independiente de cuál
    proveedor esté ACTIVO ahora mismo (a diferencia de /models, que
    lista los del proveedor activo). Ollama caído no es un error del
    endpoint, es un estado real y esperable: se informa como lista
    vacía + un aviso, no como 500.
    """
    try:
        return {"models": list_local_ollama_models(), "ollama_available": True}
    except LLMSettingsError as e:
        return {"models": [], "ollama_available": False, "detail": str(e)}


@app.post("/settings/llm/ollama/pull", dependencies=[Depends(require_admin_token)])
def pull_ollama_model_endpoint(req: OllamaPullRequest):
    try:
        pull_ollama_model(req.model)
    except LLMSettingsError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"model": req.model, "status": "downloaded"}


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

    editor_context = None
    if req.editor_context is not None:
        editor_context = EditorContextSignals(
            relative_path=req.editor_context.relative_path,
            language_id=req.editor_context.language_id,
            text=req.editor_context.text,
            is_selection=req.editor_context.is_selection,
        )
    context_bundle = orchestrator.context_service.build(session, editor_context, client=req.client)

    try:
        result = orchestrator.planning_agent.run(
            req.goal, model=req.model, use_planner=use_planner,
            history=context_bundle.history, session_context=context_bundle.session_context,
            denied_permissions=session.denied_permissions, client=req.client,
        )
    except ProviderError as e:
        raise HTTPException(status_code=503, detail=str(e))

    orchestrator.sessions.record_turn(session, req.goal, result.final_answer)
    all_steps = [s for step_result in result.step_results for s in step_result.result.steps]
    for step in all_steps:
        if step.artifact is not None and step.artifact.modality != "text":
            orchestrator.sessions.update_active_artifact(session, step.artifact)

    def _step_artifact(step) -> dict | None:
        if step.artifact is None:
            return None
        if step.artifact.modality == "project_files":
            # A diferencia de image/audio/video, esto no es un archivo YA
            # generado en disco (uri) — es una PROPUESTA que la extensión
            # de VS Code todavía tiene que revisar y aplicar (ver
            # vscode-extension/src/projectFiles.ts). El backend nunca
            # escribe esto al disco real del usuario.
            return {
                "modality": "project_files",
                "request_id": step.artifact.metadata.get("request_id"),
                "files": step.artifact.metadata.get("files", []),
            }
        if step.artifact.modality != "image":
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


# --- Permission Manager de filesystem (tool_integration/filesystem_access_manager.py) ---
#
# La política default (config.yaml: filesystem_access.auto_allow) ya
# auto-permite crear/modificar dentro del workspace de VS Code — hoy
# nada llega acá pidiendo aprobación en la práctica. Estos endpoints
# quedan listos para cuando una Skill futura (o una acción
# delete/rename de VS Code) sí lo necesite.

@app.get("/filesystem-access")
def list_pending_filesystem_access():
    return [
        {
            "id": p.id, "skill_name": p.skill_name, "scope": p.scope.value,
            "action": p.action.value, "resource_key": p.resource_key,
        }
        for p in filesystem_access_manager.list_pending()
    ]


@app.post("/filesystem-access/{request_id}/approve", dependencies=[Depends(require_admin_token)])
def approve_filesystem_access(request_id: str, req: FilesystemAccessApproveRequest):
    try:
        filesystem_access_manager.approve(request_id, level=req.level)
    except (FilesystemAccessError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": request_id, "status": "approved"}


@app.post("/filesystem-access/{request_id}/deny", dependencies=[Depends(require_admin_token)])
def deny_filesystem_access(request_id: str):
    try:
        filesystem_access_manager.deny(request_id)
    except FilesystemAccessError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": request_id, "status": "denied"}


@app.post("/filesystem-access/{request_id}/report-outcome")
def report_filesystem_access_outcome(request_id: str, req: FilesystemAccessOutcomeRequest):
    """
    Sin token admin a propósito: el Kernel ya auto-permitió esta acción
    por política (auto_allow), esto solo deja constancia auditada de
    qué pasó DE VERDAD del lado de la extensión (¿el usuario aplicó la
    propuesta o la descartó?) — nunca decide nada, solo audita.
    """
    audit_log.record(
        AuditEvent(
            event_type="filesystem_access_granted" if req.outcome == "written" else "filesystem_access_denied",
            summary=f"Extensión de VS Code reportó '{req.outcome}' para la solicitud {request_id}",
            context={"request_id": request_id, "outcome": req.outcome, "files_written": req.files_written},
            outcome="success" if req.outcome == "written" else "failure",
        )
    )
    return {"id": request_id, "outcome": req.outcome}


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


# --- Integraciones de IDE ---
# v1 escopado: solo VS Code, sin instalar VS Code mismo (se asume ya
# instalado) ni protocolo de handshake — la extensión ya habla HTTP
# simple contra esta misma API. Ver agent_core/vscode_integration.py.

@app.get("/integrations/vscode/status")
def vscode_integration_status():
    return get_vscode_status()


@app.post("/integrations/vscode/install", dependencies=[Depends(require_admin_token)])
def vscode_integration_install():
    try:
        message = install_extension()
    except VSCodeIntegrationError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"message": message}


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


@app.get("/")
def serve_index_html():
    # BUG REAL ENCONTRADO EN USO: la suposición original de que
    # "index.html no cambia tan seguido" dejó de ser cierta — ganó
    # varios campos/ids nuevos en esta misma sesión (pestañas Modelo/
    # Integraciones). Un index.html viejo cacheado junto con un app.js
    # nuevo (ese sí ya servido sin cache) rompe en silencio: el JS
    # nuevo busca ids que el HTML viejo no tiene. Mismo criterio que
    # style.css/app.js de acá arriba.
    return FileResponse(_FRONTEND_DIR / "index.html", media_type="text/html", headers={"Cache-Control": "no-store"})


# --- Artefactos (imágenes/audio/video generados o subidos) ---
# Solo lectura: sirve lo que ya hay en data/artifacts/ para que el
# frontend pueda mostrar <img src="/artifacts/..."> — sin esto, no hay
# forma de que el navegador vea una vista previa de lo subido/generado.
_ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "data" / "artifacts"
_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=str(_ARTIFACTS_DIR)), name="artifacts")

# --- Frontend estático ---
# Mount catch-all en "/" — tiene que ser el ÚLTIMO mount registrado,
# cualquier ruta/mount nuevo va ANTES de este. La ruta explícita de
# arriba (serve_index_html) ya intercepta "/" sin cache; este mount
# sigue sirviendo cualquier OTRO archivo estático del frontend.
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
