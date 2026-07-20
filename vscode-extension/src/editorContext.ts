/**
 * Parte que sí toca la API real de vscode (captura el editor activo) — no
 * verificable en este entorno sin un VS Code real corriendo. El tipo
 * EditorSnapshot en sí vive en editorContextFormat.ts (sin import de
 * vscode, testeable con Node normal).
 */
import * as vscode from "vscode";
import { EditorSnapshot } from "./editorContextFormat";

export { EditorSnapshot } from "./editorContextFormat";

/**
 * `includeContent = false` (ver ChatViewProvider): contexto LIVIANO —
 * solo `relativePath`/`languageId`, `text` vacío. Mandar el archivo
 * COMPLETO en cada mensaje de un chat libre (la vista de la barra
 * lateral, sin adjunto explícito) sería carísimo en tokens sin
 * necesidad real la mayoría de las veces; alcanza con que el modelo
 * sepa EN QUÉ ruta está trabajando el usuario (ver
 * agent_core/context_service.py, que ya distingue este caso). `true`
 * (default) sigue siendo el comportamiento de siempre — usado por
 * ChatPanel/"Preguntar sobre la selección", un adjunto explícito de un
 * solo uso donde el contenido real sí importa.
 */
export function captureEditorSnapshot(includeContent: boolean = true): EditorSnapshot | null {
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
    text: includeContent ? (hasSelection ? doc.getText(selection) : doc.getText()) : "",
    isSelection: hasSelection,
  };
}

// Carpetas que nunca aportan nada útil para que el modelo entienda la
// estructura REAL del proyecto — dependencias/artefactos generados,
// nunca algo que el usuario haya escrito a mano.
const _TREE_EXCLUDE_GLOB =
  "**/{node_modules,.git,__pycache__,.venv,venv,dist,out,.pytest_cache,data,logs}/**";
const _DEFAULT_MAX_TREE_FILES = 500;

/**
 * "Visible Tree" (ver agent_core/context_service.py::
 * EditorContextSignals.workspace_tree, pieza mínima de "Editor Context
 * Provider" pedida explícitamente por el usuario 2026-07-20, tras un
 * bug real: kal creó un archivo nuevo en la raíz del workspace sin
 * saber que un proyecto —'restaurante-web/'— ya existía como
 * subcarpeta). Async: vscode.workspace.findFiles() es la única API
 * real para esto, no tiene versión síncrona. Acotado (maxFiles) —
 * agent_core/context_service.py aplica SU PROPIO tope aparte, esto es
 * la primera barrera, del lado de la extensión.
 */
export async function captureWorkspaceTree(maxFiles: number = _DEFAULT_MAX_TREE_FILES): Promise<string[]> {
  const uris = await vscode.workspace.findFiles("**/*", _TREE_EXCLUDE_GLOB, maxFiles);
  return uris.map((uri) => vscode.workspace.asRelativePath(uri)).sort();
}

/**
 * "Open Editors" — TODAS las pestañas abiertas (no solo la activa),
 * como rutas relativas, sin duplicados. Síncrono:
 * vscode.window.tabGroups.all ya está disponible sin esperar nada.
 */
export function captureOpenEditors(): string[] {
  const paths = new Set<string>();
  for (const group of vscode.window.tabGroups.all) {
    for (const tab of group.tabs) {
      if (tab.input instanceof vscode.TabInputText) {
        paths.add(vscode.workspace.asRelativePath(tab.input.uri));
      }
    }
  }
  return Array.from(paths).sort();
}
