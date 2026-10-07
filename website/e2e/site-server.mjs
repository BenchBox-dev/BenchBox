import { createReadStream, existsSync, readdirSync, statSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";

const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".wasm": "application/wasm",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".txt": "text/plain; charset=utf-8",
  ".xml": "application/xml",
};

function resolveFile(urlPath, siteDir, dataDir) {
  const clean = path.normalize(decodeURIComponent(urlPath)).replace(/^(\.\.[/\\])+/, "");
  const underData = urlPath.startsWith("/results/data/");
  const root = underData ? dataDir : siteDir;
  const relative = underData ? clean.slice("/results/data/".length) : clean;
  const candidates = urlPath.endsWith("/") ? [path.join(relative, "index.html")] : [relative, `${relative}.html`, path.join(relative, "index.html")];
  for (const candidate of candidates) {
    const full = path.join(root, candidate);
    if (full.startsWith(root) && existsSync(full) && statSync(full).isFile()) return full;
  }
  return undefined;
}

export function startSiteServer(siteDir, dataDir) {
  const served = [];
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://localhost");
    const file = resolveFile(url.pathname, siteDir, dataDir);
    const target = file ?? path.join(siteDir, "404.html");
    const status = file ? 200 : 404;
    const size = statSync(target).size;
    const headers = { "content-type": types[path.extname(target)] ?? "application/octet-stream", "accept-ranges": "bytes" };
    const range = /^bytes=(\d+)-(\d+)?$/.exec(request.headers.range ?? "");
    if (file && range) {
      const start = Number(range[1]);
      const end = range[2] ? Math.min(Number(range[2]), size - 1) : size - 1;
      response.writeHead(206, { ...headers, "content-range": `bytes ${start}-${end}/${size}`, "content-length": String(end - start + 1) });
      served.push({ path: url.pathname, status: 206, bytes: end - start + 1 });
      createReadStream(target, { start, end }).pipe(response);
      return;
    }
    response.writeHead(status, { ...headers, "content-length": String(size) });
    served.push({ path: url.pathname, status, bytes: size });
    createReadStream(target).pipe(response);
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({ server, served })));
}

export function firstTagRoute(siteDir) {
  const directory = path.join(siteDir, "blog", "tag");
  const names = existsSync(directory) ? readdirSync(directory).filter((name) => name.endsWith(".html")).sort() : [];
  if (names.length === 0) throw new Error(`no tag page was built under ${directory}`);
  return `/blog/tag/${names[0]}`;
}
