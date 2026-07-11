/**
 * Parte que sí toca la API real de vscode (captura el editor activo) — no
 * verificable en este entorno sin un VS Code real corriendo. El tipo
 * EditorSnapshot en sí vive en editorContextFormat.ts (sin import de
 * vscode, testeable con Node normal).
 */
import * as vscode from "vscode";
import { EditorSnapshot } from "./editorContextFormat";

export { EditorSnapshot } from "./editorContextFormat";

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
