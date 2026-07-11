/**
 * Cliente HTTP hacia el backend de kal (agent_core/orchestrator.py,
 * FastAPI). Mismo contrato que ya consume frontend/app.js: POST /chat
 * con {goal, model, use_planner} -> {final_answer, status, plan, steps}.
 *
 * `fetchFn` es inyectable (por defecto el fetch global de Node 22+) para
 * poder testear sin red real — mismo patrón de DI que ya usa el backend
 * Python (ver tool_integration/adapters/browser.py::BrowserTool(driver=...)).
 *
 * `editor_context`: señal CRUDA del editor (ver
 * agent_core/context_service.py) — este cliente nunca la formatea a
 * texto, solo la reenvía tal cual. Decidir cómo se ve en el prompt
 * final es responsabilidad del backend, no de esta extensión.
 */
import { EditorSnapshot } from "./editorContextFormat";

export interface ChatStep {
  tool: string;
  arguments: Record<string, unknown>;
  observation: string;
}

export interface ChatResult {
  session_id: string;
  goal: string;
  final_answer: string;
  status: string;
  plan: string[];
  steps: ChatStep[];
}

export type FetchFn = typeof fetch;

export class KalClient {
  constructor(
    private readonly baseUrl: string,
    private readonly fetchFn: FetchFn = fetch
  ) {}

  async chat(goal: string, model?: string, sessionId?: string, editorContext?: EditorSnapshot): Promise<ChatResult> {
    let response: Response;
    try {
      response = await this.fetchFn(`${this.baseUrl}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          goal,
          model: model || null,
          session_id: sessionId || null,
          editor_context: editorContext
            ? {
                relative_path: editorContext.relativePath,
                language_id: editorContext.languageId,
                text: editorContext.text,
                is_selection: editorContext.isSelection,
              }
            : null,
        }),
      });
    } catch (e) {
      throw new Error(
        `No se pudo conectar con kal en ${this.baseUrl} — ¿está corriendo ./scripts/run_kal.sh? (${e})`
      );
    }

    if (!response.ok) {
      const detail = await response.text().catch(() => "");
      throw new Error(`Kal respondió ${response.status}: ${detail}`);
    }

    return (await response.json()) as ChatResult;
  }

  async health(): Promise<boolean> {
    try {
      const response = await this.fetchFn(`${this.baseUrl}/health`);
      return response.ok;
    } catch {
      return false;
    }
  }
}
