import { createReadStream, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import AxeBuilder from "@axe-core/playwright";
import { chromium } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const types = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };

function resolveFile(root, urlPath) {
  const clean = path.normalize(decodeURIComponent(urlPath)).replace(/^(\.\.[/\\])+/, "");
  const candidates = urlPath.endsWith("/") ? [path.join(clean, "index.html")] : [clean, `${clean}.html`, path.join(clean, "index.html")];
  return candidates.map((candidate) => path.join(root, candidate)).find((full) => full.startsWith(root) && existsSync(full) && statSync(full).isFile());
}

const servers = [];
async function serve(root) {
  const server = createServer((request, response) => {
    const file = resolveFile(root, new URL(request.url ?? "/", "http://localhost").pathname);
    response.writeHead(file ? 200 : 404, { "content-type": types[path.extname(file ?? "")] ?? "application/octet-stream" });
    if (file) createReadStream(file).pipe(response);
    else response.end();
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  servers.push(server);
  return `http://127.0.0.1:${server.address().port}`;
}

const base = process.env.BASE_URL ?? (await serve(path.resolve(process.env.SITE_DIR ?? path.join(here, "..", "dist"))));
const oldBase = process.env.OLD_BASE_URL ?? (await serve(path.resolve(process.env.LANDING_DIR ?? path.join(here, "..", "..", "landing"))));
const outDir = process.env.OUT_DIR ?? path.join(os.tmpdir(), "benchbox-website-landing");
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const failures = [];
const report = { network: {}, landing: {}, prompts: {}, parity: {} };
const fail = (message) => failures.push(message);
const check = (condition, message) => {
  if (!condition) fail(message);
};

async function open(route, { width = 1280, theme, javaScriptEnabled = true, origin = base, init, before } = {}) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: "light", javaScriptEnabled, permissions: ["clipboard-read", "clipboard-write"] });
  if (theme) await context.addInitScript((value) => localStorage.setItem("benchbox:theme", value), theme);
  if (init) await context.addInitScript(init);
  const page = await context.newPage();
  if (before) await before(page);
  await page.goto(origin + route, { waitUntil: "networkidle" });
  return { page, context };
}

async function hydrated(page) {
  await page.waitForFunction(() => !document.querySelector("astro-island[ssr]") && location.search.includes("goal="), null, { timeout: 30000 });
  await settled(page);
}

