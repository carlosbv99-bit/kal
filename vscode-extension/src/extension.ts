import * as vscode from "vscode";
import { runApplySuggestedEdit } from "./applyEdit";
import { ChatPanel } from "./chatPanel";
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
    })
  );
}

export function deactivate(): void {}
