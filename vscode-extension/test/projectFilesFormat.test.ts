import assert from "node:assert/strict";
import * as path from "path";
import { test } from "node:test";
import { ChatResult, ChatStep } from "../src/kalClient";
import { findFirstInvalidPath, findProjectFilesArtifact, isWithinRoot, validateRelativeFilePath } from "../src/projectFilesFormat";

test("validateRelativeFilePath acepta una ruta relativa simple", () => {
  assert.equal(validateRelativeFilePath("index.html"), null);
});

test("validateRelativeFilePath acepta una ruta relativa con subcarpetas", () => {
  assert.equal(validateRelativeFilePath("css/estilos.css"), null);
});

test("validateRelativeFilePath rechaza una ruta absoluta unix", () => {
  const error = validateRelativeFilePath("/etc/passwd");
  assert.ok(error);
  assert.match(error!, /absoluta/);
});

test("validateRelativeFilePath rechaza una ruta absoluta windows", () => {
  const error = validateRelativeFilePath("C:\\Windows\\System32\\algo.dll");
  assert.ok(error);
  assert.match(error!, /absoluta/);
});

test("validateRelativeFilePath rechaza un path que escapa con ..", () => {
  const error = validateRelativeFilePath("../../etc/passwd");
  assert.ok(error);
  assert.match(error!, /\.\./);
});

test("validateRelativeFilePath rechaza una ruta vacía", () => {
  const error = validateRelativeFilePath("");
  assert.ok(error);
  assert.match(error!, /vacía/);
});

test("findFirstInvalidPath devuelve null si todos los archivos son válidos", () => {
  const error = findFirstInvalidPath([
    { path: "index.html", content: "" },
    { path: "css/estilos.css", content: "" },
  ]);
  assert.equal(error, null);
});

test("findFirstInvalidPath devuelve el error del primer archivo inválido", () => {
  const error = findFirstInvalidPath([
    { path: "index.html", content: "" },
    { path: "../fuera.txt", content: "" },
  ]);
  assert.ok(error);
  assert.match(error!, /\.\./);
});

function _result(steps: ChatStep[]): ChatResult {
  return { session_id: "s", goal: "g", final_answer: "", status: "success", plan: [], steps };
}

function _projectFilesStep(requestId: string): ChatStep {
  return {
    tool: "propose_project_files",
    arguments: {},
    observation: "",
    artifact: { modality: "project_files", request_id: requestId, files: [{ path: "index.html", content: "x" }] },
  };
}

test("findProjectFilesArtifact devuelve undefined si no hay ningún step con ese modality", () => {
  const result = _result([{ tool: "run_code", arguments: {}, observation: "ok", artifact: null }]);
  assert.equal(findProjectFilesArtifact(result), undefined);
});

test("findProjectFilesArtifact devuelve la propuesta cuando hay una sola", () => {
  const result = _result([_projectFilesStep("req-1")]);
  assert.equal(findProjectFilesArtifact(result)!.request_id, "req-1");
});

test("findProjectFilesArtifact devuelve la ÚLTIMA propuesta, no la primera", () => {
  // BUG REAL: el modelo llamó a propose_project_files 3 veces en el
  // mismo turno (revisando su propio intento) — antes de este fix se
  // mostraba req-1 (el borrador más viejo), descartando en silencio
  // los dos intentos posteriores, presumiblemente más completos.
  const result = _result([
    _projectFilesStep("req-1"),
    { tool: "browser", arguments: {}, observation: "ok", artifact: null },
    _projectFilesStep("req-2"),
    _projectFilesStep("req-3"),
  ]);
  assert.equal(findProjectFilesArtifact(result)!.request_id, "req-3");
});

test("isWithinRoot acepta el propio root", () => {
  assert.ok(isWithinRoot("/home/user/proyecto", "/home/user/proyecto"));
});

test("isWithinRoot acepta un archivo dentro de una subcarpeta", () => {
  assert.ok(isWithinRoot("/home/user/proyecto", path.join("/home/user/proyecto", "css", "estilos.css")));
});

test("isWithinRoot rechaza una ruta fuera del root", () => {
  assert.equal(isWithinRoot("/home/user/proyecto", "/home/user/otro-proyecto/index.html"), false);
});

test("isWithinRoot rechaza un directorio hermano con el mismo prefijo de nombre", () => {
  // 'proyecto-2' empieza con el mismo texto que 'proyecto' pero NO es un
  // subdirectorio suyo — un chequeo ingenuo con startsWith("/home/user/proyecto")
  // (sin el separador de path) lo aceptaría por error.
  assert.equal(isWithinRoot("/home/user/proyecto", "/home/user/proyecto-2/index.html"), false);
});
