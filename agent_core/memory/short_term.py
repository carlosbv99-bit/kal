"""
Memoria de corto plazo: contexto de la tarea/sesión activa.

Vive en RAM, se descarta al terminar la tarea salvo que consolidate()
la traslade (resumida) a mediano plazo antes de expirar. No tiene
persistencia entre reinicios del proceso por diseño: si algo debe
sobrevivir un restart, no pertenece aquí.
"""
from __future__ import annotations

from collections import deque

from agent_core.memory.base import MemoryBackend, MemoryItem
from utils.config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class ShortTermMemory(MemoryBackend):
    def __init__(self, max_tokens: int | None = None):
        self.max_tokens = max_tokens or settings.memory.short_term.max_tokens
        self._buffer: deque[MemoryItem] = deque()
        self._token_count = 0

    def _estimate_tokens(self, text: str) -> int:
        # Aproximación simple; sustituir por un tokenizer real (tiktoken, etc.)
        return max(1, len(text) // 4)

    def store(self, item: MemoryItem) -> None:
        tokens = self._estimate_tokens(item.content)
        self._buffer.append(item)
        self._token_count += tokens

        while self._token_count > self.max_tokens and self._buffer:
            evicted = self._buffer.popleft()
            self._token_count -= self._estimate_tokens(evicted.content)
            logger.info(f"short_term: evict item {evicted.id} por límite de tokens")

    def retrieve(self, query: str, top_k: int = 5) -> list[MemoryItem]:
        # TODO: sustituir por similitud real (embeddings locales) en vez de
        # devolver los más recientes; de momento es un buffer FIFO simple.
        return list(self._buffer)[-top_k:]

    def forget(self, item_id: str) -> None:
        self._buffer = deque(i for i in self._buffer if i.id != item_id)

    def consolidate(self) -> list[MemoryItem]:
        """
        Devuelve los items actuales para que el orquestador los resuma
        y los pase a MidTermMemory antes de vaciar el buffer.
        La responsabilidad de resumir (llamada a un modelo) vive en
        agent_core/orchestrator.py, no aquí — este módulo es solo storage.
        """
        items = list(self._buffer)
        self._buffer.clear()
        self._token_count = 0
        return items
