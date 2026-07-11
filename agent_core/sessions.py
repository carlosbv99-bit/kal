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

Estado en memoria del proceso — no persiste a disco ni sobrevive un
reinicio del backend, mismo criterio que error_handling/circuit_breaker.py
y tool_integration/registry.py: alcanza para una sesión de trabajo, se
resetea con `uvicorn --reload` como el resto del estado en memoria de
kal (ver README: nota sobre --reload).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from tool_integration.base_tool import Artifact
from tool_integration.permissions import Permission


@dataclass
class Turn:
    goal: str
    final_answer: str


@dataclass
class Session:
    id: str
    turns: list[Turn] = field(default_factory=list)
    active_artifact: Artifact | None = None
    # Override de la cascada de permisos (ver tool_integration/permissions.py::
    # PermissionCascade) para ESTA conversación — vacío por defecto, no
    # restringe nada más allá del techo global y el nivel de confianza de
    # cada herramienta. Se puede fijar vía POST /chat (ChatRequest.
    # deny_permissions) y queda "pegajoso" para el resto de la sesión hasta
    # que se reemplace explícitamente (ver agent_core/orchestrator.py).
    denied_permissions: frozenset[Permission] = field(default_factory=frozenset)

    def history_messages(self) -> list[dict]:
        """Aplana los turnos previos a mensajes user/assistant alternados."""
        messages: list[dict] = []
        for turn in self.turns:
            messages.append({"role": "user", "content": turn.goal})
            messages.append({"role": "assistant", "content": turn.final_answer})
        return messages

    def context_message(self) -> dict | None:
        """
        Mensaje de sistema describiendo el artefacto activo, o None si
        todavía no se generó ninguno en esta sesión.
        """
        if self.active_artifact is None:
            return None
        return {
            "role": "system",
            "content": (
                f"Contexto de esta sesión: el último artefacto activo (generado por vos o "
                f"subido por el usuario) es {self.active_artifact.modality} en "
                f"'{self.active_artifact.uri}'. "
                'Si el usuario se refiere a "la imagen"/"el audio"/"el video" sin '
                "dar más detalle, probablemente hable de este."
            ),
        }


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

    def update_denied_permissions(self, session: Session, permissions: frozenset[Permission]) -> None:
        """Reemplaza el override de permisos de la sesión (no se acumula
        con el anterior — ver ChatRequest.deny_permissions en orchestrator.py)."""
        session.denied_permissions = permissions


session_manager = SessionManager()
