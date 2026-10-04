import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { inflateSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { buildSite } from "../src/converter/build.ts";
import { downloadUrlPath, imageUrlPath, publishLegacyFiles, REDIRECT_PAGES, renderObjectsInventory } from "../src/lib/legacy-assets.ts";
import { fileURLToPath } from "node:url";
import { builtSite } from "./built-site.ts";
import { writeDocs } from "./support.ts";

const dist = builtSite();
const built = dist === undefined ? describe.skip : describe;

describe("legacy public file paths", () => {
  it("reproduces the Sphinx download path from the source-relative file path", () => {
    const digest = createHash("md5").update("../examples/getting_started/run.py").digest("hex");
    expect(downloadUrlPath("../examples/getting_started/run.py")).toBe(`/docs/_downloads/${digest}/run.py`);
    expect(imageUrlPath("chart.png")).toBe("/docs/_images/chart.png");
  });

  it("copies each file to its legacy path and fails on a missing source", () => {
    const root = mkdtempSync(path.join(os.tmpdir(), "benchbox-legacy-"));
    try {
      mkdirSync(path.join(root, "docs", "blog", "images"), { recursive: true });
      mkdirSync(path.join(root, "examples"));
      writeFileSync(path.join(root, "docs", "blog", "images", "chart.png"), "png");
      writeFileSync(path.join(root, "examples", "run.py"), "print(1)\n");
      const out = path.join(root, "out");
      expect(publishLegacyFiles({ downloads: ["../examples/run.py"], images: ["chart.png"] }, path.join(root, "docs"), out)).toBe(2);
      expect(readFileSync(path.join(out, downloadUrlPath("../examples/run.py")), "utf-8")).toBe("print(1)\n");
      expect(readFileSync(path.join(out, "docs", "_images", "chart.png"), "utf-8")).toBe("png");
      expect(() => publishLegacyFiles({ downloads: ["../examples/gone.py"], images: [] }, path.join(root, "docs"), out)).toThrow("missing");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});

describe("download and image records", () => {
  it("records files that Sphinx would publish as downloads and the blog images a page uses", () => {
    const docsRoot = writeDocs({
      "docs/guide/a.md": "# A\n\n[Run](../../examples/run.py#L2) [Data](../data.csv) [Readme](../../README.md) [Pkg](../../examples/)\n",
      "docs/data.csv": "a\n",
      "examples/run.py": "x\n",
      "README.md": "# Repo\n",
      "docs/blog/images/chart.png": "png",
      "docs/blog/post.md": "# Post\n\n![Chart](images/chart.png)\n",
    });
    const result = buildSite({ docsRoot: path.join(docsRoot, "docs") });
    expect(result.errors).toEqual([]);
    const guide = result.infos.find((info) => info.path === "guide/a.md");
    expect(guide?.downloads).toEqual(["../examples/run.py", "data.csv"]);
    expect(result.infos.find((info) => info.path === "blog/post.md")?.images).toEqual(["chart.png"]);
    expect(JSON.parse(result.files.get("manifest/legacy-files.json") ?? "{}")).toEqual({ downloads: ["../examples/run.py", "data.csv"], images: ["chart.png"] });
  });
});

describe("objects inventory", () => {
  it("writes a Sphinx version 2 inventory that lists pages and labels", () => {
    const bytes = renderObjectsInventory(
      [
        { name: "usage/start", role: "doc", uri: "usage/start.html", title: "Getting started" },
        { name: "install", role: "label", uri: "usage/start.html#install", title: "Install  BenchBox" },
      ],
      "BenchBox",
      "1.2.3",
    );
    const text = bytes.toString("latin1");
    expect(text.startsWith("# Sphinx inventory version 2\n# Project: BenchBox\n# Version: 1.2.3\n# The remainder of this file is compressed using zlib.\n")).toBe(true);
    const body = bytes.subarray(Buffer.byteLength("# Sphinx inventory version 2\n# Project: BenchBox\n# Version: 1.2.3\n# The remainder of this file is compressed using zlib.\n"));
    expect(inflateSync(body).toString("utf-8")).toBe("usage/start std:doc -1 usage/start.html Getting started\ninstall std:label -1 usage/start.html#install Install BenchBox\n");
  });
});

built("built site", () => {
  it("serves redirect pages for the retired Sphinx pages", () => {
    for (const [file, target] of Object.entries(REDIRECT_PAGES)) {
      const html = readFileSync(path.join(dist as string, file), "utf-8");
      expect(html).toContain(`<meta http-equiv="refresh" content="0; url=${target}">`);
      expect(html).toContain(`<link rel="canonical" href="https://benchbox.dev${target}">`);
      expect(existsSync(path.join(dist as string, target.endsWith("/") ? `${target}index.html` : target))).toBe(true);
    }
    expect(readFileSync(path.join(dist as string, "sitemap.xml"), "utf-8")).not.toContain("genindex");
  });

  it("publishes the legacy download, image and inventory files", () => {
    const legacy = JSON.parse(readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "..", ".generated", "manifest", "legacy-files.json"), "utf-8")) as { downloads: string[]; images: string[] };
    expect(legacy.downloads.length).toBeGreaterThan(0);
    for (const relative of legacy.downloads) expect(existsSync(path.join(dist as string, downloadUrlPath(relative)))).toBe(true);
    for (const name of legacy.images) expect(existsSync(path.join(dist as string, imageUrlPath(name)))).toBe(true);
    const inventory = readFileSync(path.join(dist as string, "docs", "objects.inv"));
    expect(inventory.toString("latin1").startsWith("# Sphinx inventory version 2\n# Project: BenchBox\n")).toBe(true);
  });
});
