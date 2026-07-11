"""
Skill de referencia para el Kernel Service Bus (ver
kernel_bus/__init__.py y tool_integration/kernel_client.py): genera una
imagen SIN NINGUNA dependencia de ML propia (ni torch ni diffusers) —
le pide la imagen al servicio "image" del kernel, que comparte el mismo
pipeline de SDXL-Turbo que ya usa
tool_integration/adapters/image_gen.py (una sola instancia cargada,
nunca una copia por consumidor).

Nota para autores de skills: no declara `manifest =` (ver
skills/system_info/tool.py) — nombre/descripción/permisos/
parameters_schema/kernel_services viven en skill.yaml.
"""
from __future__ import annotations

from tool_integration.base_tool import Artifact, Tool
from tool_integration.kernel_client import call as kernel_call


class ImageViaKernelTool(Tool):
    def execute(self, prompt: str, **kwargs) -> Artifact:
        result = kernel_call("image.generate", prompt=prompt)
        return Artifact(modality="image", uri=result["artifact"], metadata=result.get("metadata", {}))
