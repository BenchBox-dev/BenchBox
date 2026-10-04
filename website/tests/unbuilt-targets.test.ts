import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { BLOG_PAGES } from "../src/converter/handlers/links.ts";

const websiteRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

describe("ablog catalog pages linked from the blog index", () => {
  it.each(Object.entries(BLOG_PAGES))("%s is served by an Astro route at %s", (source, url) => {
    expect(url).toBe(`/${source}`);
    const stem = path.join(websiteRoot, "src", "pages", source.replace(/\.html$/, ""));
    expect(existsSync(`${stem}.astro`)).toBe(true);
  });
});
