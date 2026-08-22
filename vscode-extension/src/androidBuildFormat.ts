/**
 * Parte pura (sin import de `vscode` ni de `child_process`) del flujo
 * de android_build_and_screenshot (ver tool_integration/adapters/
 * vscode_android.py) — testeable con Node normal, mismo patrón que
 * readWorkspaceFileFormat.ts/projectFilesFormat.ts. La parte que sí
 * compila con Gradle, habla con adb y muestra diálogos reales vive en
 * androidBuild.ts.
 */
import { AndroidBuildRequestArtifact, ChatResult } from "./kalClient";

/**
 * Igual que findWorkspaceFileRequestArtifact: se usa la ÚLTIMA
 * coincidencia, no la primera (mismo criterio — el backend ya acota a
 * 1 por turno, ver agent_core/client_provider.py::_VSCODE_ONLY_TOOL_NAMES,
 * pero esta función no depende de esa garantía para ser correcta).
 */
export function findAndroidBuildRequestArtifact(result: ChatResult): AndroidBuildRequestArtifact | undefined {
  let found: AndroidBuildRequestArtifact | undefined;
  for (const step of result.steps) {
    if (step.artifact && (step.artifact as AndroidBuildRequestArtifact).modality === "android_build_request") {
      found = step.artifact as AndroidBuildRequestArtifact;
    }
  }
  return found;
}

// Tope de caracteres del output real de Gradle que se muestra en el
// chat — mismo espíritu que readWorkspaceFileFormat.ts::
// _MAX_FILE_CHARS_IN_PROMPT: un log de build enorme no debería
// inundar la conversación. Se muestra el FINAL del output (donde
// suele estar el error real), no el principio.
const _MAX_BUILD_OUTPUT_CHARS = 4_000;

/** Recorta un output de proceso (build/adb) al final, con una nota si se truncó. */
export function truncateProcessOutput(output: string): string {
  const trimmed = output.trim();
  if (trimmed.length <= _MAX_BUILD_OUTPUT_CHARS) {
    return trimmed;
  }
  const tail = trimmed.slice(trimmed.length - _MAX_BUILD_OUTPUT_CHARS);
  return `[... salida truncada, se muestran los últimos ${_MAX_BUILD_OUTPUT_CHARS} caracteres ...]\n${tail}`;
}

/**
 * Interpreta la salida cruda de `adb devices -l` — el formato real de
 * adb es una primera línea "List of devices attached", después una
 * línea por dispositivo ("<serial>\tdevice ...", o "<serial>\tunauthorized
 * ..." si falta aceptar el diálogo en el teléfono), separadas por tabs.
 */
export interface AdbDevice {
  serial: string;
  state: string;
}

export function parseAdbDevices(rawOutput: string): AdbDevice[] {
  const devices: AdbDevice[] = [];
  for (const line of rawOutput.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("List of devices attached") || trimmed.startsWith("*")) {
      continue;
    }
    const parts = trimmed.split(/\s+/);
    if (parts.length >= 2) {
      devices.push({ serial: parts[0], state: parts[1] });
    }
  }
  return devices;
}
