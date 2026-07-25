"""
Runtime Manager (2026-07-25): ver docs/HISTORY.md y la memoria de
proyecto "Runtime Manager" para el contexto completo. Vive en
agent_core/ (no en kernel/) porque necesita depender de
agent_core/llm/provider.py::ChatResponse — kernel/ nunca importa de
agent_core/ (dirección de dependencia ya establecida en este
proyecto), así que esta capa, aunque conceptualmente "del Kernel" en
el sentido arquitectónico del usuario, vive físicamente del lado de
agent_core, igual que agent_core/capability_broker.py y
agent_core/conversation_engine.py (también componentes de
orquestración de nivel Kernel que ya viven acá).
"""
