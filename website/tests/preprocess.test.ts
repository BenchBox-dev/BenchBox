import { afterEach, describe, expect, it } from "vitest";
import type { UnknownConstructError } from "../src/converter/errors.ts";
import { build, bodyOf, cleanup } from "./support.ts";

afterEach(cleanup);

function constructs(files: Record<string, string>): string[] {
  return build(files).errors.map((error) => `${error.line} ${(error as UnknownConstructError).construct}`);
}

describe("label, attrs and comment lines", () => {
  it("leave indented code and raw html blocks literal", () => {
    const result = build({ "a.md": "# A\n\nIndented code:\n\n    {#notattr}\n    (notlabel)=\n    % kept\n\n<div>\n(htmllabel)=\n</div>\n" });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body).toContain("```\n{#notattr}\n(notlabel)=\n% kept\n```");
    expect(body).toContain("<div>\n(htmllabel)=\n</div>");
  });

  it("work inside blockquotes and list items and interrupt a paragraph", () => {
    const result = build({ "a.md": "# A\n\n> % hidden\n> (qlabel)=\n> quoted text\n\n- item\n\n  % list comment\n  (inner)=\n  inner text\n\nPara line\n(after)=\nnext para\n" });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body).toContain('> <span id="qlabel"></span>\n>\n> quoted text');
    expect(body).not.toContain("hidden");
    expect(body).toContain('- item\n\n  <span id="inner"></span>\n\n  inner text');
    expect(body).not.toContain("list comment");
    expect(body).toContain('Para line\n\n<span id="after"></span>\n\nnext para');
  });

  it.each([
    ["a bullet item", "- (lab)=\n  Text.\n", '- <span id="lab"></span>\n\n  Text.'],
    ["an ordered item", "1. % note\n   Text.\n", "1. Text."],
    ["a nested item", "- - % note\n    Text.\n", "- - Text."],
  ])("are found on %s even when no other line could hold one", (_where, source, expected) => {
    const result = build({ "a.md": `# A\n\n${source}` });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body).toContain(expected);
    expect(body).not.toContain("note");
  });

  it.each([
    ["a quote in a bullet item", "- > (lab)=\n  > Text.\n", "lab"],
    ["a quote in an ordered item", "1. > % comment\n   > Text.\n", undefined],
  ])("are found in %s even when no other line could hold one", (_where, source, label) => {
    const result = build({ "a.md": `# A\n\n${source}` });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    if (label) expect(body).toContain(`<span id="${label}"></span>`);
    expect(body).not.toContain("(lab)=");
    expect(body).not.toContain("comment");
  });

  it("fail inside a definition list definition with a clear error", () => {
    const front = "---\nmyst:\n  enable_extensions:\n    - deflist\n---\n# A\n\n";
    expect(constructs({ "a.md": `${front}Term\n: def\n  (lbl)=\n  more\n` })).toEqual(["10 syntax:nested-marker"]);
    expect(build({ "a.md": `${front}Term\n: (lbl)=\n` }).errors.map((error) => error.message)).toEqual([expect.stringContaining("a.md:8: deflist: a label, attrs or comment line inside a definition")]);
  });

  it("fail where MyST would read them as paragraph text", () => {
    expect(constructs({ "a.md": "# A\n\nPara line\n    (cont)=\n" })).toEqual(["4 syntax:misplaced-label"]);
  });
});

describe("nested headings", () => {
  it.each([
    ["a blockquote", "> ## Quoted\n>\n> text\n", 3],
    ["a list item", "- item\n\n  ## Inner\n", 5],
    ["a directive body", "```{note}\n## Note heading\n\nbody\n```\n", 4],
  ])("fail inside %s, where Sphinx renders a rubric", (_where, source, line) => {
    expect(constructs({ "a.md": `# A\n\n${source}` })).toEqual([`${line} syntax:nested-heading`]);
  });
});
