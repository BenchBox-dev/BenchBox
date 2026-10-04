import { spawnSync } from "node:child_process";
import { createReadStream, existsSync, mkdtempSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..", "..");
const siteDir = path.resolve(process.env.SITE_DIR ?? path.join(repoRoot, "website", "dist"));
const explorerDist = path.join(repoRoot, "results-explorer", "dist");

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

function pagesResolve(root, urlPath) {
  const clean = path.normalize(decodeURIComponent(urlPath)).replace(/^(\.\.[/\\])+/, "");
  const candidates = urlPath.endsWith("/") ? [path.join(clean, "index.html")] : [clean, `${clean}.html`, path.join(clean, "index.html")];
  for (const candidate of candidates) {
    const full = path.join(root, candidate);
    if (full.startsWith(root) && existsSync(full) && statSync(full).isFile()) return full;
  }
  return undefined;
}

function serve(root, notFound) {
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://localhost");
    const file = pagesResolve(root, url.pathname);
    const target = file ?? notFound;
    response.writeHead(file ? 200 : 404, { "content-type": types[path.extname(target)] ?? "application/octet-stream" });
    createReadStream(target).pipe(response);
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

function assemblerFallback() {
  const scratch = mkdtempSync(path.join(process.env.TMPDIR ?? os.tmpdir(), "benchbox-fallback-"));
  const file = path.join(scratch, "404.html");
  const code = "import sys; sys.path.insert(0, 'scripts'); from assemble_public_site import RESULTS_FALLBACK; sys.stdout.write(RESULTS_FALLBACK)";
  const run = spawnSync("python3", ["-c", code], { cwd: repoRoot, encoding: "utf-8" });
  if (run.status !== 0) throw new Error(`could not read assembler fallback: ${run.stderr}`);
  writeFileSync(file, run.stdout);
  return file;
}

const routes = [
  "/results/p/duckdb/?benchmark=tpch",
  "/results/platforms/",
  "/results/benchmarks/?sort=results",
  "/results/p/duckdb/tpch/sf1/#summary",
];

for (const required of [path.join(siteDir, "404.html"), path.join(siteDir, "results", "index.html"), path.join(explorerDist, "index.html")]) {
  if (!existsSync(required)) throw new Error(`missing build output: ${required}`);
}

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const failures = [];
const report = [];

async function check(label, notFound) {
  const server = await serve(siteDir, notFound);
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    for (const route of routes) {
      const context = await browser.newContext();
      const page = await context.newPage();
      const statuses = [];
      page.on("response", (response) => {
        if (response.request().isNavigationRequest()) statuses.push(response.status());
      });
      await page.goto(base + route, { waitUntil: "load" });
      await page.waitForFunction(() => document.getElementById("app")?.childElementCount > 0, null, { timeout: 30000 });
      const finalUrl = new URL(page.url());
      const expected = new URL(base + route);
      const stored = await page.evaluate(() => window.sessionStorage.getItem("benchbox.results.redirect"));
      const ok =
        statuses[0] === 404 &&
        finalUrl.pathname === expected.pathname &&
        finalUrl.search === expected.search &&
        finalUrl.hash === expected.hash &&
        stored === null;
      report.push({ label, route, statuses, finalUrl: finalUrl.pathname + finalUrl.search + finalUrl.hash, stored, ok });
      if (!ok) failures.push(`${label} ${route}`);
      await context.close();
    }
    const other = await browser.newContext();
    const page = await other.newPage();
    const response = await page.goto(`${base}/docs/no-such-page.html`, { waitUntil: "load" });
    const notFoundOk = response?.status() === 404 && new URL(page.url()).pathname === "/docs/no-such-page.html";
    report.push({ label, route: "/docs/no-such-page.html", status: response?.status(), ok: notFoundOk });
    if (!notFoundOk) failures.push(`${label} non-results path`);
    await other.close();
  } finally {
    server.close();
  }
}

await check("astro-404", path.join(siteDir, "404.html"));
await check("assembler-404", assemblerFallback());

const styled = await serve(siteDir, path.join(siteDir, "404.html"));
{
  const page = await (await browser.newContext()).newPage();
  await page.goto(`http://127.0.0.1:${styled.address().port}/nope/missing`, { waitUntil: "load" });
  const heading = await page.locator("h1").textContent();
  const hasShell = (await page.locator("[data-site-header]").count()) > 0 && (await page.locator("[data-search-open]").count()) > 0;
  await page.locator("[data-not-found-search]").click();
  const searchOpens = await page.locator("dialog[data-search-dialog]").evaluate((dialog) => dialog.open);
  report.push({ label: "styled-404", heading, hasShell, searchOpens });
  if (heading !== "Page not found" || !hasShell || !searchOpens) failures.push("styled 404 page");
}
styled.close();

await browser.close();
console.log(JSON.stringify(report, null, 2));
if (failures.length > 0) {
  console.error(`FAILED: ${failures.join("; ")}`);
  process.exit(1);
}
console.log("not-found e2e passed");
