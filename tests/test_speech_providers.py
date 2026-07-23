"""
Tests de contrato de kernel/services/provider.py — confirman que
AudioService/STTService (kernel/services/services.py) satisfacen
estructuralmente TTSProvider/STTProvider, mismo espíritu que
tests/test_llm_provider.py para LLMProvider.
"""
from __future__ import annotations

from kernel.services.provider import STTProvider, TTSProvider
from kernel.services.services import AudioService, STTService


def test_audio_service_satisfies_the_tts_provider_protocol():
    assert isinstance(AudioService(), TTSProvider)


def test_stt_service_satisfies_the_stt_provider_protocol():
    assert isinstance(STTService(), STTProvider)
