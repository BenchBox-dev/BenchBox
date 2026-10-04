import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "dist");
const port = Number(process.env.PORT ?? 4330);

const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".wasm": "application/wasm",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".xml": "application/xml",
  ".duckdb": "application/octet-stream",
  ".pf_meta": "application/octet-stream",
  ".pf_fragment": "application/octet-stream",
  ".pf_index": "application/octet-stream",
  ".pagefind": "application/octet-stream",
};

function resolve(urlPath) {
  const clean = path.normalize(decodeURIComponent(urlPath)).replace(/^(\.\.[/\\])+/, "");
  const candidates = [clean, path.join(clean, "index.html"), `${clean}.html`];
  for (const candidate of candidates) {
    const full = path.join(root, candidate);
    if (full.startsWith(root) && existsSync(full) && statSync(full).isFile()) return full;
  }
  return undefined;
}

createServer((request, response) => {
  const url = new URL(request.url ?? "/", "http://localhost");
  const file = resolve(url.pathname);
  const target = file ?? path.join(root, "404.html");
  response.writeHead(file ? 200 : 404, {
    "content-type": types[path.extname(target)] ?? "application/octet-stream",
  });
  createReadStream(target).pipe(response);
}).listen(port, "127.0.0.1");
