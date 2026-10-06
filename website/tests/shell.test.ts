import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { blogTrail, docsTrail, pathAncestors, type TrailEntry } from "../src/lib/breadcrumbs.ts";
import { editUrlFor } from "../src/lib/edit-url.ts";
import { shellCta, shellLinks, sitePath, surfaceFor } from "../src/lib/header-links.ts";

const here = path.dirname(fileURLToPath(import.meta.url));

describe("shell header links", () => {
  it("lists the contract links in order with local hrefs for site pages", () => {
    const links = shellLinks("/docs/usage/getting-started.html");
    expect(links.map((link) => [link.label, link.href])).toEqual([
      ["Home", "/"],
      ["Docs", "/docs/"],
      ["Blog", "/blog/"],
      ["Results", "/results/"],
      ["GitHub", "https://github.com/BenchBox-dev/BenchBox"],
    ]);
    expect(shellCta()).toEqual({ label: "Run benchmark", href: "/docs/usage/installation.html" });
  });

  it("marks only the link for the current surface", () => {
    const current = (pathname: string) => shellLinks(pathname).filter((link) => link.current).map((link) => link.label);
    expect(current("/")).toEqual(["Home"]);
    expect(current("/docs/usage/getting-started.html")).toEqual(["Docs"]);
    expect(current("/blog/2026-05-18-v0-3-0-release-overview.html")).toEqual(["Blog"]);
    expect(current("/results/platforms/")).toEqual(["Results"]);
    expect(current("/404.html")).toEqual([]);
  });

  it("opens only the external link in a new tab", () => {
    expect(shellLinks("/").filter((link) => link.external).map((link) => link.label)).toEqual(["GitHub"]);
  });

  it("keeps foreign hrefs absolute", () => {
    expect(sitePath("https://benchbox.dev/blog/")).toBe("/blog/");
    expect(sitePath("https://github.com/BenchBox-dev/BenchBox")).toBe("https://github.com/BenchBox-dev/BenchBox");
    expect(surfaceFor("/documents")).toBeUndefined();
  });
});

describe("edit links", () => {
  it("points authored pages at their source", () => {
    expect(editUrlFor("docs/usage/getting-started.md")).toBe("https://github.com/BenchBox-dev/BenchBox/edit/develop/docs/usage/getting-started.md");
  });

  it("omits generated and unsafe sources", () => {
    expect(editUrlFor(undefined)).toBeUndefined();
    expect(editUrlFor("docs/_tags/duckdb.md")).toBeUndefined();
    expect(editUrlFor("docs/benchmarks/queries/tpch/q1.md")).toBeUndefined();
    expect(editUrlFor("../secrets.md")).toBeUndefined();
  });
});

