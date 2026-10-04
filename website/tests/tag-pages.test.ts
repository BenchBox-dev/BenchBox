import { afterEach, describe, expect, it } from "vitest";
import { displayTag, tagBasename } from "../src/converter/tag-pages.ts";
import { build, bodyOf, cleanup, pageOf } from "./support.ts";

afterEach(cleanup);

const files = {
  "index.md": "# Home\n\n```{toctree}\n:maxdepth: 2\n:caption: Browse by Tag\n\n_tags/cat-audience\n_tags/cat-feature\n```\n",
  "README.md": "# Readme\n\n```{tags} beginner, cli\n```\n",
  "usage/index.md": "# Usage\n\n```{tags}\nbeginner,\nPython API\n```\n",
  "Zeta.md": "# Zeta Guide\n\n```{tags} advanced\n```\n",
  "platforms/duck.md": "# Duck Platform\n\n```{tags} reference, python-api\n```\n\nBody text.\n",
  "plain.md": "# Plain\n",
  "blog/2026-01-01-post.md": "---\nblogpost: true\ndate: Jan 1, 2026\ntags: beginner, blogonly\n---\n\n# A post\n\nBody.\n",
};

const GOLDEN_BEGINNER = `---
title: "Tagged with: beginner"
sourcePath: docs/_tags/beginner.md
titleId: tagged-with-beginner
sidebar:
  order: 2
---

<span id="sphx-tag-beginner"></span>

<span id="tagged-with-beginner"></span>

**Pages with this tag**

- [Readme](/docs/README.html)
- [Usage](/docs/usage/index.html)
`;

describe("tag page generation", () => {
  it("emits a golden tag page at the sphinx-tags route with matching ids", () => {
    const result = build(files);
    expect(result.errors).toEqual([]);
    expect(pageOf(result, "docs/_tags/beginner.md")).toBe(GOLDEN_BEGINNER);
  });

  it("emits one page per tag, category and the tags index, ignoring blog front matter tags", () => {
    const result = build(files);
    const generated = [...result.files.keys()].filter((key) => key.startsWith("content/docs/_tags/")).sort();
    expect(generated).toEqual(
      [
        "advanced",
        "beginner",
        "cat-audience",
        "cat-benchmark",
        "cat-content-type",
        "cat-feature",
        "cat-platform",
        "cat-platform-type",
        "cli",
        "python-api",
        "reference",
        "tagsindex",
      ]
        .map((name) => `content/docs/_tags/${name}.md`)
        .sort(),
    );
  });

  it("sorts listed pages by source path", () => {
    const result = build(files);
    const body = bodyOf(result, "docs/_tags/python-api.md");
    expect(body.indexOf("[Usage](/docs/usage/index.html)")).toBeGreaterThan(-1);
    expect(body.indexOf("[Duck Platform](/docs/platforms/duck.html)")).toBeGreaterThan(-1);
    expect(body.indexOf("Duck Platform")).toBeLessThan(body.indexOf("Usage"));
    const advanced = bodyOf(result, "docs/_tags/advanced.md");
    expect(advanced).toContain("- [Zeta Guide](/docs/Zeta.html)");
  });

  it("lists category tags with counts in category order and skips absent tags", () => {
    const result = build(files);
    const audience = bodyOf(result, "docs/_tags/cat-audience.md");
    expect(audience).toContain("- [beginner (2)](/docs/_tags/beginner.html)");
    expect(audience).toContain("- [advanced (1)](/docs/_tags/advanced.html)");
    expect(audience).not.toContain("intermediate");
    expect(audience.indexOf("beginner")).toBeLessThan(audience.indexOf("advanced"));
    expect(bodyOf(result, "docs/_tags/cat-benchmark.md")).toContain("*No tags in this category yet.*");
    expect(pageOf(result, "docs/_tags/cat-feature.md")).toContain("title: By Feature");
  });

  it("nests category tags under the tags index", () => {
    const result = build(files);
    const body = bodyOf(result, "docs/_tags/tagsindex.md");
    expect(body).toContain('<span id="tagoverview"></span>');
    expect(body).toContain("- [By Audience](/docs/_tags/cat-audience.html)\n  - [beginner (2)](/docs/_tags/beginner.html)");
    expect(pageOf(result, "docs/_tags/tagsindex.md")).toContain("title: Browse by Tag");
  });

  it("generates nothing when no page has tags", () => {
    const result = build({ "index.md": "# Home\n" });
    expect([...result.files.keys()].some((key) => key.includes("_tags"))).toBe(false);
  });
});

describe("toctree resolution of generated tag pages", () => {
  it("resolves _tags category targets from a toctree without errors", () => {
    const result = build(files);
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/index.md");
    expect(body).toContain("**Browse by Tag**");
    expect(body).toContain("- [By Audience](/docs/_tags/cat-audience.html)");
    expect(body).toContain("  - [beginner (2)](/docs/_tags/beginner.html)");
  });

  it("places generated pages in the sidebar under the index toctree", () => {
    const result = build(files);
    const sidebar = JSON.parse(result.files.get("manifest/sidebar.json") ?? "{}") as { groups: { label: string; items: { link: string; items?: { link: string }[] }[] }[] };
    expect(sidebar.groups[0].label).toBe("Browse by Tag");
    expect(sidebar.groups[0].items.map((item) => item.link)).toEqual(["/docs/_tags/cat-audience.html", "/docs/_tags/cat-feature.html"]);
    expect(sidebar.groups[0].items[0].items?.map((item) => item.link)).toEqual(["/docs/_tags/beginner.html", "/docs/_tags/advanced.html"]);
  });

  it("still reports unknown _tags targets when no such tag page exists", () => {
    const result = build({ "index.md": "# Home\n\n```{toctree}\n_tags/cat-audience\n```\n" });
    expect(result.errors.map((error) => error.message).join("\n")).toContain("_tags/cat-audience");
  });

  it("records blog post tags in the manifest only: no blog tag page is built", () => {
    const result = build(files);
    expect([...result.files.keys()].filter((name) => name.startsWith("content/blog/") || name.includes("blogonly"))).toEqual(["content/blog/2026-01-01-post.md"]);
    const tags = JSON.parse(result.files.get("manifest/tags.json") ?? "{}") as Record<string, { path: string }[]>;
    expect(tags.blogonly.map((entry) => entry.path)).toEqual(["blog/2026-01-01-post.md"]);
  });
});

describe("tag helpers", () => {
  it("normalizes display names and file basenames like sphinx-tags", () => {
    expect(displayTag('"Tag:with   (extra) whitespace"')).toBe("Tag:with (extra) whitespace");
    expect(tagBasename("Tag:with (special   characters) ")).toBe("tag-with-special-characters");
    expect(tagBasename("python-api")).toBe("python-api");
  });

});
