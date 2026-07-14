import * as vscode from "vscode";
import { buildChatHtml } from "./chatWebviewHtml";
import { EditorSnapshot } from "./editorContextFormat";
import { KalClient } from "./kalClient";
import { maybeHandleProjectFiles } from "./projectFiles";

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
  // Señal cruda del editor, adjunta al PRÓXIMO mensaje que se mande
  // (un solo uso — mismo comportamiento que el prefill de texto que
  // reemplaza, ver Context Service: agent_core/context_service.py).
  // La extensión nunca la formatea a texto, solo la reenvía.
  private pendingEditorContext: EditorSnapshot | undefined;

  private constructor(panel: vscode.WebviewPanel, extensionUri: vscode.Uri, client: KalClient) {
    this.panel = panel;
    this.extensionUri = extensionUri;
    this.client = client;

    this.panel.webview.html = buildChatHtml(this.panel.webview, this.extensionUri);

    this.disposables.push(
      this.panel.webview.onDidReceiveMessage(async (message) => {
        if (message?.type === "ask" && typeof message.text === "string") {
          await this.handleAsk(message.text);
        } else if (message?.type === "dismiss-context") {
          this.pendingEditorContext = undefined;
        }
      }),
      this.panel.onDidDispose(() => this.dispose())
    );
  }

  static createOrShow(extensionUri: vscode.Uri, client: KalClient, editorSnapshot?: EditorSnapshot): void {
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

    if (editorSnapshot) {
      ChatPanel.current.pendingEditorContext = editorSnapshot;
      ChatPanel.current.panel.webview.postMessage({
        type: "context-attached",
        relativePath: editorSnapshot.relativePath,
        isSelection: editorSnapshot.isSelection,
      });
    }
  }

  private async handleAsk(text: string): Promise<void> {
    const config = vscode.workspace.getConfiguration("kal");
    const model = config.get<string>("model") || undefined;
    const editorContext = this.pendingEditorContext;
    this.pendingEditorContext = undefined;

    try {
      const result = await this.client.chat(text, model, this.sessionId, editorContext);
      this.sessionId = result.session_id;
      this.panel.webview.postMessage({ type: "answer", result });
      await maybeHandleProjectFiles(result, this.client);
    } catch (e) {
      this.panel.webview.postMessage({ type: "error", message: String(e instanceof Error ? e.message : e) });
    }
  }

  private dispose(): void {
    ChatPanel.current = undefined;
    this.disposables.forEach((d) => d.dispose());
    this.panel.dispose();
  }
}
