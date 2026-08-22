import * as fs from "fs";
import * as vscode from "vscode";

/**
 * HTML compartido entre ChatPanel (pestaña, "Kal: Abrir chat"/"Preguntar
 * sobre la selección") y ChatViewProvider (vista fija en la barra
 * lateral) — mismo media/chat.html+.js+.css en ambos casos, solo cambia
 * dónde vive el webview (WebviewPanel vs WebviewView comparten la misma
 * interfaz `.webview`).
 *
 * BUG REAL ENCONTRADO EN USO (2026-08-23): el usuario reinstaló la
 * extensión (nueva versión de chat.js con botones reales para
 * propose_project_files) y siguió viendo el comportamiento VIEJO — el
 * mismo problema de caché que ya se había resuelto una vez para el
 * frontend web (ver técnica "Caché del navegador: no-store"), nunca
 * aplicado acá. El webview de vscode puede cachear un recurso por su
 * URL exacta entre recargas — sin ningún cache-busting, `asWebviewUri`
 * generaba la MISMA url para chat.js sin importar si el contenido del
 * archivo había cambiado. Se agrega `?v=<mtime>` (el propio timestamp
 * de modificación del archivo en disco) a cada URI — cambia sola cada
 * vez que el archivo real cambia, sin necesitar bump manual de versión.
 */
export function buildChatHtml(webview: vscode.Webview, extensionUri: vscode.Uri): string {
  const cssPath = vscode.Uri.joinPath(extensionUri, "media", "chat.css");
  const jsPath = vscode.Uri.joinPath(extensionUri, "media", "chat.js");
  const cssUri = `${webview.asWebviewUri(cssPath).toString()}?v=${_mtime(cssPath.fsPath)}`;
  const jsUri = `${webview.asWebviewUri(jsPath).toString()}?v=${_mtime(jsPath.fsPath)}`;
  const nonce = getNonce();

  const htmlPath = vscode.Uri.joinPath(extensionUri, "media", "chat.html");
  const raw = fs.readFileSync(htmlPath.fsPath, "utf-8");

  return raw
    .replaceAll("{{cssUri}}", cssUri)
    .replaceAll("{{jsUri}}", jsUri)
    .replaceAll("{{cspSource}}", webview.cspSource)
    .replaceAll("{{nonce}}", nonce);
}

function _mtime(fsPath: string): number {
  return Math.floor(fs.statSync(fsPath).mtimeMs);
}

function getNonce(): string {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let text = "";
  for (let i = 0; i < 32; i++) {
    text += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return text;
}
