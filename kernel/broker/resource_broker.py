"""
Registro de recursos "pesados" cargados perezosamente en RAM
(pipelines de imagen/audio/STT, ver kernel/services/services.py) — libera
los que llevan un rato sin usarse, o TODOS de inmediato si la RAM
disponible del sistema ya está baja.

BUG REAL ENCONTRADO EN USO: en una máquina sin GPU (todo corre en
CPU), ImageService/AudioService/STTService cargaban su modelo una vez
y lo mantenían en RAM para siempre — confirmado en logs/agent.log que
esto dejaba a Ollama con "Connection refused" durante 1-2 minutos justo
después de generar una imagen (compitiendo por la misma RAM del
sistema, Ollama solo ya usa ~18.7GB de 27GB con un modelo grande). El
reintento de agent_core/llm/ollama_client.py mitiga el síntoma (la
tarea no aborta), pero no evita que el proceso de Ollama se caiga.

Se engancha en agent_core/llm/ollama_client.py::OllamaClient.chat() —
es el único lugar que de verdad compite por RAM local con estos
servicios (un proveedor en la nube no usa RAM de esta máquina).

Fase 1 de la visión más amplia de "Resource Broker" que pidió el
usuario (descubrimiento de modelos, routing automático por capacidad,
preloading por contexto, políticas por hardware) — esas partes quedan
deliberadamente fuera por ahora, sin un segundo caso de uso real que
las justifique (ver docs/HISTORY.md y la memoria del proyecto).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from utils.config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class _ManagedResource:
    name: str
    is_loaded: Callable[[], bool]
    unload: Callable[[], None]
    last_used: float = field(default_factory=time.monotonic)


class ResourceBroker:
    def __init__(self, idle_timeout_seconds: int, min_available_ram_mb: int):
        self._idle_timeout_seconds = idle_timeout_seconds
        self._min_available_ram_mb = min_available_ram_mb
        self._resources: dict[str, _ManagedResource] = {}

    def register(self, name: str, is_loaded: Callable[[], bool], unload: Callable[[], None]) -> None:
        self._resources[name] = _ManagedResource(name=name, is_loaded=is_loaded, unload=unload)

    def mark_used(self, name: str) -> None:
        resource = self._resources.get(name)
        if resource is not None:
            resource.last_used = time.monotonic()

    def evict_idle_and_pressured(self) -> None:
        """
        Libera cada recurso cargado que lleve más de idle_timeout_seconds
        sin uso. Si la RAM disponible del sistema ya está por debajo de
        min_available_ram_mb, libera TODOS los recursos cargados de
        inmediato — evicción agresiva ante presión real, no solo por
        reloj (el timeout por sí solo no alcanzaría si la presión llega
        antes de que se cumpla).
        """
        now = time.monotonic()
        low_memory = self._available_ram_mb() < self._min_available_ram_mb
        for resource in self._resources.values():
            if not resource.is_loaded():
                continue
            idle_for = now - resource.last_used
            if low_memory or idle_for >= self._idle_timeout_seconds:
                logger.info(
                    f"Liberando '{resource.name}' de RAM (inactivo {idle_for:.0f}s, RAM del sistema baja={low_memory})"
                )
                resource.unload()

    @staticmethod
    def _available_ram_mb() -> float:
        import psutil

        return psutil.virtual_memory().available / (1024 * 1024)


# Singleton, mismo patrón que tool_registry (kernel/registry/registry.py)
# / audit_log (audit/audit_log.py) / kernel (kernel/api/bus.py).
resource_broker = ResourceBroker(
    idle_timeout_seconds=settings.resource_broker.idle_timeout_seconds,
    min_available_ram_mb=settings.resource_broker.min_available_ram_mb,
)
