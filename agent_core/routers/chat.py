"""
Chat / agente: /chat, /uploads.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from agent_core.context_service import EditorContextSignals
from agent_core.llm.provider import ProviderError
from agent_core.orchestrator import _artifact_url, orchestrator
from sdk.artifacts import Artifact
from sdk.permissions import Permission
from utils.config import settings
from utils.correlation import new_id, set_correlation_id
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class EditorContextRequest(BaseModel):
    """
    Señal cruda del editor (ver agent_core/context_service.py) — el
    frontend (extensión de VS Code) NUNCA manda texto ya formateado
    acá, solo estos campos. El Context Service decide cómo se ve en
    el mensaje final al LLM.
    """
    relative_path: str
    language_id: str
    text: str
    is_selection: bool
    # Pieza mínima de "Editor Context Provider" (2026-07-20) — ver
    # agent_core/context_service.py::EditorContextSignals. Ambos vacíos
    # por defecto: compatibilidad con clientes viejos que todavía no
    # los mandan.
    workspace_tree: list[str] = []
    open_editors: list[str] = []


class ChatRequest(BaseModel):
    goal: str
    model: str | None = None
    use_planner: bool | None = None  # None = usar el default de config.yaml (llm.planning_enabled)
    session_id: str | None = None  # None = sesión nueva (ver agent_core/sessions.py)
    # Override de la cascada de permisos para esta sesión (ver
    # sdk/permissions.py::PermissionCascade). None = no tocar
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


@router.post("/chat")
def chat(req: ChatRequest):
    # Correlation ID (ver utils/correlation.py): un identificador corto
    # que va a aparecer en cada línea de logs/agent.log y en el context
    # de cada entrada de logs/audit.log generada mientras se procesa
    # este pedido — incluida cualquier skill sandboxeada que se llame en
    # el camino. Se devuelve en la respuesta para que, ante un fallo
    # real, alcance con este valor (no hay que reconstruir la cadena a
    # mano cruzando ambos logs).
    correlation_id = new_id()
    set_correlation_id(correlation_id)
    logger.info(f"POST /chat: {req.goal!r}")

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
            workspace_tree=req.editor_context.workspace_tree,
            open_editors=req.editor_context.open_editors,
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
        if step.artifact.modality == "workspace_file_request":
            # ReadWorkspaceFileTool (tool_integration/adapters/vscode_files.py)
            # nunca lee el archivo real acá — el backend no tiene acceso al
            # disco de VS Code. Esto solo le avisa a la extensión qué ruta
            # pedir; ella responde encadenando un /chat nuevo con el
            # contenido real (ver vscode-extension/src/readWorkspaceFile.ts).
            return {
                "modality": "workspace_file_request",
                "request_id": step.artifact.metadata.get("request_id"),
                "path": step.artifact.metadata.get("path"),
            }
        if step.artifact.modality != "image":
            return None
        url = _artifact_url(step.artifact.uri)
        if url is None:
            return None
        return {"modality": step.artifact.modality, "url": url, "path": step.artifact.uri}

    return {
        "session_id": session.id,
        "correlation_id": correlation_id,
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


@router.post("/uploads")
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
