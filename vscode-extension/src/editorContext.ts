/**
 * Parte que sí toca la API real de vscode (captura el editor activo) — no
 * verificable en este entorno sin un VS Code real corriendo. La lógica de
 * formateo en sí vive en editorContextFormat.ts (sin import de vscode,
 * testeable con Node normal, ver test/editorContextFormat.test.ts).
 */
import * as vscode from "vscode";
import { EditorSnapshot, formatEditorContext } from "./editorContextFormat";

export { EditorSnapshot, formatEditorContext } from "./editorContextFormat";

export function captureEditorSnapshot(): EditorSnapshot | null {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    return null;
  }

  const doc = editor.document;
  const selection = editor.selection;
  const hasSelection = !selection.isEmpty;

  return {
    relativePath: vscode.workspace.asRelativePath(doc.uri),
    languageId: doc.languageId,
    text: hasSelection ? doc.getText(selection) : doc.getText(),
    isSelection: hasSelection,
  };
}

export function buildEditorContext(): string | null {
  const snapshot = captureEditorSnapshot();
  return snapshot ? formatEditorContext(snapshot) : null;
}
