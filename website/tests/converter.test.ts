import { mkdtempSync, readFileSync, readdirSync, statSync, utimesSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import type { RootContent } from "mdast";
import { afterEach, describe, expect, it } from "vitest";
import { assertBuilt, buildSite, writeOutput } from "../src/converter/build.ts";
import { ConversionFailedError } from "../src/converter/errors.ts";
import { createDefaultRegistry } from "../src/converter/handlers/index.ts";
import type { DirectiveHandler } from "../src/converter/types.ts";
import { toStarlightSidebar, type SidebarManifest } from "../src/converter/sidebar.ts";
import { docutilsMakeId } from "../src/lib/docutils-slug.ts";
import { IdAllocator } from "../src/converter/ids.ts";
import { build, bodyOf, cleanup, pageOf, writeDocs } from "./support.ts";

afterEach(cleanup);

const callout: DirectiveHandler = {
  kind: "directive",
  names: ["callout"],
  options: ["kind"],
  argument: "none",
  handle(call, context) {
    context.useComponent("Callout");
    const node = {
      type: "mdxJsxFlowElement",
      name: "Callout",
      attributes: [{ type: "mdxJsxAttribute", name: "kind", value: call.options.kind ?? "note" }],
      children: context.convertMarkdown(call.body, call.bodyAt),
    };
    return [node as unknown as RootContent];
  },
};

describe("output format", () => {
  it("emits mdx only for pages that use a component", () => {
    const registry = createDefaultRegistry().register(callout);
    const result = build(
      { "plain.md": "# Plain\n\nText with {braces} and a \\<not-html\\> escape.\n", "rich.md": "# Rich\n\n```{callout}\n:kind: warning\nCareful, {braces}.\n```\n" },
      registry,
    );
    expect(result.errors).toEqual([]);
    expect([...result.files.keys()].filter((name) => name.startsWith("content/"))).toEqual(["content/docs/plain.md", "content/docs/rich.mdx"]);
    expect(result.summary).toEqual({ pages: 2, md: 1, mdx: 1, mdxPages: ["rich.md"] });
    const rich = pageOf(result, "docs/rich.mdx");
    expect(rich).toContain('import Callout from "../../../src/components/docs/Callout.astro";');
    expect(rich).toContain('<Callout kind="warning">');
    expect(rich).toContain("Careful, \\{braces}.");
    expect(pageOf(result, "docs/plain.md")).not.toContain("import");
  });
});

describe("determinism", () => {
  const files = {
    "index.md": "# Home\n\n```{toctree}\n:hidden:\n\na\nb\n```\n",
    "a.md": "# A\n\n```{tags} z, y\n```\n\n## Same\n\n## Same\n",
    "b.md": "# B\n\n```{tags} y\n```\n\n{doc}`a`\n",
  };

  it("produces byte-identical output for the same input", () => {
    const first = build(files);
    const second = build(files);
    expect([...first.files.entries()]).toEqual([...second.files.entries()]);
  });

  it("orders manifest keys and files independent of input order", () => {
    const reversed = Object.fromEntries(Object.entries(files).reverse());
    expect([...build(reversed).files.keys()]).toEqual([...build(files).files.keys()]);
  });

  it("contains no timestamps or absolute paths", () => {
    const text = [...build(files).files.values()].join("\n");
    expect(text).not.toMatch(/\d{4}-\d{2}-\d{2}T\d{2}:/);
    expect(text).not.toContain(os.tmpdir());
  });
});

describe("writeOutput", () => {
  it("rewrites nothing on a second identical run and removes stale files", () => {
    const out = mkdtempSync(path.join(os.tmpdir(), "benchbox-out-"));
    const first = build({ "a.md": "# A\n", "b.md": "# B\n" });
    writeOutput(out, first.files);
    const target = path.join(out, "content/docs/a.md");
    const past = new Date(2020, 0, 1);
    utimesSync(target, past, past);
    writeOutput(out, first.files);
    expect(statSync(target).mtime.getTime()).toBe(past.getTime());
    const second = build({ "a.md": "# A\n" });
    writeOutput(out, second.files);
    expect(readdirSync(path.join(out, "content/docs"))).toEqual(["a.md"]);
    writeFileSync(path.join(out, "content/docs/a.md"), "tampered");
    writeOutput(out, second.files);
    expect(readFileSync(target, "utf-8")).toBe(second.files.get("content/docs/a.md"));
  });

  it("does not modify the docs tree", () => {
    const docsRoot = writeDocs({ "a.md": "# A\n\n% c\n" });
    const before = readFileSync(path.join(docsRoot, "a.md"), "utf-8");
    buildSite({ docsRoot });
    expect(readFileSync(path.join(docsRoot, "a.md"), "utf-8")).toBe(before);
    expect(readdirSync(docsRoot)).toEqual(["a.md"]);
  });
});

describe("failure", () => {
  it("assertBuilt throws one aggregate error and no files are produced", () => {
    const result = build({ "a.md": "# A\n\n```{nope}\n```\n", "b.md": "# B\n\n{x}`y`\n" });
    expect(result.files.size).toBe(0);
    expect(() => assertBuilt(result)).toThrow(ConversionFailedError);
    try {
      assertBuilt(result);
    } catch (error) {
      expect((error as ConversionFailedError).errors.map((failure) => `${failure.file}:${failure.line}`)).toEqual(["a.md:3", "b.md:3"]);
    }
  });
});

describe("docutils ids", () => {
  it.each([
    ["Setup", "setup"],
    ["1. Step", "step"],
    ["Café Ünï", "cafe-uni"],
    ["a_b-c", "a-b-c"],
    ["A  B", "a-b"],
    ["Æther Straße", "aether-strasze"],
    ["`code` and *em*", "code-and-em"],
    ["!!!", ""],
    ["ID1", "id1"],
    ["Ørsted Łódź", "orsted-lodz"],
  ])("makes %j into %j", (text, expected) => {
    expect(docutilsMakeId(text.replace(/[`*]/g, ""))).toBe(expected);
  });

  it("skips automatic ids that are already taken", () => {
    const ids = new IdAllocator();
    expect(ids.fromName("ID1")).toBe("id1");
    expect(ids.fromName("!!!")).toBe("id2");
    expect(ids.fromName("Setup")).toBe("setup");
    expect(ids.fromName("Setup")).toBe("id3");
  });
});

describe("sidebar config", () => {
  it("turns nested manifest items into collapsed Starlight groups", () => {
    const manifest: SidebarManifest = {
      groups: [
        { label: "Guides", items: [{ label: "One", link: "/docs/one.html", items: [{ label: "Deep", link: "/docs/deep.html" }] }] },
        { label: null, items: [{ label: "Last", link: "/docs/last.html" }] },
      ],
      order: {},
    };
    expect(toStarlightSidebar(manifest)).toEqual([
      {
        label: "Guides",
        collapsed: false,
        items: [
          {
            label: "One",
            collapsed: true,
            items: [
              { label: "One", link: "/docs/one.html" },
              { label: "Deep", link: "/docs/deep.html" },
            ],
          },
        ],
      },
      { label: "Section 2", collapsed: false, items: [{ label: "Last", link: "/docs/last.html" }] },
    ]);
  });
});

describe("body helper sanity", () => {
  it("strips front matter", () => {
    const result = build({ "a.md": "# A\n\nText.\n" });
    expect(bodyOf(result, "docs/a.md")).toBe('<span id="a"></span>\n\nText.\n');
  });
});
