import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { codeToTokensBase } from "shiki";
import { describe, expect, it } from "vitest";

const here = path.dirname(fileURLToPath(import.meta.url));
const pygmentsSource = readFileSync(path.join(here, "..", "..", "docs", "_static", "pygments_cobalt2.py"), "utf-8");
const theme = JSON.parse(readFileSync(path.join(here, "..", "src", "lib", "cobalt2-theme.json"), "utf-8"));

type Rule = { name: string; scope: string | string[]; settings: { foreground?: string; fontStyle?: string; background?: string } };

function normalize(color: string): string {
  const hex = color.toLowerCase();
  return hex.length === 4 ? `#${hex[1]}${hex[1]}${hex[2]}${hex[2]}${hex[3]}${hex[3]}` : hex;
}

function pygmentsStyles(): Map<string, { color?: string; bold: boolean; italic: boolean }> {
  const styles = new Map<string, { color?: string; bold: boolean; italic: boolean }>();
  const body = pygmentsSource.slice(pygmentsSource.indexOf("styles = {"));
  for (const match of body.matchAll(/^\s+([A-Za-z.]+): "([^"]*)"/gm)) {
    const parts = match[2].split(/\s+/).filter(Boolean);
    const color = parts.find((part) => part.startsWith("#") && !part.startsWith("bg:"));
    styles.set(match[1], { color: color ? normalize(color) : undefined, bold: parts.includes("bold"), italic: parts.includes("italic") });
  }
  return styles;
}

function ruleNamed(name: string): Rule {
  const rule = (theme.tokenColors as Rule[]).find((candidate) => candidate.name === name);
  if (rule === undefined) throw new Error(`no rule ${name}`);
  return rule;
}

const styles = pygmentsStyles();

describe("cobalt2 theme", () => {
  it("matches the Pygments background and default foreground", () => {
    const background = /background_color = "(#[0-9a-fA-F]+)"/.exec(pygmentsSource)?.[1] ?? "";
    expect(theme.colors["editor.background"].toLowerCase()).toBe(normalize(background));
    expect(normalize(theme.colors["editor.foreground"])).toBe(styles.get("Text")?.color);
  });

  const rulesToTokens = [
    "Comment", "Comment.Preproc", "Comment.PreprocFile", "Keyword", "Keyword.Namespace", "Keyword.Constant", "Keyword.Pseudo",
    "Keyword.Type", "Operator", "Operator.Word", "Number", "String", "String.Doc", "String.Backtick", "String.Escape",
    "String.Interpol", "String.Regex", "String.Symbol", "Name.Attribute", "Name.Builtin", "Name.Builtin.Pseudo", "Name.Class",
    "Name.Constant", "Name.Decorator", "Name.Exception", "Name.Function", "Name.Function.Magic", "Name.Label", "Name.Tag",
    "Generic.Deleted", "Generic.Inserted", "Generic.Heading",
  ];

  it.each(rulesToTokens)("maps %s to the same colour and emphasis", (token) => {
    const expected = styles.get(token);
    expect(expected).toBeDefined();
    const settings = ruleNamed(token).settings;
    expect(normalize(settings.foreground ?? "")).toBe(expected?.color);
    const fontStyle = settings.fontStyle ?? "";
    expect(fontStyle.includes("bold")).toBe(expected?.bold);
    expect(fontStyle.includes("italic")).toBe(expected?.italic);
  });

  it("renders a Python snippet with the Pygments colours", async () => {
    const code = ['import os', 'class Runner:', '    def run(self, n=3):', '        # note', '        return len("x") + n'].join("\n");
    const lines = await codeToTokensBase(code, { lang: "python", theme: theme });
    const colorOf = (text: string) => {
      const token = lines.flat().find((candidate) => candidate.content.trim() === text);
      return normalize(token?.color ?? "");
    };
    expect(colorOf("import")).toBe(styles.get("Keyword.Namespace")?.color);
    expect(colorOf("class")).toBe(styles.get("Keyword")?.color);
    expect(colorOf("Runner")).toBe(styles.get("Name.Class")?.color);
    expect(colorOf("run")).toBe(styles.get("Name.Function")?.color);
    expect(colorOf("3")).toBe(styles.get("Number")?.color);
    expect(colorOf("# note")).toBe(styles.get("Comment")?.color);
    expect(colorOf("len")).toBe(styles.get("Name.Builtin")?.color);
    expect(colorOf("return")).toBe(styles.get("Keyword")?.color);
    expect(colorOf("+")).toBe(styles.get("Operator")?.color);
    expect(colorOf("self")).toBe(styles.get("Name.Builtin.Pseudo")?.color);
  });
});
