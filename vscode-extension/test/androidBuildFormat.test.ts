import assert from "node:assert/strict";
import { test } from "node:test";
import { ChatResult, ChatStep } from "../src/kalClient";
import { findAndroidBuildRequestArtifact, parseAdbDevices, truncateProcessOutput } from "../src/androidBuildFormat";

function _result(steps: ChatStep[]): ChatResult {
  return { session_id: "s", goal: "g", final_answer: "", status: "success", plan: [], steps };
}

function _androidBuildRequestStep(requestId: string): ChatStep {
  return {
    tool: "android_build_and_screenshot",
    arguments: {},
    observation: "",
    artifact: { modality: "android_build_request", request_id: requestId },
  };
}

test("findAndroidBuildRequestArtifact devuelve undefined si no hay ningún step con ese modality", () => {
  const result = _result([{ tool: "run_code", arguments: {}, observation: "ok", artifact: null }]);
  assert.equal(findAndroidBuildRequestArtifact(result), undefined);
});

test("findAndroidBuildRequestArtifact devuelve el pedido cuando hay uno solo", () => {
  const result = _result([_androidBuildRequestStep("req-1")]);
  assert.equal(findAndroidBuildRequestArtifact(result)!.request_id, "req-1");
});

test("findAndroidBuildRequestArtifact devuelve el ÚLTIMO pedido, no el primero", () => {
  const result = _result([
    _androidBuildRequestStep("req-1"),
    { tool: "run_code", arguments: {}, observation: "ok", artifact: null },
    _androidBuildRequestStep("req-2"),
  ]);
  assert.equal(findAndroidBuildRequestArtifact(result)!.request_id, "req-2");
});

test("truncateProcessOutput deja intacto un output corto", () => {
  assert.equal(truncateProcessOutput("  BUILD SUCCESSFUL  "), "BUILD SUCCESSFUL");
});

test("truncateProcessOutput trunca un output enorme, mostrando el FINAL (donde suele estar el error real)", () => {
  const hugeOutput = "línea de log\n".repeat(2000) + "FAILURE: Build failed with an exception.";
  const truncated = truncateProcessOutput(hugeOutput);
  assert.match(truncated, /truncad/);
  assert.match(truncated, /FAILURE: Build failed/);
  assert.ok(truncated.length < hugeOutput.length);
});

test("parseAdbDevices interpreta un dispositivo conectado por USB", () => {
  const raw = "List of devices attached\nR58N123ABCD\tdevice usb:1-1 product:panther model:Pixel_7\n";
  const devices = parseAdbDevices(raw);
  assert.equal(devices.length, 1);
  assert.equal(devices[0].serial, "R58N123ABCD");
  assert.equal(devices[0].state, "device");
});

test("parseAdbDevices interpreta un dispositivo conectado por WiFi (serial ip:puerto)", () => {
  const raw = "List of devices attached\n192.168.1.50:5555\tdevice product:panther model:Pixel_7\n";
  const devices = parseAdbDevices(raw);
  assert.equal(devices.length, 1);
  assert.equal(devices[0].serial, "192.168.1.50:5555");
});

test("parseAdbDevices detecta un dispositivo sin autorizar (falta aceptar el diálogo en el teléfono)", () => {
  const raw = "List of devices attached\nR58N123ABCD\tunauthorized\n";
  const devices = parseAdbDevices(raw);
  assert.equal(devices[0].state, "unauthorized");
});

test("parseAdbDevices devuelve vacío sin ningún dispositivo conectado", () => {
  assert.deepEqual(parseAdbDevices("List of devices attached\n\n"), []);
});

test("parseAdbDevices devuelve varios dispositivos si hay más de uno conectado", () => {
  const raw = "List of devices attached\nR58N123ABCD\tdevice\n192.168.1.50:5555\tdevice\n";
  assert.equal(parseAdbDevices(raw).length, 2);
});
