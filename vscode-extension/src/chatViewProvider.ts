import * as vscode from "vscode";
import { buildChatHtml } from "./chatWebviewHtml";
import { KalClient } from "./kalClient";
import { maybeHandleProjectFiles } from "./projectFiles";

/**
 * Chat de kal como vista fija de la barra lateral (icono propio en la
 * Activity Bar, junto al resto de extensiones de agentes de IA que el
 * usuario tenga instaladas) — a diferencia de ChatPanel (pestaña que se
 * abre "al costado" para un pedido puntual), esta vista siempre está
 * ahí, un clic en el ícono y ya está.
 *
 * Es una conversación independiente de la de ChatPanel (su propio
 * session_id, ver agent_core/sessions.py) — no comparten historial.
 * No participa del flujo de "contexto del editor adjunto" de
 * "Kal: Preguntar sobre la selección": eso sigue siendo específico de
 * ChatPanel, esta vista es para chat libre.
 */
export class ChatViewProvider implements vscode.WebviewViewProvider {
  static readonly viewType = "kal.chatView";

  private view: vscode.WebviewView | undefined;
  private sessionId: string | undefined;

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly client: KalClient
  ) {}

  resolveWebviewView(webviewView: vscode.WebviewView): void {
    this.view = webviewView;
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, "media")],
    };
    webviewView.webview.html = buildChatHtml(webviewView.webview, this.extensionUri);

    webviewView.webview.onDidReceiveMessage(async (message) => {
      if (message?.type === "ask" && typeof message.text === "string") {
        await this.handleAsk(message.text);
      }
    });
  }

  private async handleAsk(text: string): Promise<void> {
    const config = vscode.workspace.getConfiguration("kal");
    const model = config.get<string>("model") || undefined;

    try {
      const result = await this.client.chat(text, model, this.sessionId);
      this.sessionId = result.session_id;
      this.view?.webview.postMessage({ type: "answer", result });
      await maybeHandleProjectFiles(result, this.client);
    } catch (e) {
      this.view?.webview.postMessage({ type: "error", message: String(e instanceof Error ? e.message : e) });
    }
  }
}
