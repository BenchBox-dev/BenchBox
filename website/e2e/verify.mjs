import { mkdirSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { gzipSync } from "node:zlib";
import AxeBuilder from "@axe-core/playwright";
import { chromium } from "@playwright/test";

const base = process.env.BASE_URL ?? "http://127.0.0.1:4330";
const outDir = process.env.OUT_DIR ?? path.join(os.tmpdir(), "benchbox-website-e2e");
mkdirSync(outDir, { recursive: true });

const samplePages = [
  "/",
  "/docs/usage/getting-started.html",
  "/docs/benchmarks/industry-benchmarks.html",
  "/docs/benchmarks/queries/tpch/q1.html",
  "/docs/reference/api-reference.html",
  "/blog/2026-05-18-v0-3-0-release-overview.html",
];

const explorerPages = [
  "/results/",
  "/results/platforms/",
  "/results/p/duckdb/?benchmark=tpch",
  "/results/benchmarks/?sort=results",
];

const explorerPattern = /\/results\/|duckdb|\.wasm|\.worker/i;

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const report = {};

async function newPage(theme, width = 1280) {
  const context = await browser.newContext({ viewport: { width, height: width < 600 ? 800 : 900 }, colorScheme: "light" });
  if (theme) await context.addInitScript((value) => localStorage.setItem("benchbox:theme", value), theme);
  const page = await context.newPage();
  const log = { requests: [], console: [], pageErrors: [], workers: [] };
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      log.console.push({ type: message.type(), text: message.text(), url: message.location().url });
    }
  });
  page.on("pageerror", (error) => log.pageErrors.push(String(error)));
  page.on("worker", (worker) => log.workers.push(worker.url()));
  page.on("requestfinished", async (request) => {
    const response = await request.response();
    const sizes = await request.sizes().catch(() => null);
    let gzip = null;
    const type = request.resourceType();
    if (["document", "script", "stylesheet"].includes(type)) {
      const body = await response?.body().catch(() => null);
      gzip = body ? gzipSync(body).length : null;
    }
    log.requests.push({
      url: request.url().replace(base, ""),
      type,
      status: response?.status(),
      transfer: sizes ? sizes.responseBodySize + sizes.responseHeadersSize : null,
      body: sizes?.responseBodySize ?? null,
      gzip,
    });
  });
  page.on("requestfailed", (request) => log.requests.push({ url: request.url().replace(base, ""), type: request.resourceType(), failed: request.failure()?.errorText }));
  return { page, context, log };
}

function summarize(log) {
  const sum = (types, key) =>
    log.requests.filter((r) => types.includes(r.type)).reduce((total, r) => total + (r[key] ?? 0), 0);
  const kinds = ["document", "script", "stylesheet"];
  return {
    requestCount: log.requests.length,
    htmlJsCssTransferBytes: sum(kinds, "transfer"),
    htmlJsCssBodyBytes: sum(kinds, "body"),
    htmlJsCssGzipBytes: sum(kinds, "gzip"),
    imageBytes: sum(["image"], "transfer"),
    otherBytes: sum(["font", "fetch", "xhr", "other", "media"], "transfer"),
    explorerOrDuckdbRequests: log.requests.filter((r) => explorerPattern.test(r.url) && r.type !== "document").map((r) => r.url),
    workers: log.workers,
    consoleErrors: log.console,
    pageErrors: log.pageErrors,
    requests: log.requests.map((r) => `${r.type} ${r.status ?? r.failed} ${r.transfer ?? "-"} ${r.url}`),
  };
}

report.pages = {};
for (const route of samplePages) {
  const { page, context, log } = await newPage();
  await page.goto(base + route, { waitUntil: "networkidle" });
  await page.waitForTimeout(300);
  report.pages[route] = summarize(log);
  report.pages[route].title = await page.title();
  report.pages[route].h1 = await page.locator("h1").first().innerText().catch(() => null);
  await context.close();
}

const widths = [320, 375, 1280];
const headerSelector = ".site-header a, .site-header button, button.sl-menu-button";

function intersects(a, b) {
  const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  return w > 1 && h > 1;
}

