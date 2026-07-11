import assert from "node:assert/strict";
import { test } from "node:test";
import { formatEditorContext } from "../src/editorContextFormat";

test("formatEditorContext etiqueta una selección correctamente", () => {
  const text = formatEditorContext({
    relativePath: "src/foo.py",
    languageId: "python",
    text: "def foo():\n    pass\n",
    isSelection: true,
  });

  assert.match(text, /selección de src\/foo\.py/);
  assert.match(text, /lenguaje python/);
  assert.match(text, /```python\ndef foo/);
});

test("formatEditorContext etiqueta el archivo completo cuando no hay selección", () => {
  const text = formatEditorContext({
    relativePath: "src/bar.ts",
    languageId: "typescript",
    text: "export const x = 1;",
    isSelection: false,
  });

  assert.match(text, /archivo completo de src\/bar\.ts/);
});

test("formatEditorContext cierra el bloque de código", () => {
  const text = formatEditorContext({
    relativePath: "a.js",
    languageId: "javascript",
    text: "console.log(1);",
    isSelection: false,
  });

  assert.ok(text.trim().endsWith("```"));
});
