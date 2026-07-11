import * as fs from "fs";
import * as vscode from "vscode";
import { KalClient } from "./kalClient";

/**
 * WebviewPanel singleton para el chat con kal. El webview (media/chat.js)
 * nunca llama a la API de kal directamente — le hace postMessage a este
 * host (Node.js, sin restricción CORS), que es quien usa KalClient.
 */
export class ChatPanel {
  private static current: ChatPanel | undefined;

  private readonly panel: vscode.WebviewPanel;
  private readonly client: KalClient;
  private readonly extensionUri: vscode.Uri;
  private readonly disposables: vscode.Disposable[] = [];
  // Un panel = una conversación (ver agent_core/sessions.py) — vive
  // mientras el panel esté abierto, se pierde al cerrarlo (igual que
  // cerrar una pestaña de chat empieza una conversación nueva).
  private sessionId: string | undefined;

  private constructor(panel: vscode.WebviewPanel, extensionUri: vscode.Uri, client: KalClient) {
    this.panel = panel;
    this.extensionUri = extensionUri;
    this.client = client;

    this.panel.webview.html = this.buildHtml();

    this.disposables.push(
      this.panel.webview.onDidReceiveMessage(async (message) => {
        if (message?.type === "ask" && typeof message.text === "string") {
          await this.handleAsk(message.text);
        }
      }),
      this.panel.onDidDispose(() => this.dispose())
    );
  }

  static createOrShow(extensionUri: vscode.Uri, client: KalClient, prefill?: string): void {
    if (ChatPanel.current) {
      ChatPanel.current.panel.reveal(vscode.ViewColumn.Beside);
    } else {
      const panel = vscode.window.createWebviewPanel(
        "kalChat",
        "Kal",
        vscode.ViewColumn.Beside,
        {
          enableScripts: true,
          retainContextWhenHidden: true,
          localResourceRoots: [vscode.Uri.joinPath(extensionUri, "media")],
        }
      );
      ChatPanel.current = new ChatPanel(panel, extensionUri, client);
    }

    if (prefill) {
      ChatPanel.current.panel.webview.postMessage({ type: "prefill", text: prefill });
    }
  }

  private async handleAsk(text: string): Promise<void> {
    const config = vscode.workspace.getConfiguration("kal");
    const model = config.get<string>("model") || undefined;

    try {
      const result = await this.client.chat(text, model, this.sessionId);
      this.sessionId = result.session_id;
      this.panel.webview.postMessage({ type: "answer", result });
    } catch (e) {
      this.panel.webview.postMessage({ type: "error", message: String(e instanceof Error ? e.message : e) });
    }
  }

  private buildHtml(): string {
    const webview = this.panel.webview;
    const cssUri = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "media", "chat.css"));
    const jsUri = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "media", "chat.js"));
    const nonce = getNonce();

    const htmlPath = vscode.Uri.joinPath(this.extensionUri, "media", "chat.html");
    const raw = fs.readFileSync(htmlPath.fsPath, "utf-8");

    return raw
      .replaceAll("{{cssUri}}", cssUri.toString())
      .replaceAll("{{jsUri}}", jsUri.toString())
      .replaceAll("{{cspSource}}", webview.cspSource)
      .replaceAll("{{nonce}}", nonce);
  }

  private dispose(): void {
    ChatPanel.current = undefined;
    this.disposables.forEach((d) => d.dispose());
    this.panel.dispose();
  }
}

function getNonce(): string {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let text = "";
  for (let i = 0; i < 32; i++) {
    text += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return text;
}
