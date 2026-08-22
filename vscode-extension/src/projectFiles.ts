/**
 * Crea archivos/carpetas REALES en el workspace abierto de VS Code, a
 * partir de una propuesta de la herramienta propose_project_files (ver
 * tool_integration/adapters/vscode_files.py). El backend de Python
 * NUNCA escribe nada al disco real (no conoce qué carpeta tiene
 * abierta VS Code) — la escritura real, la vista previa y la
 * aprobación del usuario ocurren acá, la única parte del sistema que
 * de verdad sabe cuál es el workspace.
 *
 * BUG REAL ENCONTRADO EN USO (2026-07-30): el diseño anterior dependía
 * ENTERAMENTE de un diálogo modal nativo de VS Code
 * (showInformationMessage) para decidir aplicar/descartar — el usuario
 * reportó que el diálogo se cerró solo antes de poder leerlo, sin
 * ninguna forma de recuperar la propuesta. Rediseñado: la decisión
 * (Ver detalle/Aplicar/Descartar) ahora vive como botones REALES
 * dentro del propio mensaje del panel de chat (ver media/chat.js) —
 * parte del historial persistente de la conversación, no un diálogo
 * transitorio que se pueda perder. maybeHandleProjectFiles() ya NO
 * espera una decisión: valida y publica la propuesta, listo.
 * handleProjectFilesDecision() aplica la decisión real cuando el
 * usuario hace clic en un botón del webview (ver chatPanel.ts/
 * chatViewProvider.ts::onDidReceiveMessage). La confirmación de
 * colisiones (sobrescribir archivos ya existentes) sigue siendo un
 * diálogo nativo por ahora — camino secundario, menos frecuente, no
 * el que se reportó roto — a revisar si algún día se reporta el mismo
 * problema ahí.
 *
 * Parte de la API real de vscode (workspace.fs, diálogos nativos), no
 * verificable en este entorno sin un VS Code real corriendo — la
 * validación de rutas en sí (sin depender de vscode) vive aparte, en
 * projectFilesFormat.ts, testeable con Node normal.
 */
import * as vscode from "vscode";
import { ChatResult, KalClient, ProjectFile } from "./kalClient";
import { findFirstInvalidPath, findProjectFilesArtifact, isWithinRoot } from "./projectFilesFormat";

async function fileExists(uri: vscode.Uri): Promise<boolean> {
  try {
    await vscode.workspace.fs.stat(uri);
    return true;
  } catch {
    return false;
  }
}

/**
 * Si la respuesta de /chat trae una propuesta de propose_project_files,
 * valida lo básico (workspace abierto, rutas válidas) y la publica en
 * el chat como un mensaje INTERACTIVO (con botones reales) — nunca
 * escribe nada acá. La decisión real llega después, de forma
 * asincrónica, vía handleProjectFilesDecision() cuando el usuario hace
 * clic en un botón del webview.
 */
export async function maybeHandleProjectFiles(
  result: ChatResult,
  client: KalClient,
  postToChat: (message: unknown) => void
): Promise<void> {
  const artifact = findProjectFilesArtifact(result);
  if (!artifact || artifact.files.length === 0) {
    return;
  }

  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (!workspaceFolders || workspaceFolders.length === 0) {
    postToChat({
      type: "project-files-notice",
      text: `⚠️ Kal propuso ${artifact.files.length} archivo(s), pero no hay ninguna carpeta abierta en VS Code — no se guardó nada.`,
    });
    const action = await vscode.window.showWarningMessage(
      `Kal propone crear ${artifact.files.length} archivo(s), pero no hay ninguna carpeta abierta en VS Code.`,
      "Abrir una carpeta..."
    );
    if (action === "Abrir una carpeta...") {
      await vscode.commands.executeCommand("vscode.openFolder");
    }
    // Nada que reportar: sin workspace, ni siquiera hubo una vista previa real.
    return;
  }

  const invalidPathError = findFirstInvalidPath(artifact.files);
  if (invalidPathError !== null) {
    postToChat({
      type: "project-files-notice",
      text: `⚠️ Kal propuso un archivo inválido, se descartó la propuesta entera: ${invalidPathError}`,
    });
    await client.reportFilesystemAccessOutcome(artifact.request_id, "discarded", []);
    return;
  }

  // Publica la propuesta como mensaje interactivo — chat.js dibuja los
  // botones y guarda `files` tal cual para devolverlos en la decisión
  // (el extension host no necesita mantener ningún estado pendiente
  // propio: el webview es la fuente de verdad mientras el usuario
  // decide, mismo espíritu "sin servidor" que el resto de este flujo).
  postToChat({
    type: "project-files-proposal",
    requestId: artifact.request_id,
    files: artifact.files,
  });
}

