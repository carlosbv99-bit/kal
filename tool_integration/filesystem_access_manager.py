"""
Permission Manager del Kernel para filesystem — decide si una acción
concreta (create/read/modify/delete/rename) sobre un alcance concreto
(workspace/home/external) se auto-permite o necesita un humano, deja
auditoría de cada decisión, y recuerda concesiones ya otorgadas para no
volver a preguntar.

ORTOGONAL a tool_integration/permission_cascade.py::PermissionCascade:
aquella decide "¿esta herramienta puede pedir tocar el filesystem en
absoluto?" (FILESYSTEM_READ/WRITE por nivel de confianza, chequeada
ANTES de invocar cualquier handler). Esta decide, para una herramienta
que YA tiene FILESYSTEM_WRITE, "¿esta acción concreta necesita que un
humano la apruebe, o ya está cubierta por la política/una concesión
previa?".

NUNCA ejecuta la escritura real — eso es responsabilidad de quien
consulta esta decisión (para el agente IDE de VS Code, la extensión
misma, vía vscode.workspace.fs; el backend de Python jamás tiene acceso
al workspace real de un editor externo). El rol de este módulo es
puramente de POLÍTICA + AUDITORÍA + memoria de concesiones.

Separado de tool_integration/filesystem_permissions.py por el mismo
motivo que permission_cascade.py está separado de permissions.py: este
módulo depende de utils.config/audit_log, así que NUNCA se envía a un
contenedor de skill.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import uuid4

from audit.audit_log import AuditEvent, audit_log
from tool_integration.filesystem_permissions import FilesystemAction, FilesystemScope
from utils.config import settings

FilesystemAccessDecision = Literal["auto_allowed", "requires_approval"]
GrantLevel = Literal["once", "session", "project", "skill"]

_GRANTS_PATH = Path("data/keys/filesystem_grants.json")


class FilesystemAccessError(Exception):
    """El id pedido no corresponde a ninguna solicitud pendiente conocida."""


@dataclass
class PendingFilesystemAccess:
    id: str
    skill_name: str
    scope: FilesystemScope
    action: FilesystemAction
    resource_key: str
    status: str = "pending_approval"  # "pending_approval" | "approved" | "denied"


@dataclass
class _Grant:
    skill_name: str
    scope: str
    action: str
    resource_key: str | None  # None = aplica a cualquier resource_key de esta skill/scope/acción ("skill" level)


def _grant_matches(grant: _Grant, skill_name: str, scope: str, action: str, resource_key: str) -> bool:
    if grant.skill_name != skill_name or grant.scope != scope or grant.action != action:
        return False
    return grant.resource_key is None or grant.resource_key == resource_key


class FilesystemAccessManager:
    def __init__(self, grants_path: Path | None = None):
        self._grants_path = grants_path or _GRANTS_PATH
        self._session_grants: list[_Grant] = []
        self._pending: dict[str, PendingFilesystemAccess] = {}

    # --- Decisión ---

    def evaluate(
        self, skill_name: str, scope: FilesystemScope, action: FilesystemAction, resource_key: str
    ) -> FilesystemAccessDecision:
        """
        Fail-safe por diseño: si nada dice explícitamente que esto se
        auto-permite (política de config.yaml o una concesión previa),
        requiere aprobación — nunca al revés.
        """
        self._audit(
            "filesystem_access_requested",
            f"'{skill_name}' pide {action.value} en alcance {scope.value} ({resource_key})",
            skill_name, scope, action, resource_key, outcome="pending",
        )

        if self._is_policy_auto_allowed(scope, action) or self._has_grant(skill_name, scope, action, resource_key):
            self._audit(
                "filesystem_access_granted",
                f"'{skill_name}' autorizado automáticamente: {action.value} en {scope.value} ({resource_key})",
                skill_name, scope, action, resource_key, outcome="success",
            )
            return "auto_allowed"

        self._audit(
            "filesystem_access_escalated",
            f"'{skill_name}' requiere aprobación humana: {action.value} en {scope.value} ({resource_key})",
            skill_name, scope, action, resource_key, outcome="escalated",
        )
        return "requires_approval"

    def _is_policy_auto_allowed(self, scope: FilesystemScope, action: FilesystemAction) -> bool:
        allowed_actions = settings.filesystem_access.auto_allow.get(scope.value, [])
        return action.value in allowed_actions

    def _has_grant(self, skill_name: str, scope: FilesystemScope, action: FilesystemAction, resource_key: str) -> bool:
        grants = self._session_grants + self._load_persisted_grants()
        return any(_grant_matches(g, skill_name, scope.value, action.value, resource_key) for g in grants)

    # --- Solicitudes pendientes (cuando evaluate() da requires_approval) ---

    def create_pending_request(
        self, skill_name: str, scope: FilesystemScope, action: FilesystemAction, resource_key: str
    ) -> PendingFilesystemAccess:
        pending = PendingFilesystemAccess(
            id=str(uuid4()), skill_name=skill_name, scope=scope, action=action, resource_key=resource_key
        )
        self._pending[pending.id] = pending
        return pending

    def list_pending(self) -> list[PendingFilesystemAccess]:
        return [p for p in self._pending.values() if p.status == "pending_approval"]

    def approve(self, request_id: str, level: GrantLevel) -> None:
        pending = self._get_pending(request_id)
        pending.status = "approved"
        self._grant(pending.skill_name, pending.scope, pending.action, pending.resource_key, level)
        self._audit(
            "filesystem_access_granted",
            f"Aprobado por humano ({level}): '{pending.skill_name}' — {pending.action.value} en "
            f"{pending.scope.value} ({pending.resource_key})",
            pending.skill_name, pending.scope, pending.action, pending.resource_key, outcome="success",
        )

    def deny(self, request_id: str) -> None:
        pending = self._get_pending(request_id)
        pending.status = "denied"
        self._audit(
            "filesystem_access_denied",
            f"Denegado por humano: '{pending.skill_name}' — {pending.action.value} en "
            f"{pending.scope.value} ({pending.resource_key})",
            pending.skill_name, pending.scope, pending.action, pending.resource_key, outcome="failure",
        )

    def _get_pending(self, request_id: str) -> PendingFilesystemAccess:
        pending = self._pending.get(request_id)
        if pending is None:
            raise FilesystemAccessError(f"No existe una solicitud de acceso a filesystem pendiente con id '{request_id}'.")
        return pending

    # --- Concesiones (grants) ---

    def _grant(
        self, skill_name: str, scope: FilesystemScope, action: FilesystemAction, resource_key: str, level: GrantLevel
    ) -> None:
        if level == "once":
            return  # nunca se recuerda — la próxima vez vuelve a preguntar
        if level == "session":
            self._session_grants.append(_Grant(skill_name, scope.value, action.value, resource_key))
            return
        if level == "project":
            self._persist_grant(_Grant(skill_name, scope.value, action.value, resource_key))
            return
        if level == "skill":
            self._persist_grant(_Grant(skill_name, scope.value, action.value, resource_key=None))
            return
        raise ValueError(f"Nivel de concesión desconocido: '{level}'")

    def _load_persisted_grants(self) -> list[_Grant]:
        if not self._grants_path.exists():
            return []
        raw = json.loads(self._grants_path.read_text(encoding="utf-8"))
        return [_Grant(**g) for g in raw]

    def _persist_grant(self, grant: _Grant) -> None:
        grants = self._load_persisted_grants()
        grants.append(grant)
        self._grants_path.parent.mkdir(parents=True, exist_ok=True)
        self._grants_path.write_text(
            json.dumps([g.__dict__ for g in grants], indent=2), encoding="utf-8"
        )

    # --- Auditoría ---

    @staticmethod
    def _audit(
        event_type: str, summary: str, skill_name: str, scope: FilesystemScope, action: FilesystemAction,
        resource_key: str, outcome: str,
    ) -> None:
        audit_log.record(
            AuditEvent(
                event_type=event_type,  # type: ignore[arg-type]
                summary=summary,
                context={
                    "skill_name": skill_name, "scope": scope.value, "action": action.value,
                    "resource_key": resource_key,
                },
                outcome=outcome,
            )
        )


# Singleton, mismo patrón que tool_registry/audit_log/kernel_bus/resource_broker.
filesystem_access_manager = FilesystemAccessManager()
