"""
Circuit breaker: evita que un bucle de auto-reparación fallido consuma
recursos indefinidamente. Tras N intentos fallidos sobre el MISMO error
(identificado por firma, no por instancia), se abre el circuito y se
escala a un humano en vez de seguir reintentando.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

from audit.audit_log import AuditEvent, audit_log
from utils.config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def error_signature(error_type: str, error_message: str, location: str) -> str:
    """Identifica un error de forma estable para no confundir reintentos
    de errores distintos con reintentos del mismo error."""
    raw = f"{error_type}:{location}:{error_message[:200]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class _CircuitState:
    attempts: int = 0
    first_seen: float = field(default_factory=time.time)
    open: bool = False


class CircuitBreaker:
    def __init__(self, max_attempts: int | None = None):
        self.max_attempts = max_attempts or settings.error_handling.max_repair_attempts
        self._states: dict[str, _CircuitState] = {}

    def allow_attempt(self, signature: str) -> bool:
        state = self._states.setdefault(signature, _CircuitState())
        return not state.open

    def open_circuit_count(self) -> int:
        """Para la franja de estado del frontend — cuántas firmas de error están escaladas ahora mismo."""
        return sum(1 for state in self._states.values() if state.open)

    def record_attempt(self, signature: str, success: bool, context: dict) -> None:
        state = self._states.setdefault(signature, _CircuitState())

        if success:
            # éxito resetea el contador para esa firma de error
            self._states[signature] = _CircuitState()
            return

        state.attempts += 1
        if state.attempts >= self.max_attempts:
            state.open = True
            logger.error(
                f"Circuit breaker ABIERTO para error {signature} "
                f"tras {state.attempts} intentos fallidos. Escalando a humano."
            )
            audit_log.record(
                AuditEvent(
                    event_type="circuit_breaker_triggered",
                    summary=f"Circuito abierto tras {state.attempts} intentos fallidos",
                    context={**context, "error_signature": signature},
                    outcome="escalated",
                )
            )
            audit_log.record(
                AuditEvent(
                    event_type="human_escalation",
                    summary="Error requiere intervención humana",
                    context={**context, "error_signature": signature},
                    outcome="pending",
                )
            )

    def reset(self, signature: str) -> None:
        """Permite a un humano reabrir manualmente el circuito tras revisar."""
        self._states.pop(signature, None)


circuit_breaker = CircuitBreaker()
