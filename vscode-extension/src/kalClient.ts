/**
 * Cliente HTTP hacia el backend de kal (agent_core/orchestrator.py,
 * FastAPI). Mismo contrato que ya consume frontend/app.js: POST /chat
 * con {goal, model, use_planner} -> {final_answer, status, plan, steps}.
 *
 * `fetchFn` es inyectable (por defecto el fetch global de Node 22+) para
 * poder testear sin red real — mismo patrón de DI que ya usa el backend
 * Python (ver tool_integration/adapters/browser.py::BrowserTool(driver=...)).
 */

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

  async chat(goal: string, model?: string, sessionId?: string): Promise<ChatResult> {
    let response: Response;
    try {
      response = await this.fetchFn(`${this.baseUrl}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal, model: model || null, session_id: sessionId || null }),
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
