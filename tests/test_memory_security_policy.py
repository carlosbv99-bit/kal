"""
Tests de agent_core/memory/security_policy.py — Memory Security Policy
Engine (Fase 1): clasificación por regex de credenciales de formato
conocido + redactado por substitución de spans, sin depender de un
LLM (determinístico, rápido, sin falsos "motivos" inventados).
"""
from __future__ import annotations

from agent_core.memory.security_policy import (
    MemoryClassification,
    classify,
    is_cloud_provider,
    redact,
)


def test_classify_marks_plain_text_as_public():
    assert classify("me gusta el café por la mañana") == MemoryClassification.PUBLIC


def test_classify_detects_an_openai_key():
    assert classify("mi key es sk-abcdefghijklmnopqrstuvwx") == MemoryClassification.SECRET


def test_classify_detects_an_aws_key():
    assert classify("AWS_ACCESS_KEY_ID=AKIAABCDEFGHIJKLMNOP") == MemoryClassification.SECRET


def test_classify_detects_a_github_token():
    assert classify("token: ghp_" + "a" * 36) == MemoryClassification.SECRET


def test_classify_detects_a_jwt():
    fake_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dQw4w9WgXcQ-abcdefghij"
    assert classify(f"el token es {fake_jwt}") == MemoryClassification.SECRET


def test_classify_detects_a_pem_private_key_block():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJ...\n-----END RSA PRIVATE KEY-----"
    assert classify(pem) == MemoryClassification.SECRET


def test_classify_never_returns_sensitive_in_phase_1():
    """
    Sin un clasificador real (Fase 4), no hay forma determinística de
    poblar SENSITIVE distinto de PUBLIC/SECRET — Fase 1 solo asigna uno
    de esos dos, nunca finge una inteligencia que todavía no existe.
    """
    samples = [
        "hola, ¿cómo estás?",
        "mi dirección es Av. Siempreviva 742",
        "sk-abcdefghijklmnopqrstuvwx",
        "",
    ]
    assert all(classify(s) != MemoryClassification.SENSITIVE for s in samples)


def test_redact_masks_only_the_matched_span_and_preserves_the_rest():
    """
    Decisión explícita: enmascarar solo el secreto detectado, nunca
    reemplazar todo el contenido por un resumen inferido (un regex no
    puede confirmar de verdad el motivo real del mensaje).
    """
    original = "ayudame a debuggear el error 500, mi key es sk-abcdefghijklmnopqrstuvwx"

    redacted = redact(original)

    assert "sk-abcdefghijklmnopqrstuvwx" not in redacted
    assert "[REDACTED:openai_key]" in redacted
    assert "ayudame a debuggear el error 500" in redacted


def test_redact_masks_multiple_distinct_secrets_in_the_same_content():
    original = "key openai sk-abcdefghijklmnopqrstuvwx y también AKIAABCDEFGHIJKLMNOP de AWS"

    redacted = redact(original)

    assert "[REDACTED:openai_key]" in redacted
    assert "[REDACTED:aws_key]" in redacted
    assert "sk-abcdefghijklmnopqrstuvwx" not in redacted
    assert "AKIAABCDEFGHIJKLMNOP" not in redacted


def test_redact_leaves_plain_text_untouched():
    original = "esto no tiene ningún secreto adentro"

    assert redact(original) == original


def test_is_cloud_provider_true_for_openai_compatible():
    assert is_cloud_provider("openai_compatible") is True


def test_is_cloud_provider_false_for_ollama():
    assert is_cloud_provider("ollama") is False
