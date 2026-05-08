#!/usr/bin/env node
/**
 * Static server used by the Playwright `webServer` block.
 *
 * Serves the built explorer from `dist/` under `/results/` while routing
 * `/results/data/` to the requested fixture directory. The default remains
 * `test-fixtures/.generated/data/`; UAT can set E2E_FIXTURE_DIR for a
 * log-dir-scoped data mount. The curated corpus under `public/data/` is never
 * touched - that is the architecture decision recorded in
 * `docs/development/browser-test-architecture.md` (Decision 2).
 *
 * The server also sets `Accept-Ranges: bytes` and honors a single `Range`
 * header so Playwright-level tests can verify the RG-2 range-read contract
 * that the browser DuckDB-WASM `ATTACH` depends on.
 */

import { createReadStream, statSync, existsSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize, resolve } from "node:path";
import { parseArgs } from "node:util";
import { fileURLToPath } from "node:url";

const { values } = parseArgs({
  options: {
    port: { type: "string", default: process.env.E2E_PORT ?? "4319" },
    host: { type: "string", default: process.env.E2E_HOST ?? "127.0.0.1" },
    "dist-dir": { type: "string" },
    "fixture-dir": { type: "string" },
  },
});

const here = fileURLToPath(new URL(".", import.meta.url));
const projectRoot = resolve(here, "..");
const distDir = resolve(values["dist-dir"] ?? join(projectRoot, "dist"));
const fixtureDir = resolve(
  values["fixture-dir"] ??
    process.env.E2E_FIXTURE_DIR ??
    join(projectRoot, "test-fixtures", ".generated", "data"),
);

if (!existsSync(distDir)) {
  console.error(
    `[serve-browser-tests] dist dir not found: ${distDir}\n` +
      `Run \`npm run build\` inside results-explorer/ before starting the e2e server.`,
  );
  process.exit(2);
}
if (!existsSync(fixtureDir)) {
  console.error(
    `[serve-browser-tests] fixture dir not found: ${fixtureDir}\n` +
      `Run \`npm run test:e2e:fixtures\` inside results-explorer/ to generate the corpus.`,
  );
  process.exit(2);
}

