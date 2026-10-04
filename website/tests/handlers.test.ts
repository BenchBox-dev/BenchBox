import { afterEach, describe, expect, it } from "vitest";
import { NotYetImplementedError, UnknownConstructError, UnresolvedReferenceError } from "../src/converter/errors.ts";
import { createDefaultRegistry } from "../src/converter/handlers/index.ts";
import { buildSite } from "../src/converter/build.ts";
import { build, bodyOf, cleanup, frontMatterOf, pageOf, STUB, writeDocs } from "./support.ts";

afterEach(cleanup);

describe("front matter", () => {
  it("passes known keys through and maps meta_description to description", () => {
    const result = build({
      "post.md": "---\norphan: true\nmeta_description: A short summary\nauthor: Joe\ndate: 2026-01-02\n---\n\n# Post\n",
    });
    expect(result.errors).toEqual([]);
    const front = frontMatterOf(result, "docs/post.md");
    expect(front).toContain("description: A short summary");
    expect(front).toContain("orphan: true");
    expect(front).toContain("author: Joe");
    expect(front).toContain("date: 2026-01-02");
  });

  it("rejects an unknown key with its file and line", () => {
    const result = build({ "a.md": "---\nmystery: 1\n---\n\n# A\n" });
    expect(result.errors).toHaveLength(1);
    const [error] = result.errors;
    expect(error).toBeInstanceOf(UnknownConstructError);
    expect(error.file).toBe("a.md");
    expect(error.line).toBe(2);
    expect((error as UnknownConstructError).construct).toBe("front-matter:mystery");
  });

  it("accepts myst.enable_extensions deflist and rejects other extensions", () => {
    expect(build({ "a.md": "---\nmyst:\n  enable_extensions:\n    - deflist\n---\n\n# A\n" }).errors).toEqual([]);
    const result = build({ "a.md": "---\nmyst:\n  enable_extensions:\n    - dollarmath\n---\n\n# A\n" });
    expect(result.errors[0]).toBeInstanceOf(NotYetImplementedError);
  });

  it("uses a front matter title when there is no first-level heading", () => {
    const result = build({ "a.md": "---\ntitle: From Front Matter\n---\n\nBody text.\n" });
    expect(result.errors).toEqual([]);
    expect(frontMatterOf(result, "docs/a.md")).toContain("title: From Front Matter");
  });

  it("reports a document without any title", () => {
    const result = build({ "a.md": "Just text.\n" });
    expect(result.errors[0].message).toContain("no title");
  });
});

describe("tags directive", () => {
  it("writes tags to front matter and the tag manifest", () => {
    const result = build({ "a.md": "# A\n\n```{tags} beginner, cli\n```\n", "b.md": "# B\n\n```{tags} cli\n```\n" });
    expect(result.errors).toEqual([]);
    expect(frontMatterOf(result, "docs/a.md")).toContain("tags:\n  - beginner\n  - cli");
    expect(bodyOf(result, "docs/a.md")).not.toContain("tags");
    const manifest = JSON.parse(result.files.get("manifest/tags.json") ?? "{}") as Record<string, { path: string }[]>;
    expect(Object.keys(manifest)).toEqual(["beginner", "cli"]);
    expect(manifest.cli.map((page) => page.path)).toEqual(["a.md", "b.md"]);
  });
});

describe("comments", () => {
  it("drops percent comment lines but keeps them inside code fences", () => {
    const result = build({ "a.md": "# A\n\n% hidden note\n\nVisible.\n\n```text\n% kept\n```\n" });
    const body = bodyOf(result, "docs/a.md");
    expect(body).not.toContain("hidden note");
    expect(body).toContain("% kept");
  });

  it("drops html comments", () => {
    const result = build({ "a.md": "<!-- licence -->\n\n# A\n\nText <!-- inline --> more.\n" });
    expect(result.errors).toEqual([]);
    expect(pageOf(result, "docs/a.md")).not.toContain("licence");
    expect(pageOf(result, "docs/a.md")).not.toContain("inline");
  });
});