report.reflow = {};
for (const width of widths) {
  for (const route of samplePages) {
    const { page, context } = await newPage(undefined, width);
    await page.goto(base + route, { waitUntil: "networkidle" });
    const layout = await page.evaluate((selector) => {
      const controls = [...document.querySelectorAll(selector)]
        .filter((el) => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden")
        .map((el) => {
          const r = el.getBoundingClientRect();
          return {
            name: (el.getAttribute("aria-label") || el.textContent || el.dataset.themeOption || "").trim().slice(0, 24),
            left: r.left,
            right: r.right,
            top: r.top,
            bottom: r.bottom,
          };
        });
      const root = document.scrollingElement;
      return { scrollWidth: root.scrollWidth, innerWidth: window.innerWidth, controls };
    }, headerSelector);
    const overlaps = [];
    for (let i = 0; i < layout.controls.length; i++) {
      for (let j = i + 1; j < layout.controls.length; j++) {
        if (intersects(layout.controls[i], layout.controls[j])) overlaps.push(`${layout.controls[i].name} x ${layout.controls[j].name}`);
      }
    }
    const outside = layout.controls
      .filter((c) => c.left < -0.5 || c.right > layout.innerWidth + 0.5 || c.top < -0.5)
      .map((c) => `${c.name} [${Math.round(c.left)}..${Math.round(c.right)}]`);
    const result = await new AxeBuilder({ page }).analyze();
    const seriousOrCritical = result.violations
      .filter((v) => v.impact === "serious" || v.impact === "critical")
      .reduce((total, v) => total + v.nodes.length, 0);
    const entry = {
      scrollWidth: layout.scrollWidth,
      innerWidth: layout.innerWidth,
      overflowPx: Math.max(0, layout.scrollWidth - layout.innerWidth),
      noHorizontalOverflow: layout.scrollWidth <= layout.innerWidth,
      headerControls: layout.controls.length,
      overlaps,
      outsideViewport: outside,
      axeSeriousCritical: seriousOrCritical,
    };
    if (width === 375) {
      const toggle = page.locator('.theme-toggle [data-theme-option="dark"]').first();
      try {
        await toggle.click({ timeout: 3000 });
        entry.themeToggleClickable = (await page.evaluate(() => document.documentElement.dataset.theme)) === "dark";
        await page.locator('.theme-toggle [data-theme-option="system"]').first().click({ timeout: 3000 });
      } catch (error) {
        entry.themeToggleClickable = false;
        entry.themeToggleError = String(error).split("\n")[0];
      }
      await page.locator('.theme-toggle [aria-checked="true"]').first().focus();
      await page.keyboard.press("ArrowRight");
      entry.themeToggleKeyboard = (await page.evaluate(() => document.documentElement.dataset.bbThemeChoice)) === "light";
      const menu = page.locator("button.sl-menu-button");
      if (await menu.count()) {
        await menu.first().click({ timeout: 3000 });
        await page.waitForTimeout(300);
        entry.menuOpensSidebar = await page.evaluate(() => document.querySelector("#starlight__sidebar")?.matches(":popover-open") ?? false);
      }
      await page.screenshot({ path: path.join(outDir, `w375-${route.replace(/\W+/g, "_")}.png`) });
    }
    if (width === 320) await page.screenshot({ path: path.join(outDir, `w320-${route.replace(/\W+/g, "_")}.png`) });
    report.reflow[`${width} ${route}`] = entry;
    await context.close();
  }
}
report.reflowFailures = Object.entries(report.reflow)
  .filter(
    ([, e]) =>
      !e.noHorizontalOverflow ||
      e.overlaps.length ||
      e.outsideViewport.length ||
      e.axeSeriousCritical ||
      e.themeToggleClickable === false ||
      e.themeToggleKeyboard === false ||
      e.menuOpensSidebar === false,
  )
  .map(([key]) => key);

report.axe = {};
for (const theme of ["light", "dark"]) {
  for (const route of samplePages) {
    const { page, context } = await newPage(theme);
    await page.goto(base + route, { waitUntil: "networkidle" });
    const effective = await page.evaluate(() => document.documentElement.dataset.theme);
    const result = await new AxeBuilder({ page }).analyze();
    const counts = { critical: 0, serious: 0, moderate: 0, minor: 0 };
    for (const violation of result.violations) counts[violation.impact ?? "minor"] += violation.nodes.length;
    report.axe[`${theme} ${route}`] = {
      effective,
      counts,
      violations: result.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        nodes: v.nodes.length,
        targets: v.nodes.slice(0, 3).map((n) => n.target.join(" ")),
      })),
    };
    if (theme === "light" || route === "/") await page.screenshot({ path: path.join(outDir, `${theme}-${route.replace(/\W+/g, "_")}.png`), fullPage: false });
    await context.close();
  }
}

{
  const { page, context } = await newPage();
  const trail = [];
  const mark = async (label) => trail.push({ label, url: page.url().replace(base, ""), title: await page.title(), scrollY: await page.evaluate(() => Math.round(scrollY)) });
  await page.goto(base + "/docs/usage/getting-started.html", { waitUntil: "load" });
  await page.evaluate(() => window.scrollTo(0, 1200));
  await page.waitForTimeout(200);
  await mark("start (scrolled 1200)");
  await page.getByRole("link", { name: "Industry Benchmarks" }).first().click();
  await page.waitForURL("**/industry-benchmarks.html");
  await mark("clicked sidebar: industry");
  await page.getByRole("link", { name: "TPC-H Q1" }).first().click();
  await page.waitForURL("**/tpch/q1.html");
  await mark("clicked sidebar: q1");
  await page.goBack({ waitUntil: "load" });
  await mark("back 1");
  await page.goBack({ waitUntil: "load" });
  await page.waitForTimeout(200);
  await mark("back 2");
  await page.goForward({ waitUntil: "load" });
  await mark("forward 1");
  await page.goForward({ waitUntil: "load" });
  await mark("forward 2");
  report.history = trail;
  await context.close();
}

