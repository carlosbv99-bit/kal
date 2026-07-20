"""
Skill Creator: el agente propone una Skill NUEVA (código + skill.yaml),
un humano la revisa y la aprueba explícitamente antes de que exista
como carpeta real bajo skills/ — mismo espíritu que
agent_core/self_modification.py (proponer -> validar barato -> humano
decide), pero para un caso que self_modification.py excluye a
propósito: crear archivos que no existían, no modificar uno existente.

Zero standing trust, sin excepciones nuevas:
  1. propose() nunca escribe bajo skills/ — solo bajo
     data/proposed_skills/<id>/, una carpeta de REVISIÓN, invisible para
     kernel/registry/skills.py::load_skills() (que solo mira skills/).
  2. La validación en propose() es barata y sobre el MANIFIESTO, nunca
     sobre el código en sí: a diferencia de self_modification.py (que sí
     corre el denylist AST), una Skill legítima necesita os/subprocess/
     etc. para hacer algo útil (ver kernel/registry/skills.py — por eso
     una Skill nunca pasa por ese denylist). El único chequeo sobre el
     código es que sea sintácticamente válido (ast.parse no rompe) —
     un sanity check barato antes de pedirle a un humano que lo lea, no
     una barrera de seguridad real. La barrera real sigue siendo la
     MISMA que ya tiene cualquier Skill: aislamiento Docker real al
     ejecutarse, y enabled: false hasta que un humano decida lo
     contrario.
  3. approve() copia la propuesta a skills/<name>/, la firma (identidad
     PROPIA, separada de data/keys/kal_project — ver
     SkillCreatorManager.__init__), pero jamás toca `enabled` — queda
     en `false`, igual que cualquier Skill recién instalada a mano. Un
     humano todavía tiene que habilitarla explícitamente aparte (ver
     scripts/enable_skill.py) — dos gates independientes, no uno.
  4. reject() borra la propuesta sin dejar rastro en skills/ — nunca
     existió como Skill real.
"""
from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from audit.audit_log import AuditEvent, audit_log
from kernel.registry.skill_signing import SkillSigner
from sdk.permissions import Permission
from utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_STAGING_ROOT = Path("data") / "proposed_skills"
_DEFAULT_SKILLS_ROOT = Path("skills")
_DEFAULT_KEY_DIR = Path("data") / "keys" / "agent_generated_skills"

# Snake_case simple, coherente con el nombre de carpeta de las 6 skills
# ya existentes (qr_code, audio_via_kernel, ...) — rechaza cualquier
# intento de path traversal ('..', '/') en el propio nombre.
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

_CODE_FILENAME = "tool.py"
_MANIFEST_FILENAME = "skill.yaml"


class SkillProposalRejectedError(Exception):
    """La propuesta no pasó la validación barata de propose() — nunca llega a escribirse a disco."""


@dataclass
class SkillProposal:
    id: str
    name: str
    description: str
    class_name: str
    code: str
    justification: str
    permissions: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    kernel_services: list[str] = field(default_factory=list)
    parameters_schema: dict = field(default_factory=lambda: {"type": "object", "properties": {}})
    version: str = "0.1.0"
    # "pending_human_approval" | "approved" | "rejected"
    status: str = "pending_human_approval"
    detail: str = ""
    staging_dir: str = ""

    @property
    def entry_point(self) -> str:
        return f"tool:{self.class_name}"