/**
 * Aplica la decisión real que el usuario tomó haciendo clic en un
 * botón del mensaje interactivo (ver maybeHandleProjectFiles arriba) —
 * llamada desde chatPanel.ts/chatViewProvider.ts::onDidReceiveMessage
 * cuando llega `{type: "project-files-decision", ...}` desde el
 * webview. "detail" no escribe nada, solo abre una vista previa real
 * del contenido; "apply"/"discard" son las decisiones finales.
 */
export async function handleProjectFilesDecision(
  decision: { requestId: string; decision: "detail" | "apply" | "discard"; files: ProjectFile[] },
  client: KalClient,
  postToChat: (message: unknown) => void
): Promise<void> {
  if (decision.decision === "detail") {
    // Archivos binarios (encoding "base64", ver Artifact Service /
    // import_resource): mostrar un placeholder, nunca el blob base64
    // crudo — ilegible e inútil para revisar en una vista previa.
    const combined = decision.files
      .map((f) => {
        if (f.encoding === "base64") {
          const approxBytes = Math.floor((f.content.length * 3) / 4);
          return `// ${f.path}\n[archivo binario, ~${Math.ceil(approxBytes / 1024)} KB — no se muestra el contenido]`;
        }
        return `// ${f.path}\n${f.content}`;
      })
      .join("\n\n");
    const doc = await vscode.workspace.openTextDocument({ content: combined });
    await vscode.window.showTextDocument(doc, { preview: true });
    // Los botones siguen disponibles en el mensaje del chat después de
    // esto — el usuario decide aplicar/descartar desde ahí, no hace
    // falta un segundo paso acá.
    return;
  }

  if (decision.decision === "discard") {
    postToChat({ type: "project-files-notice", text: "❌ La propuesta de archivos fue descartada — no se guardó nada." });
    await client.reportFilesystemAccessOutcome(decision.requestId, "discarded", []);
    return;
  }

  // decision.decision === "apply" de acá en adelante.
  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (!workspaceFolders || workspaceFolders.length === 0) {
    postToChat({ type: "project-files-notice", text: "⚠️ No hay ninguna carpeta abierta en VS Code — no se guardó nada." });
    await client.reportFilesystemAccessOutcome(decision.requestId, "discarded", []);
    return;
  }
  const root = workspaceFolders[0].uri;

  // Colisiones: todo o nada (ver "Fuera de alcance" del plan — sin
  // merge parcial). Sigue siendo un diálogo nativo por ahora (ver
  // docstring del archivo) — camino secundario, no el reportado roto.
  const collisions: string[] = [];
  for (const file of decision.files) {
    if (await fileExists(vscode.Uri.joinPath(root, file.path))) {
      collisions.push(file.path);
    }
  }
  if (collisions.length > 0) {
    const overwriteChoice = await vscode.window.showWarningMessage(
      `${collisions.length} archivo(s) ya existen y se sobrescribirían: ${collisions.join(", ")}`,
      { modal: true },
      "Sobrescribir todos",
      "Cancelar"
    );
    if (overwriteChoice !== "Sobrescribir todos") {
      postToChat({ type: "project-files-notice", text: "❌ La propuesta de archivos fue descartada — no se guardó nada." });
      await client.reportFilesystemAccessOutcome(decision.requestId, "discarded", []);
      return;
    }
  }

  // Defensa en profundidad: nunca escribir fuera del workspace, aunque
  // el backend ya rechazó rutas absolutas/".." antes de proponer nada.
  // Si CUALQUIER archivo resuelve fuera de la raíz, se aborta TODO —
  // ninguna escritura parcial.
  for (const file of decision.files) {
    const targetUri = vscode.Uri.joinPath(root, file.path);
    if (!isWithinRoot(root.fsPath, targetUri.fsPath)) {
      postToChat({
        type: "project-files-notice",
        text: `⚠️ '${file.path}' queda fuera de la carpeta del proyecto — se abortó todo, no se escribió nada.`,
      });
      await client.reportFilesystemAccessOutcome(decision.requestId, "discarded", []);
      return;
    }
  }

  const written: string[] = [];
  for (const file of decision.files) {
    const targetUri = vscode.Uri.joinPath(root, file.path);
    const parentDir = vscode.Uri.joinPath(targetUri, "..");
    await vscode.workspace.fs.createDirectory(parentDir);
    const bytes = Buffer.from(file.content, file.encoding === "base64" ? "base64" : "utf-8");
    await vscode.workspace.fs.writeFile(targetUri, bytes);
    written.push(file.path);
  }

  postToChat({ type: "project-files-notice", text: `✅ Se guardaron ${written.length} archivo(s) en el proyecto: ${written.join(", ")}` });
  await client.reportFilesystemAccessOutcome(decision.requestId, "written", written);
}
