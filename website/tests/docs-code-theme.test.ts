import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = path.dirname(fileURLToPath(import.meta.url));
const theme = JSON.parse(readFileSync(path.join(here, "..", "src", "lib", "code-theme.json"), "utf-8"));
const tokens = readFileSync(path.join(here, "..", "..", "landing", "shared", "site-tokens.css"), "utf-8");
const config = readFileSync(path.join(here, "..", "astro.config.ts"), "utf-8");

type Rule = { name: string; settings: { foreground?: string; background?: string } };

function block(selector: string): string {
  const start = tokens.indexOf(`${selector} {`);
  return tokens.slice(start, tokens.indexOf("}", start));
}

function token(css: string, name: string): string {
  const match = new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6});`).exec(css);
  if (!match) throw new Error(`missing --${name}`);
  return match[1].toLowerCase();
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((index) => {
    const channel = Number.parseInt(hex.slice(index, index + 2), 16) / 255;
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const light = block(":root");
const dark = block(':root[data-bb-theme="dark"]');
const grounds = { light: token(light, "code-bg"), dark: token(dark, "code-bg") };
const foregrounds = [
  ...new Set(
    (theme.tokenColors as Rule[])
      .filter((rule) => rule.settings.foreground && !rule.settings.background)
      .map((rule) => rule.settings.foreground!.toLowerCase()),
  ),
];

describe("docs code theme", () => {
  it("uses the shared code foreground and the dark code ground", () => {
    expect(theme.colors["editor.foreground"].toLowerCase()).toBe(token(light, "code-fg"));
    expect(theme.colors["editor.background"].toLowerCase()).toBe(grounds.dark);
  });

  it("paints code blocks from the shared code tokens", () => {
    expect(config).toContain('codeBackground: "var(--code-bg)"');
    expect(config).toContain('codeForeground: "var(--code-fg)"');
    expect(config).not.toContain("cobalt2");
  });

  it.each(Object.entries(grounds))("keeps every token colour at 4.5:1 on the %s code ground", (_, ground) => {
    for (const foreground of foregrounds) expect(contrast(foreground, ground), foreground).toBeGreaterThanOrEqual(4.5);
  });
});