class SkillCreatorManager:
    def __init__(
        self,
        staging_root: Path | None = None,
        skills_root: Path | None = None,
        key_dir: Path | None = None,
    ):
        self.staging_root = staging_root or _DEFAULT_STAGING_ROOT
        self.skills_root = skills_root or _DEFAULT_SKILLS_ROOT
        self.key_dir = key_dir or _DEFAULT_KEY_DIR
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.skills_root.mkdir(parents=True, exist_ok=True)
        self._proposals: dict[str, SkillProposal] = {}

    def propose(
        self,
        name: str,
        description: str,
        class_name: str,
        code: str,
        justification: str,
        permissions: list[str] | None = None,
        requirements: list[str] | None = None,
        kernel_services: list[str] | None = None,
        parameters_schema: dict | None = None,
    ) -> SkillProposal:
        permissions = permissions or []
        requirements = requirements or []
        kernel_services = kernel_services or []
        parameters_schema = parameters_schema or {"type": "object", "properties": {}}

        self._validate_name(name)
        self._validate_class_name(class_name)
        self._validate_code_syntax(code)
        self._validate_permissions(permissions)

        proposal_id = str(uuid.uuid4())
        proposal = SkillProposal(
            id=proposal_id, name=name, description=description, class_name=class_name,
            code=code, justification=justification, permissions=permissions,
            requirements=requirements, kernel_services=kernel_services,
            parameters_schema=parameters_schema,
        )

        staging_dir = self.staging_root / proposal_id
        staging_dir.mkdir(parents=True, exist_ok=True)
        (staging_dir / _CODE_FILENAME).write_text(code, encoding="utf-8")
        (staging_dir / _MANIFEST_FILENAME).write_text(self._render_manifest(proposal), encoding="utf-8")
        proposal.staging_dir = str(staging_dir)

        self._proposals[proposal_id] = proposal
        audit_log.record(
            AuditEvent(
                event_type="skill_proposed",
                summary=f"Skill nueva propuesta: '{name}' ({justification})",
                context={"proposal_id": proposal_id, "name": name, "class_name": class_name},
                outcome="pending",
            )
        )
        logger.info(f"Skill propuesta por el agente: '{name}' (proposal_id={proposal_id})")
        return proposal

    def approve(self, proposal_id: str, approved_by: str) -> SkillProposal:
        proposal = self._require_pending(proposal_id)

        final_dir = self.skills_root / proposal.name
        if final_dir.exists():
            # Chequeado también en propose(), pero el tiempo entre
            # proponer y aprobar puede ser largo — alguien pudo instalar
            # (a mano o vía market) una skill con el mismo nombre en el
            # medio. Nunca pisar una skill real existente.
            raise ValueError(f"Ya existe una skill real llamada '{proposal.name}' — no se puede aprobar sin conflicto.")

        shutil.copytree(proposal.staging_dir, final_dir)

        signer = SkillSigner(key_dir=self.key_dir)
        signer.write_signature(final_dir)

        proposal.status = "approved"
        proposal.detail = f"Instalada en {final_dir} (deshabilitada por defecto), firmada, aprobada por {approved_by}."
        shutil.rmtree(proposal.staging_dir, ignore_errors=True)

        audit_log.record(
            AuditEvent(
                event_type="skill_proposed",
                summary=f"Skill propuesta '{proposal.name}' aprobada e instalada (deshabilitada) por {approved_by}",
                context={"proposal_id": proposal_id, "name": proposal.name, "approved_by": approved_by},
                outcome="success",
            )
        )
        logger.info(
            f"Skill propuesta '{proposal.name}' instalada en {final_dir} — sigue con enabled: false, "
            "requiere habilitarla aparte (ver scripts/enable_skill.py)."
        )
        return proposal

    def reject(self, proposal_id: str, reason: str = "") -> SkillProposal:
        proposal = self._require_pending(proposal_id)

        shutil.rmtree(proposal.staging_dir, ignore_errors=True)
        proposal.status = "rejected"
        proposal.detail = reason or "Rechazada sin motivo especificado."

        audit_log.record(
            AuditEvent(
                event_type="skill_proposed",
                summary=f"Skill propuesta '{proposal.name}' rechazada: {proposal.detail}",
                context={"proposal_id": proposal_id, "name": proposal.name, "reason": reason},
                outcome="failure",
            )
        )
        logger.info(f"Skill propuesta '{proposal.name}' rechazada: {proposal.detail}")
        return proposal

    def get(self, proposal_id: str) -> SkillProposal | None:
        return self._proposals.get(proposal_id)

    def list_proposals(self) -> list[SkillProposal]:
        """Más recientes primero, mismo criterio que self_modification_manager.list_proposals()."""
        return list(self._proposals.values())[::-1]

    def _require_pending(self, proposal_id: str) -> SkillProposal:
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise ValueError(f"No existe una propuesta de skill con id {proposal_id}")
        if proposal.status != "pending_human_approval":
            raise ValueError(f"La propuesta {proposal_id} no está pendiente (status: {proposal.status})")
        return proposal

    def _validate_name(self, name: str) -> None:
        if not _NAME_PATTERN.match(name):
            raise SkillProposalRejectedError(
                f"'{name}' no es un nombre de skill válido — usá snake_case (p.ej. 'web_scraper'), "
                "empezando con una letra minúscula."
            )
        if (self.skills_root / name).exists():
            raise SkillProposalRejectedError(f"Ya existe una skill instalada llamada '{name}'.")
        if any(p.name == name and p.status == "pending_human_approval" for p in self._proposals.values()):
            raise SkillProposalRejectedError(f"Ya hay una propuesta pendiente llamada '{name}'.")

    @staticmethod
    def _validate_class_name(class_name: str) -> None:
        if not class_name.isidentifier():
            raise SkillProposalRejectedError(f"'{class_name}' no es un nombre de clase Python válido.")

    @staticmethod
    def _validate_code_syntax(code: str) -> None:
        import ast

        try:
            ast.parse(code)
        except SyntaxError as e:
            raise SkillProposalRejectedError(f"El código propuesto no es Python válido: {e}") from e

    @staticmethod
    def _validate_permissions(permissions: list[str]) -> None:
        try:
            for p in permissions:
                Permission(p)
        except ValueError as e:
            valid = ", ".join(p.value for p in Permission)
            raise SkillProposalRejectedError(f"Permiso inválido en la propuesta: {e}. Válidos: {valid}") from e

    @staticmethod
    def _render_manifest(proposal: SkillProposal) -> str:
        # enabled SIEMPRE false acá — ni propose() ni approve() lo tocan
        # nunca; solo un humano, aparte, con scripts/enable_skill.py.
        data = {
            "name": proposal.name,
            "description": proposal.description,
            "version": proposal.version,
            "entry_point": proposal.entry_point,
            "enabled": False,
            "permissions": proposal.permissions,
            "requirements": proposal.requirements,
            "kernel_services": proposal.kernel_services,
            "parameters_schema": proposal.parameters_schema,
        }
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


skill_creator_manager = SkillCreatorManager()
