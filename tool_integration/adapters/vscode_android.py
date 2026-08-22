"""
AndroidBuildScreenshotTool: le permite al agente pedirle a la
extensión de VS Code que compile un proyecto Android real del
workspace, lo instale en un dispositivo conectado (USB o WiFi, vía
adb) y devuelva una captura de pantalla real — para que el usuario
pueda monitorear visualmente el progreso de una app mientras se
construye (pedido explícito del usuario, 2026-07-30).

Mismo límite arquitectónico que el resto de tool_integration/adapters/
vscode_files.py: este backend de Python no sabe qué carpeta tiene
abierta VS Code, ni tiene acceso a ningún dispositivo Android — nunca
compila ni instala nada él mismo. Esta Tool SOLO devuelve un Artifact
"pendiente"; el trabajo real (detectar el proyecto, compilar con
Gradle, instalar con adb, capturar la pantalla) ocurre enteramente del
lado de la extensión (ver vscode-extension/src/androidBuild.ts), la
única parte del sistema con acceso real al workspace y al dispositivo.

A diferencia de read_workspace_file, esto NO se encadena de vuelta a
otro paso del agente — el modelo no necesita "ver" los píxeles de la
captura para poder responder, el resultado (éxito con captura, o el
error real de Gradle) se le muestra directamente al usuario del lado
de la extensión, igual que el resultado de propose_project_files.
"""
from __future__ import annotations

from uuid import uuid4

from sdk.artifacts import Artifact
from sdk.skill import Tool, ToolManifest


class AndroidBuildScreenshotTool(Tool):
    manifest = ToolManifest(
        name="android_build_and_screenshot",
        description=(
            "Compila el proyecto Android REAL que el usuario tiene en su workspace, lo instala en "
            "un dispositivo conectado (USB o WiFi, vía adb) y le muestra una captura de pantalla "
            "real — para que el usuario pueda ver visualmente el progreso de la app mientras se "
            "construye. El resultado NO llega en esta misma respuesta: la extensión de VS Code hace "
            "el trabajo real (compilar, instalar, capturar) y se lo muestra al usuario directamente "
            "en el panel de chat, en un momento posterior — nunca inventes ni describas cómo se "
            "vería la app antes de eso, y en tu respuesta final aclará que todavía está compilando/"
            "instalando, nunca digas que ya se instaló o que ya podés ver el resultado. Si no hay "
            "ningún proyecto Android real en el workspace (falta gradlew) o no hay ningún "
            "dispositivo conectado, el usuario va a ver un aviso explicando qué falta — no asumas "
            "que funcionó."
        ),
        created_by="system",
        requires_filesystem_write=False,
        parameters_schema={"type": "object", "properties": {}},
    )

    def execute(self, **kwargs) -> Artifact:
        return Artifact(
            modality="android_build_request",
            uri="",
            metadata={"request_id": str(uuid4())},
        )
