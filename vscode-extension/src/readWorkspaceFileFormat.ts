/**
 * Parte pura (sin import de `vscode`) del flujo de read_workspace_file
 * (ver tool_integration/adapters/vscode_files.py::ReadWorkspaceFileTool
 * y agent_core/context_service.py) — testeable con Node normal, mismo
 * patrón que projectFilesFormat.ts. La parte que sí toca el disco real
 * (leer el archivo, validar que quede dentro del workspace) vive en
 * readWorkspaceFile.ts.
 */
import { ChatResult, WorkspaceFileRequestArtifact } from "./kalClient";

/**
 * Igual que findProjectFilesArtifact: se usa la ÚLTIMA coincidencia,
 * no la primera — mismo criterio (un turno puede, en teoría, llamar a
 * la herramienta más de una vez, aunque el backend ya lo acota a 1 por
 * pedido — ver agent_core/llm/agent_loop.py::_VSCODE_ONLY_TOOL_NAMES).
 */
export function findWorkspaceFileRequestArtifact(result: ChatResult): WorkspaceFileRequestArtifact | undefined {
  let found: WorkspaceFileRequestArtifact | undefined;
  for (const step of result.steps) {
    if (step.artifact && (step.artifact as WorkspaceFileRequestArtifact).modality === "workspace_file_request") {
      found = step.artifact as WorkspaceFileRequestArtifact;
    }
  }
  return found;
}

// Tope de caracteres del contenido real que se manda de vuelta al
// modelo — mismo espíritu que agent_core/context_service.py::
// _MAX_WORKSPACE_TREE_PATHS_IN_PROMPT: un archivo enorme no debería
// inflar sin límite el historial de la conversación.
const _MAX_FILE_CHARS_IN_PROMPT = 20_000;

/**
 * El mensaje que se manda como `goal` del /chat encadenado — se marca
 * explícitamente como una respuesta al pedido anterior (no un mensaje
 * nuevo del usuario) para que el modelo no lo confunda con un pedido
 * distinto ni le pregunte al usuario por qué "escribió" esto.
 */
export function buildFileContentGoal(filePath: string, content: string): string {
  let body = content;
  let truncatedNote = "";
  if (body.length > _MAX_FILE_CHARS_IN_PROMPT) {
    body = body.slice(0, _MAX_FILE_CHARS_IN_PROMPT);
    truncatedNote = `\n\n[... archivo truncado, se muestran los primeros ${_MAX_FILE_CHARS_IN_PROMPT} caracteres de ${content.length} reales ...]`;
  }
  return (
    `[Contenido real de '${filePath}', que pediste con read_workspace_file — esto NO es un mensaje nuevo ` +
    "del usuario, es la respuesta a tu pedido anterior en este mismo turno, seguí con lo que estabas haciendo]:\n\n" +
    "```\n" + body + truncatedNote + "\n```"
  );
}

/** Igual que buildFileContentGoal, para cuando la lectura real falló. */
export function buildFileErrorGoal(filePath: string, reason: string): string {
  return (
    `[read_workspace_file no pudo leer '${filePath}': ${reason} — esto NO es un mensaje nuevo del usuario, ` +
    "es la respuesta a tu pedido anterior en este mismo turno. No inventes su contenido, avisale al usuario si hace falta.]"
  );
}
