import * as fs from "fs";
import * as vscode from "vscode";

/**
 * HTML compartido entre ChatPanel (pestaña, "Kal: Abrir chat"/"Preguntar
 * sobre la selección") y ChatViewProvider (vista fija en la barra
 * lateral) — mismo media/chat.html+.js+.css en ambos casos, solo cambia
 * dónde vive el webview (WebviewPanel vs WebviewView comparten la misma
 * interfaz `.webview`).
 */
export function buildChatHtml(webview: vscode.Webview, extensionUri: vscode.Uri): string {
  const cssUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, "media", "chat.css"));
  const jsUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, "media", "chat.js"));
  const nonce = getNonce();

  const htmlPath = vscode.Uri.joinPath(extensionUri, "media", "chat.html");
  const raw = fs.readFileSync(htmlPath.fsPath, "utf-8");

  return raw
    .replaceAll("{{cssUri}}", cssUri.toString())
    .replaceAll("{{jsUri}}", jsUri.toString())
    .replaceAll("{{cspSource}}", webview.cspSource)
    .replaceAll("{{nonce}}", nonce);
}

function getNonce(): string {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let text = "";
  for (let i = 0; i < 32; i++) {
    text += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return text;
}
