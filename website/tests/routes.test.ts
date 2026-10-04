import { describe, expect, it } from "vitest";
import { docIndexDir } from "../src/lib/doc-index-route.ts";
import { htmlSitemapUrl } from "../src/lib/sitemap-url.ts";

describe("docIndexDir", () => {
  it("maps the docs root index to no directory", () => {
    expect(docIndexDir("docs/index")).toBeUndefined();
  });

  it("maps a section index to its directory", () => {
    expect(docIndexDir("docs/benchmarks/index")).toBe("benchmarks");
  });

  it("keeps nested directories", () => {
    expect(docIndexDir("docs/platforms/cloud/index")).toBe("platforms/cloud");
  });

  it("does not strip an index-suffixed directory name", () => {
    expect(docIndexDir("docs/reindex/index")).toBe("reindex");
  });
});

describe("htmlSitemapUrl", () => {
  it("keeps the site root", () => {
    expect(htmlSitemapUrl("https://benchbox.dev/")).toBe("https://benchbox.dev/");
  });

  it("appends the html extension to page urls", () => {
    expect(htmlSitemapUrl("https://benchbox.dev/docs/benchmarks/tpch")).toBe("https://benchbox.dev/docs/benchmarks/tpch.html");
    expect(htmlSitemapUrl("https://benchbox.dev/docs/benchmarks/index")).toBe("https://benchbox.dev/docs/benchmarks/index.html");
  });

  it("leaves urls that already end in html", () => {
    expect(htmlSitemapUrl("https://benchbox.dev/docs/index.html")).toBe("https://benchbox.dev/docs/index.html");
  });
});
