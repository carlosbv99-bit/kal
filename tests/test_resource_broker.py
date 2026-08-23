"""
Tests de kernel/broker/resource_broker.py — libera recursos "pesados"
(pipelines de imagen/audio/STT) que llevan un rato sin uso, o TODOS de
inmediato si la RAM disponible del sistema está baja. Bug real que
motivó esto: sin esto, un pipeline de varios GB queda en RAM para
siempre tras el primer uso, compitiendo con Ollama por la misma RAM
del sistema (confirmado: Ollama quedaba con "Connection refused" tras
generar una imagen).

Reloj y RAM disponible siempre inyectados/monkeypatcheados — nunca
`time.sleep` real ni depender de la RAM real de la máquina que corre
los tests.
"""
from __future__ import annotations

from kernel.broker.resource_broker import ResourceBroker


def _broker(idle_timeout_seconds=300, min_available_ram_mb=2048, available_ram_mb=8192, monkeypatch=None):
    broker = ResourceBroker(idle_timeout_seconds=idle_timeout_seconds, min_available_ram_mb=min_available_ram_mb)
    monkeypatch.setattr(ResourceBroker, "_available_ram_mb", staticmethod(lambda: available_ram_mb))
    return broker


def test_is_registered_true_after_register(monkeypatch):
    broker = _broker(monkeypatch=monkeypatch)
    broker.register("x", is_loaded=lambda: True, unload=lambda: None)

    assert broker.is_registered("x") is True


def test_is_registered_false_for_an_unknown_resource(monkeypatch):
    broker = _broker(monkeypatch=monkeypatch)

    assert broker.is_registered("no-existe") is False


def test_mark_used_on_unknown_resource_is_a_no_op(monkeypatch):
    broker = _broker(monkeypatch=monkeypatch)
    broker.mark_used("no-existe")  # no debe lanzar