describe("heading ids", () => {
  it("numbers duplicate headings id1, id2 as Sphinx does", () => {
    const result = build({ "a.md": "# A\n\n## Setup\n\n## Setup\n\n## Setup\n\n## !!!\n" });
    expect(frontMatterOf(result, "docs/a.md")).toContain("headingIds:\n  - setup\n  - id1\n  - id2\n  - id3");
  });

  it("keeps the document title id as an alias span for docs only", () => {
    const result = build({ "a.md": "# Getting Started\n\nText.\n", "blog/post.md": "# Post Title\n\nText.\n" });
    expect(bodyOf(result, "docs/a.md")).toContain('<span id="getting-started"></span>');
    expect(bodyOf(result, "blog/post.md")).not.toContain("<span");
    expect(frontMatterOf(result, "blog/post.md")).toContain("titleId: post-title");
  });

  it("matches docutils for non-ascii titles and leading digits", () => {
    const result = build({ "a.md": "# A\n\n## 1. Step\n\n## Æther Straße\n" });
    expect(frontMatterOf(result, "docs/a.md")).toContain("  - step\n  - aether-strasze");
  });
});

describe("labels", () => {
  it("gives a label its id before the heading it precedes, as docutils does", () => {
    const result = build({
      "a.md": "# A\n\n(other)=\n## Other\n\n(my_label)=\n## Third\n\n(alpha)=\n(beta)=\n## Two\n\n## Other\n",
      "b.md": "# B\n\n{ref}`other` {ref}`beta`\n",
    });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body).toContain('<span id="id1"></span>\n\n## Other');
    expect(body).toContain('<span id="my-label"></span>');
    expect(body).toContain('<span id="alpha"></span>\n\n<span id="beta"></span>\n\n## Two');
    expect(frontMatterOf(result, "docs/a.md")).toContain("  - other\n  - third\n  - two\n  - id2");
    expect(bodyOf(result, "docs/b.md")).toContain("[Other](/docs/a.html#other) [Two](/docs/a.html#beta)");
  });

  it("uses the label id for a page title whose slug the label already took", () => {
    const result = build({ "a.md": "(driver-version-management)=\n# Driver Version Management\n" });
    expect(frontMatterOf(result, "docs/a.md")).toContain("titleId: driver-version-management");
    expect(bodyOf(result, "docs/a.md")).toContain('<span id="id1"></span>');
  });

  it("keeps a label standalone when a comment follows it", () => {
    const result = build({ "a.md": "(blog)=\n\n% note\n\n# Blog\n" });
    expect(frontMatterOf(result, "docs/a.md")).toContain("titleId: id1");
    expect(bodyOf(result, "docs/a.md")).toContain('<span id="blog"></span>');
  });

  it("anchors a label that precedes a paragraph", () => {
    const result = build({ "a.md": "# A\n\n(para-label)=\nSome text.\n" });
    expect(bodyOf(result, "docs/a.md")).toContain('<span id="para-label"></span>\n\nSome text.');
  });

  it("anchors an indented label inside a list item as Sphinx does", () => {
    const result = build({ "a.md": "# A\n\n- item\n\n  (inner)=\n  text in item\n\nSee {ref}`the item <inner>`.\n" });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body).toContain('- item\n\n  <span id="inner"></span>\n\n  text in item');
    expect(body).toContain("[the item](/docs/a.html#inner)");
  });

  it("requires explicit text for a ref to a label without a heading", () => {
    const result = build({ "a.md": "# A\n\n(para)=\nText.\n\n{ref}`para`\n" });
    expect(result.errors.map((error) => error.message)).toEqual([expect.stringContaining("a.md:6: ref:para labels content without a heading")]);
  });

  it("resolves ref roles to the label id, with and without explicit text", () => {
    const result = build({
      "a.md": "# A\n\n(topic-label)=\n## Topic\n\nBody.\n",
      "b.md": "# B\n\nSee {ref}`topic-label` and {ref}`the topic <topic-label>`.\n",
    });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/b.md");
    expect(body).toContain("[Topic](/docs/a.html#topic-label)");
    expect(body).toContain("[the topic](/docs/a.html#topic-label)");
  });

  it("fails on an unknown ref label", () => {
    const result = build({ "a.md": "# A\n\n{ref}`missing`\n" });
    expect(result.errors[0]).toBeInstanceOf(UnresolvedReferenceError);
    expect(result.errors[0].line).toBe(3);
  });

  it("fails on a label defined in two documents", () => {
    const result = build({ "a.md": "(dup)=\n# A\n", "b.md": "(dup)=\n# B\n" });
    expect(result.errors[0].message).toContain("already defined");
  });
});

