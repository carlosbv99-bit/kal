/**
 * Lógica PURA de formateo del contexto del editor — sin ningún import de
 * `vscode` a propósito, para poder testearla con Node normal (el módulo
 * `vscode` no existe fuera del extension host; importarlo en un archivo
 * rompe cualquier test que lo cargue, aunque no use nada de vscode).
 */

export interface EditorSnapshot {
  relativePath: string;
  languageId: string;
  text: string;
  isSelection: boolean;
}

export function formatEditorContext(snapshot: EditorSnapshot): string {
  const label = snapshot.isSelection ? "selección" : "archivo completo";
  return (
    `Contexto del editor (${label} de ${snapshot.relativePath}, lenguaje ${snapshot.languageId}):\n` +
    "```" +
    snapshot.languageId +
    "\n" +
    snapshot.text +
    "\n```"
  );
}
