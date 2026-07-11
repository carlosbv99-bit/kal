/**
 * Lógica PURA para el flujo de "aplicar cambios a la selección" — sin
 * ningún import de `vscode` a propósito (mismo criterio que
 * editorContextFormat.ts), para poder testearla con Node normal.
 */

import { EditorSnapshot } from "./editorContextFormat";

export function buildEditGoal(snapshot: EditorSnapshot, instruction: string): string {
  const label = snapshot.isSelection ? "selección" : "archivo completo";
  return (
    `Reescribí el siguiente código incorporando este cambio: "${instruction}".\n\n` +
    "Reglas estrictas de formato de tu respuesta:\n" +
    "- Respondé ÚNICAMENTE con el código resultante completo, nada más.\n" +
    "- No agregues explicación, comentarios sobre el cambio, ni texto antes o después.\n" +
    "- Envolvé el código en un único bloque de código con tres backticks.\n\n" +
    `Código actual (${label} de ${snapshot.relativePath}, lenguaje ${snapshot.languageId}):\n` +
    "```" +
    snapshot.languageId +
    "\n" +
    snapshot.text +
    "\n```"
  );
}

/**
 * Busca el primer bloque ```...``` en la respuesta y devuelve su
 * contenido, descartando una posible primera línea de tag de lenguaje
 * (p.ej. "python"). Devuelve null si no encuentra ningún bloque — el
 * modelo no respetó el formato pedido, hay que manejarlo explícitamente
 * en vez de asumir que la respuesta siempre viene bien formada.
 */
export function extractCodeBlock(responseText: string): string | null {
  const match = responseText.match(/```([^\n]*)\n([\s\S]*?)```/);
  if (!match) {
    return null;
  }
  return match[2].replace(/\n$/, "");
}

export interface BraceBalance {
  isBalanced: boolean;
  detail: string;
}

const BRACKET_PAIRS: [string, string][] = [
  ["{", "}"],
  ["(", ")"],
  ["[", "]"],
];

/**
 * Cuenta cuántas veces aparece cada símbolo de apertura/cierre en el
 * texto — bug real encontrado en uso: seleccionar un fragmento que abre
 * llaves sin cerrarlas dentro de la propia selección (p.ej. una clase
 * entera cortada antes de sus llaves de cierre, porque cierran mucho
 * más abajo en el archivo) hace que kal "complete" el fragmento con sus
 * propias llaves de cierre — que después chocan con las reales del
 * archivo y rompen el balance al aplicar el reemplazo.
 *
 * Es un conteo simple (no un parser real): no distingue llaves dentro
 * de strings/comentarios, así que puede dar falsos positivos — por eso
 * se usa solo para una ADVERTENCIA que el usuario puede ignorar, nunca
 * para bloquear el flujo.
 */
export function checkBraceBalance(text: string): BraceBalance {
  const mismatches: string[] = [];
  for (const [open, close] of BRACKET_PAIRS) {
    const opens = text.split(open).length - 1;
    const closes = text.split(close).length - 1;
    if (opens !== closes) {
      mismatches.push(`${opens} '${open}' vs ${closes} '${close}'`);
    }
  }
  return { isBalanced: mismatches.length === 0, detail: mismatches.join(", ") };
}