{
  const { page, context } = await newPage();
  const trail = [];
  const mark = async (label) => trail.push({ label, url: page.url().replace(base, ""), title: await page.title(), h1: await page.locator("h1").first().innerText().catch(() => null) });
  await page.goto(base + "/docs/usage/getting-started.html", { waitUntil: "load" });
  await mark("docs");
  await page.locator(".site-header__link", { hasText: "Results" }).first().click();
  await page.waitForURL("**/results/");
  await page.waitForSelector("tbody tr", { timeout: 30000 }).catch(() => null);
  await mark("clicked Results");
  await page.goBack({ waitUntil: "load" });
  await mark("back to docs");
  await page.goForward({ waitUntil: "load" });
  await page.waitForSelector("tbody tr", { timeout: 30000 }).catch(() => null);
  await mark("forward to results");
  await page.getByRole("link", { name: "Platforms" }).first().click();
  await page.waitForURL("**/results/platforms/**");
  await page.waitForSelector("tbody tr", { timeout: 30000 }).catch(() => null);
  await mark("explorer: Platforms");
  await page.goBack({ waitUntil: "load" });
  await page.waitForSelector("h1", { timeout: 30000 }).catch(() => null);
  await mark("explorer: back");
  await page.goForward({ waitUntil: "load" });
  await page.waitForSelector("h1", { timeout: 30000 }).catch(() => null);
  await mark("explorer: forward");
  const urls = trail.map((t) => t.url);
  report.crossHistory = {
    trail,
    pass:
      urls[1].startsWith("/results/") &&
      urls[2] === "/docs/usage/getting-started.html" &&
      urls[3].startsWith("/results/") &&
      urls[4].startsWith("/results/platforms") &&
      urls[5] === urls[3] &&
      urls[6] === urls[4],
  };
  await context.close();
}

{
  const { page, context, log } = await newPage();
  await page.goto(base + "/docs/usage/getting-started.html", { waitUntil: "networkidle" });
  const before = log.requests.length;
  await page.getByRole("button", { name: "Search" }).click();
  await page.locator(".pagefind-ui__search-input").fill("scale factor");
  await page.waitForSelector(".pagefind-ui__result", { timeout: 10000 });
  const results = await page.locator(".pagefind-ui__result-link").evaluateAll((links) => links.map((a) => a.getAttribute("href")));
  await page.screenshot({ path: path.join(outDir, "search.png") });
  report.search = { query: "scale factor", results, requestsAfterOpen: log.requests.slice(before).map((r) => `${r.type} ${r.status} ${r.transfer} ${r.url}`) };
  await context.close();
}

{
  const { page, context } = await newPage();
  await page.goto(base + "/docs/usage/getting-started.html", { waitUntil: "load" });
  const states = [];
  const read = async (label) =>
    states.push({
      label,
      stored: await page.evaluate(() => localStorage.getItem("benchbox:theme")),
      theme: await page.evaluate(() => document.documentElement.dataset.theme),
      choice: await page.evaluate(() => document.documentElement.dataset.bbThemeChoice),
    });
  await read("initial");
  await page.getByRole("radio", { name: "Dark" }).click();
  await read("clicked Dark");
  await page.goto(base + "/results/", { waitUntil: "load" });
  await page.waitForSelector("#app *");
  await read("explorer after Dark on docs");
  await page.goto(base + "/", { waitUntil: "load" });
  await read("landing");
  await page.getByRole("radio", { name: "System" }).click();
  await read("clicked System");
  report.theme = states;
  await context.close();
}

report.explorer = {};
for (const route of explorerPages) {
  const { page, context, log } = await newPage();
  const response = await page.goto(base + route, { waitUntil: "load" });
  const initialStatus = response?.status();
  let rows = null;
  try {
    await page.waitForSelector("tbody tr", { timeout: 30000 });
    rows = await page.locator("tbody tr").count();
  } catch {
    rows = 0;
  }
  await page.waitForLoadState("networkidle").catch(() => null);
  const summary = summarize(log);
  report.explorer[route] = {
    initialStatus,
    finalUrl: page.url().replace(base, ""),
    h1: await page.locator("h1").first().innerText().catch(() => null),
    rows,
    wasmAndWorkerRequests: summary.requests.filter((r) => /\.wasm|worker/.test(r)),
    dataRequests: summary.requests.filter((r) => /duckdb|\/data\//.test(r) && !/\.wasm|worker/.test(r)),
    workers: summary.workers,
    consoleErrors: summary.consoleErrors,
    pageErrors: summary.pageErrors,
  };
  await page.screenshot({ path: path.join(outDir, `explorer-${route.replace(/\W+/g, "_")}.png`) });
  await context.close();
}

await browser.close();
writeFileSync(path.join(outDir, "verify.json"), JSON.stringify(report, null, 2));
console.log(`wrote ${path.join(outDir, "verify.json")}`);

const failed = [...report.reflowFailures, ...(report.crossHistory?.pass ? [] : ["crossHistory"])];
if (failed.length) {
  console.error(`verification failures: ${failed.join(", ")}`);
  process.exitCode = 1;
}
