import { codeToTokens } from "shiki";
import { describe, expect, it } from "vitest";
import { landingCodeTheme } from "../src/lib/code-theme.ts";

async function colours(lang: "bash" | "python", code: string): Promise<Map<string, string | undefined>> {
  const { tokens } = await codeToTokens(code, { lang, theme: landingCodeTheme });
  return new Map(tokens.flat().map((token) => [token.content.trim(), token.color]));
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

  it("leaves commands and unquoted arguments in the code foreground", async () => {
    const bash = await colours("bash", "benchbox run --platform duckdb");
    expect(bash.get("benchbox")).toBe("var(--code-fg)");
    expect(bash.get("run")).toBe("var(--code-fg)");
  });
});
