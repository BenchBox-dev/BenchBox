import { mkdirSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { chromium } from "@playwright/test";

const base = process.env.BASE_URL ?? "http://127.0.0.1:4330";
const outDir = process.env.OUT_DIR ?? path.join(os.tmpdir(), "benchbox-website-shell");
mkdirSync(outDir, { recursive: true });

const pages = {
  docs: "/docs/usage/getting-started.html",
  blog: "/blog/2026-05-18-v0-3-0-release-overview.html",
  landing: "/",
};
const widths = { desktop: 1280, mobile: 390, narrow: 320 };
const expectedLinks = [
  ["Home", "/"],
  ["Docs", "/docs/"],
  ["Blog", "/blog/"],
  ["Results", "/results/"],
  ["GitHub", "https://github.com/BenchBox-dev/BenchBox"],
  ["Run benchmark", "/docs/usage/installation.html"],
];
const proseLink = "p a, li a, td a, dd a, .sl-markdown-content a, .prose a";

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const report = { axe: {}, layout: {}, theme: {}, search: {}, header: {} };
const failures = [];

function fail(message) {
  failures.push(message);
}

async function open(width, route, theme) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: "light" });
  if (theme) await context.addInitScript((value) => localStorage.setItem("benchbox:theme", value), theme);
  const page = await context.newPage();
  await page.goto(base + route, { waitUntil: "networkidle" });
  return { page, context };
}

async function openNav(page) {
  const toggle = page.locator("[data-site-header-toggle]");
  if (await toggle.isVisible()) {
    if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
    return true;
  }
  return false;
}

for (const [name, route] of Object.entries(pages)) {
  for (const [size, width] of Object.entries(widths)) {
    for (const theme of ["light", "dark"]) {
      const key = `${name} ${size} ${theme}`;
      const { page, context } = await open(width, route, theme);
      await openNav(page);
      const result = await new AxeBuilder({ page }).analyze();
      const blocking = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      report.axe[key] = {
        blocking: blocking.map((v) => ({ id: v.id, impact: v.impact, targets: v.nodes.slice(0, 3).map((n) => n.target.join(" ")) })),
        other: result.violations.filter((v) => !blocking.includes(v)).map((v) => `${v.id}:${v.impact}`),
      };
      if (blocking.length) fail(`axe ${key}: ${blocking.map((v) => v.id).join(", ")}`);
      await context.close();
    }

    const { page, context } = await open(width, route);
    const layout = await page.evaluate(
      ({ proseSelector, mobile }) => {
        const root = document.scrollingElement;
        const small = [];
        const candidates = [...document.querySelectorAll("a[href], button, summary, input, select, [role=radio]")];
        for (const el of candidates) {
          const rect = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          if (rect.width === 0 || rect.height === 0 || style.visibility === "hidden" || el.closest("[hidden], dialog:not([open])")) continue;
          if (el.matches(".sl-sr-only, .sr-only, .skip-link") || el.closest(".sr-only")) continue;
          if (el.matches(proseSelector) && !el.closest(".site-header, .site-footer, .breadcrumbs, nav")) continue;
          if (rect.height < 43.5 || rect.width < 43.5) {
            small.push({ text: (el.getAttribute("aria-label") || el.textContent || el.tagName).trim().slice(0, 30), w: Math.round(rect.width), h: Math.round(rect.height), cls: String(el.className).slice(0, 40) });
          }
        }
        return { scrollWidth: root.scrollWidth, innerWidth: window.innerWidth, small, mobile };
      },
      { proseSelector: proseLink, mobile: width < 600 },
    );
    const key = `${name} ${size}`;
    report.layout[key] = { overflowPx: Math.max(0, layout.scrollWidth - layout.innerWidth), smallTargets: layout.small };
    if (layout.scrollWidth > layout.innerWidth) fail(`horizontal overflow ${key}`);
    const shellSmall = layout.small.filter((t) => /site-header|site-footer|search|theme|breadcrumb|blog-post/.test(t.cls) || ["Search", "Docs", "Blog", "Results", "GitHub", "Home", "BenchBox"].includes(t.text));
    if (shellSmall.length) fail(`touch targets under 44px in ${key}: ${JSON.stringify(shellSmall)}`);
    await context.close();
  }
}

{
  const { page, context } = await open(1280, pages.docs);
  const links = await page.evaluate(() =>
    [...document.querySelectorAll("[data-site-header-nav] a")].map((a) => [a.textContent.trim(), a.getAttribute("href"), a.getAttribute("aria-current")]),
  );
  report.header.links = links;
  expectedLinks.forEach(([label, href], position) => {
    if (links[position]?.[0] !== label || links[position]?.[1] !== href) fail(`header link ${position} is ${JSON.stringify(links[position])}, expected ${label} ${href}`);
  });
  const current = links.filter((l) => l[2] === "page").map((l) => l[0]);
  report.header.current = current;
  if (current.join() !== "Docs") fail(`header current on docs is ${current}`);
  report.header.nav = await page.evaluate(() => document.querySelector("[data-site-header-nav]").getAttribute("aria-label"));
  report.header.searchButton = await page.getByRole("button", { name: "Search" }).count();
  report.header.breadcrumbs = await page.locator(".breadcrumbs li").allInnerTexts();
  report.header.editLink = await page.locator('a[href*="/edit/develop/docs/"]').first().getAttribute("href");
  report.header.sidebar = await page.locator("nav[aria-label='Main'] a, #starlight__sidebar a").count();
  report.header.toc = await page.locator("starlight-toc a, .right-sidebar a").count();
  if (!report.header.editLink) fail("docs page has no edit link");
  if (report.header.breadcrumbs.length < 2) fail("docs page has no breadcrumbs");
  if (!report.header.sidebar) fail("docs page has no sidebar links");
  if (!report.header.toc) fail("docs page has no on-page table of contents");
  await context.close();
}

