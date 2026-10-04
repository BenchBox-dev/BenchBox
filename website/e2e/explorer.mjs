import { createReadStream, existsSync, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import AxeBuilder from "@axe-core/playwright";
import { chromium } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..", "..");
const siteDir = path.resolve(process.env.SITE_DIR ?? path.join(repoRoot, "website", "dist"));
const dataDir = path.resolve(process.env.EXPLORER_DATA_DIR ?? path.join(repoRoot, "results-explorer", "test-fixtures", ".generated", "data"));
const ids = JSON.parse(readFileSync(path.join(dataDir, "fixture-ids.json"), "utf-8"));

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

const explorerAsset = /^\/results\/|duckdb|\.wasm$/i;
const failures = [];
const report = {};

function fail(message) {
  failures.push(message);
}

function resolveFile(urlPath) {
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

function startServer() {
  const served = [];
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://localhost");
    const file = resolveFile(url.pathname);
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

for (const required of [path.join(siteDir, "404.html"), path.join(siteDir, "results", "index.html"), path.join(dataDir, "results.duckdb")]) {
  if (!existsSync(required)) throw new Error(`missing e2e input: ${required}`);
}

const { server, served } = await startServer();
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });

async function open(route, { width = 1280, beforeGoto } = {}) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: "light" });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  if (beforeGoto) await beforeGoto(page, context);
  const response = await page.goto(base + route, { waitUntil: "load" });
  return { page, context, response, pageErrors };
}

async function settleRows(page, selector = "main tbody tr") {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      await page.waitForSelector(selector, { timeout: 15000 });
      return true;
    } catch {
      await page.reload({ waitUntil: "load" });
    }
  }
  return false;
}

