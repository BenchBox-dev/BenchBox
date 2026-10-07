import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { TAG_CATEGORIES } from "../src/converter/tag-categories.ts";

const pythonSource = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "_extensions", "sphinx_tags_fix.py");

function parsePythonCategories(): { slug: string; title: string; tags: string[] }[] {
  const source = readFileSync(pythonSource, "utf-8");
  const start = source.indexOf("TAG_CATEGORIES = {");
  const end = source.indexOf("\n}\n", start);
  const body = source
    .slice(start + "TAG_CATEGORIES = ".length, end + 2)
    .split("\n")
    .filter((line) => !line.trim().startsWith("#"))
    .join("\n");
  const entry = /"([^"]+)":\s*\(\s*"([^"]+)",\s*\[([^\]]*)\]/g;
  return [...body.matchAll(entry)].map((match) => ({
    slug: match[1],
    title: match[2],
    tags: [...match[3].matchAll(/"([^"]+)"/g)].map((tag) => tag[1]),
  }));
}

describe("tag categories", () => {
  it("match the Sphinx extension", () => {
    const parsed = parsePythonCategories();
    expect(parsed.length).toBeGreaterThan(0);
    expect(TAG_CATEGORIES.map((category) => ({ slug: category.slug, title: category.title, tags: [...category.tags] }))).toEqual(parsed);
  });
});