describe("doc role and links", () => {
  const docs = { "guides/a.md": "# A\n\n{doc}`b` {doc}`/top` {doc}`../top` {doc}`Custom <b>`\n", "guides/b.md": "# Bee\n", "top.md": "# Top\n" };

  it("resolves relative and absolute doc targets with titles", () => {
    const result = build(docs);
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/guides/a.md")).toContain("[Bee](/docs/guides/b.html) [Top](/docs/top.html) [Top](/docs/top.html) [Custom](/docs/guides/b.html)");
  });

  it("fails on an unresolved doc target with the role line", () => {
    const result = build({ "a.md": "# A\n\ntext\n\n{doc}`nowhere`\n" });
    expect(result.errors[0]).toBeInstanceOf(UnresolvedReferenceError);
    expect(result.errors[0].file).toBe("a.md");
    expect(result.errors[0].line).toBe(5);
  });

  it("rewrites markdown links and keeps fragments, external and anchor links", () => {
    const result = build({
      "a/x.md": "# X\n\n## Here\n\n[b](../b.md#part) [ext](https://example.com/p.md) [here](#here) [mail](mailto:a@b.c)\n",
      "b.md": "# B\n\n## Part\n",
    });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/a/x.md")).toContain("[b](/docs/b.html#part) [ext](https://example.com/p.md) [here](#here) [mail](mailto:a@b.c)");
  });

  it("resolves extensionless and trailing-slash doc targets as MyST does", () => {
    const result = build({
      "guide/a.md": "# A\n\n[x](../ref/api/platforms/) [y](../ref/api/platforms) [z](../ref) [w](./)\n",
      "ref/api/platforms.md": "# Platforms\n",
      "ref/api/platforms/duckdb.md": "# DuckDB\n",
      "ref/index.md": "# Ref\n",
      "guide/index.md": "# Guide\n",
    });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/guide/a.md")).toContain(
      "[x](/docs/ref/api/platforms.html) [y](/docs/ref/api/platforms.html) [z](/docs/ref/index.html) [w](/docs/guide/index.html)",
    );
  });

  it("fails on any reStructuredText page, which this site does not build", () => {
    const result = build({ "a.md": "# A\n\n[api](api/core.rst)\n", "api/core.rst": "Core\n====\n" });
    expect(result.errors.map((error) => error.message)).toEqual([
      "api/core.rst:1: reStructuredText pages are not built by this site; convert the page to MyST Markdown",
      "a.md:3: link:api/core.rst does not match a document under docs/ (looked for api/core.md)",
    ]);
  });

  it("fails on unresolvable relative targets with file and line", () => {
    const result = build({ "a.md": "# A\n\n[d](nowhere/)\n\n[h](other.html) [s](sub/)\n", "sub/page.md": STUB, "other.md": STUB });
    expect(result.errors.map((error) => [error.file, error.line, (error as UnresolvedReferenceError).reference])).toEqual([
      ["a.md", 3, "link:nowhere/"],
      ["a.md", 5, "link:other.html"],
      ["a.md", 5, "link:sub/"],
    ]);
  });

  it("validates fragments against the target page ids", () => {
    const result = build({
      "a.md": "# A\n\n[ok](b.md#sec) [label](b.md#lbl) [bad](b.md#nope) [self](#gone) [bare](b#sec)\n",
      "b.md": "# B\n\n## Sec\n\n(lbl)=\nText.\n",
    });
    expect(result.errors.map((error) => (error as UnresolvedReferenceError).reference)).toEqual(["link:b.md#nope", "link:a.md#gone", "link:b#sec"]);
  });

  it("allows only the broken fragments listed as known Sphinx breakage", () => {
    const docsRoot = writeDocs({ "a.md": "# A\n\n[bad](b.md#nope) [other](b.md#also)\n", "b.md": STUB });
    const result = buildSite({ docsRoot, knownBrokenLinks: new Set(["/docs/a.html /docs/b.html#nope"]) });
    expect(result.errors.map((error) => (error as UnresolvedReferenceError).reference)).toEqual(["link:b.md#also"]);
  });

  it("fails on a markdown link to a missing document", () => {
    const result = build({ "a.md": "# A\n\n[gone](gone.md)\n" });
    expect(result.errors[0].message).toContain("link:gone.md");
  });

  it("links blog pages under /blog/", () => {
    const result = build({ "a.md": "# A\n\n[post](blog/p.md)\n", "blog/p.md": "# P\n" });
    expect(bodyOf(result, "docs/a.md")).toContain("[post](/blog/p.html)");
  });
});