async function blocking(page) {
  const result = await new AxeBuilder({ page }).analyze();
  return result.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.slice(0, 2).map((n) => n.target.join(" ")).join(", ")}`);
}

const nonExplorerPages = [
  "/",
  "/docs/usage/getting-started.html",
  "/docs/benchmarks/industry-benchmarks.html",
  "/docs/reference/api-reference.html",
  "/blog/",
  "/blog/2026-05-18-v0-3-0-release-overview.html",
  "/docs/no-such-page.html",
];

report.zeroExplorerBytes = {};
for (const route of nonExplorerPages) {
  for (const interaction of ["load", "search"]) {
    if (interaction === "search" && !route.startsWith("/docs/usage")) continue;
    served.length = 0;
    const requests = [];
    const { page, context } = await open(route, { beforeGoto: (opened) => opened.on("request", (request) => requests.push(request.url().replace(base, ""))) });
    await page.waitForLoadState("networkidle").catch(() => null);
    if (interaction === "search") {
      await page.getByRole("button", { name: "Search" }).click();
      await page.locator(".pagefind-ui__search-input").fill("scale factor");
      await page.waitForSelector(".pagefind-ui__result", { timeout: 15000 }).catch(() => null);
    }
    const key = `${route} ${interaction}`;
    const browserHits = requests.filter((url) => explorerAsset.test(url.split("?")[0]));
    const serverHits = served.filter((entry) => explorerAsset.test(entry.path));
    const workers = page.workers().filter((worker) => !worker.url().includes("/pagefind/")).length;
    report.zeroExplorerBytes[key] = { requests: requests.length, serverBytes: served.reduce((total, entry) => total + entry.bytes, 0), explorerRequests: browserHits.length, explorerServerBytes: serverHits.reduce((total, entry) => total + entry.bytes, 0), workers };
    if (browserHits.length || serverHits.length || workers) fail(`${key} touched Explorer assets: ${JSON.stringify([...browserHits, ...serverHits])} workers=${workers}`);
    await context.close();
  }
}

report.deepLinks = {};
const deepLinks = [
  { route: "/results/p/duckdb/?benchmark=tpch", heading: /DuckDB/, rows: true },
  { route: `/results/r/${ids.ids.duckdb}`, heading: /TPC-H result/, rows: false },
  { route: `/results/compare?ids=${ids.shortIds.duckdb},${ids.shortIds.polars}`, heading: /Comparison/, rows: false },
  { route: "/results/benchmarks/?sort=results", heading: /Benchmarks/, rows: true },
  { route: "/results/platforms/", heading: /Platforms/, rows: true },
  { route: "/results/query?q=duckdb&limit=all", heading: /Find benchmark runs/, rows: false },
];
const searchOf = (url) => [...new URL(url).searchParams].sort().join("&");
for (const { route, heading, rows } of deepLinks) {
  const { page, context, response, pageErrors } = await open(route);
  const expected = new URL(base + route);
  const headingLocator = page.getByRole("heading", { name: heading }).first();
  const shown = async () => headingLocator.waitFor({ state: "visible", timeout: 30000 }).then(() => true).catch(() => false);
  const first = { status: response?.status(), headingShown: await shown() };
  if (rows) first.rows = await settleRows(page);
  const landed = new URL(page.url());
  const alerts = await page.locator("main [role=alert]").allInnerTexts();
  await page.reload({ waitUntil: "load" });
  const reloadedHeading = await shown();
  const reloaded = new URL(page.url());
  report.deepLinks[route] = { ...first, landed: landed.pathname + landed.search, reloaded: reloaded.pathname + reloaded.search, reloadedHeading, alerts, pageErrors };
  if (landed.pathname !== expected.pathname || searchOf(landed) !== searchOf(expected)) fail(`deep link ${route} landed on ${landed.pathname + landed.search}`);
  if (reloaded.pathname !== expected.pathname || searchOf(reloaded) !== searchOf(expected)) fail(`deep link ${route} lost its URL on reload: ${reloaded.pathname + reloaded.search}`);
  if (!first.headingShown || !reloadedHeading) fail(`deep link ${route} rendered no heading matching ${heading}`);
  if (rows && !first.rows) fail(`deep link ${route} rendered no result rows`);
  if (alerts.length) fail(`deep link ${route} shows an alert: ${alerts.join(" | ")}`);
  if (pageErrors.length) fail(`deep link ${route} threw: ${pageErrors.join(" | ")}`);
  await context.close();
}

{
  const { page, context } = await open("/results/benchmarks/");
  await settleRows(page, "main a[href^='/results/']");
  const trail = [];
  const mark = (label) => trail.push({ label, path: new URL(page.url()).pathname + new URL(page.url()).search });
  mark("benchmarks");
  await page.getByRole("navigation", { name: "Results Explorer" }).getByRole("link", { name: "Platforms" }).click();
  await page.waitForURL("**/results/platforms/");
  mark("platforms");
  await page.getByRole("navigation", { name: "Results Explorer" }).getByRole("link", { name: "Find runs" }).click();
  await page.waitForURL("**/results/query");
  const search = page.getByTestId("query-result-search");
  await search.waitFor({ state: "visible", timeout: 30000 });
  await search.fill("duckdb");
  await page.waitForFunction(() => new URL(location.href).searchParams.get("q") === "duckdb", null, { timeout: 10000 });
  mark("query with q");
  await page.goBack({ waitUntil: "load" });
  mark("back to platforms");
  await page.goBack({ waitUntil: "load" });
  mark("back to benchmarks");
  await page.goForward({ waitUntil: "load" });
  mark("forward to platforms");
  await page.goForward({ waitUntil: "load" });
  await page.getByTestId("query-result-search").waitFor({ state: "visible", timeout: 30000 });
  mark("forward to query");
  const restored = new URL(page.url()).searchParams.get("q");
  const inputValue = await page.getByTestId("query-result-search").inputValue();
  report.history = { trail, restored, inputValue };
  const paths = trail.map((step) => step.path);
  const ok =
    paths[0] === "/results/benchmarks/" &&
    paths[1] === "/results/platforms/" &&
    paths[2].startsWith("/results/query") &&
    paths[3] === "/results/platforms/" &&
    paths[4] === "/results/benchmarks/" &&
    paths[5] === "/results/platforms/" &&
    paths[6].startsWith("/results/query") &&
    restored === "duckdb" &&
    inputValue === "duckdb";
  if (!ok) fail(`explorer history walk diverged: ${JSON.stringify(trail)}`);
  await context.close();
}

report.states = {};
{
  const held = [];
  const { page, context } = await open("/results/", {
    beforeGoto: async (opened) => {
      await opened.route("**/results/data/results.duckdb", async (route) => {
        await new Promise((resolve) => held.push(resolve));
        await route.continue();
      });
    },
  });
  await page.locator("main [role=status]").first().waitFor({ state: "attached", timeout: 15000 }).catch(() => null);
  const loading = await page.evaluate(() => {
    const statuses = [...document.querySelectorAll("main [role=status]")];
    const named = statuses.filter((el) => el.getAttribute("aria-label") || el.getAttribute("aria-labelledby"));
    const live = statuses.filter((el) => el.getAttribute("aria-live") === "polite" && (el.textContent ?? "").trim().length > 0);
    return { statuses: statuses.length, named: named.map((el) => el.getAttribute("aria-label")), live: live.map((el) => (el.textContent ?? "").trim().slice(0, 60)) };
  });
  const loadingViolations = await blocking(page);
  report.states.loading = { ...loading, axe: loadingViolations };
  if (!loading.statuses || !loading.named.length || !loading.live.length) fail(`loading state lacks a named polite status region: ${JSON.stringify(loading)}`);
  if (loadingViolations.length) fail(`loading state axe: ${loadingViolations.join("; ")}`);
  held.splice(0).forEach((release) => release());
  await context.close();
}

{
  let blocked = 0;
  const { page, context } = await open("/results/", {
    beforeGoto: async (opened) => {
      await opened.route("**/results/assets/duckdb-*worker*.js", (route) => {
        blocked += 1;
        return route.abort();
      });
    },
  });
  const alert = page.locator("main [role=alert]").filter({ has: page.getByRole("heading", { name: "Could not load results" }) });
  await alert.waitFor({ state: "visible", timeout: 60000 }).catch(() => null);
  const errorState = await alert.evaluate((el) => ({ name: el.getAttribute("aria-labelledby") ? document.getElementById(el.getAttribute("aria-labelledby"))?.textContent : null, role: el.getAttribute("role") })).catch(() => null);
  const errorViolations = await blocking(page);
  report.states.error = { blocked, ...errorState, axe: errorViolations };
  if (!errorState || errorState.name !== "Could not load results" || errorState.role !== "alert") fail(`error state is not a named alert: ${JSON.stringify(errorState)}`);
  if (errorViolations.length) fail(`error state axe: ${errorViolations.join("; ")}`);
  await page.unroute("**/results/assets/duckdb-*worker*.js");
  await alert.getByRole("button", { name: "Retry" }).click();
  const recovered = await page.waitForSelector("main tbody tr", { timeout: 60000 }).then(() => true).catch(() => false);
  const stillFailing = await alert.isVisible().catch(() => false);
  const workerUrls = page.workers().map((worker) => worker.url());
  report.states.recovery = { recovered, stillFailing, workers: workerUrls.length, finalPath: new URL(page.url()).pathname };
  if (!recovered || stillFailing) fail("explorer did not recover after the worker asset became reachable and Retry was pressed");
  await context.close();
}

{
  const { page, context } = await open("/results/", {
    beforeGoto: async (opened) => {
      await opened.route("**/results/data/results.duckdb", (route) => route.fulfill({ status: 404 }));
    },
  });
  const alert = page.locator("main [role=alert]").filter({ has: page.getByRole("heading", { name: "Could not load results" }) });
  await alert.waitFor({ state: "visible", timeout: 60000 }).catch(() => null);
  const snapshotViolations = await blocking(page);
  report.states.snapshotMissing = { visible: await alert.isVisible().catch(() => false), axe: snapshotViolations };
  if (!report.states.snapshotMissing.visible) fail("a missing snapshot did not surface the named error alert");
  if (snapshotViolations.length) fail(`snapshot error axe: ${snapshotViolations.join("; ")}`);
  await context.close();
}

const docsPage = "/docs/usage/getting-started.html";
const resultsPage = "/results/";

async function headerScript(route) {
  const context = await browser.newContext({ viewport: { width: 390, height: 900 } });
  const page = await context.newPage();
  await page.goto(base + route, { waitUntil: "load" });
  await page.locator("[data-site-header-toggle]").waitFor({ state: "visible", timeout: 30000 });
  const toggle = page.locator("[data-site-header-toggle]");
  const expanded = () => toggle.getAttribute("aria-expanded");
  const out = {};
  await toggle.focus();
  await page.keyboard.press("Enter");
  out.opened = await expanded();
  const visited = [];
  await page.keyboard.press("Tab");
  for (let step = 0; step < 8; step += 1) {
    if (!(await page.evaluate(() => !!document.activeElement?.closest("[data-site-header-panel]")))) break;
    visited.push(await page.evaluate(() => document.activeElement.textContent.trim()));
    await page.keyboard.press("Tab");
  }
  out.visited = visited.join("|");
  await toggle.focus();
  if ((await expanded()) !== "true") await page.keyboard.press("Enter");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Escape");
  out.escape = { expanded: await expanded(), focusOnToggle: await page.evaluate(() => document.activeElement?.hasAttribute("data-site-header-toggle")) };
  await toggle.click();
  await page.locator(".site-header__cta").focus();
  for (let step = 0; step < 3; step += 1) await page.keyboard.press("Tab");
  out.tabOut = await expanded();
  await toggle.click();
  out.reopened = await expanded();
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.waitForTimeout(200);
  out.grewClosed = await expanded();
  await page.locator(".site-header__link", { hasText: "Blog" }).focus();
  await page.setViewportSize({ width: 390, height: 900 });
  await page.waitForTimeout(200);
  out.shrinkFocusOnToggle = await page.evaluate(() => document.activeElement?.hasAttribute("data-site-header-toggle"));
  await page.setViewportSize({ width: 1280, height: 900 });
  const radio = (name) => page.getByRole("radio", { name });
  await radio("Light theme").click();
  await radio("Light theme").focus();
  const choices = [];
  for (const key of ["ArrowRight", "ArrowRight", "ArrowRight", "ArrowLeft", "Home", "End", "ArrowUp"]) {
    await page.keyboard.press(key);
    await page.waitForTimeout(150);
    choices.push(await page.evaluate(() => document.documentElement.dataset.bbThemeChoice));
  }
  out.radioKeys = choices.join(",");
  out.styles = await page.evaluate(() => {
    const read = (selector) => {
      const el = document.querySelector(selector);
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return [style.color, style.fontFamily, style.fontSize, style.lineHeight, style.textDecorationLine, selector === ".site-header" ? "" : Math.round(rect.height)].join(" / ");
    };
    return { header: read(".site-header"), headerLink: read(".site-header__link"), footer: read(".site-footer"), footerLink: read(".site-footer__link"), legal: read(".site-footer__legal") };
  });
  await context.close();
  return out;
}

{
  const docs = await headerScript(docsPage);
  const results = await headerScript(resultsPage);
  report.headerParity = { docs, results };
  const expectations = { opened: "true", visited: "Home|Docs|Blog|Results|GitHub|Run benchmark", tabOut: "false", grewClosed: "false", shrinkFocusOnToggle: true };
  for (const [name, value] of Object.entries(expectations)) {
    if (docs[name] !== value) fail(`docs header ${name} is ${docs[name]}`);
  }
  if (docs.escape.expanded !== "false" || !docs.escape.focusOnToggle) fail(`docs Escape behaviour ${JSON.stringify(docs.escape)}`);
  for (const key of Object.keys(docs)) {
    if (JSON.stringify(docs[key]) !== JSON.stringify(results[key])) fail(`header behaviour differs between docs and results for ${key}: ${JSON.stringify(docs[key])} vs ${JSON.stringify(results[key])}`);
  }
}

{
  const { page, context } = await open("/results/tpch/?sf=0.01&phase=power", { width: 1280 });
  await page.setViewportSize({ width: 1280, height: 600 });
  const header = page.getByTestId("benchbox-global-header");
  await header.waitFor({ state: "visible", timeout: 30000 });
  const preview = page.locator('[data-testid="summary-chart-preview-query_heatmap"]').first();
  const previewShown = await preview.waitFor({ state: "attached", timeout: 30000 }).then(() => true).catch(() => false);
  if (previewShown && !(await preview.evaluate((el) => el.open))) await preview.locator("summary").click();
  const scroller = page.getByTestId("query-heatmap-scroll-container").first();
  const heatmapShown = await scroller.waitFor({ state: "visible", timeout: 30000 }).then(() => true).catch(() => false);
  if (heatmapShown) {
    await scroller.evaluate((container) => {
      const tbody = container.querySelector("tbody");
      if (!tbody) return;
      const rows = [...tbody.querySelectorAll("tr")];
      for (let repeat = 0; repeat < 18; repeat += 1) for (const row of rows) tbody.appendChild(row.cloneNode(true));
    });
  }
  const position = await header.evaluate((el) => getComputedStyle(el).position);
  const target = heatmapShown ? await scroller.evaluate((container) => window.scrollY + container.getBoundingClientRect().top + 180) : 600;
  await page.evaluate((y) => window.scrollTo(0, y), target);
  await page.waitForTimeout(300);
  const headerBottom = await header.evaluate((el) => Math.round(el.getBoundingClientRect().bottom));
  report.stickiness = { position, scrolled: await page.evaluate(() => Math.round(window.scrollY)), headerBottom, heatmapShown };
  if (position === "sticky" || position === "fixed") fail(`explorer header is ${position}`);
  if (headerBottom > 0) fail(`explorer header did not scroll away: bottom=${headerBottom}`);
  if (!heatmapShown) fail("the query heatmap did not render, so sticky coverage was not checked");
  else {
    const sticky = page.getByTestId("query-heatmap-page-sticky-header").first();
    const covered = await sticky.evaluate((el) => {
      for (const node of [el.parentElement, el]) if (node) node.style.pointerEvents = "auto";
      const rect = el.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + Math.max(1, Math.min(rect.height / 2, 10)));
      return { top: Math.round(rect.top), covered: !(hit && el.contains(hit)), hit: hit ? `${hit.tagName}.${String(hit.className).slice(0, 60)}[${hit.getAttribute("data-testid") ?? ""}]` : null };
    });
    report.stickiness.heatmap = covered;
    if (covered.covered || covered.top > 1) fail(`heatmap sticky header is covered or displaced: ${JSON.stringify(covered)}`);
  }
  await context.close();
}

report.paths = { snapshot: "/results/data/results.duckdb", dataRequests: served.filter((entry) => entry.path === "/results/data/results.duckdb").length, workerAssets: served.filter((entry) => /\/results\/assets\/.*(worker|\.wasm)/.test(entry.path)).length };
if (!report.paths.dataRequests) fail("the Explorer never requested /results/data/results.duckdb");
if (!report.paths.workerAssets) fail("the Explorer never requested worker or wasm assets under /results/assets/");

await browser.close();
server.close();
console.log(JSON.stringify(report, null, 2));
if (failures.length > 0) {
  console.error(`FAILED:\n${failures.join("\n")}`);
  process.exit(1);
}
console.log("explorer e2e passed");
