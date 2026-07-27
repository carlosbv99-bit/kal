"""
KnowledgeBase: almacenamiento de Pattern — ver agent_core/knowledge/__init__.py.

Infraestructura, no Funcionalidad: hoy es una lista en memoria de
proceso (se pierde al reiniciar), y `query()` siempre devuelve `[]`
(sin ninguna similaridad/clustering real todavía). Existe con su firma
FINAL para que un consumidor futuro (p.ej. el Planner preguntando "¿hay
un patrón relacionado con este error?") ya pueda integrarse contra
ella, sin tener que rediseñar la interfaz cuando la minería real llegue.
"""
from __future__ import annotations

from agent_core.knowledge.models import Pattern


class KnowledgeBase:
    def __init__(self):
        self._patterns: list[Pattern] = []

    def add(self, pattern: Pattern) -> None:
        self._patterns.append(pattern)

    def query(self, text: str, top_k: int = 3) -> list[Pattern]:
        # Sin similaridad/clustering real todavía — ver docstring del
        # módulo. Firma final, comportamiento pendiente de la fase
        # "Funcionalidad" (datos de uso real, no hipótesis).
        return []
