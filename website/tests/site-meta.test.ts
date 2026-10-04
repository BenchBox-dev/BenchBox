import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { canonicalPath, pageMeta, renderRobots, renderSitemap, sitemapPathForFile } from "../src/lib/page-meta.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const dist = path.resolve(here, "..", "dist");
const origin = "https://benchbox.dev";

describe("canonicalPath", () => {
  it("keeps the site root and the Explorer directory", () => {
    expect(canonicalPath("/")).toBe("/");
    expect(canonicalPath("/index.html")).toBe("/");
    expect(canonicalPath("/results/")).toBe("/results/");
  });

  it("appends the html extension to page paths", () => {
    expect(canonicalPath("/docs/benchmarks/tpch")).toBe("/docs/benchmarks/tpch.html");
    expect(canonicalPath("/docs/benchmarks/")).toBe("/docs/benchmarks/index.html");
  });

  it("leaves paths that already end in html", () => {
    expect(canonicalPath("/docs/index.html")).toBe("/docs/index.html");
  });
});

describe("pageMeta", () => {
  it("emits canonical, description, Open Graph and Twitter tags", () => {
    const tags = pageMeta({ title: "T", description: "D", pathname: "/blog/x" });
    const names = tags.map((tag) => tag.attrs.rel ?? tag.attrs.name ?? tag.attrs.property);
    expect(names).toEqual(
      expect.arrayContaining(["canonical", "description", "og:title", "og:description", "og:url", "og:image", "twitter:card", "twitter:title", "twitter:description"]),
    );
    expect(tags.find((tag) => tag.attrs.rel === "canonical")?.attrs.href).toBe(`${origin}/blog/x.html`);
  });

  it("falls back to the site description", () => {
    const tags = pageMeta({ title: "T", pathname: "/" });
    expect(tags.find((tag) => tag.attrs.name === "description")?.attrs.content).toContain("database benchmarking");
  });
});

describe("sitemap and robots", () => {
  it("maps files to served paths", () => {
    expect(sitemapPathForFile("index.html")).toBe("/");
    expect(sitemapPathForFile("results/index.html")).toBe("/results/");
    expect(sitemapPathForFile("docs/index.html")).toBe("/docs/index.html");
  });

  it("escapes and sorts urls", () => {
    const locs = [...renderSitemap(["/b.html", "/a&b.html"]).matchAll(/<loc>([^<]*)<\/loc>/g)].map((match) => match[1]);
    expect(locs).toEqual([`${origin}/a&amp;b.html`, `${origin}/b.html`]);
  });

  it("points robots at the sitemap", () => {
    expect(renderRobots()).toContain(`Sitemap: ${origin}/sitemap.xml`);
  });
});

function htmlPages(root: string, relative = ""): string[] {
  return readdirSync(path.join(root, relative), { withFileTypes: true }).flatMap((entry) => {
    const child = path.posix.join(relative, entry.name);
    if (entry.isDirectory()) return entry.name === "pagefind" || entry.name === "_astro" || entry.name === "assets" ? [] : htmlPages(root, child);
    return entry.name.endsWith(".html") ? [child] : [];
  });
}

function head(file: string): string {
  const markup = readFileSync(path.join(dist, file), "utf-8");
  return markup.slice(0, markup.indexOf("</head>"));
}

function content(markup: string, attribute: "name" | "property", value: string): string | undefined {
  const tag = new RegExp(`<meta[^>]*${attribute}="${value}"[^>]*>`).exec(markup)?.[0];
  return tag && /content="([^"]*)"/.exec(tag)?.[1];
}

describe.skipIf(!existsSync(path.join(dist, "index.html")))("built site", () => {
  const pages = existsSync(dist) ? htmlPages(dist) : [];

  it("gives every html page canonical, description, Open Graph and Twitter tags", () => {
    const missing: string[] = [];
    for (const file of pages) {
      const markup = head(file);
      const canonical = /<link[^>]*rel="canonical"[^>]*href="([^"]*)"/.exec(markup)?.[1] ?? /<link[^>]*href="([^"]*)"[^>]*rel="canonical"/.exec(markup)?.[1];
      const required = [
        canonical,
        content(markup, "name", "description"),
        content(markup, "property", "og:title"),
        content(markup, "property", "og:description"),
        content(markup, "property", "og:url"),
        content(markup, "property", "og:image"),
        content(markup, "name", "twitter:card"),
        content(markup, "name", "twitter:title"),
        content(markup, "name", "twitter:description"),
      ];
      if (required.some((value) => !value)) missing.push(file);
      else if (!canonical?.startsWith(origin)) missing.push(`${file} (canonical origin)`);
      else if (file !== "404.html" && canonical !== `${origin}${sitemapPathForFile(file)}`) missing.push(`${file} (canonical ${canonical})`);
    }
    expect(pages.length).toBeGreaterThan(1000);
    expect(missing).toEqual([]);
  });

  it("lists exactly the indexable pages in sitemap.xml", () => {
    const listed = [...readFileSync(path.join(dist, "sitemap.xml"), "utf-8").matchAll(/<loc>([^<]*)<\/loc>/g)].map((match) => match[1]);
    const expected = pages.filter((file) => file !== "404.html").map((file) => `${origin}${sitemapPathForFile(file)}`);
    expect(new Set(listed).size).toBe(listed.length);
    expect([...listed].sort()).toEqual([...expected].sort());
  });

  it("references the sitemap from robots.txt", () => {
    expect(readFileSync(path.join(dist, "robots.txt"), "utf-8")).toContain(`Sitemap: ${origin}/sitemap.xml`);
  });

  it("keeps CNAME and .nojekyll", () => {
    expect(readFileSync(path.join(dist, "CNAME"), "utf-8")).toBe(readFileSync(path.resolve(here, "..", "..", "docs", "CNAME"), "utf-8"));
    expect(existsSync(path.join(dist, ".nojekyll"))).toBe(true);
  });

  it("keeps the results redirect in the 404 page", () => {
    const markup = readFileSync(path.join(dist, "404.html"), "utf-8");
    expect(markup).toContain("benchbox.results.redirect");
    expect(markup).toContain("window.location.pathname.startsWith('/results/')");
    expect(markup).toContain("window.location.replace('/results/')");
  });
});
