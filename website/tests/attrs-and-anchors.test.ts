import { afterEach, describe, expect, it } from "vitest";
import type { UnknownConstructError } from "../src/converter/errors.ts";
import { build, bodyOf, cleanup, frontMatterOf } from "./support.ts";

afterEach(cleanup);

const ATTRS = "---\nmyst:\n  enable_extensions:\n    - attrs_block\n---\n";

function messages(files: Record<string, string>): string[] {
  return build(files).errors.map((error) => error.message);
}

describe("attrs_block ids", () => {
  it("gives headings and blocks the ids Sphinx gives them", () => {
    const result = build({
      "a.md": `${ATTRS}{#title-id}\n# A\n\n{#custom}\n## Foo\n\n## Foo\n\n{#gap}\n\nGap paragraph.\n\n## Bar\n\n{#bar}\nPara.\n\n{#list-id}\n- item\n\n{#code-id}\n\`\`\`python\nx = 1\n\`\`\`\n\n(lbl)=\n{#both}\n## Labeled\n`,
      "b.md": "# B\n\n[c](a.md#custom) [g](a.md#gap) [l](a.md#list-id) {ref}`lbl`\n",
    });
    expect(result.errors).toEqual([]);
    const front = frontMatterOf(result, "docs/a.md");
    expect(front).toContain("titleId: title-id");
    expect(front).toContain("headingIds:\n  - custom\n  - foo\n  - bar\n  - both");
    const body = bodyOf(result, "docs/a.md");
    expect(body).toContain('<span id="gap"></span>\n\nGap paragraph.');
    expect(body).toContain('<span id="id1"></span>\n\nPara.');
    expect(body).toContain('<span id="list-id"></span>\n\n- item');
    expect(body).toContain('<span id="code-id"></span>\n\n```python');
    expect(body).toContain('<span id="lbl"></span>\n\n## Labeled');
    expect(bodyOf(result, "docs/b.md")).toContain("[c](/docs/a.html#custom) [g](/docs/a.html#gap) [l](/docs/a.html#list-id) [Labeled](/docs/a.html#lbl)");
  });

  it("fails closed on attrs Sphinx would drop or that are not a single id", () => {
    expect(messages({ "a.md": `${ATTRS}# A\n\n{#x}\n(lbl)=\n## H\n` })).toEqual([expect.stringContaining("a.md:8: attrs block cannot attach to a label")]);
    expect(messages({ "a.md": `${ATTRS}# A\n\n{#x}\n\`\`\`{note}\nN.\n\`\`\`\n` })).toEqual([expect.stringContaining("a.md:8: attrs block cannot attach to a directive")]);
    expect(messages({ "a.md": `${ATTRS}# A\n\n{#a}\n{#b}\nText.\n` })).toEqual([expect.stringContaining("a.md:8: attrs block is followed by another attrs block")]);
    expect(messages({ "a.md": `${ATTRS}# A\n\nText.\n\n{#end}\n` })).toEqual([expect.stringContaining("a.md:10: attrs block is not followed")]);
    expect(messages({ "a.md": `${ATTRS}# A\n\n{.cls}\nText.\n` })).toEqual([expect.stringContaining("a.md:8: attrs block {.cls} is not supported")]);
    expect(messages({ "a.md": `${ATTRS}# A\n\n{#x .cls}\nText.\n` })).toEqual([expect.stringContaining("is not supported")]);
    expect(messages({ "a.md": "# A\n\n{#x}\nText.\n" })).toEqual([expect.stringContaining("a.md:3: attrs blocks need myst.enable_extensions: attrs_block")]);
  });
});

describe("raw span anchors", () => {
  it("passes bare span anchors through and registers their ids for fragment links", () => {
    const result = build({
      "a.md": '# A\n\n<span id="pkg.Class"></span>\n\nInline <span id="inline-a"></span>text.\n\n<span id="lead"></span><span id="lead.two"></span>Lead text.\n',
      "b.md": "# B\n\n[x](a.md#pkg.Class) [y](a.md#inline-a) [z](a.md#lead.two)\n",
    });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/a.md")).toContain('<span id="lead"></span><span id="lead.two"></span>Lead text.');
    expect(bodyOf(result, "docs/b.md")).toContain("[x](/docs/a.html#pkg.Class) [y](/docs/a.html#inline-a) [z](/docs/a.html#lead.two)");
  });

  it("rejects span anchors with other attributes and duplicate ids", () => {
    expect(messages({ "a.md": '# A\n\nSee <span id="x" class="c"></span>here.\n' })).toEqual([expect.stringContaining('must be a bare <span id="..."> anchor')]);
    expect(messages({ "a.md": '# A\n\n<span id="dup"></span>x <span id="dup"></span>y\n' })).toEqual([expect.stringContaining('raw html id "dup" is already used')]);
    expect(messages({ "a.md": '# A\n\n<span id="intro"></span>x\n\n## Intro\n' })).toEqual([expect.stringContaining('raw html id "intro" duplicates an id')]);
  });
});

describe("closed gaps", () => {
  it("rejects $$ math", () => {
    expect(build({ "a.md": "# A\n\n$$x^2$$\n" }).errors.map((error) => (error as UnknownConstructError).construct)).toEqual(["syntax:math"]);
  });

  it("rejects unknown elements with content and unknown html blocks", () => {
    expect(messages({ "a.md": "# A\n\n<custom-el>hi</custom-el>\n" })).toEqual([expect.stringContaining('raw html "</custom-el>"')]);
    expect(messages({ "a.md": "# A\n\n<custom-el>\n\nText.\n" })).toEqual([expect.stringContaining('raw html "<custom-el>"')]);
  });

  it("keeps a lone unknown inline tag as literal text", () => {
    const result = build({ "a.md": "# A\n\nRun with --platform <name> today.\n" });
    expect(result.errors).toEqual([]);
  });

  it("rejects an empty tags directive", () => {
    expect(build({ "a.md": "# A\n\n```{tags}\n```\n" }).errors.map((error) => (error as UnknownConstructError).construct)).toEqual(["directive-argument:tags"]);
  });
});
