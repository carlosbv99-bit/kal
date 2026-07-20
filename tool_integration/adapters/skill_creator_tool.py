"""
Herramienta para que el agente PROPONGA una Skill nueva — nunca la
instala ni la ejecuta él mismo. Ver agent_core/skill_creator.py para
el pipeline completo (propose/approve/reject) y por qué el código
propuesto NO pasa por el denylist AST (una Skill legítima necesita
capacidades que ese denylist bloquea; el aislamiento real sigue siendo
Docker, igual que cualquier otra Skill, recién si un humano la
aprueba Y la habilita).
"""
from __future__ import annotations

from agent_core.skill_creator import skill_creator_manager
from sdk.artifacts import Artifact
from sdk.skill import Tool, ToolManifest


class ProposeSkillTool(Tool):
    manifest = ToolManifest(
        name="propose_skill",
        description=(
            "Propone crear una Skill NUEVA (una capacidad reutilizable, ejecutada en su propio "
            "sandbox Docker) cuando el pedido del usuario necesita algo que ninguna herramienta "
            "existente resuelve bien y que tiene sentido reusar en el futuro — no para una tarea "
            "puntual de una sola vez (para eso ya existe run_code). La propuesta NUNCA se instala "
            "sola: queda pendiente de que un humano la revise y la apruebe explícitamente, y aun "
            "aprobada queda deshabilitada hasta que un humano la habilite aparte. 'code' es el "
            "contenido COMPLETO de tool.py: debe definir una clase 'class_name' que herede de "
            "sdk.skill.Tool (from sdk.skill import Tool; from sdk.artifacts import Artifact) e "
            "implemente execute(self, **kwargs) -> Artifact. 'permissions' son los permisos que "
            "declara (p.ej. ['network']) — dejar vacío si no necesita ninguno especial."
        ),
        created_by="system",
        requires_filesystem_write=True,
        parameters_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Nombre en snake_case, p.ej. 'web_scraper' — será el nombre de la carpeta bajo skills/.",
                },
                "description": {"type": "string", "description": "Qué hace la skill, para su skill.yaml."},
                "class_name": {
                    "type": "string",
                    "description": "Nombre de la clase Python definida en 'code' (p.ej. 'WebScraperTool').",
                },
                "code": {"type": "string", "description": "Contenido completo de tool.py."},
                "justification": {
                    "type": "string",
                    "description": "Por qué esta capacidad merece ser una Skill reutilizable y no una tarea puntual.",
                },
                "permissions": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Permisos declarados (p.ej. ['network']). Vacío por defecto.",
                },
                "requirements": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Paquetes de pip adicionales (p.ej. ['requests==2.32.3']). Vacío si solo necesita stdlib.",
                },
                "parameters_schema": {
                    "type": "object",
                    "description": "JSON Schema de los argumentos que recibirá execute() de la skill propuesta.",
                },
            },
            "required": ["name", "description", "class_name", "code", "justification"],
        },
    )

    def execute(
        self,
        name: str,
        description: str,
        class_name: str,
        code: str,
        justification: str,
        permissions: list[str] | None = None,
        requirements: list[str] | None = None,
        parameters_schema: dict | None = None,
        **kwargs,
    ) -> Artifact:
        proposal = skill_creator_manager.propose(
            name=name, description=description, class_name=class_name, code=code,
            justification=justification, permissions=permissions, requirements=requirements,
            parameters_schema=parameters_schema,
        )
        return Artifact(
            modality="text",
            uri="",
            metadata={
                "summary": (
                    f"Skill '{proposal.name}' propuesta (id={proposal.id}) — pendiente de revisión y "
                    "aprobación humana. No está instalada ni activa todavía."
                ),
                "proposal_id": proposal.id,
                "status": proposal.status,
            },
        )
