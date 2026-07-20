"""
Correlation ID: un identificador corto generado por pedido (hoy solo en
POST /chat) que termina apareciendo en cada línea de logs/agent.log y
en el "context" de cada entrada de logs/audit.log producida durante ese
mismo pedido — para no tener que reconstruir a mano la cadena
orchestrator -> AgentLoop -> tool_registry -> sandbox Docker -> Kernel
Bus -> Kernel Service cruzando ambos logs (bug real de esta sesión:
se hizo así más de una vez, p.ej. investigando por qué había tantos
archivos de audio generados).

Implementado con contextvars, NO pasando el id como parámetro explícito
por cada función de la cadena (agent_core/llm/agent_loop.py ->
kernel/registry/registry.py -> kernel/registry/sandboxed_skill.py ->
kernel/lifecycle/executor.py -> kernel/lifecycle/docker_runner.py...):
todo ese camino corre en el MISMO thread que originó el pedido HTTP
(Starlette corre cada `def` sync en un thread de su pool, pero un único
pedido nunca salta de thread a mitad de camino), así que un ContextVar
seteado al principio de /chat ya es visible en toda esa cadena sin
tocar ninguna firma intermedia.

EXCEPCIÓN real: kernel/api/socket_server.py::KernelBusSocketServer
sirve el socket Unix en un thread de background PROPIO
(threading.Thread) — contextvars NO cruza automáticamente a un thread
nuevo. Ahí se vuelve a llamar a set_correlation_id() explícitamente,
apenas empieza a correr ese thread, con el valor capturado en el
thread original ANTES de lanzarlo.
"""
from __future__ import annotations

import contextvars
import uuid

_current: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)


def new_id() -> str:
    """Corto (12 hex) — alcanza para grep sin ensuciar cada línea de log."""
    return uuid.uuid4().hex[:12]


def set_correlation_id(value: str | None) -> None:
    _current.set(value)


def get_correlation_id() -> str | None:
    return _current.get()
