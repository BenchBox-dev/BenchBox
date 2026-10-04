import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildSite, loadKnownBrokenLinks } from "../src/converter/build.ts";

const websiteRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const baselineDirectory = path.join(websiteRoot, "..", "_project", "design", "site-inventory", "baseline-develop");
const THEME_ID = /^(svg-|toctree-checkbox-|__navigation$|__toc$|searchbox$|furo-main-content$|benchbox-site-header-nav$|post-meta-data$)/;

type BaselinePage = { ids: string[] };

const baseline = new Map<string, Set<string>>();
for (const name of readdirSync(baselineDirectory).filter((entry) => /^pages-(docs|blog)-/.test(entry))) {
  const pages = JSON.parse(readFileSync(path.join(baselineDirectory, name), "utf-8")) as Record<string, BaselinePage>;
  for (const [route, page] of Object.entries(pages)) baseline.set(route, new Set(page.ids.filter((id) => !THEME_ID.test(id))));
}

const knownBrokenLinks = loadKnownBrokenLinks(path.join(websiteRoot, "..", "_project", "design", "site-inventory", "known-broken-links.json"));
const result = buildSite({ docsRoot: path.join(websiteRoot, "..", "docs"), knownBrokenLinks });
let compared = 0;
let lost = 0;
const lines: string[] = [];
for (const info of result.infos) {
  const expected = baseline.get(info.route);
  if (!expected) continue;
  compared += 1;
  const produced = new Set(info.ids);
  const missing = [...expected].filter((id) => !produced.has(id)).sort();
  lost += missing.length;
  if (missing.length > 0) lines.push(`${info.route}: lost ${missing.join(", ")}`);
}
process.stdout.write(`${lines.join("\n")}\ncompared ${compared} pages, ${lost} lost ids\n`);