for (const [size, width] of Object.entries(widths).filter(([size]) => size !== "narrow")) {
  const { page, context } = await open(width, pages.docs);
  const steps = [];
  const read = async (label) =>
    steps.push({
      label,
      stored: await page.evaluate(() => localStorage.getItem("benchbox:theme")),
      dataTheme: await page.evaluate(() => document.documentElement.dataset.theme),
      dataBbTheme: await page.evaluate(() => document.documentElement.dataset.bbTheme),
      bodyTheme: await page.evaluate(() => document.body.getAttribute("data-theme")),
      choice: await page.evaluate(() => document.documentElement.dataset.bbThemeChoice),
    });
  await openNav(page);
  await page.getByRole("radio", { name: "Dark theme" }).click();
  await read("dark");
  await page.reload({ waitUntil: "networkidle" });
  await read("dark after reload");
  await page.goto(base + pages.landing, { waitUntil: "networkidle" });
  await read("landing");
  await openNav(page);
  await page.getByRole("radio", { name: "Light theme" }).click();
  await read("light");
  await page.getByRole("radio", { name: "Light theme" }).focus();
  await page.keyboard.press("ArrowRight");
  await read("arrow right");
  await page.keyboard.press("Home");
  await read("home");
  await page.getByRole("radio", { name: "System theme" }).click();
  await read("system");
  report.theme[size] = steps;
  const byLabel = Object.fromEntries(steps.map((s) => [s.label, s]));
  const ok =
    byLabel.dark.stored === "dark" &&
    byLabel.dark.dataTheme === "dark" &&
    byLabel.dark.dataBbTheme === "dark" &&
    byLabel.dark.bodyTheme === "dark" &&
    byLabel["dark after reload"].dataTheme === "dark" &&
    byLabel["dark after reload"].dataBbTheme === "dark" &&
    byLabel.landing.dataTheme === "dark" &&
    byLabel.light.stored === "light" &&
    byLabel.light.dataBbTheme === "light" &&
    byLabel["arrow right"].stored === "dark" &&
    byLabel.home.choice === "system" &&
    byLabel.system.stored === null &&
    byLabel.system.dataBbTheme === byLabel.system.dataTheme;
  if (!ok) fail(`theme behaviour ${size}: ${JSON.stringify(steps)}`);
  await context.close();
}

for (const [name, query, expectedFirst, size] of [
  ["docs term", "installation environment setup", "/docs/usage/installation.html", "desktop"],
  ["blog title", "BenchBox v0.3.0: JoinOrder fix, approximate analytics, and agent prompt composer", "/blog/2026-05-18-v0-3-0-release-overview.html", "desktop"],
  ["docs term mobile", "installation environment setup", "/docs/usage/installation.html", "mobile"],
]) {
  const { page, context } = await open(widths[size], pages.landing);
  await page.getByRole("button", { name: "Search" }).click();
  await page.locator(".pagefind-ui__search-input").fill(query);
  await page.waitForSelector(".pagefind-ui__result", { timeout: 15000 }).catch(() => null);
  const hrefs = await page.locator(".pagefind-ui__result-link").evaluateAll((links) => links.map((a) => new URL(a.href).pathname));
  const resultsSection = await page.evaluate(() => {
    const section = document.querySelector('[data-search-section="results"]');
    if (!section) return { present: false };
    return { present: true, hidden: section.hidden, items: section.querySelectorAll("li").length, visible: section.getClientRects().length > 0 };
  });
  report.search[name] = { query, hrefs: hrefs.slice(0, 5), resultsSection };
  if (hrefs[0] !== expectedFirst) fail(`search ${name} returned ${hrefs.slice(0, 5)}`);
  if (resultsSection.present && (resultsSection.items !== 0 || resultsSection.visible)) fail(`results section not empty for ${name}`);
  if (size === "desktop") await page.screenshot({ path: path.join(outDir, `search-${name.replace(/\W+/g, "_")}.png`) });
  await context.close();
}

{
  const { page, context } = await open(1280, pages.docs);
  const requests = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.getByRole("button", { name: "Search" }).click();
  await page.locator(".pagefind-ui__search-input").fill("scale factor");
  await page.waitForSelector(".pagefind-ui__result", { timeout: 15000 }).catch(() => null);
  const touched = requests.filter((url) => /duckdb|\.wasm|\/results\//i.test(url));
  report.search.explorerRequests = touched;
  if (touched.length) fail(`search touched explorer assets: ${touched}`);
  await context.close();
}

for (const [size, width] of Object.entries(widths).filter(([size]) => size !== "narrow")) {
  for (const [name, route] of Object.entries(pages)) {
    const { page, context } = await open(width, route);
    await openNav(page);
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(outDir, `${name}-${size}.png`) });
    await context.close();
  }
}

await browser.close();
report.failures = failures;
writeFileSync(path.join(outDir, "shell.json"), JSON.stringify(report, null, 2));
console.log(`wrote ${path.join(outDir, "shell.json")}`);
if (failures.length) {
  console.error(failures.join("\n"));
  process.exitCode = 1;
} else {
  console.log("shell checks passed");
}
