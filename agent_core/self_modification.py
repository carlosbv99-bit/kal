"""
Pipeline real de self-modification.

Diferencia con tool_integration/registry.py (creación de herramientas
dinámicas): aquella valida y ejecuta código NUEVO como una herramienta
standalone (un script que se corre y se observa su salida). Esto aquí
valida una MODIFICACIÓN a un archivo EXISTENTE del proyecto, y la
"prueba" real es correr el test suite completo contra una COPIA
aislada del proyecto con el cambio ya aplicado — nunca in-place, nunca
contra el proyecto real hasta que un humano aprueba explícitamente.

Flujo de propose():
  1. Si target_path es núcleo (agent_core/, error_handling/, sandbox/):
     bloqueo inmediato, ni siquiera se valida ni se prueba. Ver
     CORE_PATHS_HARDCODED — deliberadamente independiente de
     config.yaml para que no se pueda desactivar alterando la config.
  2. Validación estática del código propuesto (mismo denylist AST que
     usa el sandbox para código no confiable).
  3. Copia completa del proyecto a un directorio temporal (dos copias:
     "baseline" sin el cambio, "candidate" con el cambio aplicado).
  4. Se corre el test suite completo en AMBAS copias.
  5. Si el candidato tiene más fallos/errores o menos tests pasando que
     el baseline: regresión detectada, propuesta rechazada.
  6. Sin regresión: la propuesta queda "pending_human_approval". Nunca
     se aplica sola, ni siquiera para módulos periféricos — escribir a
     disco es la acción de mayor alcance de todo el proyecto.

apply() escribe el cambio al archivo real, guardando un backup
timestamped para poder revertir con rollback() si algo se detecta mal
después (p.ej. en producción, con datos reales, algo que los tests no
cubrieron).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from audit.audit_log import AuditEvent, audit_log
from code_analysis.ast_validator import validate_code
from utils.config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# Última barrera, independiente de config.yaml — igual criterio que en
# el resto del proyecto: aunque la config fuera corrompida por código
# generado dinámicamente, estas rutas nunca se auto-modifican.
CORE_PATHS_HARDCODED = ("agent_core/", "error_handling/", "sandbox/")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Directorios que no tiene sentido copiar al probar una modificación:
# entornos virtuales (pueden pesar GBs con torch instalado), datos
# generados, logs, y caches — ninguno afecta el resultado de los tests.
_COPY_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".git", ".venv", "venv", "data", "logs", ".pytest_cache"
)


class PathTraversalError(Exception):
    """target_path intenta escapar del directorio del proyecto."""


@dataclass
class TestRunResult:
    passed: int
    failed: int
    errors: int
    raw_output: str
    exit_code: int

    @property
    def is_clean(self) -> bool:
        return self.failed == 0 and self.errors == 0


@dataclass
class SelfModProposal:
    id: str
    target_path: str
    proposed_source: str
    justification: str
    # "disabled" | "blocked_core" | "rejected_unsafe" |
    # "regression_detected" | "pending_human_approval" | "applied" |
    # "rolled_back"
    status: str
    baseline_tests: TestRunResult | None = None
    candidate_tests: TestRunResult | None = None
    detail: str = ""
    backup_path: str | None = None


class SelfModificationManager:
    def __init__(self, project_root: Path | None = None):
        self.project_root = (project_root or PROJECT_ROOT).resolve()
        self._proposals: dict[str, SelfModProposal] = {}

    def is_core_path(self, target_path: str) -> bool:
        return target_path.startswith(CORE_PATHS_HARDCODED) or settings.self_modification.is_core_path(target_path)

    def propose(
        self,
        target_path: str,
        proposed_source: str,
        justification: str,
        test_args: list[str] | None = None,
    ) -> SelfModProposal:
        proposal_id = str(uuid.uuid4())
        test_args = test_args or ["-q", "--tb=short"]

        # Chequeo MÁS TEMPRANO que cualquier otro, antes incluso de dejar
        # el evento "pending" habitual: si self-modification está
        # deshabilitada por configuración, no corresponde ni empezar a
        # auditar una propuesta "en curso" — se resuelve en un solo
        # evento. BUG REAL encontrado en revisión (2026-07-11):
        # settings.self_modification.enabled existía en el esquema
        # (default False en el modelo) pero ningún código lo leía nunca
        # — config.yaml lo tenía en `true` sin que importara, la
        # funcionalidad quedaba SIEMPRE activa sin importar ese valor.
        # Default ahora en `false` en config.yaml: opt-in explícito.
        if not settings.self_modification.enabled:
            proposal = SelfModProposal(
                id=proposal_id, target_path=target_path, proposed_source=proposed_source,
                justification=justification, status="disabled",
                detail="self-modification está deshabilitada por configuración (self_modification.enabled: false).",
            )
            self._proposals[proposal_id] = proposal
            self._audit(proposal, "failure", proposal.detail)
            return proposal

        audit_log.record(
            AuditEvent(
                event_type="self_modification_proposed",
                summary=f"Propuesta de modificación sobre {target_path}",
                context={"target_path": target_path, "justification": justification, "proposal_id": proposal_id},
                outcome="pending",
            )
        )

        if self.is_core_path(target_path):
            logger.warning(f"Propuesta sobre módulo NÚCLEO ({target_path}) bloqueada — ni se valida ni se prueba.")
            proposal = SelfModProposal(
                id=proposal_id, target_path=target_path, proposed_source=proposed_source,
                justification=justification, status="blocked_core",
                detail="agent_core/, error_handling/ y sandbox/ nunca se prueban ni aplican automáticamente.",
            )
            self._proposals[proposal_id] = proposal
            # BUG REAL ENCONTRADO EN REVISIÓN: este era el único branch
            # que no dejaba un segundo evento de auditoría con el
            # desenlace — el evento "pending" inicial quedaba huérfano
            # para el caso más crítico de todos (bloqueo de núcleo).
            # Los demás branches (rejected_unsafe, regression_detected,
            # pending_human_approval) sí completan el ciclo intent+outcome.
            self._audit(proposal, "failure", proposal.detail)
            return proposal

        try:
            self._safe_join(self.project_root, target_path)
        except PathTraversalError as e:
            proposal = SelfModProposal(
                id=proposal_id, target_path=target_path, proposed_source=proposed_source,
                justification=justification, status="rejected_unsafe", detail=str(e),
            )
            self._proposals[proposal_id] = proposal
            self._audit(proposal, "failure", str(e))
            return proposal

        validation = validate_code(proposed_source)
        if not validation.is_safe:
            reason = validation.syntax_error or "; ".join(validation.violations)
            proposal = SelfModProposal(
                id=proposal_id, target_path=target_path, proposed_source=proposed_source,
                justification=justification, status="rejected_unsafe", detail=reason,
            )
            self._proposals[proposal_id] = proposal
            self._audit(proposal, "failure", f"Rechazada en validación estática: {reason}")
            return proposal

        with tempfile.TemporaryDirectory(prefix="kal_selfmod_") as tmp_dir:
            candidate_root = Path(tmp_dir) / "candidate"
            baseline_root = Path(tmp_dir) / "baseline"
            self._copy_project(candidate_root)
            self._copy_project(baseline_root)

            candidate_target = self._safe_join(candidate_root, target_path)
            if not candidate_target.exists():
                proposal = SelfModProposal(
                    id=proposal_id, target_path=target_path, proposed_source=proposed_source,
                    justification=justification, status="rejected_unsafe",
                    detail=(
                        f"target_path '{target_path}' no existe en el proyecto actual — "
                        "self-modification solo modifica archivos existentes, no crea nuevos "
                        "(usar tool_integration/registry.py para herramientas nuevas)."
                    ),
                )
                self._proposals[proposal_id] = proposal
                self._audit(proposal, "failure", proposal.detail)
                return proposal

            candidate_target.write_text(proposed_source, encoding="utf-8")

            logger.info("Corriendo test suite baseline (sin el cambio) para poder comparar regresiones...")
            baseline_result = self._run_tests(baseline_root, test_args)

            logger.info("Corriendo test suite candidato (con el cambio ya aplicado)...")
            candidate_result = self._run_tests(candidate_root, test_args)

            regression = (
                candidate_result.failed > baseline_result.failed
                or candidate_result.errors > baseline_result.errors
                or candidate_result.passed < baseline_result.passed
            )

            if regression:
                proposal = SelfModProposal(
                    id=proposal_id, target_path=target_path, proposed_source=proposed_source,
                    justification=justification, status="regression_detected",
                    baseline_tests=baseline_result, candidate_tests=candidate_result,
                    detail=(
                        f"Regresión: baseline(passed={baseline_result.passed}, failed={baseline_result.failed}, "
                        f"errors={baseline_result.errors}) vs candidato(passed={candidate_result.passed}, "
                        f"failed={candidate_result.failed}, errors={candidate_result.errors})"
                    ),
                )
                self._proposals[proposal_id] = proposal
                self._audit(proposal, "failure", proposal.detail)
                return proposal

            proposal = SelfModProposal(
                id=proposal_id, target_path=target_path, proposed_source=proposed_source,
                justification=justification, status="pending_human_approval",
                baseline_tests=baseline_result, candidate_tests=candidate_result,
                detail="Sin regresiones detectadas. Requiere aprobación humana explícita para aplicarse a disco.",
            )
            self._proposals[proposal_id] = proposal
            self._audit(proposal, "escalated", "Sin regresiones — pendiente de aprobación humana")
            return proposal

    def apply(self, proposal_id: str, approved_by: str) -> SelfModProposal:
        proposal = self._require_proposal(proposal_id)
        if proposal.status != "pending_human_approval":
            raise ValueError(f"La propuesta {proposal_id} no está pendiente de aprobación (status: {proposal.status})")

        # El número de versión se calcula ANTES de nombrar el backup e
        # incluirse en el nombre del archivo: dos apply() dentro del
        # mismo segundo generarían el mismo nombre con solo
        # int(time.time()) (BUG REAL encontrado al escribir
        # rollback_to(): el segundo backup pisaba al primero,
        # rollback_to(v1) devolvía el contenido de v2).
        next_version = len(self._load_version_index(proposal.target_path)) + 1
        real_target = self._safe_join(self.project_root, proposal.target_path)
        backup_path = real_target.with_name(real_target.name + f".bak.v{next_version}.{int(time.time())}")
        shutil.copy2(real_target, backup_path)
        real_target.write_text(proposal.proposed_source, encoding="utf-8")

        proposal.status = "applied"
        proposal.backup_path = str(backup_path)

        version = self._append_version_entry(
            proposal.target_path,
            {"backup_path": str(backup_path), "proposal_id": proposal_id, "applied_at": time.time()},
        )

        audit_log.record(
            AuditEvent(
                event_type="self_modification_applied",
                summary=f"Modificación aplicada a {proposal.target_path} (aprobada por {approved_by}, v{version})",
                context={
                    "proposal_id": proposal_id, "target_path": proposal.target_path,
                    "approved_by": approved_by, "backup_path": proposal.backup_path, "version": version,
                },
                outcome="success",
            )
        )
        logger.info(f"Self-modification aplicada a {proposal.target_path}. Backup: {backup_path} (v{version})")
        return proposal

    def rollback(self, proposal_id: str, reason: str = "") -> SelfModProposal:
        proposal = self._require_proposal(proposal_id)
        if proposal.status != "applied":
            raise ValueError(f"La propuesta {proposal_id} no está aplicada, nada que revertir (status: {proposal.status})")
        if proposal.backup_path is None:
            raise RuntimeError(f"Propuesta {proposal_id} marcada 'applied' sin backup registrado — no se puede revertir con seguridad")

        real_target = self._safe_join(self.project_root, proposal.target_path)
        shutil.copy2(proposal.backup_path, real_target)
        proposal.status = "rolled_back"

        audit_log.record(
            AuditEvent(
                event_type="self_modification_rolled_back",
                summary=f"Modificación revertida en {proposal.target_path}",
                context={"proposal_id": proposal_id, "target_path": proposal.target_path, "reason": reason},
                outcome="success",
            )
        )
        logger.info(f"Self-modification revertida en {proposal.target_path}")
        return proposal

    def list_versions(self, target_path: str) -> list[dict]:
        """Historial de aplicaciones exitosas sobre target_path, más antigua primero."""
        return self._load_version_index(target_path)

    def rollback_to(self, target_path: str, version: int, reason: str = "") -> None:
        """
        Restaura target_path al contenido que tenía en una versión
        específica del historial (no necesariamente la última aplicada
        — para eso ya está rollback(proposal_id)). Sirve para volver
        varios pasos atrás sin tener que conocer el proposal_id exacto
        de cada apply() intermedio.
        """
        entries = self._load_version_index(target_path)
        entry = next((e for e in entries if e["version"] == version), None)
        if entry is None:
            raise ValueError(f"No existe la versión {version} para '{target_path}'")

        backup_path = Path(entry["backup_path"])
        if not backup_path.exists():
            raise RuntimeError(f"El backup de la versión {version} ya no existe en disco: {backup_path}")

        real_target = self._safe_join(self.project_root, target_path)
        shutil.copy2(backup_path, real_target)

        audit_log.record(
            AuditEvent(
                event_type="self_modification_rolled_back",
                summary=f"{target_path} revertido a versión {version}",
                context={"target_path": target_path, "version": version, "reason": reason},
                outcome="success",
            )
        )
        logger.info(f"{target_path} revertido a v{version} ({reason})")

    def _version_index_path(self, target_path: str) -> Path:
        """
        Índice de versiones por target_path (una entrada por cada
        apply() exitoso), para poder volver a una versión específica con
        rollback_to(), no solo a la última aplicada (eso ya lo cubre
        rollback()). Vive bajo self.project_root — no un directorio fijo
        del módulo — para que los tests que usan un `fake_project`
        aislado (ver tests/test_self_modification.py) no escriban en
        el data/ real de kal.
        """
        versions_dir = self.project_root / "data" / "selfmod_versions"
        versions_dir.mkdir(parents=True, exist_ok=True)
        safe_name = target_path.replace("/", "__")
        return versions_dir / f"{safe_name}.json"

    def _load_version_index(self, target_path: str) -> list[dict]:
        path = self._version_index_path(target_path)
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def _append_version_entry(self, target_path: str, entry: dict) -> int:
        entries = self._load_version_index(target_path)
        version = len(entries) + 1
        entries.append({"version": version, **entry})
        self._version_index_path(target_path).write_text(json.dumps(entries, indent=2), encoding="utf-8")
        return version

    def get(self, proposal_id: str) -> SelfModProposal | None:
        return self._proposals.get(proposal_id)

    def list_proposals(self) -> list[SelfModProposal]:
        """Para el dashboard del frontend — más recientes primero (orden de inserción)."""
        return list(self._proposals.values())[::-1]

    def _require_proposal(self, proposal_id: str) -> SelfModProposal:
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise ValueError(f"No existe una propuesta con id {proposal_id}")
        return proposal

    @staticmethod
    def _safe_join(base: Path, relative: str) -> Path:
        """
        Une `base` con `relative` y garantiza que el resultado no se
        sale de `base` (protección contra path traversal vía '../').
        Sin esto, un target_path como '../../etc/cron.d/evil' podría
        escribir fuera del directorio aislado de pruebas o, peor, fuera
        del proyecto real en apply().
        """
        candidate = (base / relative).resolve()
        base_resolved = base.resolve()
        if candidate != base_resolved and base_resolved not in candidate.parents:
            raise PathTraversalError(
                f"target_path '{relative}' se sale del directorio del proyecto (path traversal detectado)"
            )
        return candidate

    def _copy_project(self, dest: Path) -> None:
        shutil.copytree(self.project_root, dest, ignore=_COPY_IGNORE)

    def _run_tests(self, root: Path, test_args: list[str]) -> TestRunResult:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *test_args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=600,
        )
        passed, failed, errors = self._parse_pytest_summary(result.stdout)
        return TestRunResult(passed=passed, failed=failed, errors=errors, raw_output=result.stdout, exit_code=result.returncode)

    @staticmethod
    def _parse_pytest_summary(output: str) -> tuple[int, int, int]:
        """
        Parsea el resumen final de pytest (p.ej. "3 failed, 12 passed,
        2 errors in 4.51s") con regex simple. Punto de fragilidad
        conocido: si pytest cambia su formato de salida entre versiones
        mayores, esto podría necesitar ajuste.
        """
        passed = failed = errors = 0
        if m := re.search(r"(\d+) passed", output):
            passed = int(m.group(1))
        if m := re.search(r"(\d+) failed", output):
            failed = int(m.group(1))
        if m := re.search(r"(\d+) error", output):
            errors = int(m.group(1))
        return passed, failed, errors

    def _audit(self, proposal: SelfModProposal, outcome: str, detail: str) -> None:
        audit_log.record(
            AuditEvent(
                event_type="self_modification_proposed",
                summary=f"Propuesta {proposal.id} sobre {proposal.target_path}: {detail}",
                context={"proposal_id": proposal.id, "target_path": proposal.target_path, "status": proposal.status},
                outcome=outcome,
            )
        )


self_modification_manager = SelfModificationManager()
