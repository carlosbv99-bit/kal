"""
Sesiones de conversación: continuidad entre llamadas a /chat dentro de
la misma conversación (mismo panel de chat, misma pestaña del
frontend).

BUG REAL ENCONTRADO EN USO: antes de esto, cada POST /chat armaba la
conversación desde cero ([system_prompt, goal]) — si el usuario decía
"hazme un logo" y después "hazle el fondo azul", el segundo pedido no
tenía ninguna noción de que el primero existió. Este módulo guarda,
por sesión: el historial de turnos (para continuidad conversacional
real) y el último artefacto generado (para que "la imagen" tenga a
qué referirse sin que el usuario repita la ruta).

Este módulo es SOLO almacenamiento — decidir qué de esto entra al
próximo mensaje al LLM (ventana de turnos, fusión con el contexto del
editor, etc.) es responsabilidad de agent_core/context_service.py,
no de `Session` (antes tenía esa lógica mezclada: `history_messages()`/
`context_message()` devolvían TODO sin ningún límite).

Estado en memoria del proceso — no persiste a disco ni sobrevive un
reinicio del backend, mismo criterio que error_handling/circuit_breaker.py
y kernel/registry/registry.py: alcanza para una sesión de trabajo, se
resetea con `uvicorn --reload` como el resto del estado en memoria de
kal (ver README: nota sobre --reload).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from sdk.artifacts import Artifact
from sdk.permissions import Permission


@dataclass
class Turn:
    goal: str
    final_answer: str


@dataclass
class ArtifactRecord:
    """
    Entrada del historial de artefactos de una sesión (ver
    Session.artifacts más abajo) — a diferencia de `active_artifact`
    (solo el ÚLTIMO), esto permite responder "qué generé en esta
    sesión" de verdad. `tool_name` y `created_at` son metadata de
    ORQUESTACIÓN (no del Artifact en sí, que es un tipo del SDK
    público) — por eso viven acá, no en sdk/artifacts.py.
    """
    artifact: Artifact
    tool_name: str
    created_at: float = field(default_factory=time.time)


@dataclass
class Session:
    id: str
    turns: list[Turn] = field(default_factory=list)
    active_artifact: Artifact | None = None
    # Override de la cascada de permisos (ver sdk/permissions.py::
    # PermissionCascade) para ESTA conversación — vacío por defecto, no
    # restringe nada más allá del techo global y el nivel de confianza de
    # cada herramienta. Se puede fijar vía POST /chat (ChatRequest.
    # deny_permissions) y queda "pegajoso" para el resto de la sesión hasta
    # que se reemplace explícitamente (ver agent_core/orchestrator.py).
    denied_permissions: frozenset[Permission] = field(default_factory=frozenset)
    # Historial completo de artefactos generados/subidos EN ESTA sesión
    # (ver ArtifactRecord arriba) — `active_artifact` sigue existiendo
    # tal cual para no romper nada (context_service.py lo usa para "el
    # artefacto activo"), esto es un registro ADITIVO, consultable, para
    # responder preguntas sobre el historial completo, no solo el último.
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    # Recorrido en vivo del turno EN CURSO (ver GET /chat/progress/{id}
    # en agent_core/routers/chat.py) — se reinicia al empezar cada
    # /chat, se va llenando durante el procesamiento (funciona porque
    # uvicorn corre con un solo worker, ver scripts/run_kal.sh: sin
    # --workers, este mismo diccionario en memoria es compartido entre
    # la request que está procesando el pedido y la que lo consulta).
    # Estado efímero, no es parte del historial real de la conversación
    # (eso son `turns`) — no tiene sentido que sobreviva más allá del
    # turno que lo generó.
    progress: list[dict] = field(default_factory=list)


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def get_or_create(self, session_id: str | None) -> Session:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        # Degradación con gracia (mismo espíritu que Planner.plan()): un
        # session_id desconocido (p.ej. el backend se reinició) no falla,
        # simplemente arranca una sesión nueva bajo ese mismo id.
        new_id = session_id or str(uuid.uuid4())
        session = Session(id=new_id)
        self._sessions[new_id] = session
        return session

    def record_turn(self, session: Session, goal: str, final_answer: str) -> None:
        session.turns.append(Turn(goal=goal, final_answer=final_answer))

    def update_active_artifact(self, session: Session, artifact: Artifact) -> None:
        session.active_artifact = artifact

    def record_artifact(self, session: Session, artifact: Artifact, tool_name: str) -> None:
        session.artifacts.append(ArtifactRecord(artifact=artifact, tool_name=tool_name))

    def update_denied_permissions(self, session: Session, permissions: frozenset[Permission]) -> None:
        """Reemplaza el override de permisos de la sesión (no se acumula
        con el anterior — ver ChatRequest.deny_permissions en orchestrator.py)."""
        session.denied_permissions = permissions

    def clear_progress(self, session: Session) -> None:
        session.progress = []

    def append_progress(self, session: Session, entry: dict) -> None:
        session.progress.append(entry)


session_manager = SessionManager()
