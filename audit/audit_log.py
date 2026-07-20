"""
Registro de auditoría inmutable (append-only) para decisiones autónomas.

Se registra aquí, y SOLO aquí, cualquier evento donde el agente actuó sin
intervención humana directa:
  - reparación automática de un error
  - creación o promoción de una herramienta nueva
  - ejecución de código en sandbox y su resultado
  - propuesta o aplicación de self-modification
  - activación del circuit breaker

Este log es append-only por diseño: el agente no tiene ninguna función
para editar o borrar entradas existentes, ni siquiera código generado por
él mismo (ver code_analysis/denylist.py, que bloquea escritura fuera de
/workspace y por tanto también sobre este archivo).
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from utils.correlation import get_correlation_id

AUDIT_LOG_PATH = Path("logs/audit.log")
AUDIT_LOG_PATH.parent.mkdir(exist_ok=True)

EventType = Literal[
    "error_repair",
    "tool_created",
    "tool_promoted",
    "sandbox_execution",
    "self_modification_proposed",
    "self_modification_applied",
    "self_modification_rolled_back",
    "circuit_breaker_triggered",
    "human_escalation",
    "tool_rolled_back",
    "tool_tamper_detected",
    "browser_navigation",
    "skill_loaded",
    "self_diagnosis_run",
    "permission_denied",
    "kernel_service_call",
    "kernel_service_denied",
    "syscall_policy_violation",
    "skill_enabled",
    "skill_disabled",
    "artifact_scan_blocked",
    "vscode_extension_installed",
    "kernel_line_too_long",
    "filesystem_access_requested",
    "filesystem_access_granted",
    "filesystem_access_denied",
    "filesystem_access_escalated",
    "artifact_imported",
    "network_access_requested",
    "network_access_granted",
    "network_access_denied",
    "network_access_escalated",
]


@dataclass
class AuditEvent:
    event_type: EventType
    summary: str
    context: dict[str, Any] = field(default_factory=dict)
    outcome: str = "pending"          # pending | success | failure | escalated
    timestamp: float = field(default_factory=time.time)
    prev_hash: str = ""                # encadenado para detectar manipulación
    event_hash: str = ""

    def compute_hash(self) -> str:
        payload = json.dumps(
            {
                "event_type": self.event_type,
                "summary": self.summary,
                "context": self.context,
                "outcome": self.outcome,
                "timestamp": self.timestamp,
                "prev_hash": self.prev_hash,
            },
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass
class ChainBreak:
    index: int
    event_type: str
    outcome: str
    chain_ok: bool  # prev_hash coincide con el event_hash real de la entrada anterior
    hash_ok: bool    # event_hash coincide con el contenido de la propia entrada


@dataclass
class ChainDiagnosis:
    is_valid: bool
    total_entries: int
    breaks: list[ChainBreak] = field(default_factory=list)

    def summary(self) -> str:
        if self.is_valid:
            return f"Cadena de auditoría íntegra ({self.total_entries} entradas)."

        content_tampered = [b for b in self.breaks if not b.hash_ok]
        chain_only = [b for b in self.breaks if b.hash_ok and not b.chain_ok]
        parts = [f"Cadena rota en {len(self.breaks)} de {self.total_entries} entradas."]
        if content_tampered:
            parts.append(
                f"{len(content_tampered)} con event_hash que NO coincide con su propio "
                "contenido (fuerte indicio de manipulación real del archivo)."
            )
        if chain_only:
            parts.append(
                f"{len(chain_only)} con prev_hash que no coincide pero event_hash propio "
                "íntegro (típico de una condición de carrera entre escritores concurrentes "
                "al mismo archivo, no manipulación)."
            )
        return " ".join(parts)


class AuditLog:
    """
    Cadena de eventos hash-linked (similar a un log tipo blockchain simple):
    cada entrada incluye el hash de la anterior, así una edición retroactiva
    del archivo rompe la cadena y es detectable, aunque no sea criptográficamente
    inviolable (para eso haría falta firma externa / almacenamiento WORM real).

    BUG REAL ENCONTRADO EN USO (no solo en tests): esta clase cacheaba
    `_last_hash` en memoria de proceso. Dos procesos escribiendo al mismo
    audit.log (p.ej. el servidor real + un script de verificación aparte)
    interfoliaban entradas sin que ninguno de los dos supiera lo que el
    otro acababa de escribir — cada uno confiaba en SU último hash
    cacheado, que quedaba desincronizado del archivo real, y la cadena se
    rompía (aunque cada entrada individual seguía siendo internamente
    íntegra: no era manipulación, era una condición de carrera). Corregido
    leyendo siempre el último hash del disco (nunca de un caché en
    memoria) Y tomando un lock exclusivo de archivo (fcntl.flock, POSIX)
    durante todo el ciclo leer-último-hash + escribir, para que dos
    procesos nunca puedan leer el mismo "último hash" y bifurcar la
    cadena.
    """

    def __init__(self, path: Path = AUDIT_LOG_PATH):
        self.path = path

    @staticmethod
    def _read_last_hash(f) -> str:
        """Asume que `f` ya está posicionado al inicio y bajo lock exclusivo."""
        content = f.read()
        if not content.strip():
            return "genesis"
        last_entry = json.loads(content.strip().splitlines()[-1])
        return last_entry["event_hash"]

    def record(self, event: AuditEvent) -> AuditEvent:
        # Correlation ID (ver utils/correlation.py) inyectado automáticamente
        # en el context — así ningún llamador (son ~15 call sites distintos
        # en todo el proyecto) tiene que acordarse de agregarlo a mano. Nunca
        # pisa uno que el propio llamador ya haya puesto explícitamente.
        correlation_id = get_correlation_id()
        if correlation_id and "correlation_id" not in event.context:
            event.context["correlation_id"] = correlation_id

        # "a+": crea el archivo si no existe; en POSIX, cada write() de un
        # descriptor abierto en modo append va SIEMPRE al final real del
        # archivo (O_APPEND), sin importar dónde haya quedado el cursor
        # tras el seek(0) de lectura de abajo.
        with open(self.path, "a+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                event.prev_hash = self._read_last_hash(f)
                event.event_hash = event.compute_hash()
                f.write(json.dumps(asdict(event)) + "\n")
                f.flush()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        return event

    def tail(self, n: int = 50) -> list[dict]:
        """
        Devuelve las últimas `n` entradas (más reciente primero). Usado
        por el dashboard del frontend — no valida la cadena, solo lee
        (usar verify_chain() aparte si se necesita esa garantía).
        """
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").strip().splitlines()
        recent = lines[-n:] if n > 0 else lines
        return [json.loads(line) for line in reversed(recent)]

    def verify_chain(self) -> bool:
        """
        Valida DOS cosas por cada entrada: encadenamiento (prev_hash
        coincide con el event_hash de la entrada anterior — detecta
        entradas insertadas/borradas/reordenadas) e integridad de
        contenido (el event_hash coincide con el hash recalculado de sus
        propios campos — detecta edición de summary/context/outcome/etc.
        sin recalcular el hash). Ver diagnose_chain() para el detalle de
        QUÉ entradas fallan y de qué tipo, útil para investigar la causa.
        """
        return self.diagnose_chain().is_valid

    def diagnose_chain(self) -> ChainDiagnosis:
        if not self.path.exists():
            return ChainDiagnosis(is_valid=True, total_entries=0)

        lines = self.path.read_text(encoding="utf-8").strip().splitlines()
        prev = "genesis"
        breaks: list[ChainBreak] = []

        for i, line in enumerate(lines):
            entry = json.loads(line)

            chain_ok = entry["prev_hash"] == prev
            recomputed = AuditEvent(
                event_type=entry["event_type"],
                summary=entry["summary"],
                context=entry["context"],
                outcome=entry["outcome"],
                timestamp=entry["timestamp"],
                prev_hash=entry["prev_hash"],
            ).compute_hash()
            hash_ok = recomputed == entry["event_hash"]

            if not chain_ok or not hash_ok:
                breaks.append(
                    ChainBreak(
                        index=i, event_type=entry["event_type"], outcome=entry["outcome"],
                        chain_ok=chain_ok, hash_ok=hash_ok,
                    )
                )

            # Avanza con el hash RECLAMADO por la entrada (no el recomputado):
            # si esta entrada fue tampereada, la siguiente debe seguir
            # evaluándose contra lo que el archivo dice que es su hash, para
            # poder seguir detectando rupturas de encadenamiento posteriores
            # de forma independiente de esta.
            prev = entry["event_hash"]

        return ChainDiagnosis(is_valid=not breaks, total_entries=len(lines), breaks=breaks)


audit_log = AuditLog()
