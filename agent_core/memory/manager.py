"""
MemoryManager: fachada única sobre los tres niveles de memoria.

El resto del sistema no debería instanciar ShortTermMemory/MidTermMemory/
LongTermMemory directamente — usa esta clase, que además implementa el
flujo de consolidación y promoción entre niveles.
"""
from __future__ import annotations

from agent_core.memory.base import MemoryConfidence, MemoryItem
from agent_core.memory.long_term import LongTermMemory
from agent_core.memory.mid_term import MidTermMemory
from agent_core.memory.short_term import ShortTermMemory
from utils.logger import get_logger

logger = get_logger(__name__)

# Confianzas que un humano ya fijó explícitamente — la promoción
# automática (patrón auto-inferido) nunca las degrada de vuelta a
# APRENDIDA, solo las sube nunca las baja.
_HUMAN_CONFIRMED = frozenset({MemoryConfidence.VERIFICADA, MemoryConfidence.PERMANENTE})


class MemoryManager:
    def __init__(
        self,
        short_term: ShortTermMemory | None = None,
        mid_term: MidTermMemory | None = None,
        long_term: LongTermMemory | None = None,
    ):
        """
        Por defecto construye los tres backends reales (rutas de
        config.yaml). Permite inyectar instancias propias — usado en
        tests para evitar escribir en data/mid_term o
        data/long_term reales del proyecto durante la suite.
        """
        self.short_term = short_term or ShortTermMemory()
        self.mid_term = mid_term or MidTermMemory()
        self.long_term = long_term or LongTermMemory()

    def remember(
        self,
        content: str,
        metadata: dict | None = None,
        confidence: MemoryConfidence = MemoryConfidence.TEMPORAL,
    ) -> MemoryItem:
        """Punto de entrada por defecto: todo lo nuevo entra por corto plazo."""
        item = MemoryItem(content=content, metadata=metadata or {}, confidence=confidence)
        self.short_term.store(item)
        return item

    def recall(self, query: str, top_k: int = 5) -> dict[str, list[MemoryItem]]:
        """
        Busca en los tres niveles. El llamador decide cómo priorizar
        (p.ej., corto plazo primero por ser más específico a la tarea actual).
        """
        return {
            "short_term": self.short_term.retrieve(query, top_k),
            "mid_term": self.mid_term.retrieve(query, top_k),
            "long_term": self.long_term.retrieve(query, top_k),
        }

    def consolidate_short_to_mid(self, summarizer=None) -> int:
        """
        Traslada el contenido de corto plazo a mediano plazo, resumiendo
        si se provee un `summarizer` (callable str -> str, típicamente
        una llamada a un modelo). Sin summarizer, se guarda el contenido tal cual.
        """
        items = self.short_term.consolidate()
        for item in items:
            if summarizer is not None:
                item.content = summarizer(item.content)
            self.mid_term.store(item)
        logger.info(f"Consolidados {len(items)} items de corto a mediano plazo")
        return len(items)

    def promote_mid_to_long(self) -> int:
        """
        Evalúa candidatos de mediano plazo según la política de promoción
        (repeticiones + relevancia, ver config.yaml) y los traslada a
        largo plazo. No borra automáticamente de mediano plazo: eso lo
        maneja purge_expired() por TTL de forma independiente.

        Un patrón que cruza el umbral de repeticiones/relevancia es una
        inferencia del propio agente, no algo que un humano confirmó —
        se etiqueta APRENDIDA, salvo que ya sea VERIFICADA/PERMANENTE
        (un humano ya se pronunció sobre ese item, no se le baja el nivel).
        """
        candidates = self.mid_term.candidates_for_promotion()
        for item in candidates:
            if item.confidence not in _HUMAN_CONFIRMED:
                item.confidence = MemoryConfidence.APRENDIDA
            self.long_term.store(item)
        logger.info(f"Promovidos {len(candidates)} items de mediano a largo plazo")
        return len(candidates)

    def verify(self, item_id: str, tier: str, verified_by: str) -> MemoryItem:
        """
        Un humano confirma explícitamente que un recuerdo es correcto:
        sube su confianza a VERIFICADA, sin importar cómo haya entrado
        (temporal, aprendida, externa). Trabaja sobre mid_term o
        long_term (donde existe get_by_id por clave exacta) — short_term
        no aplica: vive solo en RAM de la tarea activa.
        """
        backend = self._backend_for_tier(tier)
        item = backend.get_by_id(item_id)
        if item is None:
            raise ValueError(f"No existe el item '{item_id}' en la memoria de nivel '{tier}'")
        item.confidence = MemoryConfidence.VERIFICADA
        item.metadata = {**item.metadata, "verified_by": verified_by}
        backend.store(item)
        logger.info(f"Item {item_id} ({tier}) marcado VERIFICADA por {verified_by}")
        return item

    def pin(self, item_id: str, tier: str) -> MemoryItem:
        """
        Fija un recuerdo como PERMANENTE: nunca se purga por TTL (ver
        MidTermMemory.purge_expired) y se trata como hecho base, no
        como una inferencia sujeta a revisión.
        """
        backend = self._backend_for_tier(tier)
        item = backend.get_by_id(item_id)
        if item is None:
            raise ValueError(f"No existe el item '{item_id}' en la memoria de nivel '{tier}'")
        item.confidence = MemoryConfidence.PERMANENTE
        backend.store(item)
        logger.info(f"Item {item_id} ({tier}) fijado como PERMANENTE")
        return item

    def _backend_for_tier(self, tier: str):
        if tier == "mid_term":
            return self.mid_term
        if tier == "long_term":
            return self.long_term
        raise ValueError(f"Nivel de memoria inválido para verify()/pin(): '{tier}' (usar 'mid_term' o 'long_term')")
