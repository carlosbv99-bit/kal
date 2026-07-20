/**
 * Resuelve los pedidos pendientes de read_workspace_file (ver
 * tool_integration/adapters/vscode_files.py::ReadWorkspaceFileTool):
 * el backend de Python no puede leer el disco real del usuario (no
 * sabe cuál es el workspace de VS Code), así que la Tool devuelve un
 * Artifact "pending" con la ruta pedida — esta función lee el archivo
 * REAL acá, y encadena automáticamente un /chat nuevo (mismo
 * session_id) con su contenido, de forma transparente para el
 * usuario. Mismo patrón async ya usado para propose_project_files/
 * import_resource (ver projectFiles.ts), invertido: acá se LEE en vez
 * de escribir.
 *
 * Parte de la API real de vscode (workspace.fs), no verificable en
 * este entorno sin un VS Code real corriendo — el armado de los
 * mensajes en sí (sin depender de vscode) vive en
 * readWorkspaceFileFormat.ts, testeable con Node normal.
 */
import * as vscode from "vscode";
import { ChatResult, KalClient } from "./kalClient";
import { EditorSnapshot } from "./editorContextFormat";
import { isWithinRoot } from "./projectFilesFormat";
import { buildFileContentGoal, buildFileErrorGoal, findWorkspaceFileRequestArtifact } from "./readWorkspaceFileFormat";

// Tope de vueltas del encadenado por cada pedido original del usuario —
// evita un loop infinito si el modelo sigue pidiendo archivos sin
// converger nunca a una respuesta final (p.ej. por un bug de prompt).
const _MAX_CHAINED_READS = 5;

async function readRequestedFile(relativePath: string): Promise<string> {
  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (!workspaceFolders || workspaceFolders.length === 0) {
    return buildFileErrorGoal(relativePath, "no hay ninguna carpeta de proyecto abierta en VS Code");
  }

  const root = workspaceFolders[0].uri;
  const targetUri = vscode.Uri.joinPath(root, relativePath);
  if (!isWithinRoot(root.fsPath, targetUri.fsPath)) {
    return buildFileErrorGoal(relativePath, "esa ruta queda fuera de la carpeta del proyecto");
  }

  try {
    const bytes = await vscode.workspace.fs.readFile(targetUri);
    return buildFileContentGoal(relativePath, Buffer.from(bytes).toString("utf-8"));
  } catch (e) {
    return buildFileErrorGoal(relativePath, `no se pudo leer el archivo (${e instanceof Error ? e.message : e})`);
  }
}

/**
 * Si `result` trae un pedido pendiente de read_workspace_file, lo
 * resuelve leyendo el archivo real y encadenando /chat hasta 5 veces
 * (por si el modelo necesita más de un archivo antes de responder de
 * verdad) — devuelve el ChatResult FINAL, listo para mostrarle al
 * usuario (nunca se muestran los pasos intermedios: son un detalle de
 * implementación, no algo que el usuario pidió ver).
 */
export async function resolvePendingWorkspaceFileReads(
  initialResult: ChatResult,
  client: KalClient,
  model: string | undefined,
  editorContext?: EditorSnapshot
): Promise<ChatResult> {
  let result = initialResult;
  for (let i = 0; i < _MAX_CHAINED_READS; i++) {
    const artifact = findWorkspaceFileRequestArtifact(result);
    if (!artifact) {
      return result;
    }
    const goal = await readRequestedFile(artifact.path);
    result = await client.chat(goal, model, result.session_id, editorContext);
  }
  return result;
}
