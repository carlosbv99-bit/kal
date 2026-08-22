"""
Tests de tool_integration/adapters/vscode_android.py::AndroidBuildScreenshotTool
— mismo límite arquitectónico que ReadWorkspaceFileTool/
ProposeProjectFilesTool: nunca compila, instala ni captura nada ella
misma. Devuelve un Artifact "pendiente"; la extensión de VS Code hace
el trabajo real (ver vscode-extension/src/androidBuild.ts).
"""
from __future__ import annotations

from tool_integration.adapters.vscode_android import AndroidBuildScreenshotTool


def test_returns_a_pending_android_build_request():
    tool = AndroidBuildScreenshotTool()

    artifact = tool.execute()

    assert artifact.modality == "android_build_request"
    assert artifact.metadata["request_id"]


def test_each_call_gets_a_distinct_request_id():
    tool = AndroidBuildScreenshotTool()

    first = tool.execute()
    second = tool.execute()

    assert first.metadata["request_id"] != second.metadata["request_id"]


def test_manifest_takes_no_required_parameters():
    tool = AndroidBuildScreenshotTool()

    assert tool.manifest.parameters_schema.get("required", []) == []
