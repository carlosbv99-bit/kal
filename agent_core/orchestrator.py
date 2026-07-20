"""
Orchestrator: punto de coordinación central del agente.

Responsabilidades:
  - Construir el singleton Orchestrator (memoria, tareas, herramientas,
    sesiones, self-modification, self-diagnosis) y el cliente LLM real.
  - Armar la app de FastAPI: token administrativo, montar los routers
    por dominio (agent_core/routers/*.py) y servir el frontend estático.
  - Exponer el loop de razonamiento (agent_core/llm/agent_loop.py) vía
    /chat (agent_core/routers/chat.py) — esto es lo que conecta a kal
    con Ollama y lo hace utilizable desde el frontend, no solo desde
    llamadas API de bajo nivel.

Este archivo YA NO declara los endpoints en sí (2026-07-20: eran 44,
todos acá, con imports de prácticamente todos los subsistemas del
proyecto — un cuello de botella de mantenibilidad real). Cada dominio
(chat, tareas, herramientas, memoria, self-modification, permisos,
diagnóstico, integraciones de IDE, auditoría, estado general) vive en
su propio APIRouter bajo agent_core/routers/, que importa desde acá lo
que necesita compartir (el singleton `orchestrator`, `require_admin_token`,
`_artifact_url`, `_reinject_llm_client`) — nunca al revés.
"""
from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent_core.context_service import ContextService
from agent_core.llm.agent_loop import AgentLoop
from agent_core.llm.ollama_client import OllamaClient
from agent_core.llm.openai_compatible_client import OpenAICompatibleClient
from agent_core.llm.planner import PlanningAgentLoop
from agent_core.llm.provider import LLMProvider
from agent_core.llm_settings import read_llm_env_var
from agent_core.memory.manager import MemoryManager
from agent_core.self_diagnosis import SelfDiagnosisAgent
from agent_core.self_modification import self_modification_manager
from agent_core.sessions import session_manager
from kernel.registry.registry import tool_registry
from task_execution.executor import TaskExecutor
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


# --- Artefactos (imágenes/audio/video generados o subidos) ---
_ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "data" / "artifacts"
_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def _artifact_url(uri: str) -> str | None:
    """
    Traduce una ruta de archivo real (uri de un Artifact) a la URL
    servida por el mount /artifacts (solo lectura, ver más abajo) para
    que el frontend pueda mostrarla en <img src=...>. None si la ruta
    no está bajo data/artifacts/ (no se puede servir).

    Hallazgo de la revisión de seguridad 2026-07-09: la versión anterior
    comparaba con Path.relative_to() SIN resolver antes — un uri como
    "data/artifacts/../../etc/passwd" tiene ('data', 'artifacts') como
    prefijo literal de sus partes, así que relative_to() lo aceptaba
    igual (devolviendo "../../etc/passwd"), dependiendo enteramente de
    que Starlette bloqueara el traversal real al servir el archivo. Hoy
    no hay ningún llamador que pase un uri controlado por un tercero,
    pero la función debe ser segura POR SÍ SOLA, no solo por la capa que
    la usa después. resolve() normaliza ".." y símlinks ANTES de
    comparar, así que un intento de escape termina en una ruta absoluta
    fuera de _ARTIFACTS_DIR y relative_to() lo rechaza de verdad.
    """
    try:
        return f"/artifacts/{Path(uri).resolve().relative_to(_ARTIFACTS_DIR)}"
    except ValueError:
        return None


# --- Routers por dominio (ver agent_core/routers/) ---
# Importados recién acá, DESPUÉS de que orchestrator/require_admin_token/
# _artifact_url/_reinject_llm_client ya existen en este módulo — cada
# router hace `from agent_core.orchestrator import ...` de estos nombres,
# así que tienen que estar definidos antes de este punto.
from agent_core.routers import (  # noqa: E402
    audit,
    chat,
    diagnostics,
    health,
    llm_settings,
    memory,
    permissions,
    self_modification,
    skill_creator,
    tasks,
    tools,
    vscode_integration,
)

for _router_module in (
    health, llm_settings, chat, tasks, tools, memory,
    self_modification, permissions, diagnostics, vscode_integration, audit,
    skill_creator,
):
    app.include_router(_router_module.router)


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


app.mount("/artifacts", StaticFiles(directory=str(_ARTIFACTS_DIR)), name="artifacts")

# --- Frontend estático ---
# Mount catch-all en "/" — tiene que ser el ÚLTIMO mount registrado,
# cualquier ruta/mount nuevo va ANTES de este. La ruta explícita de
# arriba (serve_index_html) ya intercepta "/" sin cache; este mount
# sigue sirviendo cualquier OTRO archivo estático del frontend.
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
