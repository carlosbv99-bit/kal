import * as vscode from "vscode";
import { runApplySuggestedEdit } from "./applyEdit";
import { ChatPanel } from "./chatPanel";
import { ChatViewProvider } from "./chatViewProvider";
import { captureEditorSnapshot } from "./editorContext";
import { KalClient } from "./kalClient";

export function activate(context: vscode.ExtensionContext): void {
  const getClient = (): KalClient => {
    const config = vscode.workspace.getConfiguration("kal");
    const serverUrl = config.get<string>("serverUrl", "http://localhost:8000");
    return new KalClient(serverUrl);
  };

  context.subscriptions.push(
    vscode.commands.registerCommand("kal.openChat", () => {
      ChatPanel.createOrShow(context.extensionUri, getClient());
    }),

    vscode.commands.registerCommand("kal.askAboutSelection", () => {
      const snapshot = captureEditorSnapshot();
      if (!snapshot) {
        vscode.window.showWarningMessage("Kal: no hay ningún editor activo para tomar contexto.");
        return;
      }
      ChatPanel.createOrShow(context.extensionUri, getClient(), snapshot);
    }),

    vscode.commands.registerCommand("kal.applySuggestedEdit", () => {
      void runApplySuggestedEdit(getClient());
    }),

    // Vista fija en la barra lateral (icono propio en la Activity Bar,
    // junto a otras extensiones de agentes de IA) — ver ChatViewProvider.
    //
    // BUG REAL ENCONTRADO EN USO (2026-07-20): sin retainContextWhenHidden,
    // VS Code destruye el documento HTML de esta vista cada vez que el
    // usuario cambia a OTRA vista de la misma Activity Bar (p.ej. el
    // Explorer, para mirar el árbol de archivos) y lo reconstruye vacío
    // al volver — el usuario ve el chat "borrarse" en cada ida y vuelta.
    // Costo real (más memoria por mantener el webview vivo en segundo
    // plano) aceptado a propósito: es la única vista de kal pensada para
    // quedar "siempre ahí" con una conversación en curso.
    vscode.window.registerWebviewViewProvider(
      ChatViewProvider.viewType,
      new ChatViewProvider(context.extensionUri, getClient()),
      { webviewOptions: { retainContextWhenHidden: true } }
    )
  );

  // Ítem en la barra de estado: acceso de un clic a "Kal: Abrir chat"
  // sin tener que recordar el comando en la paleta.
  const statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBarItem.text = "$(comment-discussion) Kal";
  statusBarItem.tooltip = "Abrir chat con Kal";
  statusBarItem.command = "kal.openChat";
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);
}

export function deactivate(): void {}