describe("toctree", () => {
  const docs = {
    "index.md": "# Home\n\n```{toctree}\n:caption: Guides\n:maxdepth: 2\n\nguides/one\nCustom Two <guides/two.md>\nhttps://example.com/x\n```\n\n```{toctree}\n:hidden:\n\nlast\n```\n",
    "guides/one.md": "# One\n\n```{toctree}\n:hidden:\n\n../deep\n```\n",
    "guides/two.md": "# Two\n",
    "deep.md": "# Deep\n",
    "last.md": "# Last\n",
  };

  it("renders visible toctrees as link lists and omits hidden ones", () => {
    const result = build(docs);
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/index.md");
    expect(body).toContain("**Guides**");
    expect(body).toContain("- [One](/docs/guides/one.html)");
    expect(body).toContain("- [Custom Two](/docs/guides/two.html)");
    expect(body).toContain("- <https://example.com/x>");
    expect(body).not.toContain("/docs/last.html");
    expect(body).not.toContain("/docs/deep.html");
  });

  it("emits a sidebar manifest with groups, nesting and a depth-first order", () => {
    const manifest = JSON.parse(build(docs).files.get("manifest/sidebar.json") ?? "{}") as {
      groups: { label: string | null; items: { label: string; link: string; items?: unknown[] }[] }[];
      order: Record<string, number>;
    };
    expect(manifest.groups.map((group) => group.label)).toEqual(["Guides", null]);
    expect(manifest.groups[0].items.map((item) => item.label)).toEqual(["One", "Custom Two", "https://example.com/x"]);
    expect(manifest.groups[0].items[0].items).toEqual([{ label: "Deep", link: "/docs/deep.html" }]);
    expect(manifest.order).toEqual({ "index.md": 0, "guides/one.md": 1, "deep.md": 2, "guides/two.md": 3, "last.md": 4 });
    const result = build(docs);
    expect(frontMatterOf(result, "docs/guides/two.md")).toContain("sidebar:\n  order: 3");
  });

  it("expands globs and rejects entries that match nothing", () => {
    const result = build({
      "index.md": "# Home\n\n```{toctree}\n:glob:\n:hidden:\n\ng/*\n```\n",
      "g/a.md": "# A\n",
      "g/b.md": "# B\n",
    });
    expect(result.errors).toEqual([]);
    const sidebar = JSON.parse(result.files.get("manifest/sidebar.json") ?? "{}") as { groups: { items: { label: string }[] }[] };
    expect(sidebar.groups[0].items.map((item) => item.label)).toEqual(["A", "B"]);
    const missing = build({ "index.md": "# Home\n\n```{toctree}\n:glob:\n\nnone/*\n```\n" });
    expect(missing.errors[0]).toBeInstanceOf(UnresolvedReferenceError);
  });

  it("reports the line of a missing toctree entry", () => {
    const result = build({ "index.md": "# Home\n\n```{toctree}\n:maxdepth: 1\n\nreal\nmissing\n```\n", "real.md": STUB });
    expect(result.errors).toHaveLength(1);
    expect(result.errors[0].line).toBe(7);
    expect(result.errors[0].message).toContain("toctree:missing");
  });

  it("rejects an unknown toctree option", () => {
    const result = build({ "index.md": "# Home\n\n```{toctree}\n:bogus: 1\n\n```\n" });
    expect((result.errors[0] as UnknownConstructError).construct).toBe("directive-option:toctree:bogus");
  });
});

