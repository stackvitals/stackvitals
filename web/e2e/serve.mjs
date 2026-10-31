// Serves the committed build (src/stackvitals/web) for the browser tests, never cached. Usage: node e2e/serve.mjs <port>
import { createReadStream, statSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../src/stackvitals/web");
const port = Number(process.argv[2] || process.env.SV_E2E_PORT || 4173);
const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8", ".md": "text/markdown; charset=utf-8",
  ".txt": "text/plain; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
  ".woff2": "font/woff2", ".csv": "text/csv; charset=utf-8",
};

createServer((req, res) => {
  const path = decodeURIComponent(new URL(req.url || "/", "http://x").pathname);
  let file = normalize(join(root, path));
  // Never leave the build folder.
  if (file !== root && !file.startsWith(root + sep)) { res.writeHead(403).end(); return; }
  // A 404 has no body: the app may not read it, and an unread body keeps the request open.
  try { if (statSync(file).isDirectory()) file = join(file, "index.html"); statSync(file); } catch { res.writeHead(404, { "Cache-Control": "no-store", "Content-Length": "0" }).end(); return; }
  res.writeHead(200, { "Content-Type": TYPES[extname(file)] || "application/octet-stream", "Cache-Control": "no-store" });
  createReadStream(file).pipe(res);
}).listen(port, "127.0.0.1", () => console.log(`serving ${root} on http://127.0.0.1:${port}`));
