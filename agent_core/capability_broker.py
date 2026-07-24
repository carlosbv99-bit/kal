"""
Capability Broker: primer caso de uso real de `required_capabilities`
(ver agent_core/conversation_engine.py::ConversationEngineResult), que
hasta ahora se calculaba en cada turno sin ningún consumidor.

Motivación (2026-07-24, pedido explícito del usuario): "armando una
página web en VS Code, a veces hace falta ADEMÁS generar/importar una
imagen o un sonido" — hoy eso está bloqueado de raíz:
`agent_core/client_provider.py::_MULTIMEDIA_TOOL_NAMES` excluye TODA
herramienta multimedia para client="vscode" sin excepción (fix
deliberado de un bug real: "creá la página web para una panadería"
generó fotos en vez de código) — un martillo demasiado grande que
también bloquea los casos legítimos.

Este componente NO elige entre varios proveedores compitiendo por una
capacidad (no existe ese caso real todavía — LLM/audio/imagen siguen
siendo UN proveedor configurado a la vez, ver
project_kernel_provider_pivot en la memoria del proyecto). Es más
simple: dado el `required_capabilities` que el Conversation Engine ya
calculó para ESTE turno puntual, decide qué herramientas multimedia
(normalmente bloqueadas para VS Code) desbloquear — nunca al revés
(nunca agrega restricciones nuevas, nunca toca `_VSCODE_ONLY_TOOL_NAMES`,
ver agent_core/llm/agent_loop.py::_build_tools_from_registry para la
barrera de seguridad exacta).
"""
from __future__ import annotations

# Capacidad (vocabulario de ConversationEngineResult.required_capabilities)
# -> nombres de herramientas reales que la resuelven. Construido contra
# el inventario real de herramientas registradas (kernel/registry/
# registry.py + los 3 instance tools de AgentLoop) — no es un mapeo
# aspiracional, cada nombre de acá existe hoy.
#
# "conversation" queda deliberadamente sin ninguna herramienta (no
# necesita desbloquear nada especial); `remember`/`recall`/`system_info`
# quedan FUERA de este mapeo a propósito — nunca están excluidas de
# entrada por ningún ClientProvider, no necesitan desbloqueo.
_CAPABILITY_TOOL_NAMES: dict[str, frozenset[str]] = {
    "coding": frozenset({"run_code", "propose_project_files", "read_workspace_file", "propose_skill"}),
    "web-browsing": frozenset({"browser"}),
    "text-to-speech": frozenset({"audio_generation", "audio_via_kernel", "voice_roundtrip_via_kernel"}),
    "speech-to-text": frozenset({"speech_to_text", "voice_roundtrip_via_kernel"}),
    "image-generation": frozenset({"image_generation", "image_via_kernel", "qr_code", "image_inpaint_via_kernel"}),
    "image-editing": frozenset({"image_editing", "image_composition", "image_inpaint_via_kernel", "import_resource"}),
    "vision": frozenset({"analyze_image"}),
    "video": frozenset({"video_composition"}),
    "conversation": frozenset(),
}


class CapabilityBroker:
    def tool_names_for(self, capabilities: list[str]) -> frozenset[str]:
        """Unión de las herramientas que resuelven CUALQUIERA de las capacidades dadas."""
        allowed: set[str] = set()
        for capability in capabilities:
            allowed |= _CAPABILITY_TOOL_NAMES.get(capability, frozenset())
        return frozenset(allowed)


# Singleton, mismo patrón que tool_registry (kernel/registry/registry.py)
# / resource_broker (kernel/broker/resource_broker.py).
capability_broker = CapabilityBroker()
