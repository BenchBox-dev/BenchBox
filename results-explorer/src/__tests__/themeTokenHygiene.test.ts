// @vitest-environment node

import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = fileURLToPath(new URL(".", import.meta.url));
const srcRoot = resolve(here, "..");
const themeCss = readFileSync(join(srcRoot, "index.css"), "utf8");

const THEME_INVARIANT_TOKENS = new Set([
  "--bb-bp-desktop",
  "--bb-bp-mobile",
  "--bb-bp-tablet",
  "--bb-font-mono",
  "--bb-font-sans",
  "--bb-inset-bottom",
  "--bb-inset-left",
  "--bb-inset-right",
  "--bb-inset-top",
  "--bb-skeleton-radius-md",
  "--bb-skeleton-radius-sm",
  "--bb-skeleton-row-height",
  "--bb-text-2xl",
  "--bb-text-base",
  "--bb-text-lg",
  "--bb-text-sm",
  "--bb-text-xl",
  "--bb-text-xs",
]);

function tokens(pattern: RegExp, source: string): Set<string> {
  return new Set([...source.matchAll(pattern)].map((match) => match[1]!));
}

function ruleBody(selector: string): string {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = themeCss.match(new RegExp(`${escapedSelector}\\s*\\{([\\s\\S]*?)\\n\\s*\\}`));
  if (!match) throw new Error(`Theme selector not found: ${selector}`);
  return match[1]!;
}

function collectRuntimeSources(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "__tests__") continue;
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      collectRuntimeSources(path, out);
    } else if (entry.isFile() && /\.(css|ts|tsx)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name)) {
      out.push(readFileSync(path, "utf8"));
    }
  }
  return out;
}

function missingTokens(source: string, declared: Set<string>): string[] {
  return [...tokens(/var\((--bb-[a-z0-9-]+)/g, source)].filter((token) => !declared.has(token)).sort();
}

describe("theme token hygiene", () => {
  it("declares every referenced --bb-* token", () => {
    const declared = tokens(/(--bb-[a-z0-9-]+)\s*:/g, ruleBody(":root"));
    const runtimeSource = collectRuntimeSources(srcRoot).join("\n");

    expect(missingTokens(runtimeSource, declared)).toEqual([]);
  });

  it("requires dark overrides unless a token is explicitly theme-invariant", () => {
    const light = tokens(/(--bb-[a-z0-9-]+)\s*:/g, ruleBody(":root"));
    const dark = tokens(/(--bb-[a-z0-9-]+)\s*:/g, ruleBody(':root[data-bb-theme="dark"]'));
    const lightOnly = [...light].filter((token) => !dark.has(token)).sort();

    expect(lightOnly).toEqual([...THEME_INVARIANT_TOKENS].sort());
  });

  it("reports a deliberately undeclared token", () => {
    const syntheticReference = "color: " + "var(" + "--bb-deliberately-undeclared);";
    expect(missingTokens(syntheticReference, new Set())).toEqual([
      "--bb-deliberately-undeclared",
    ]);
  });
});
