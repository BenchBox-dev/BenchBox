// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = fileURLToPath(new URL(".", import.meta.url));
const css = readFileSync(resolve(here, "../index.css"), "utf8");

function ruleBody(selector: string): string {
  const start = css.indexOf(`${selector} {`);
  expect(start, `${selector} must be declared`).toBeGreaterThanOrEqual(0);
  return css.slice(start, css.indexOf("}", start));
}

describe("Explorer link colour scoping", () => {
  it("scopes link colours with :where so a link styled as a button keeps its own colour", () => {
    expect(ruleBody(":where(.bb-explorer) a")).toContain("color: var(--bb-accent)");
    expect(ruleBody(":where(.bb-explorer) a:hover")).toContain("color: var(--bb-accent-hover)");
  });

  it("never lets the page scope raise the specificity of a link colour rule", () => {
    const colourRules = [...css.matchAll(/^\s*([^{}@\n][^{}\n]*)\{\s*[^}]*?\bcolor:/gm)].map((match) => (match[1] ?? "").trim());
    const scoped = colourRules.filter((selector) => /\.bb-explorer(-page)?\s+a\b/.test(selector) && !selector.includes(":where("));
    expect(scoped).toEqual([]);
  });

  it("keeps the primary button text on the on-accent token in the resting state", () => {
    expect(ruleBody(".btn-primary")).toContain("color: var(--bb-fg-on-accent)");
  });
});
