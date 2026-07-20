import assert from "node:assert/strict";
import { test } from "node:test";
import { ChatResult, ChatStep } from "../src/kalClient";
import { buildFileContentGoal, buildFileErrorGoal, findWorkspaceFileRequestArtifact } from "../src/readWorkspaceFileFormat";

function _result(steps: ChatStep[]): ChatResult {
  return { session_id: "s", goal: "g", final_answer: "", status: "success", plan: [], steps };
}

function _workspaceFileRequestStep(requestId: string, path: string): ChatStep {
  return {
    tool: "read_workspace_file",
    arguments: { path },
    observation: "",
    artifact: { modality: "workspace_file_request", request_id: requestId, path },
  };
}

test("findWorkspaceFileRequestArtifact devuelve undefined si no hay ningún step con ese modality", () => {
  const result = _result([{ tool: "run_code", arguments: {}, observation: "ok", artifact: null }]);
  assert.equal(findWorkspaceFileRequestArtifact(result), undefined);
});

test("findWorkspaceFileRequestArtifact devuelve el pedido cuando hay uno solo", () => {
  const result = _result([_workspaceFileRequestStep("req-1", "restaurante-web/menu.html")]);
  const artifact = findWorkspaceFileRequestArtifact(result);
  assert.equal(artifact!.request_id, "req-1");
  assert.equal(artifact!.path, "restaurante-web/menu.html");
});

test("findWorkspaceFileRequestArtifact devuelve el ÚLTIMO pedido, no el primero", () => {
  const result = _result([
    _workspaceFileRequestStep("req-1", "a.html"),
    { tool: "browser", arguments: {}, observation: "ok", artifact: null },
    _workspaceFileRequestStep("req-2", "b.html"),
  ]);
  assert.equal(findWorkspaceFileRequestArtifact(result)!.path, "b.html");
});

test("buildFileContentGoal incluye la ruta y el contenido real, marcado como respuesta a un pedido anterior", () => {
  const goal = buildFileContentGoal("restaurante-web/menu.html", "<h1>Menú</h1>");
  assert.match(goal, /restaurante-web\/menu\.html/);
  assert.match(goal, /<h1>Menú<\/h1>/);
  assert.match(goal, /NO es un mensaje nuevo/);
});

test("buildFileContentGoal trunca archivos enormes en vez de mandarlos completos", () => {
  const hugeContent = "x".repeat(30_000);
  const goal = buildFileContentGoal("archivo-grande.txt", hugeContent);
  assert.match(goal, /truncado/);
  assert.ok(goal.length < hugeContent.length + 1000);
});

test("buildFileErrorGoal explica el motivo y le pide al modelo que no invente el contenido", () => {
  const goal = buildFileErrorGoal("no-existe.txt", "no se pudo leer el archivo (ENOENT)");
  assert.match(goal, /no-existe\.txt/);
  assert.match(goal, /ENOENT/);
  assert.match(goal, /no inventes/i);
});
