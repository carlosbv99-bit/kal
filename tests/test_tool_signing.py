"""
Tests de kernel/registry/signing.py: firma/verificación Ed25519 de
versiones de herramientas dinámicas.
"""
from __future__ import annotations

from kernel.registry.signing import ToolSigner


def test_sign_and_verify_roundtrip(tmp_path):
    signer = ToolSigner(key_dir=tmp_path)
    signature = signer.sign("mi_herramienta", 1, "print('hola')")

    assert signer.verify("mi_herramienta", 1, "print('hola')", signature) is True


def test_verify_fails_if_source_code_changed(tmp_path):
    signer = ToolSigner(key_dir=tmp_path)
    signature = signer.sign("mi_herramienta", 1, "print('hola')")

    assert signer.verify("mi_herramienta", 1, "print('adios')", signature) is False


def test_verify_fails_if_version_changed(tmp_path):
    signer = ToolSigner(key_dir=tmp_path)
    signature = signer.sign("mi_herramienta", 1, "print('hola')")

    assert signer.verify("mi_herramienta", 2, "print('hola')", signature) is False


def test_verify_fails_if_name_changed(tmp_path):
    signer = ToolSigner(key_dir=tmp_path)
    signature = signer.sign("mi_herramienta", 1, "print('hola')")

    assert signer.verify("otra_herramienta", 1, "print('hola')", signature) is False


def test_verify_fails_on_garbage_signature(tmp_path):
    signer = ToolSigner(key_dir=tmp_path)

    assert signer.verify("mi_herramienta", 1, "print('hola')", "no_es_hex_valido") is False


def test_keypair_persists_across_instances(tmp_path):
    """
    Recrear ToolSigner apuntando al mismo key_dir debe reusar la misma
    clave (no generar una nueva cada vez) — si no, una firma hecha con
    una instancia no verificaría con otra tras un reinicio del proceso.
    """
    signer_a = ToolSigner(key_dir=tmp_path)
    signature = signer_a.sign("mi_herramienta", 1, "print('hola')")

    signer_b = ToolSigner(key_dir=tmp_path)
    assert signer_b.verify("mi_herramienta", 1, "print('hola')", signature) is True
    assert signer_a.public_key_hex() == signer_b.public_key_hex()


def test_private_key_file_has_restrictive_permissions(tmp_path):
    signer = ToolSigner(key_dir=tmp_path)
    key_path = tmp_path / "tool_signing_key"

    assert key_path.exists()
    assert oct(key_path.stat().st_mode)[-3:] == "600"
