/**
 * Tipo PURO, sin ningún import de `vscode` a propósito, para poder
 * usarlo en archivos testeables con Node normal (el módulo `vscode`
 * no existe fuera del extension host).
 *
 * El formateo a texto (antes `formatEditorContext()`, acá mismo) se
 * eliminó: ahora la extensión manda esta señal CRUDA al backend
 * (ver kalClient.ts) y es agent_core/context_service.py quien decide
 * cómo se ve en el mensaje final al LLM — la extensión nunca
 * concatena texto de contexto por su cuenta. `applyEditFormat.ts`
 * sigue usando este mismo tipo para su propio flujo (aplicar un
 * parche), sin relación con esto.
 */
export interface EditorSnapshot {
  relativePath: string;
  languageId: string;
  text: string;
  isSelection: boolean;
}
