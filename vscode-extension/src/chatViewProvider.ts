import * as vscode from "vscode";
import { buildChatHtml } from "./chatWebviewHtml";
import { captureEditorSnapshot, captureOpenEditors, captureWorkspaceTree } from "./editorContext";
import { KalClient } from "./kalClient";
import { maybeHandleProjectFiles } from "./projectFiles";
import { resolvePendingWorkspaceFileReads } from "./readWorkspaceFile";

/**
 * Chat de kal como vista fija de la barra lateral (icono propio en la
 * Activity Bar, junto al resto de extensiones de agentes de IA que el
 * usuario tenga instaladas) — a diferencia de ChatPanel (pestaña que se
 * abre "al costado" para un pedido puntual), esta vista siempre está
 * ahí, un clic en el ícono y ya está.
 *
 * Es una conversación independiente de la de ChatPanel (su propio
 * session_id, ver agent_core/sessions.py) — no comparten historial.
 * No participa del flujo de "contexto del editor adjunto" EXPLÍCITO de
 * "Kal: Preguntar sobre la selección" (adjunto de un solo uso, con el
 * archivo/selección completos) — eso sigue siendo específico de
 * ChatPanel. Sí manda un contexto LIVIANO automático en cada pedido
 * (ver editorContext.ts::captureEditorSnapshot(includeContent=false)):
 * solo la ruta del archivo activo, sin su contenido — más, desde el
 * "Visible Tree"/"Open Editors" de la propuesta de Editor Context
 * Provider (2026-07-20), el árbol real de archivos del workspace y la
 * lista de pestañas abiertas (ver editorContext.ts::
 * captureWorkspaceTree()/captureOpenEditors()).
 *
 * BUG REAL ENCONTRADO EN USO (2026-07-20): pedido de agregar fotos a
 * "la página de menú" con esa página realmente abierta en el editor —
 * kal no tenía forma de saberlo (esta vista no mandaba NINGÚN contexto
 * del editor) y creó un archivo nuevo en el lugar equivocado,
 * desconectado del proyecto real que ya existía. El contexto liviano
 * evita exactamente esto sin pagar el costo en tokens de mandar el
 * archivo completo en cada mensaje de un chat pensado para ser libre;
 * el árbol/pestañas abiertas cubren el caso en que el archivo relevante
 * ni siquiera es el activo (p.ej. "agregá esas fotos" con menu.html
 * abierto en OTRA pestaña, no la que tiene foco).
 *
 * También resuelve, de forma transparente para el usuario, cualquier
 * pedido pendiente de read_workspace_file encadenando /chat
 * automáticamente (ver readWorkspaceFile.ts).
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
    // Contexto liviano y AUTOMÁTICO (sin contenido) en cada pedido —
    // ver el docstring de la clase. `?? undefined` porque
    // captureEditorSnapshot devuelve `null` sin un editor activo, y
    // KalClient.chat espera `undefined` para "sin contexto".
    const editorSnapshot = captureEditorSnapshot(false) ?? undefined;
    // Árbol de archivos/pestañas abiertas: solo tiene sentido adjuntarlos
    // junto a un editor activo real (decisión de diseño explícita) — sin
    // ningún archivo activo, un editorContext con relativePath vacío es
    // un caso raro que el backend no espera tener que manejar.
    const editorContext = editorSnapshot
      ? { ...editorSnapshot, workspaceTree: await captureWorkspaceTree(), openEditors: captureOpenEditors() }
      : undefined;

    try {
      const result = await this.client.chat(text, model, this.sessionId, editorContext);
      this.sessionId = result.session_id;
      // Resuelve cualquier pedido pendiente de read_workspace_file
      // encadenando /chat automáticamente (ver readWorkspaceFile.ts) —
      // transparente para el usuario, solo se muestra la respuesta FINAL.
      const finalResult = await resolvePendingWorkspaceFileReads(result, this.client, model, editorContext);
      this.sessionId = finalResult.session_id;
      this.view?.webview.postMessage({ type: "answer", result: finalResult });
      await maybeHandleProjectFiles(finalResult, this.client);
    } catch (e) {
      this.view?.webview.postMessage({ type: "error", message: String(e instanceof Error ? e.message : e) });
    } finally {
      // Ver el comentario equivalente en chatPanel.ts — sin esto,
      // el usuario podía mandar un pedido nuevo mientras la vista
      // previa de archivos del pedido actual todavía esperaba una
      // decisión (VS Code encola los diálogos nativos, mostrando el
      // más viejo primero, no el último).
      this.view?.webview.postMessage({ type: "ready" });
    }
  }
}
