import { codeToTokens } from "shiki";
import { describe, expect, it } from "vitest";
import { landingCodeTheme, landingTransformers } from "../src/lib/code-theme.ts";

async function colours(lang: "bash" | "python", code: string): Promise<Map<string, string | undefined>> {
  const { tokens } = await codeToTokens(code, { lang, theme: landingCodeTheme });
  const found = new Map<string, string | undefined>();
  for (const token of tokens.flat()) {
    const node = { type: "element" as const, tagName: "span", properties: { style: `color:${token.color}` }, children: [] };
    for (const transformer of landingTransformers(lang)) transformer.span?.call({} as never, node, 1, 1, {} as never, token);
    const style = String(node.properties.style);
    found.set(token.content.trim(), style.slice(style.indexOf("color:") + 6).split(";")[0]);
  }
  return found;
}

describe("landing code theme", () => {
  it("maps comments, strings and keywords to the page palette variables", async () => {
    const bash = await colours("bash", '# note\necho "hi"');
    expect(bash.get("# note")).toBe("var(--code-comment)");
    expect(bash.get('"hi"')).toBe("var(--prism-string)");
    expect(bash.get("echo")).toBe("var(--prism-keyword)");
    const python = await colours("python", "from benchbox import TPCH");
    expect(python.get("from")).toBe("var(--prism-keyword)");
    expect(python.get("import")).toBe("var(--prism-keyword)");
  });

  it("colours shell options like Prism parameters and leaves other words plain", async () => {
    const bash = await colours("bash", "benchbox run --platform duckdb --dry-run -m x --scale 0.1");
    expect(bash.get("--platform")).toBe("var(--prism-variable)");
    expect(bash.get("-m")).toBe("var(--prism-variable)");
    expect(bash.get("--scale")).toBe("var(--prism-variable)");
    expect(bash.get("--dry-run")).toBe("var(--code-fg)");
    expect(bash.get("benchbox")).toBe("var(--code-fg)");
    expect(bash.get("run")).toBe("var(--code-fg)");
    expect(bash.get("0.1")).toBe("var(--prism-deleted)");
  });

  it("colours the words Prism treats as shell keywords", async () => {
    const bash = await colours("bash", "uv add benchbox\nfrom benchbox import TPCH");
    expect(bash.get("add")).toBe("var(--prism-keyword)");
    expect(bash.get("import")).toBe("var(--prism-keyword)");
    expect(bash.get("uv")).toBe("var(--code-fg)");
  });

  it("uses the secondary colour for call punctuation and not for keyword arguments", async () => {
    const python = await colours("python", "tpch = TPCH(scale_factor=0.1)");
    expect(python.get(")")).toBe("var(--code-punctuation)");
    expect(python.get("scale_factor")).toBe("var(--code-fg)");
    expect(python.get("=")).toBe("var(--prism-operator)");
    expect(python.get("0.1")).toBe("var(--prism-deleted)");
  });
});
