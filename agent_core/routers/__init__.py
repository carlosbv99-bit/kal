"""
Endpoints HTTP del agente, agrupados por dominio (un APIRouter por
archivo) en vez de vivir todos declarados directamente en
agent_core/orchestrator.py.

Motivo (revisión de arquitectura, 2026-07-20): orchestrator.py había
crecido a 44 endpoints + imports de prácticamente todos los subsistemas
del proyecto en un solo archivo — cualquier cambio lo tocaba, y el
acoplamiento por import dificultaba razonar sobre qué depende de qué.
Refactor mecánico, sin cambios de comportamiento: cada router importa
`orchestrator`/`require_admin_token`/`_artifact_url`/etc. desde
agent_core.orchestrator (que sigue siendo el único lugar donde vive el
singleton `Orchestrator` y se arma la app), y agent_core/orchestrator.py
queda reducido a construir la app, el token administrativo, servir el
frontend estático, y montar estos routers con app.include_router(...).
"""
