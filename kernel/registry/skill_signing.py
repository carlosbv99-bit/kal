"""
Firma de identidad del AUTOR de una skill (F3 del plan de marketplace,
ver memoria del proyecto y README) — distinta de
kernel/registry/signing.py, que firma con la clave PROPIA de kal para
detectar tampering de una herramienta dinámica ya aprobada. Acá el
problema es otro: un tercero escribe una skill, la publica, y este
usuario la instala en su propia copia de kal — hace falta saber si el
paquete llegó intacto desde que su autor lo firmó, no si kal mismo lo
alteró.

ALCANCE DELIBERADO Y ACOTADO (acordado explícitamente con el usuario):
esto resuelve "¿este paquete fue alterado desde que se firmó?"
(integridad), NUNCA "¿debería confiar en este autor?" (eso es un
problema de reputación/registro de autores que solo tiene sentido
resolver con un marketplace real y autores externos de verdad — no
construir esa infraestructura sin demanda validada, mismo criterio ya
aplicado antes en este proyecto). Una skill "verified" significa
únicamente que el contenido coincide bit a bit con lo que alguien
firmó con esa clave — nada más.

Nunca se envía a un contenedor de skill (a diferencia de
sdk/permissions.py/base_tool.py/kernel_client.py) — la
verificación ocurre enteramente en el host, ANTES de que
kernel/lifecycle/skill_runner.py exista siquiera para esa ejecución.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

SIGNATURE_FILENAME = "skill.sig"

SignatureStatus = Literal["unsigned", "verified", "tampered"]


def _skill_files(skill_dir: Path) -> list[Path]:
    """
    Todos los archivos que integran el paquete de la skill, en el
    mismo criterio que SandboxedSkillTool._collect_skill_files() (sin
    __pycache__/.pyc — no son contenido real, pueden variar entre
    versiones de Python sin que la skill haya cambiado) — EXCLUYE
    además el propio skill.sig, que no puede firmarse a sí mismo.
    """
    return [
        p for p in skill_dir.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix != ".pyc"
        and p.name != SIGNATURE_FILENAME
    ]


_MANIFEST_FILENAME = "skill.yaml"


def _skill_yaml_hash_excluding_enabled(manifest_path: Path) -> str:
    """
    `enabled` es una decisión de instalación LOCAL (ver
    kernel/registry/skills.py: "no es una propiedad del catálogo, cada
    usuario la decide") — cambia con set_skill_enabled() (que edita
    skill.yaml con un reemplazo de texto dirigido, ver
    scripts/enable_skill.py) sin que el AUTOR original haya tocado nada.

    BUG REAL encontrado probando el Skill Creator (2026-07-20): antes,
    skill.yaml se hasheaba entero (bytes crudos) como cualquier otro
    archivo — habilitar una skill YA FIRMADA invalidaba su propia firma
    en el acto, aunque enable_skill.py acabara de mostrar "Firma:
    verificada" un segundo antes. Nunca se había disparado en la
    práctica porque las 6 skills existentes siempre se firmaron con
    `enabled` ya en su valor final. El resto de skill.yaml
    (permissions/requirements/kernel_services/entry_point/etc., que SÍ
    son decisión del autor) sigue cubierto por la firma tal cual —
    normalizamos SOLO `enabled` a un valor fijo antes de hashear.
    """
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    raw["enabled"] = False
    canonical = yaml.safe_dump(raw, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_manifest(skill_dir: Path) -> bytes:
    """
    Lista determinística [(ruta_relativa, sha256), ...] de TODO el
    contenido de la skill — incluye skill.yaml a propósito: ahí viven
    `permissions`/`kernel_services`, y tienen que quedar cubiertos por
    la firma tanto como el código (si no, alguien podría mantener el
    código firmado intacto pero escalar permisos en el manifiesto sin
    invalidar nada). Excepción deliberada: el campo `enabled` DENTRO de
    skill.yaml se normaliza antes de hashear (ver
    _skill_yaml_hash_excluding_enabled) — es la única parte de todo el
    paquete que cambia por una decisión LOCAL, no del autor.
    """
    entries = sorted(
        (
            p.relative_to(skill_dir).as_posix(),
            _skill_yaml_hash_excluding_enabled(p)
            if p.relative_to(skill_dir).as_posix() == _MANIFEST_FILENAME
            else hashlib.sha256(p.read_bytes()).hexdigest(),
        )
        for p in _skill_files(skill_dir)
    )
    return json.dumps(entries, separators=(",", ":")).encode("utf-8")


class SkillSigner:
    """Identidad criptográfica de un AUTOR de skills — un keypair Ed25519
    propio, nunca el mismo que kernel/registry/signing.py::tool_signer
    (ese es la identidad de kal, no la de un autor externo)."""

    def __init__(self, key_dir: Path | str):
        self.key_dir = Path(key_dir)
        self.key_dir.mkdir(parents=True, exist_ok=True)
        self._private_key_path = self.key_dir / "skill_author_key"
        self._public_key_path = self.key_dir / "skill_author_key.pub"
        self._private_key = self._load_or_create_keypair()

    def _load_or_create_keypair(self) -> Ed25519PrivateKey:
        if self._private_key_path.exists():
            return Ed25519PrivateKey.from_private_bytes(self._private_key_path.read_bytes())

        private_key = Ed25519PrivateKey.generate()
        raw_private = private_key.private_bytes(
            encoding=Encoding.Raw, format=PrivateFormat.Raw, encryption_algorithm=NoEncryption()
        )
        raw_public = private_key.public_key().public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
        self._private_key_path.write_bytes(raw_private)
        self._private_key_path.chmod(0o600)
        self._public_key_path.write_bytes(raw_public)
        return private_key

    def public_key_hex(self) -> str:
        raw_public = self._private_key.public_key().public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
        return raw_public.hex()

    def sign_skill(self, skill_dir: Path) -> dict:
        """
        Firma el estado ACTUAL de `skill_dir` y devuelve el dict a
        escribir tal cual como skill.sig (json.dump). `files` es
        puramente informativo (para que un humano pueda ver qué cubre
        la firma) — verify_skill_signature() nunca confía en este
        campo, siempre recalcula desde disco.
        """
        manifest = _canonical_manifest(skill_dir)
        signature = self._private_key.sign(manifest)
        files = dict(json.loads(manifest.decode("utf-8")))
        return {
            "algorithm": "ed25519",
            "author_public_key": self.public_key_hex(),
            "signature": signature.hex(),
            "files": files,
        }

    def write_signature(self, skill_dir: Path) -> Path:
        sig_path = skill_dir / SIGNATURE_FILENAME
        sig_path.write_text(json.dumps(self.sign_skill(skill_dir), indent=2) + "\n", encoding="utf-8")
        return sig_path


def verify_skill_signature(skill_dir: Path) -> SignatureStatus:
    """
    "unsigned": no hay skill.sig — comportamiento actual, sin cambios
    (compatibilidad total con skills existentes sin firmar).
    "verified": la firma coincide con el contenido ACTUAL de la
    carpeta (recalculado ahora, no lo que diga el campo "files" del
    propio skill.sig).
    "tampered": skill.sig existe pero no verifica contra el contenido
    actual — un archivo (incluido skill.yaml) cambió desde que se
    firmó, o el propio skill.sig está corrupto/incompleto/con datos
    inválidos. Fail closed: cualquier problema de parseo cuenta como
    "tampered", nunca una excepción sin manejar.
    """
    sig_path = skill_dir / SIGNATURE_FILENAME
    if not sig_path.exists():
        return "unsigned"

    try:
        data = json.loads(sig_path.read_text(encoding="utf-8"))
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(data["author_public_key"]))
        signature = bytes.fromhex(data["signature"])
        # _canonical_manifest() ahora parsea skill.yaml (para normalizar
        # 'enabled', ver más arriba) — un YAML corrupto debe caer acá
        # también, fail closed, nunca una excepción sin manejar.
        current_manifest = _canonical_manifest(skill_dir)
    except (json.JSONDecodeError, KeyError, ValueError, TypeError, yaml.YAMLError):
        return "tampered"

    try:
        public_key.verify(signature, current_manifest)
    except InvalidSignature:
        return "tampered"
    return "verified"