describe("unknown constructs", () => {
  it("names the file and line of an unknown directive", () => {
    const result = build({ "a.md": "# A\n\ntext\n\n```{frobnicate} arg\nbody\n```\n" });
    const [error] = result.errors;
    expect(error).toBeInstanceOf(UnknownConstructError);
    expect(error.message).toBe("a.md:5: unknown construct directive:frobnicate");
  });

  it("names the file and line of an unknown role, including on later lines of a paragraph", () => {
    const result = build({ "a.md": "# A\n\nfirst line\nsecond {frob}`x` line\n" });
    expect(result.errors[0].message).toBe("a.md:4: unknown construct role:frob");
  });

  it("reports every error in a document, not only the first", () => {
    const result = build({ "a.md": "# A\n\n```{one}\n```\n\n```{two}\n```\n" });
    expect(result.errors.map((error) => error.line)).toEqual([3, 6]);
  });

  it("reports directive body line offsets for nested conversion", () => {
    const registry = createDefaultRegistry();
    registry.register({
      kind: "directive",
      names: ["wrap"],
      options: [],
      argument: "none",
      handle: (call, context) => context.convertMarkdown(call.body, call.bodyAt),
    });
    const result = build({ "a.md": "# A\n\n```{wrap}\nplain\n\n{frob}`x`\n```\n" }, registry);
    expect(result.errors[0].message).toBe("a.md:6: unknown construct role:frob");
  });

  it("renders a colon fence as the plain paragraph Sphinx renders without colon_fence", () => {
    const result = build({ "a.md": "# A\n\n:::{note}\nhi\n:::\n" });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/a.md")).toContain("&#58;::{note}\nhi\n&#58;::");
  });

  it("escapes a colon fence inside a blockquote, including on later lines", () => {
    const result = build({ "a.md": "# A\n\n> :::note\n> quoted\n> :::\n\n> Intro\n> :::tip\n" });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body).toContain("> &#58;::note\n> quoted\n> &#58;::");
    expect(body).toContain("> Intro\n> &#58;::tip");
  });

  it("escapes a brace-less :::note fence so the page renders it as the literal text Sphinx shows", () => {
    const result = build({ "a.md": "# A\n\nIntro line\n:::note\nliteral *text*\n:::\n" });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/a.md")).toContain("Intro line\n&#58;::note\nliteral *text*\n&#58;::");
  });

  it("rejects colon_fence when a page enables it", () => {
    const result = build({ "a.md": "---\nmyst:\n  enable_extensions:\n    - colon_fence\n---\n# A\n" });
    expect(result.errors[0]).toBeInstanceOf(NotYetImplementedError);
  });
});

describe("not yet implemented handlers", () => {
  const cases: [string, string, string][] = [
    ["sphinx-design", "```{grid} 2\n```\n", "directive:grid"],
    ["highlighting", "```{code-block} python\nx = 1\n```\n", "directive:code-block"],
  ];

  it.each(cases)("%s throws a clear not-yet-implemented error", (_owner, source, construct) => {
    const result = build({ "a.md": `# A\n\n${source}` });
    const [error] = result.errors;
    expect(error).toBeInstanceOf(NotYetImplementedError);
    expect((error as NotYetImplementedError).construct).toBe(construct);
    expect(error.message).toContain("is not yet implemented");
    expect(error.line).toBe(3);
  });
});

describe("plain markdown passthrough", () => {
  it("keeps tables, lists, emphasis, code and footnotes", () => {
    const source = "# A\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\n- one\n- two\n\n*em* **strong** `code` ~~gone~~\n\n```python\nprint(1)\n```\n";
    const result = build({ "a.md": source });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body).toContain("| a | b |");
    expect(body).toContain("- one\n- two");
    expect(body).toContain("*em* **strong** `code` ~~gone~~");
    expect(body).toContain("```python\nprint(1)\n```");
  });
});
