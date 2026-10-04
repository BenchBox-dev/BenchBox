import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import AxeBuilder from "@axe-core/playwright";
import { chromium } from "@playwright/test";
import { startSiteServer } from "./site-server.mjs";
import { templateRoutes } from "./templates.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..", "..");
const siteDir = path.resolve(process.env.SITE_DIR ?? path.join(repoRoot, "website", "dist"));
const dataDir = path.resolve(process.env.EXPLORER_DATA_DIR ?? path.join(repoRoot, "results-explorer", "test-fixtures", ".generated", "data"));
const outFile = process.env.PARITY_E2E_REPORT;

const failures = [];
const report = { axe: {}, search: {} };

function fail(message) {
  failures.push(message);
}

const templates = templateRoutes(siteDir, path.join(repoRoot, "website", "src", "pages"));

for (const required of [path.join(siteDir, "404.html"), path.join(siteDir, "results", "index.html"), path.join(dataDir, "results.duckdb")]) {
  if (!existsSync(required)) throw new Error(`missing e2e input: ${required}`);
}

const { server } = await startSiteServer(siteDir, dataDir);
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });

async function open(route, theme, stripRefresh = false) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: "light" });
  if (stripRefresh) {
    const markup = readFileSync(path.join(siteDir, route), "utf-8").replace(/<meta http-equiv="refresh"[^>]*>/i, "");
    await context.route(`**${route}`, (request) => request.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: markup }));
  }
  if (theme) await context.addInitScript((value) => localStorage.setItem("benchbox:theme", value), theme);
  const page = await context.newPage();
  const response = await page.goto(base + route, { waitUntil: "load" });
  await page.waitForLoadState("networkidle").catch(() => null);
  await page
    .waitForFunction(() => [...document.querySelectorAll(".expressive-code pre")].every((pre) => pre.scrollWidth <= pre.clientWidth || pre.hasAttribute("tabindex")), null, { timeout: 10000 })
    .catch(() => null);
  return { page, context, response };
}

for (const template of templates) {
  for (const theme of ["light", "dark"]) {
    const key = `${template.name} ${theme}`;
    const { page, context, response } = await open(template.route, theme, template.stripRefresh);
    if (template.settle) await page.waitForSelector(template.settle, { timeout: 60000 }).catch(() => fail(`${key}: ${template.settle} never rendered`));
    const expectedStatus = template.status ?? 200;
    if (response?.status() !== expectedStatus) fail(`${key}: ${template.route} answered ${response?.status()}, expected ${expectedStatus}`);
    const result = await new AxeBuilder({ page }).analyze();
    const blocking = result.violations.filter((violation) => violation.impact === "serious" || violation.impact === "critical");
    report.axe[key] = { route: template.route, status: response?.status(), violations: result.violations.length, blocking: blocking.map((violation) => violation.id) };
    for (const violation of blocking) fail(`${key}: axe ${violation.id} on ${violation.nodes.slice(0, 2).map((node) => node.target.join(" ")).join(", ")}`);
    await context.close();
  }
}

const searches = [
  { name: "docs term", query: "installation environment setup", expectedFirst: "/docs/usage/installation.html" },
  { name: "blog title", query: "BenchBox v0.3.0: JoinOrder fix, approximate analytics, and agent prompt composer", expectedFirst: "/blog/2026-05-18-v0-3-0-release-overview.html" },
];
for (const { name, query, expectedFirst } of searches) {
  const { page, context } = await open("/docs/usage/getting-started.html");
  await page.getByRole("button", { name: "Search" }).click();
  await page.locator(".pagefind-ui__search-input").fill(query);
  await page.waitForSelector(".pagefind-ui__result-link", { timeout: 15000 }).catch(() => null);
  const hrefs = await page.locator(".pagefind-ui__result-link").evaluateAll((links) => links.map((anchor) => new URL(anchor.href).pathname));
  report.search[name] = { query, hrefs: hrefs.slice(0, 5) };
  if (hrefs.length === 0) fail(`pagefind search "${name}" returned no results`);
  else if (hrefs[0] !== expectedFirst) fail(`pagefind search "${name}" ranked ${hrefs[0]} first, expected ${expectedFirst}`);
  await context.close();
}

await browser.close();
server.close();
if (outFile) {
  mkdirSync(path.dirname(outFile), { recursive: true });
  writeFileSync(outFile, `${JSON.stringify({ ...report, failures }, null, 2)}\n`);
}
console.log(JSON.stringify(report, null, 2));
if (failures.length > 0) {
  console.error(`FAILED:\n${failures.join("\n")}`);
  process.exit(1);
}
console.log("parity e2e passed");
