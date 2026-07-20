import assert from "node:assert/strict";
import * as http from "node:http";
import { test } from "node:test";
import { nodeHttpFetch } from "../src/nodeHttpFetch";

/** Levanta un servidor HTTP real en un puerto libre, para probar nodeHttpFetch contra red real (loopback). */
function withServer(handler: http.RequestListener, run: (url: string) => Promise<void>): Promise<void> {
  return new Promise((resolve, reject) => {
    const server = http.createServer(handler);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      run(`http://127.0.0.1:${port}`)
        .then(() => server.close(() => resolve()))
        .catch((e) => server.close(() => reject(e)));
    });
  });
}

test("nodeHttpFetch hace un GET real y devuelve status/body", () =>
  withServer(
    (_req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true }));
    },
    async (url) => {
      const response = await nodeHttpFetch(url);
      assert.equal(response.status, 200);
      assert.equal(response.ok, true);
      assert.deepEqual(await response.json(), { ok: true });
    }
  ));

test("nodeHttpFetch manda el body de un POST y el método correctos", () =>
  withServer(
    (req, res) => {
      let received = "";
      req.on("data", (chunk) => (received += chunk));
      req.on("end", () => {
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ method: req.method, received }));
      });
    },
    async (url) => {
      const response = await nodeHttpFetch(url, { method: "POST", body: JSON.stringify({ goal: "hola" }) });
      const body = (await response.json()) as { method: string; received: string };
      assert.equal(body.method, "POST");
      assert.equal(body.received, JSON.stringify({ goal: "hola" }));
    }
  ));

test("nodeHttpFetch refleja un status de error sin lanzar (response.ok=false)", () =>
  withServer(
    (_req, res) => {
      res.writeHead(503);
      res.end("no disponible");
    },
    async (url) => {
      const response = await nodeHttpFetch(url);
      assert.equal(response.status, 503);
      assert.equal(response.ok, false);
      assert.equal(await response.text(), "no disponible");
    }
  ));

test("nodeHttpFetch rechaza la promesa si no hay nada escuchando en el puerto", async () => {
  await assert.rejects(() => nodeHttpFetch("http://127.0.0.1:1"));
});

test("nodeHttpFetch respeta un timeoutMs corto en vez de esperar para siempre", () =>
  withServer(
    (_req, res) => {
      // Nunca responde dentro de la ventana del test — server.close()
      // en withServer espera a que la conexión termine, así que hay
      // que cerrar la respuesta igual (aunque después del timeout del
      // cliente, que es lo que se está probando acá).
      setTimeout(() => res.end("tarde"), 500);
    },
    async (url) => {
      await assert.rejects(() => nodeHttpFetch(url, {}, 100), /Tiempo de espera agotado/);
    }
  ));
