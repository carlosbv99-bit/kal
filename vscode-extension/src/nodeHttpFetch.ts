/**
 * Reemplazo del fetch() global de Node para las llamadas HTTP de
 * KalClient — mismo contrato `(url, init) => Promise<Response>` que el
 * fetch() nativo, así que KalClient y sus tests (que inyectan un
 * fetchFn falso con esta misma forma) no necesitan cambiar nada.
 *
 * BUG REAL ENCONTRADO EN USO (2026-07-20): el fetch() global de Node
 * (implementado con undici) tiene un tope fijo de ~300s (5 min) para
 * recibir la respuesta completa del servidor (headersTimeout/
 * bodyTimeout=300000ms por defecto), sin forma de extenderlo sin un
 * Agent/Dispatcher a medida — que a su vez requiere el paquete npm
 * 'undici' como dependencia REAL en tiempo de ejecución, pero
 * .vscodeignore excluye node_modules/** del .vsix empaquetado (no
 * estaría disponible al usuario sin además cambiar el empaquetado a
 * un bundler). Confirmado con una reproducción real en esta máquina:
 * un servidor local deliberadamente lento hizo que fetch() tirara
 * "TypeError: fetch failed" (causa: "Headers Timeout Error") a los
 * 300.8s exactos.
 *
 * Un pedido real del usuario ("Aplica la barra de menú...") disparó
 * esto de verdad: el modelo local (CPU, sin tool-calling nativo, ver
 * agent_core/llm/agent_loop.py) reintentó varias veces una herramienta
 * ya rechazada por el tope de repeticiones antes de converger, y el
 * pedido encadenado de read_workspace_file (ver readWorkspaceFile.ts)
 * superó los 5 minutos — el backend seguía trabajando de verdad
 * (confirmado con logs/agent.log + los logs del propio Ollama), pero
 * la extensión ya había mostrado "no se pudo conectar" y nadie
 * esperaba la respuesta cuando por fin llegó.
 *
 * node:http/node:https no tienen ningún tope de tiempo salvo el que se
 * pida explícitamente vía la opción `timeout` — por eso esta
 * implementación evita fetch() por completo para el uso real (no solo
 * en los tests).
 */
import * as http from "node:http";
import * as https from "node:https";

// Generoso a propósito: un pedido real puede encadenar varios pasos de
// un modelo local lento — mejor esperar de más que mostrar "no se pudo
// conectar" mientras el backend sigue trabajando de verdad.
const _DEFAULT_TIMEOUT_MS = 20 * 60 * 1000;

// `input` acepta la misma unión que el fetch() global (string | URL |
// Request) para que nodeHttpFetch pueda usarse como reemplazo directo
// del tipo FetchFn en kalClient.ts — en la práctica esta extensión
// siempre llama con un string simple, nunca con un Request.
export function nodeHttpFetch(input: string | URL | Request, init: RequestInit = {}, timeoutMs: number = _DEFAULT_TIMEOUT_MS): Promise<Response> {
  return new Promise((resolve, reject) => {
    const url = input instanceof Request ? input.url : input.toString();
    const target = new URL(url);
    const transport = target.protocol === "https:" ? https : http;
    const method = init.method ?? "GET";
    const headers = (init.headers as Record<string, string>) ?? {};
    const body = typeof init.body === "string" ? init.body : undefined;

    const req = transport.request(target, { method, headers, timeout: timeoutMs }, (res) => {
      const chunks: Buffer[] = [];
      res.on("data", (chunk: Buffer) => chunks.push(chunk));
      res.on("end", () => {
        const responseHeaders: [string, string][] = Object.entries(res.headers)
          .filter((entry): entry is [string, string] => typeof entry[1] === "string");
        resolve(new Response(Buffer.concat(chunks), { status: res.statusCode ?? 0, headers: responseHeaders }));
      });
    });

    req.on("timeout", () => req.destroy(new Error(`Tiempo de espera agotado tras ${timeoutMs}ms sin respuesta de ${url}`)));
    req.on("error", reject);
    if (body !== undefined) {
      req.write(body);
    }
    req.end();
  });
}
