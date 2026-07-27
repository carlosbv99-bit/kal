"""
Knowledge Miner / Knowledge Base (2026-07-25): infraestructura
preparada, NO funcionalidad — ver docs/HISTORY.md y la memoria de
proyecto del "modelo de madurez de 4 estados" (Visión → Arquitectura →
Infraestructura → Funcionalidad).

Componente DISTINTO del "Knowledge Service" (memoria estructurada
NO-textual por Skill, diseñado en una sesión anterior, todavía sin
construir) — este paquete es sobre CONOCIMIENTO OPERATIVO del sistema
completo (patrones detectados a partir de eventos de memoria hoy,
potencialmente logs del Kernel/errores de Skills/métricas del Runtime
más adelante), nunca sobre el estado propio de una Skill entre
llamadas. Cuidado de no confundir los dos nombres parecidos.

Deliberadamente vacío de lógica real: `KnowledgeMiner` implementa
`agent_core.memory.events.MemoryObserver` pero no hace ningún
clustering/análisis todavía — eso queda pospuesto hasta tener uso real
acumulado (la fase "Funcionalidad" no se adivina con hipótesis).
"""