describe("breadcrumbs", () => {
  const sidebar: TrailEntry[] = [
    {
      type: "group",
      label: "Getting Started",
      entries: [
        { type: "link", label: "Overview", href: "/docs/README.html", isCurrent: false },
        {
          type: "group",
          label: "Tutorials",
          entries: [
            { type: "link", label: "Tutorials", href: "/docs/tutorials/index.html", isCurrent: false },
            { type: "link", label: "First run", href: "/docs/tutorials/first-run.html", isCurrent: true },
          ],
        },
      ],
    },
  ];

  it("builds the trail from the sidebar groups", () => {
    expect(docsTrail(sidebar, "First run", "/docs/tutorials/first-run.html")).toEqual([
      { label: "Docs", href: "/docs/" },
      { label: "Getting Started" },
      { label: "Tutorials", href: "/docs/tutorials/index.html" },
      { label: "First run" },
    ]);
  });

  it("does not repeat a section whose own page is current", () => {
    const own = structuredClone(sidebar);
    const tutorials = (own[0] as { entries: TrailEntry[] }).entries[1] as { entries: { isCurrent: boolean }[] };
    tutorials.entries[0].isCurrent = true;
    tutorials.entries[1].isCurrent = false;
    expect(docsTrail(own, "Tutorials", "/docs/tutorials/index.html").map((crumb) => crumb.label)).toEqual(["Docs", "Getting Started", "Tutorials"]);
  });

  it("falls back to the docs root for pages outside the sidebar and hides on the docs root", () => {
    expect(docsTrail([], "Loose page", "/docs/loose.html")).toEqual([{ label: "Docs", href: "/docs/" }, { label: "Loose page" }]);
    expect(docsTrail(sidebar, "BenchBox", "/docs/")).toEqual([]);
  });

  it("builds ancestors from index pages when the sidebar has no match", () => {
    const titles = new Map([
      ["benchmarks", "Benchmarks"],
      ["benchmarks/queries", "Query Templates"],
      ["benchmarks/queries/tpch", "TPC-H"],
    ]);
    const path = "/docs/benchmarks/queries/tpch/q1.html";
    expect(docsTrail([], "TPC-H Q1", path, titles)).toEqual([
      { label: "Docs", href: "/docs/" },
      { label: "Benchmarks", href: "/docs/benchmarks/index.html" },
      { label: "Query Templates", href: "/docs/benchmarks/queries/index.html" },
      { label: "TPC-H", href: "/docs/benchmarks/queries/tpch/index.html" },
      { label: "TPC-H Q1" },
    ]);
    expect(pathAncestors("/docs/benchmarks/queries/tpch/q1.html", new Map([["benchmarks/queries", "Query Templates"]]))).toEqual([
      { label: "Query Templates", href: "/docs/benchmarks/queries/index.html" },
    ]);
    expect(docsTrail([], "TPC-H", "/docs/benchmarks/queries/tpch/index.html", titles).map((crumb) => crumb.label)).toEqual([
      "Docs",
      "Benchmarks",
      "Query Templates",
      "TPC-H",
    ]);
  });

  it("builds the blog trail except on the blog index", () => {
    expect(blogTrail("A post", false)).toEqual([{ label: "Blog", href: "/blog/" }, { label: "A post" }]);
    expect(blogTrail("Blog", true)).toEqual([]);
  });
});

describe("shell sources", () => {
  const read = (relative: string) => readFileSync(path.join(here, "..", relative), "utf-8");

  it("takes labels and links from the shared header contract only", () => {
    const header = read("src/components/SiteHeader.astro");
    expect(header).toContain("shellLinks");
    expect(header).not.toMatch(/benchbox\.dev|href="\/docs/);
  });

  it("uses the shared theme storage key and writes both theme attributes", () => {
    for (const file of ["src/components/ThemeScript.astro", "src/components/ThemeToggle.astro"]) {
      const source = read(file);
      expect(source).toContain("benchbox:theme");
      expect(source).toContain("dataset.bbTheme");
      expect(source).toContain("dataset.theme");
    }
  });

  it("limits the search index to docs and blog and keeps shell chrome out of it", () => {
    const search = read("src/components/SearchBox.astro");
    expect(search).not.toContain("data-search-section");
    expect(read("scripts/pagefind-index.mjs")).toContain('["docs", "blog"]');
    expect(read("src/components/SiteFooter.astro")).toContain("data-pagefind-ignore");
  });

  it("puts the theme control beside search in the header and out of the footer", () => {
    const header = read("src/components/SiteHeader.astro");
    expect(header.indexOf("<SearchBox />")).toBeLessThan(header.indexOf("<ThemeToggle />"));
    expect(header.indexOf("<ThemeToggle />")).toBeGreaterThan(header.indexOf("</nav>"));
    expect(read("src/components/SiteFooter.astro")).not.toContain("ThemeToggle");
  });

  it("keeps the nav toggle before the panel it controls", () => {
    const header = read("src/components/SiteHeader.astro");
    expect(header.indexOf("data-site-header-toggle")).toBeLessThan(header.indexOf("data-site-header-panel"));
    expect(header).toContain('aria-controls="site-header-panel"');
  });
});
