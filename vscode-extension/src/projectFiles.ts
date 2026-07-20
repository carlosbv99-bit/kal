/**
 * Crea archivos/carpetas REALES en el workspace abierto de VS Code, a
 * partir de una propuesta de la herramienta propose_project_files (ver
 * tool_integration/adapters/vscode_files.py). El backend de Python
 * NUNCA escribe nada al disco real (no conoce qué carpeta tiene
 * abierta VS Code) — la escritura real, la vista previa y la
 * aprobación del usuario ocurren acá, la única parte del sistema que
 * de verdad sabe cuál es el workspace.
 *
 * Parte de la API real de vscode (workspace.fs, diálogos nativos), no
 * verificable en este entorno sin un VS Code real corriendo — la
 * validación de rutas en sí (sin depender de vscode) vive aparte, en
 * projectFilesFormat.ts, testeable con Node normal.
 */
import * as vscode from "vscode";
import { ChatResult, KalClient } from "./kalClient";
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
 * maneja todo el flujo: vista previa, aprobación del usuario, y
 * escritura real (o descarte) — nunca se llama dos veces para la misma
 * respuesta, así que no hace falta deduplicar.
 */
export async function maybeHandleProjectFiles(result: ChatResult, client: KalClient): Promise<void> {
  const artifact = findProjectFilesArtifact(result);
  if (!artifact || artifact.files.length === 0) {
    return;
  }

  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (!workspaceFolders || workspaceFolders.length === 0) {
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
    vscode.window.showErrorMessage(`Kal propuso un archivo inválido, se descarta la propuesta entera: ${invalidPathError}`);
    await client.reportFilesystemAccessOutcome(artifact.request_id, "discarded", []);
    return;
  }

  const root = workspaceFolders[0].uri;
  const fileList = artifact.files.map((f) => f.path).join("\n");

  let choice = await vscode.window.showInformationMessage(
    `Kal propone crear ${artifact.files.length} archivo(s) en el proyecto:\n${fileList}`,
    { modal: true },
    "Ver detalle",
    "Aplicar",
    "Descartar"
  );

  if (choice === "Ver detalle") {
    // Archivos binarios (encoding "base64", ver Artifact Service /
    // import_resource): mostrar un placeholder, nunca el blob base64
    // crudo — ilegible e inútil para revisar en una vista previa.
    const combined = artifact.files
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
    choice = await vscode.window.showInformationMessage(
      `¿Aplicar los ${artifact.files.length} archivo(s) propuestos?`,
      { modal: true },
      "Aplicar",
      "Descartar"
    );
  }

  if (choice !== "Aplicar") {
    await client.reportFilesystemAccessOutcome(artifact.request_id, "discarded", []);
    return;
  }

  // Colisiones: todo o nada (ver "Fuera de alcance" del plan — sin merge parcial).
  const collisions: string[] = [];
  for (const file of artifact.files) {
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
      await client.reportFilesystemAccessOutcome(artifact.request_id, "discarded", []);
      return;
    }
  }

  // Defensa en profundidad: nunca escribir fuera del workspace, aunque
  // el backend ya rechazó rutas absolutas/".." antes de proponer nada.
  // Si CUALQUIER archivo resuelve fuera de la raíz, se aborta TODO —
  // ninguna escritura parcial.
  for (const file of artifact.files) {
    const targetUri = vscode.Uri.joinPath(root, file.path);
    if (!isWithinRoot(root.fsPath, targetUri.fsPath)) {
      vscode.window.showErrorMessage(
        `Kal: '${file.path}' queda fuera de la carpeta del proyecto — se aborta todo, no se escribió nada.`
      );
      await client.reportFilesystemAccessOutcome(artifact.request_id, "discarded", []);
      return;
    }
  }

  const written: string[] = [];
  for (const file of artifact.files) {
    const targetUri = vscode.Uri.joinPath(root, file.path);
    const parentDir = vscode.Uri.joinPath(targetUri, "..");
    await vscode.workspace.fs.createDirectory(parentDir);
    const bytes = Buffer.from(file.content, file.encoding === "base64" ? "base64" : "utf-8");
    await vscode.workspace.fs.writeFile(targetUri, bytes);
    written.push(file.path);
  }

  vscode.window.showInformationMessage(`Kal creó ${written.length} archivo(s) en el proyecto.`);
  await client.reportFilesystemAccessOutcome(artifact.request_id, "written", written);
}