def test_does_not_evict_a_resource_used_recently(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("kernel.broker.resource_broker.time.monotonic", lambda: clock[0])
    broker = _broker(idle_timeout_seconds=300, monkeypatch=monkeypatch)

    unloaded = []
    broker.register("x", is_loaded=lambda: True, unload=lambda: unloaded.append(1))
    broker.mark_used("x")

    clock[0] = 10.0  # muy por debajo del timeout de 300s
    broker.evict_idle_and_pressured()

    assert unloaded == []


def test_evicts_a_resource_idle_past_the_timeout(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("kernel.broker.resource_broker.time.monotonic", lambda: clock[0])
    broker = _broker(idle_timeout_seconds=300, monkeypatch=monkeypatch)

    unloaded = []
    broker.register("x", is_loaded=lambda: True, unload=lambda: unloaded.append(1))
    broker.mark_used("x")

    clock[0] = 301.0
    broker.evict_idle_and_pressured()

    assert unloaded == [1]


def test_never_evicts_a_resource_that_is_not_loaded(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("kernel.broker.resource_broker.time.monotonic", lambda: clock[0])
    broker = _broker(idle_timeout_seconds=300, monkeypatch=monkeypatch)

    unloaded = []
    broker.register("x", is_loaded=lambda: False, unload=lambda: unloaded.append(1))

    clock[0] = 10_000.0
    broker.evict_idle_and_pressured()

    assert unloaded == []


def test_evicts_every_loaded_resource_immediately_under_memory_pressure(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("kernel.broker.resource_broker.time.monotonic", lambda: clock[0])
    broker = _broker(idle_timeout_seconds=300, min_available_ram_mb=2048, available_ram_mb=100, monkeypatch=monkeypatch)

    unloaded = []
    broker.register("x", is_loaded=lambda: True, unload=lambda: unloaded.append("x"))
    broker.register("y", is_loaded=lambda: True, unload=lambda: unloaded.append("y"))
    broker.mark_used("x")
    broker.mark_used("y")

    clock[0] = 1.0  # ninguno llegó al timeout — la presión de RAM igual los libera
    broker.evict_idle_and_pressured()

    assert sorted(unloaded) == ["x", "y"]


def test_does_not_evict_when_ram_is_plentiful_and_nothing_is_idle(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("kernel.broker.resource_broker.time.monotonic", lambda: clock[0])
    broker = _broker(idle_timeout_seconds=300, min_available_ram_mb=2048, available_ram_mb=8192, monkeypatch=monkeypatch)

    unloaded = []
    broker.register("x", is_loaded=lambda: True, unload=lambda: unloaded.append("x"))
    broker.mark_used("x")

    clock[0] = 1.0
    broker.evict_idle_and_pressured()

    assert unloaded == []


class TestPerResourceIdleTimeout:
    """
    register(idle_timeout_seconds=...) — diagnóstico de lentitud
    (2026-08-23, ver docs/HISTORY.md): un recurso chico y de uso muy
    frecuente (el modelo de chat de Ollama) puede pedir un timeout
    PROPIO, más largo que el general del broker (pensado para
    pipelines pesados de imagen/audio/STT, que sí conviene liberar
    rápido). El chequeo de RAM baja nunca respeta este override — sigue
    aplicando sin excepción a TODOS los recursos.
    """

    def test_uses_the_broker_general_timeout_when_none_given(self, monkeypatch):
        clock = [0.0]
        monkeypatch.setattr("kernel.broker.resource_broker.time.monotonic", lambda: clock[0])
        broker = _broker(idle_timeout_seconds=300, monkeypatch=monkeypatch)

        unloaded = []
        broker.register("x", is_loaded=lambda: True, unload=lambda: unloaded.append(1))
        broker.mark_used("x")

        clock[0] = 301.0
        broker.evict_idle_and_pressured()

        assert unloaded == [1]

    def test_does_not_evict_before_its_own_longer_timeout_even_past_the_general_one(self, monkeypatch):
        clock = [0.0]
        monkeypatch.setattr("kernel.broker.resource_broker.time.monotonic", lambda: clock[0])
        broker = _broker(idle_timeout_seconds=300, monkeypatch=monkeypatch)

        unloaded = []
        broker.register("ollama.chat_model", is_loaded=lambda: True, unload=lambda: unloaded.append(1), idle_timeout_seconds=1800)
        broker.mark_used("ollama.chat_model")

        clock[0] = 301.0  # pasó el general (300s) pero no el propio (1800s)
        broker.evict_idle_and_pressured()

        assert unloaded == []

    def test_evicts_once_its_own_longer_timeout_is_reached(self, monkeypatch):
        clock = [0.0]
        monkeypatch.setattr("kernel.broker.resource_broker.time.monotonic", lambda: clock[0])
        broker = _broker(idle_timeout_seconds=300, monkeypatch=monkeypatch)

        unloaded = []
        broker.register("ollama.chat_model", is_loaded=lambda: True, unload=lambda: unloaded.append(1), idle_timeout_seconds=1800)
        broker.mark_used("ollama.chat_model")

        clock[0] = 1800.0
        broker.evict_idle_and_pressured()

        assert unloaded == [1]

    def test_a_longer_own_timeout_never_survives_real_ram_pressure(self, monkeypatch):
        """La protección real contra el freeze de RAM (ver el bug
        documentado en el docstring del módulo) nunca se debilita por
        un timeout propio más largo — ante RAM baja, se libera igual."""
        clock = [0.0]
        monkeypatch.setattr("kernel.broker.resource_broker.time.monotonic", lambda: clock[0])
        broker = _broker(idle_timeout_seconds=300, min_available_ram_mb=2048, available_ram_mb=100, monkeypatch=monkeypatch)

        unloaded = []
        broker.register(
            "ollama.chat_model", is_loaded=lambda: True, unload=lambda: unloaded.append(1), idle_timeout_seconds=1800
        )
        broker.mark_used("ollama.chat_model")

        clock[0] = 1.0  # muy lejos de cualquiera de los dos timeouts
        broker.evict_idle_and_pressured()

        assert unloaded == [1]