const MIME = new Map([
  [".html", "text/html; charset=utf-8"],
  [".js", "application/javascript; charset=utf-8"],
  [".mjs", "application/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".svg", "image/svg+xml"],
  [".png", "image/png"],
  [".ico", "image/x-icon"],
  [".wasm", "application/wasm"],
  [".duckdb", "application/octet-stream"],
  [".map", "application/json"],
  [".txt", "text/plain; charset=utf-8"],
]);

const mimeFor = (path) => MIME.get(extname(path).toLowerCase()) ?? "application/octet-stream";

const safeJoin = (root, relPath) => {
  const candidate = normalize(join(root, relPath));
  if (!candidate.startsWith(root)) return null;
  return candidate;
};

const writeNotFound = (res, reason) => {
  res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
  res.end(`not found: ${reason}\n`);
};

const sendFile = (req, res, absPath, logPath) => {
  let stat;
  try {
    stat = statSync(absPath);
  } catch {
    writeNotFound(res, absPath);
    return;
  }
  if (stat.isDirectory()) {
    const indexPath = join(absPath, "index.html");
    if (existsSync(indexPath)) return sendFile(req, res, indexPath, logPath);
    writeNotFound(res, absPath);
    return;
  }

  const headers = {
    "Content-Type": mimeFor(absPath),
    "Accept-Ranges": "bytes",
    // DuckDB-WASM needs SharedArrayBuffer; production headers mirror these.
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "cross-origin",
    "Cache-Control": "no-store",
  };

  const method = req.method ?? "GET";
  const range = req.headers.range;
  if (range) {
    const match = /^bytes=(\d+)-(\d+)?$/.exec(range);
    if (match) {
      const start = Number(match[1]);
      const end = match[2] ? Number(match[2]) : stat.size - 1;
      if (start > end || end >= stat.size) {
        res.writeHead(416, {
          "Content-Range": `bytes */${stat.size}`,
          "Accept-Ranges": "bytes",
        });
        res.end();
        return;
      }
      const contentLength = end - start + 1;
      res.writeHead(206, {
        ...headers,
        "Content-Range": `bytes ${start}-${end}/${stat.size}`,
        "Content-Length": String(contentLength),
      });
      if (logPath) {
        transferLog.push({
          path: logPath,
          method,
          status: 206,
          hasRange: true,
          contentLength: method === "HEAD" ? 0 : contentLength,
        });
      }
      if (method === "HEAD") {
        res.end();
      } else {
        createReadStream(absPath, { start, end }).pipe(res);
      }
      return;
    }
  }

  res.writeHead(200, { ...headers, "Content-Length": String(stat.size) });
  if (logPath) {
    transferLog.push({
      path: logPath,
      method,
      status: 200,
      hasRange: false,
      contentLength: method === "HEAD" ? 0 : stat.size,
    });
  }
  if (method === "HEAD") {
    res.end();
  } else {
    createReadStream(absPath).pipe(res);
  }
};

// Any path whose extension *isn't* a known static asset is treated as an
// SPA route and falls back to index.html. Result IDs in URLs can contain
// dots (e.g. `tpch-duckdb-sf0.01-...`) so a naive `extname() === ""` check
// sends those to 404. Matching against the MIME whitelist keeps asset
// misses as 404 while letting SPA routes resolve.

// Per-path transfer log so Playwright can assert range-read behaviour that
// originates inside the DuckDB-WASM worker - sync XHR from a dedicated
// worker is not reliably captured by `page.on("response")`, so we account
// server-side instead. Cleared on `POST /__test/transfers/reset`.
const transferLog = [];

const handler = (req, res) => {
  // Strip query string but keep the pathname for routing.
  const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
  const pathname = decodeURIComponent(url.pathname);

  // Test-only transfer-log endpoints. Not exposed in production builds -
  // this server is only used by the e2e harness.
  if (pathname === "/__test/transfers") {
    res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify(transferLog));
    return;
  }
  if (pathname === "/__test/transfers/reset" && req.method === "POST") {
    transferLog.length = 0;
    res.writeHead(204);
    res.end();
    return;
  }

  // `/results/data/*` → fixture dir (the only mount that diverges from dist).
  if (pathname.startsWith("/results/data/")) {
    const rel = pathname.slice("/results/data/".length);
    const abs = safeJoin(fixtureDir, rel);
    if (!abs) return writeNotFound(res, "path traversal");
    return sendFile(req, res, abs, pathname);
  }

  // `/results/` → dist/
  if (pathname === "/results" || pathname === "/results/") {
    return sendFile(req, res, join(distDir, "index.html"));
  }
  if (pathname.startsWith("/results/")) {
    const rel = pathname.slice("/results/".length);
    const abs = safeJoin(distDir, rel);
    if (!abs) return writeNotFound(res, "path traversal");
    if (existsSync(abs)) return sendFile(req, res, abs);
    const ext = extname(abs).toLowerCase();
    if (!MIME.has(ext)) {
      return sendFile(req, res, join(distDir, "index.html"));
    }
    return writeNotFound(res, abs);
  }

  // Root redirect for convenience.
  if (pathname === "/") {
    res.writeHead(302, { Location: "/results/" });
    res.end();
    return;
  }

  writeNotFound(res, pathname);
};

const port = Number(values.port);
const host = values.host;
const server = createServer(handler);
server.listen(port, host, () => {
  console.log(`[serve-browser-tests] dist=${distDir}`);
  console.log(`[serve-browser-tests] fixtures=${fixtureDir}`);
  console.log(`[serve-browser-tests] listening on http://${host}:${port}/results/`);
});

const shutdown = () => {
  server.close(() => process.exit(0));
};
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
