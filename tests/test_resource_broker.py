"""
Tests de kernel_bus/resource_broker.py — libera recursos "pesados"
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

from kernel_bus.resource_broker import ResourceBroker


def _broker(idle_timeout_seconds=300, min_available_ram_mb=2048, available_ram_mb=8192, monkeypatch=None):
    broker = ResourceBroker(idle_timeout_seconds=idle_timeout_seconds, min_available_ram_mb=min_available_ram_mb)
    monkeypatch.setattr(ResourceBroker, "_available_ram_mb", staticmethod(lambda: available_ram_mb))
    return broker


def test_mark_used_on_unknown_resource_is_a_no_op(monkeypatch):
    broker = _broker(monkeypatch=monkeypatch)
    broker.mark_used("no-existe")  # no debe lanzar


def test_does_not_evict_a_resource_used_recently(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("kernel_bus.resource_broker.time.monotonic", lambda: clock[0])
    broker = _broker(idle_timeout_seconds=300, monkeypatch=monkeypatch)

    unloaded = []
    broker.register("x", is_loaded=lambda: True, unload=lambda: unloaded.append(1))
    broker.mark_used("x")

    clock[0] = 10.0  # muy por debajo del timeout de 300s
    broker.evict_idle_and_pressured()

    assert unloaded == []


def test_evicts_a_resource_idle_past_the_timeout(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("kernel_bus.resource_broker.time.monotonic", lambda: clock[0])
    broker = _broker(idle_timeout_seconds=300, monkeypatch=monkeypatch)

    unloaded = []
    broker.register("x", is_loaded=lambda: True, unload=lambda: unloaded.append(1))
    broker.mark_used("x")

    clock[0] = 301.0
    broker.evict_idle_and_pressured()

    assert unloaded == [1]


def test_never_evicts_a_resource_that_is_not_loaded(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("kernel_bus.resource_broker.time.monotonic", lambda: clock[0])
    broker = _broker(idle_timeout_seconds=300, monkeypatch=monkeypatch)

    unloaded = []
    broker.register("x", is_loaded=lambda: False, unload=lambda: unloaded.append(1))

    clock[0] = 10_000.0
    broker.evict_idle_and_pressured()

    assert unloaded == []


def test_evicts_every_loaded_resource_immediately_under_memory_pressure(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("kernel_bus.resource_broker.time.monotonic", lambda: clock[0])
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
    monkeypatch.setattr("kernel_bus.resource_broker.time.monotonic", lambda: clock[0])
    broker = _broker(idle_timeout_seconds=300, min_available_ram_mb=2048, available_ram_mb=8192, monkeypatch=monkeypatch)

    unloaded = []
    broker.register("x", is_loaded=lambda: True, unload=lambda: unloaded.append("x"))
    broker.mark_used("x")

    clock[0] = 1.0
    broker.evict_idle_and_pressured()

    assert unloaded == []
