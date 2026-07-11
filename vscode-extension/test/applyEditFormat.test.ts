import assert from "node:assert/strict";
import { test } from "node:test";
import { buildEditGoal, checkBraceBalance, extractCodeBlock } from "../src/applyEditFormat";

test("buildEditGoal incluye la instrucción y el código de la selección", () => {
  const goal = buildEditGoal(
    {
      relativePath: "src/foo.py",
      languageId: "python",
      text: "def foo():\n    pass\n",
      isSelection: true,
    },
    "agregá manejo de errores"
  );

  assert.match(goal, /agregá manejo de errores/);
  assert.match(goal, /selección de src\/foo\.py/);
  assert.match(goal, /```python\ndef foo/);
});

test("buildEditGoal pide explícitamente código sin explicación", () => {
  const goal = buildEditGoal(
    { relativePath: "a.ts", languageId: "typescript", text: "const x = 1;", isSelection: false },
    "convertí x en let"
  );

  assert.match(goal, /ÚNICAMENTE con el código/);
  assert.match(goal, /No agregues explicación/);
});

test("extractCodeBlock extrae el contenido de un bloque con tag de lenguaje", () => {
  const response = "Acá está:\n```python\nprint('hola')\n```\n";
  assert.equal(extractCodeBlock(response), "print('hola')");
});

test("extractCodeBlock extrae el contenido de un bloque sin tag de lenguaje", () => {
  const response = "```\nconst x = 1;\n```";
  assert.equal(extractCodeBlock(response), "const x = 1;");
});

test("extractCodeBlock toma el primer bloque si hay varios", () => {
  const response = "```python\nprimero()\n```\ny después:\n```python\nsegundo()\n```";
  assert.equal(extractCodeBlock(response), "primero()");
});

test("extractCodeBlock devuelve null si no hay ningún bloque de código", () => {
  const response = "Este código suma dos números y no necesita cambios.";
  assert.equal(extractCodeBlock(response), null);
});

test("extractCodeBlock preserva código multilínea con indentación", () => {
  const response = "```python\ndef foo():\n    if True:\n        pass\n```";
  assert.equal(extractCodeBlock(response), "def foo():\n    if True:\n        pass");
});

test("checkBraceBalance acepta un bloque autocontenido (lambda completo)", () => {
  const result = checkBraceBalance(
    "Thread.setDefaultUncaughtExceptionHandler { _, exception ->\n    // comentario\n}"
  );
  assert.equal(result.isBalanced, true);
});

test("checkBraceBalance detecta una clase cortada antes de sus llaves de cierre", () => {
  // Bug real: exactamente este caso (class + onCreate + lambda abiertos,
  // ninguno cerrado dentro de la selección) rompió un archivo Kotlin real.
  const result = checkBraceBalance(
    "class MainActivity : ComponentActivity() {\n" +
      "    override fun onCreate(savedInstanceState: Bundle?) {\n" +
      "        Thread.setDefaultUncaughtExceptionHandler { _, exception ->\n" +
      "            // comentario\n"
  );
  assert.equal(result.isBalanced, false);
  assert.match(result.detail, /3 '\{' vs 0 '\}'/);
});

test("checkBraceBalance detecta paréntesis desbalanceados aunque las llaves estén bien", () => {
  const result = checkBraceBalance("foo(bar { baz() }");
  assert.equal(result.isBalanced, false);
  assert.match(result.detail, /'\(' vs/);
});

test("checkBraceBalance acepta texto vacío", () => {
  assert.equal(checkBraceBalance("").isBalanced, true);
});
