import { afterEach, describe, expect, it } from "vitest";
import type { UnknownConstructError } from "../src/converter/errors.ts";
import { build, bodyOf, cleanup } from "./support.ts";

afterEach(cleanup);

function constructs(files: Record<string, string>): string[] {
  return build(files).errors.map((error) => `${error.line} ${(error as UnknownConstructError).construct}`);
}

describe("directive arguments", () => {
  it("makes an admonition argument the first line of its body", () => {
    const result = build({ "a.md": "# A\n\n```{note} This first line\ncontinues here.\n\nSecond paragraph.\n```\n" });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/a.mdx")).toContain('<Callout type="note" title="Note">\n  This first line\n  continues here.\n\n  Second paragraph.\n</Callout>');
  });

  it("splits a deprecated argument into the version and a lead paragraph", () => {
    const result = build({ "a.md": "# A\n\n```{deprecated} v0.2.0 Use the new name.\nMore detail.\n```\n" });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/a.mdx")).toContain('<Callout type="caution" title="Deprecated since v0.2.0">\n  Use the new name.\n\n  More detail.\n</Callout>');
  });

  it.each([
    ["mermaid", "diagrams/x.mmd", "graph TD; A-->B"],
    ["eval-rst", "x", "* `a <https://a>`_"],
    ["list-table", "My caption", "* - a"],
    ["toctree", "weird", ""],
  ])("rejects an argument on %s at the fence line", (name, argument, body) => {
    expect(constructs({ "a.md": `# A\n\n\`\`\`{${name}} ${argument}\n${body}\n\`\`\`\n` })).toEqual([`3 directive-argument:${name}`]);
  });
});

describe("YAML option blocks", () => {
  it("reads options from a leading --- block instead of treating it as body", () => {
    const result = build({ "a.md": "# A\n\n```{list-table}\n---\nheader-rows: 1\n---\n* - H\n* - v\n```\n" });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/a.md")).toContain("| H |\n| - |\n| v |");
  });

  it("accepts flag options with an empty value", () => {
    const result = build({ "index.md": "# Home\n\n```{toctree}\n---\nhidden:\nmaxdepth: 1\n---\nb\n```\n", "b.md": "# B\n" });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/index.md")).not.toContain("/docs/b.html");
  });

  it("validates option names, flag values and the block shape", () => {
    expect(constructs({ "a.md": "# A\n\n```{list-table}\n---\nbogus: 1\n---\n* - a\n```\n" })).toEqual(["3 directive-option:list-table:bogus"]);
    expect(constructs({ "a.md": "# A\n\n```{toctree}\n---\nhidden: true\n---\n```\n" })).toEqual(["3 directive-option:toctree:hidden"]);
    expect(constructs({ "a.md": "# A\n\n```{list-table}\n---\nheader-rows: 1\n* - a\n```\n" })).toEqual(["4 directive-options:list-table"]);
    expect(constructs({ "a.md": "# A\n\n```{list-table}\n---\n- a\n---\n* - a\n```\n" })).toEqual(["4 directive-options:list-table"]);
  });
});

describe("toctree options and depth", () => {
  const docs = {
    "index.md": "# Home\n\n```{toctree}\n:maxdepth: 2\n\nguide\nother\n```\n",
    "guide.md": "# Guide\n\n## Setup\n\n### Detail\n\n## Usage\n\n```{toctree}\n:hidden:\n\nchild\n```\n\n# Troubleshooting\n",
    "child.md": "# Child\n\n## Child section\n",
    "other.md": "# Other\n\n```{toctree}\n\nchild\n```\n",
  };

  it("nests section headings and child toctrees up to maxdepth and lists every top-level heading", () => {
    const result = build(docs);
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/index.md")).toContain(
      [
        "- [Guide](/docs/guide.html)",
        "  - [Setup](/docs/guide.html#setup)",
        "  - [Usage](/docs/guide.html#usage)",
        "- [Troubleshooting](/docs/guide.html#troubleshooting)",
        "- [Other](/docs/other.html)",
        "  - [Child](/docs/child.html)",
      ].join("\n"),
    );
  });

  it("includes hidden child toctrees with includehidden and drops sections with titlesonly", () => {
    const included = build({ ...docs, "index.md": "# Home\n\n```{toctree}\n:includehidden:\n:titlesonly:\n\nguide\n```\n" });
    expect(included.errors).toEqual([]);
    expect(bodyOf(included, "docs/index.md")).toContain(
      ["- [Guide](/docs/guide.html)", "  - [Child](/docs/child.html)", "- [Troubleshooting](/docs/guide.html#troubleshooting)"].join("\n"),
    );
  });

  it("uses an explicit title only for a page with one top-level heading and honours reversed and maxdepth 1", () => {
    const result = build({ ...docs, "index.md": "# Home\n\n```{toctree}\n:maxdepth: 1\n:reversed:\n\nGuide page <guide>\nOther page <other>\n```\n" });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/index.md")).toContain(
      ["- [Other page](/docs/other.html)", "- [Guide](/docs/guide.html)", "- [Troubleshooting](/docs/guide.html#troubleshooting)"].join("\n"),
    );
  });

  it.each(["numbered", "name", "class"])("rejects the unimplemented :%s: option", (option) => {
    expect(constructs({ "index.md": `# Home\n\n\`\`\`{toctree}\n:${option}: x\n\nb\n\`\`\`\n`, "b.md": "# B\n" })).toEqual([`3 directive-option:toctree:${option}`]);
  });

  it("globs docnames in sorted order without repeating explicit entries", () => {
    const result = build({
      "index.md": "# Home\n\n```{toctree}\n:glob:\n:maxdepth: 1\n\ng/b\ng/*\n```\n",
      "g/a.md": "# A\n",
      "g/a-b.md": "# AB\n",
      "g/b.md": "# B\n",
    });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/index.md")).toContain(["- [B](/docs/g/b.html)", "- [A](/docs/g/a.html)", "- [AB](/docs/g/a-b.html)"].join("\n"));
  });
});
