import assert from "node:assert/strict";
import { test } from "node:test";
import { findFirstInvalidPath, validateRelativeFilePath } from "../src/projectFilesFormat";

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
