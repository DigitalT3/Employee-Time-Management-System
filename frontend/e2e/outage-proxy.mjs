/**
 * Test-only pass-through proxy that sits between the production preview server and the FastAPI
 * backend so that browser specs can create a *real* backend outage.
 *
 * Why: Playwright's `context.setOffline()` does not affect requests made by a service worker, and
 * the app routes every /api call through the worker (NetworkOnly). Cutting this proxy instead makes
 * those requests fail exactly as they would when a tablet loses its network.
 *
 * Control endpoints (not under /api, so they never collide with application routes):
 *   POST /__control/down   - drop every following request at the socket level
 *   POST /__control/up     - forward requests again
 *   GET  /__control/status - readiness probe, reports the current state
 *
 * Configuration (environment): ETMS_UPSTREAM (default http://127.0.0.1:8000),
 * ETMS_OUTAGE_PROXY_PORT (default 8100).
 */
import http from "node:http";

const upstream = new URL(process.env.ETMS_UPSTREAM ?? "http://127.0.0.1:8000");
const port = Number(process.env.ETMS_OUTAGE_PROXY_PORT ?? 8100);
let down = false;

const server = http.createServer((req, res) => {
  if (req.url?.startsWith("/__control/")) {
    if (req.url === "/__control/down") down = true;
    if (req.url === "/__control/up") down = false;
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ down }));
    return;
  }
  if (down) {
    // Reset the connection: the caller sees a network-level failure, not an HTTP answer.
    req.socket.destroy();
    return;
  }
  const forwarded = http.request(
    { host: upstream.hostname, port: upstream.port, path: req.url, method: req.method, headers: req.headers },
    (response) => {
      res.writeHead(response.statusCode ?? 502, response.headers);
      response.pipe(res);
    },
  );
  forwarded.on("error", () => {
    if (!res.headersSent) res.writeHead(502);
    res.end();
  });
  req.pipe(forwarded);
});

server.listen(port, "127.0.0.1");
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