async function stableSearch(page) {
  return page.evaluate(
    () =>
      new Promise((resolve) => {
        let previous = location.search;
        let steady = 0;
        const step = () => {
          steady = location.search === previous ? steady + 1 : 0;
          previous = location.search;
          if (steady >= 2 && previous.includes("goal=")) resolve(previous);
          else requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      }),
  );
}

async function settled(page) {
  await page.evaluate(async () => {
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await Promise.all(document.getAnimations().map((animation) => animation.finished.catch(() => undefined)));
  });
}

async function revealAll(page) {
  const height = await page.evaluate(() => document.body.scrollHeight);
  for (let y = 0; y < height; y += 400) {
    await page.evaluate(async (top) => {
      window.scrollTo(0, top);
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }, y);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await until(page, () => [...document.querySelectorAll(".feature-card, .benchmark-card, .install-step")].every((el) => getComputedStyle(el).opacity === "1"));
  await settled(page);
}

async function until(page, predicate, arg) {
  try {
    await page.waitForFunction(predicate, arg, { timeout: 20000 });
    return true;
  } catch {
    return false;
  }
}

const textIs = (page, selector, expected) => until(page, ([sel, text]) => document.querySelector(sel)?.textContent === text, [selector, expected]);

function luminance(rgb) {
  const [r, g, b] = rgb.match(/[\d.]+/g).slice(0, 3).map((v) => {
    const c = Number(v) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

{
  const requests = [];
  const { page, context } = await open("/", { before: (target) => target.on("request", (request) => requests.push(request.url())) });
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForLoadState("networkidle");
  await settled(page);
  const origin = new URL(base).origin;
  const foreign = requests.filter((url) => !url.startsWith(origin) && !url.startsWith("data:") && !url.startsWith("blob:"));
  const scriptSources = await page.evaluate(() => [...document.scripts].map((s) => s.src).filter(Boolean));
  const externalScripts = scriptSources.filter((src) => new URL(src).origin !== origin);
  report.network = { total: requests.length, foreign, externalScripts };
  check(foreign.length === 0, `third-party requests on /: ${foreign.join(", ")}`);
  check(externalScripts.length === 0, `third-party scripts on /: ${externalScripts.join(", ")}`);
  check(!requests.some((url) => /cdnjs|prismjs|prism/i.test(url)), "prism or cdnjs requested on /");
  check((await page.locator(".token").count()) === 0, "prism tokens present on /");

  const ids = await page.evaluate(() => [...document.querySelectorAll("[id]")].map((el) => el.id));
  for (const id of ["overview", "features", "results-explorer", "benchmarks", "platforms", "formats", "mcp", "install", "hero-code", "format-code", "mcp-setup-code", "install-code"]) {
    check(ids.includes(id), `missing id ${id} on /`);
  }
  const shiki = await page.evaluate(() => {
    const code = document.querySelector("#hero-code");
    return { spans: code.querySelectorAll("span[style*='color']").length, text: code.textContent, cls: code.className };
  });
  report.landing.shiki = shiki;
  check(shiki.spans > 0, "hero code is not highlighted at build time");
  check(shiki.text.startsWith("# CLI - Quick benchmarking\nbenchbox run"), "hero code text changed");

  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const heroCopy = page.locator('[data-target="hero-code"]');
  await page.evaluate(() => {
    const button = document.querySelector('[data-target="hero-code"]');
    window.__heroLabels = [];
    new MutationObserver(() => window.__heroLabels.push(button.textContent)).observe(button, { childList: true, characterData: true, subtree: true });
  });
  await heroCopy.click();
  await until(page, () => window.__heroLabels.includes("Copied!"));
  const label = (await page.evaluate(() => window.__heroLabels)).includes("Copied!") ? "Copied!" : await heroCopy.textContent();
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  report.landing.copy = { label, clip: clip.slice(0, 40) };
  check(label === "Copied!", `landing copy label is ${label}`);
  check(clip.startsWith("# CLI - Quick benchmarking"), "landing copy did not write the code text");

  await page.locator(".section-nav__link--platforms").click();
  await until(page, () => location.hash === "#platforms" && document.querySelector(".section-nav__link[aria-current='location']")?.textContent === "Platforms");
  const current = await page.locator(".section-nav__link[aria-current='location']").allTextContents();
  report.landing.sectionNav = current;
  check(current.join() === "Platforms", `section nav current after click is ${current}`);
  check((await page.evaluate(() => location.hash)) === "#platforms", "section nav did not update the hash");

  await page.keyboard.press("Tab");
  const skip = await page.evaluate(() => document.activeElement?.className);
  report.landing.skipLinkReachable = skip;
  await context.close();
}

const prismRoot = path.join(here, "..", "node_modules", "prismjs");
const prismTypes = { ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8" };

async function servePrism(context) {
  await context.route(/^https:\/\/cdnjs\.cloudflare\.com\/ajax\/libs\/prism\/1\.29\.0\//, async (route) => {
    const relative = new URL(route.request().url()).pathname.replace(/^\/ajax\/libs\/prism\/1\.29\.0\//, "");
    const file = path.join(prismRoot, relative);
    if (!file.startsWith(prismRoot) || !existsSync(file)) return route.fulfill({ status: 404, body: "" });
    return route.fulfill({ status: 200, contentType: prismTypes[path.extname(file)] ?? "text/plain", body: readFileSync(file) });
  });
}

const PRISM_TOMORROW_TEXT = "rgb(204, 204, 204)";

function codeColours(page) {
  return page.evaluate(() => {
    const blocks = [...document.querySelectorAll(".code-block pre code")];
    const resolve = (host, variable) => {
      const probe = document.createElement("span");
      probe.style.color = `var(${variable})`;
      host.appendChild(probe);
      const color = getComputedStyle(probe).color;
      probe.remove();
      return color;
    };
    return {
      fg: getComputedStyle(blocks[0].closest("pre")).color,
      bg: getComputedStyle(blocks[0].closest(".code-block")).backgroundColor,
      variables: Object.fromEntries(["--text-muted", "--code-line-number", "--code-comment", "--text-secondary", "--prism-string", "--prism-keyword", "--prism-deleted", "--prism-variable", "--prism-operator"].map((name) => [name, resolve(blocks[0], name)])),
      blocks: blocks.map((code) => {
        const chars = [];
        const walker = document.createTreeWalker(code, NodeFilter.SHOW_TEXT);
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
          const color = getComputedStyle(node.parentElement).color;
          for (const ch of node.textContent) if (!/\s/.test(ch)) chars.push([ch, color]);
        }
        return chars;
      }),
    };
  });
}

for (const theme of ["light", "dark"]) {
  const old = await open("/", { theme, origin: oldBase, before: (target) => servePrism(target.context()) });
  const prismLoaded = await until(old.page, () => document.querySelectorAll(".token").length > 20 && document.querySelector("#install .token.keyword"));
  check(prismLoaded, `Prism did not highlight the static page in ${theme}`);
  const oldColours = await codeColours(old.page);
  await old.context.close();
  const current = await open("/", { theme });
  const newColours = await codeColours(current.page);
  await current.context.close();

  const translate = (color) => {
    if (color === PRISM_TOMORROW_TEXT) return newColours.fg;
    const names = Object.keys(oldColours.variables).filter((name) => oldColours.variables[name] === color);
    if (theme === "dark" || names.length === 0) return color;
    const mapped = new Set(names.map((name) => newColours.variables[name === "--text-muted" ? "--code-comment" : name]));
    return mapped.size === 1 ? [...mapped][0] : color;
  };
  const differences = [];
  check(oldColours.blocks.length === newColours.blocks.length, `code block count differs in ${theme}`);
  oldColours.blocks.forEach((oldChars, index) => {
    const newChars = newColours.blocks[index] ?? [];
    check(oldChars.map(([ch]) => ch).join("") === newChars.map(([ch]) => ch).join(""), `code text differs in block ${index}`);
    let run = null;
    oldChars.forEach(([ch, color], position) => {
      const want = translate(color);
      const got = newChars[position]?.[1];
      if (want === got) {
        run = null;
        return;
      }
      if (run && run.want === want && run.got === got) run.text += ch;
      else {
        run = { block: index, text: ch, want, got, was: color };
        differences.push(run);
      }
    });
  });
  const ratios = Object.fromEntries([...new Set(newColours.blocks.flat().map(([, color]) => color))].map((color) => [color, contrast(color, newColours.bg)]));
  for (const [color, ratio] of Object.entries(ratios)) check(ratio >= 4.5, `code colour ${color} on ${newColours.bg} in ${theme} is ${ratio.toFixed(2)}:1`);
  report.landing[`tokens ${theme}`] = { ratios, variables: newColours.variables, oldVariables: oldColours.variables, differences };
  for (const d of differences.slice(0, 12)) fail(`code colour in ${theme}, block ${d.block}, "${d.text}": Prism page ${d.was} (expected ${d.want}), Astro ${d.got}`);
  if (differences.length > 12) fail(`${differences.length - 12} more code colour differences in ${theme}`);
}

for (const [route, name] of [["/", "landing"], ["/prompts/", "prompts"]]) {
  for (const theme of ["light", "dark"]) {
    for (const width of [400, 768, 1280]) {
      const { page, context } = await open(route, { width, theme });
      if (route === "/prompts/") await hydrated(page);
      else await revealAll(page);
      const result = await new AxeBuilder({ page }).analyze();
      const key = `${name} ${theme} ${width}`;
      report[name === "landing" ? "landing" : "prompts"][`axe ${theme} ${width}`] = result.violations.map((v) => `${v.id}:${v.impact}`);
      if (result.violations.length) fail(`axe ${key}: ${result.violations.map((v) => `${v.id} ${v.nodes.slice(0, 2).map((n) => n.target.join(" ")).join("|")}`).join("; ")}`);
      if (route === "/") {
        const code = await new AxeBuilder({ page }).include("pre").withRules(["color-contrast"]).analyze();
        if (code.violations.length) fail(`axe code blocks ${key}: ${code.violations.map((v) => `${v.id} ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join("|")}`).join("; ")}`);
      }
      const overflow = await page.evaluate(() => document.scrollingElement.scrollWidth - window.innerWidth);
      check(overflow <= 0, `horizontal overflow ${key}: ${overflow}`);
      await context.close();
    }
  }
}

{
  const { page, context } = await open("/prompts/");
  await hydrated(page);
  check((await page.locator("h1").allTextContents()).join() === "Instruct a coding agent to use BenchBox", "prompts h1 changed");

  const names = ["Goal", "Surface", "Interface", "Deployment", "Platform", "Benchmark", "Scale"];
  for (const name of names) check((await page.getByRole("combobox", { name, exact: true }).count()) === 1, `select ${name} has no accessible name`);

  const order = [];
  await page.focus("#sel-goal");
  for (let i = 0; i < 12; i++) {
    const info = await page.evaluate(() => {
      const el = document.activeElement;
      return { id: el.id, inPage: Boolean(el.closest(".prompts-page")), target: el.getAttribute("data-copy-target") };
    });
    if (!info.inPage) break;
    order.push(info.id || `copy:${info.target}`);
    await page.keyboard.press("Tab");
  }
  report.prompts.tabOrder = order;
  const expectedOrder = ["sel-goal", "sel-surface", "sel-interface", "sel-deployment", "sel-platform", "sel-benchmark", "sel-scale", "copy:prompt-text"];
  check(order.slice(0, expectedOrder.length).join() === expectedOrder.join(), `tab order ${order}`);
  const back = [];
  await page.focus('[data-copy-target="prompt-text"]');
  for (let i = 0; i < expectedOrder.length; i++) {
    back.push(await page.evaluate(() => document.activeElement.id || `copy:${document.activeElement.getAttribute("data-copy-target")}`));
    await page.keyboard.press("Shift+Tab");
  }
  check(back.join() === [...expectedOrder].reverse().join(), `shift+tab order ${back}`);

  const focusVisible = [];
  for (const selector of ["#sel-goal", "#sel-scale", '[data-copy-target="prompt-text"]']) {
    await page.focus("body");
    const before = await page.locator(selector).evaluate((el) => getComputedStyle(el).backgroundColor);
    await page.locator(selector).focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    await settled(page);
    const state = await page.locator(selector).evaluate((el) => {
      const style = getComputedStyle(el);
      return { outline: style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0, bg: style.backgroundColor };
    });
    const visible = state.outline || state.bg !== before;
    focusVisible.push([selector, visible]);
    check(visible, `no visible focus indicator on ${selector}`);
  }
  report.prompts.focusVisible = focusVisible;

  const reachable = new Set();
  await page.focus("body");
  for (let i = 0; i < 80; i++) {
    await page.keyboard.press("Tab");
    reachable.add(await page.evaluate(() => document.activeElement.id || document.activeElement.getAttribute("data-copy-target") || document.activeElement.getAttribute("aria-label") || document.activeElement.textContent.trim().slice(0, 16)));
  }
  report.prompts.tabStops = [...reachable];
  for (const needed of ["sel-goal", "sel-scale", "prompt-text"]) check(reachable.has(needed), `keyboard cycle never reached ${needed}`);
  check([...reachable].some((stop) => /theme$/i.test(stop)), "keyboard cycle never reached the theme control");
  check(reachable.size < 80, "keyboard focus never repeats, which suggests a trap");

  for (const key of ["Enter", "Space"]) {
    await page.evaluate(() => {
      window.__written = [];
      navigator.clipboard.writeText = async (text) => void window.__written.push(text);
    });
    await page.focus('[data-copy-target="prompt-text"]');
    await page.keyboard.press(key);
    await until(page, () => window.__written.length > 0);
    const written = await page.evaluate(() => window.__written.length);
    check(written === 1, `${key} on copy wrote ${written} times`);
  }

  const status = await page.locator("#copy-status").evaluate((el) => ({ role: el.getAttribute("role"), live: el.getAttribute("aria-live") }));
  check(status.role === "status" && status.live === "polite", "copy status is not a polite live region");
  check(await until(page, () => document.querySelector('[data-copy-target="prompt-text"]').textContent === "Copy" && document.querySelector("#copy-status").textContent === ""), "copy control did not return to idle");
  await page.evaluate(() => {
    window.__labels = [];
    window.__statuses = [];
    const button = document.querySelector('[data-copy-target="prompt-text"]');
    const region = document.querySelector("#copy-status");
    new MutationObserver(() => window.__labels.push(button.textContent)).observe(button, { childList: true, characterData: true, subtree: true });
    new MutationObserver(() => window.__statuses.push(region.textContent)).observe(region, { childList: true, characterData: true, subtree: true });
  });
  await page.locator('[data-copy-target="prompt-text"]').click();
  check(await until(page, () => window.__labels.includes("Copied") && window.__labels.at(-1) === "Copy"), "copy label did not change and reset");
  const history = await page.evaluate(() => ({ labels: window.__labels, statuses: window.__statuses }));
  check(history.statuses.includes("Copied agent prompt"), `copy status text history ${history.statuses}`);
  check(await until(page, () => document.querySelector("#copy-status").textContent === ""), "copy status did not clear");

  await page.selectOption("#sel-surface", "mcp");
  await until(page, () => !document.querySelector("#block-mcp-setup").hidden);
  await page.locator('[data-copy-target="mcp-setup-text"]').click();
  check(await textIs(page, "#copy-status", "Copied MCP server config"), "mcp copy status text");

  await page.selectOption("#sel-goal", "compare");
  await until(page, () => !document.querySelector("#sel-platformA").closest("label").hidden && document.querySelector("#sel-platformA").options.length > 0);
  check((await page.getByRole("combobox", { name: "Platform A" }).count()) === 1, "Platform A not exposed in compare");
  check((await page.getByRole("combobox", { name: "Platform B" }).count()) === 1, "Platform B not exposed in compare");
  check((await page.getByRole("combobox", { name: "Platform", exact: true }).count()) === 0, "Platform still exposed in compare");
  check((await page.locator("#prompt-text").textContent()).includes("compare"), "compare prompt not rendered");
  await page.selectOption("#sel-goal", "test_one");
  await until(page, () => !document.querySelector("#sel-platform").closest("label").hidden && document.querySelector("#sel-platform").options.length > 0);
  check((await page.getByRole("combobox", { name: "Platform", exact: true }).count()) === 1, "Platform not restored");
  check((await page.getByRole("combobox", { name: "Platform A" }).count()) === 0, "Platform A still exposed");

  const sqlPlatforms = await page.locator("#sel-platform option").count();
  await page.selectOption("#sel-interface", "dataframe");
  await until(page, (before) => document.querySelector("#sel-platform").options.length < before && ![...document.querySelectorAll("#sel-benchmark option")].some((o) => o.textContent === "ClickBench"), sqlPlatforms);
  const dfPlatforms = await page.locator("#sel-platform option").count();
  const dfBenchmarks = await page.locator("#sel-benchmark option").allTextContents();
  await page.selectOption("#sel-deployment", "managed");
  await until(page, () => location.search.includes("deployment=managed") && document.querySelector("#sel-platform").options.length > 0);
  const managedPlatforms = await page.locator("#sel-platform option").allTextContents();
  report.prompts.filter = { sqlPlatforms, dfPlatforms, dfBenchmarks, managedPlatforms: managedPlatforms.length };
  check(dfPlatforms > 0 && dfPlatforms < sqlPlatforms, "interface filter did not narrow platforms");
  check(!dfBenchmarks.includes("ClickBench"), "interface filter kept an unsupported benchmark");
  check(managedPlatforms.length > 0, "deployment filter emptied platforms");
  check((await page.evaluate(() => location.search)).includes("deployment=managed"), "url did not record deployment");

  await page.selectOption("#sel-interface", "sql");
  await until(page, () => location.search.includes("interface=sql"));
  await page.selectOption("#sel-deployment", "managed");
  await until(page, () => location.search.includes("deployment=managed") && location.search.includes("interface=sql"));
  const safetyBefore = await page.locator("#block-cloud-safety").isVisible();
  const options = await page.locator("#sel-platform option").evaluateAll((list) => list.map((o) => o.value));
  let safetyShown = safetyBefore;
  for (const value of options) {
    await page.selectOption("#sel-platform", value);
    check(await until(page, (id) => location.search.includes(`platform=${id}`), value), `url did not record platform ${value}`);
    if (await page.locator("#block-cloud-safety").isVisible()) {
      safetyShown = true;
      break;
    }
  }
  check(safetyShown, "credential safety block never shown for managed platforms");
  const glyph = await page.locator("#block-cloud-safety h2").evaluate((el) => getComputedStyle(el, "::before").content);
  report.prompts.safetyGlyph = glyph;
  check(glyph.includes("⚠"), "credential safety heading has no warning glyph");
  check((await page.locator("#cloud-safety-list li").count()) > 0, "credential safety list empty");

  const url = await stableSearch(page);
  await page.reload({ waitUntil: "networkidle" });
  await hydrated(page);
  check(await until(page, () => document.querySelector("#sel-deployment").value === "managed"), "deployment not restored from the url");
  check((await stableSearch(page)) === url, "url state changed across reload");
  await context.close();
}

{
  const { page, context } = await open("/prompts/", {
    init: () => {
      Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
      window.__exec = [];
      document.execCommand = (command) => {
        window.__exec.push(command);
        return true;
      };
    },
  });
  await hydrated(page);
  await page.locator('[data-copy-target="prompt-text"]').click();
  const exec = await page.evaluate(() => window.__exec);
  check(exec.join() === "copy", `execCommand fallback calls ${exec}`);
  check(await textIs(page, "#copy-status", "Copied agent prompt"), "fallback copy status");
  await context.close();
}

{
  const { page, context } = await open("/prompts/", { javaScriptEnabled: false });
  const noscript = await page.evaluate(() => document.querySelector("noscript")?.textContent ?? "");
  const rendered = await page.locator(".prompts-noscript").isVisible();
  check(rendered, "noscript fallback is not rendered without JavaScript");
  check(noscript.includes("uv add 'benchbox[duckdb]' && uv run benchbox run --platform duckdb --benchmark tpch --scale 0.01") || (await page.locator(".prompts-noscript code").textContent()).includes("uv run benchbox run --platform duckdb"), "noscript recipe missing");
  await context.close();
}

for (const theme of ["light", "dark"]) {
  const { page, context } = await open("/prompts/", { theme });
  await hydrated(page);
  const body = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const lede = await page.locator(".prompts-lede").evaluate((el) => getComputedStyle(el).color);
  const label = await page.locator(".prompts-field > span").first().evaluate((el) => getComputedStyle(el).color);
  const fieldBg = await page.locator(".prompts-form").evaluate((el) => getComputedStyle(el).backgroundColor);
  const ratios = { lede: contrast(lede, body), label: contrast(label, fieldBg) };
  const button = page.locator('[data-copy-target="prompt-text"]');
  const idle = await button.evaluate((el) => ({ color: getComputedStyle(el).color, bg: getComputedStyle(el).backgroundColor }));
  await button.hover();
  await until(page, (idleBg) => getComputedStyle(document.querySelector('[data-copy-target="prompt-text"]')).backgroundColor !== idleBg, idle.bg);
  await settled(page);
  const hover = await button.evaluate((el) => ({ color: getComputedStyle(el).color, bg: getComputedStyle(el).backgroundColor }));
  ratios.copyIdle = contrast(idle.color, idle.bg);
  ratios.copyHover = contrast(hover.color, hover.bg);
  report.prompts[`contrast ${theme}`] = ratios;
  for (const [name, ratio] of Object.entries(ratios)) check(ratio >= 4.5, `contrast ${name} ${theme} is ${ratio.toFixed(2)}`);
  await context.close();
}

{
  const { page, context } = await open("/prompts/", { width: 400 });
  await hydrated(page);
  const lefts = await page.locator(".prompts-field:not([hidden])").evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().left)));
  check(new Set(lefts).size === 1, `fields do not stack at 400px: ${lefts}`);
  await page.selectOption("#sel-platform", { index: 0 });
  const copy = await page.locator('[data-copy-target="prompt-text"]').boundingBox();
  check(copy && copy.x >= 0 && copy.x + copy.width <= 400, "copy button not reachable at 400px");
  await context.close();
}

{
  const { page, context } = await open("/prompts/", { width: 768 });
  await hydrated(page);
  const rects = await page.locator(".prompts-field:not([hidden])").evaluateAll((els) => els.map((el) => el.getBoundingClientRect().toJSON()));
  const overlap = rects.some((a, i) => rects.some((b, j) => i < j && a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1));
  check(!overlap, "fields overlap at 768px");
  await context.close();
}

{
  const { page, context } = await open("/prompts/", { width: 1280 });
  await hydrated(page);
  const widths = await page.evaluate(() => ({ form: document.querySelector("#prompts-form").getBoundingClientRect().width, block: document.querySelector("#block-prompt").getBoundingClientRect().width }));
  check(Math.abs(widths.form - widths.block) <= 2, `output block does not span the content column: ${JSON.stringify(widths)}`);
  await context.close();
}

{
  const catalogRaw = await (await fetch(`${oldBase}/prompts/catalog.generated.js`)).text();
  const catalog = JSON.parse(catalogRaw.slice(catalogRaw.indexOf("{"), catalogRaw.lastIndexOf("}") + 1));
  const combos = [];
  for (const goal of catalog.goals.map((g) => g.id))
    for (const surface of catalog.surfaces.map((s) => s.id))
      for (const iface of catalog.interfaces.map((i) => i.id))
        for (const deployment of catalog.deployments.map((d) => d.id))
          for (const scale of ["0.01", "1.0"]) combos.push({ goal, surface, interface: iface, deployment, scale });
  for (const platform of catalog.platforms) combos.push({ platform: platform.id, surface: "mcp", scale: "1.0", deployment: platform.deployments[0], interface: platform.interfaces[0] }, { platform: platform.id, deployment: platform.deployments[0], interface: platform.interfaces[0], scale: "0.1" });
  for (const [key, value] of [["goal", "bogus"], ["surface", "bogus"], ["interface", "bogus"], ["deployment", "bogus"], ["benchmark", "bogus"], ["scale", "bogus"], ["platform", "bogus"]])
    combos.push({ [key]: value }, { [key]: value, surface: "mcp", scale: "1.0" });
  combos.push({ goal: "compare", platformA: "bogus", platformB: "bogus" }, { goal: "compare", platformA: "bogus", platformB: "bogus", surface: "mcp" });
  for (const benchmark of catalog.benchmarks) combos.push({ benchmark: benchmark.id, scale: "0.1" }, { benchmark: benchmark.id, scale: "0.01", surface: "mcp" });
  const a = await open("/prompts/", { origin: oldBase });
  const b = await open("/prompts/");
  const snapshot = (page) =>
    page.evaluate(() => ({
      prompt: document.querySelector("#prompt-text").textContent,
      mcp: document.querySelector("#mcp-setup-text").textContent,
      mcpHidden: document.querySelector("#block-mcp-setup").hidden,
      safetyHidden: document.querySelector("#block-cloud-safety").hidden,
      safety: [...document.querySelectorAll("#cloud-safety-list li")].map((li) => li.textContent),
      selects: [...document.querySelectorAll("select")].map((s) => [s.id, s.value, [...s.options].map((o) => o.value + "=" + o.textContent), s.closest("label").hidden]),
      search: location.search,
    }));
  const canonical = (snap) => {
    const params = new URLSearchParams(snap.search);
    for (const [key, list] of [["goal", catalog.goals], ["surface", catalog.surfaces]]) if (params.has(key) && !list.some((item) => item.id === params.get(key))) params.set(key, catalog.defaults[key]);
    return { ...snap, search: params.toString() };
  };
  let mismatches = 0;
  for (const combo of combos) {
    const query = new URLSearchParams(combo).toString();
    await a.page.goto(`${oldBase}/prompts/?${query}`);
    await b.page.goto(`${base}/prompts/?${query}`);
    await hydrated(b.page);
    const [x, y] = [canonical(await snapshot(a.page)), canonical(await snapshot(b.page))];
    if (JSON.stringify(x) !== JSON.stringify(y)) {
      mismatches += 1;
      if (mismatches <= 5) fail(`prompt parity mismatch for ?${query}: ${Object.keys(x).filter((k) => JSON.stringify(x[k]) !== JSON.stringify(y[k]))}`);
    }
  }
  report.parity = { combos: combos.length, mismatches };
  check(mismatches === 0, `${mismatches} prompt parity mismatches`);
  await a.context.close();
  await b.context.close();
}

await browser.close();
for (const server of servers) server.close();
report.failures = failures;
writeFileSync(path.join(outDir, "landing.json"), JSON.stringify(report, null, 2));
console.log(`wrote ${path.join(outDir, "landing.json")}`);
if (failures.length) {
  console.error(failures.join("\n"));
  process.exitCode = 1;
} else {
  console.log("landing checks passed");
}
