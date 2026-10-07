import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";
import { EXCLUSIONS_FILE, listDocSources, PUBLISH_LIST_FILE, PUBLISH_LIST_ROOTS, readPublishExclusions, readPublishList, RENDERER_ROOTS } from "../src/converter/sources.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const docsDir = path.join(here, "..", "..", "docs");
const confPath = path.join(docsDir, "conf.py");
const conf = readFileSync(confPath, "utf-8");

function pythonList(name: string): string[] {
  const block = new RegExp(`^${name}\\s*=\\s*\\[([^\\]]*)\\]`, "m").exec(conf);
  if (block === null) return [];
  return [...block[1].matchAll(/"([^"]+)"/g)].map((match) => match[1]);
}

function pythonString(name: string): string {
  const value = new RegExp(`^${name}\\s*=\\s*"([^"]+)"`, "m").exec(conf);
  if (value === null) throw new Error(`${name} not found in docs/conf.py`);
  return value[1];
}

function sphinxExcludes(): string[] {
  const patterns = pythonList("exclude_patterns");
  if (patterns.length === 0) throw new Error("exclude_patterns not found in docs/conf.py");
  return patterns;
}

const workDir = mkdtempSync(path.join(os.tmpdir(), "sources-"));
afterAll(() => rmSync(workDir, { recursive: true, force: true }));

const exclusions = readPublishExclusions(docsDir);

describe("source exclusions", () => {
  it("read a non-empty exclusion list from the docs tree", () => {
    expect(existsSync(path.join(docsDir, EXCLUSIONS_FILE))).toBe(true);
    expect(exclusions.roots.size).toBeGreaterThan(0);
    expect(exclusions.files.size).toBeGreaterThan(0);
  });

  it("skip every listed Markdown page and directory", () => {
    const docsRoot = path.join(workDir, "docs");
    mkdirSync(docsRoot);
    writeFileSync(path.join(docsRoot, "kept.md"), "# Kept\n");
    writeFileSync(path.join(docsRoot, EXCLUSIONS_FILE), readFileSync(path.join(docsDir, EXCLUSIONS_FILE), "utf-8"));
    for (const root of [...exclusions.roots, ...RENDERER_ROOTS]) {
      mkdirSync(path.join(docsRoot, root), { recursive: true });
      writeFileSync(path.join(docsRoot, root, "page.md"), "# Excluded\n");
    }
    for (const file of [...exclusions.files].filter((entry) => entry.endsWith(".md"))) {
      mkdirSync(path.dirname(path.join(docsRoot, file)), { recursive: true });
      writeFileSync(path.join(docsRoot, file), "# Excluded\n");
    }
    expect(listDocSources(docsRoot).map((source) => source.relative)).toEqual(["kept.md"]);
  });

  it("skip what Sphinx skips: the shared list plus each renderer's own working directories", () => {
    expect(conf).toContain(`DOCS_ROOT / "${EXCLUSIONS_FILE}"`);
    expect(sphinxExcludes().sort()).toEqual([".DS_Store", "Thumbs.db", "_build"]);
    const assetPaths = [...pythonList("templates_path"), ...pythonList("html_static_path"), ...pythonList("html_extra_path")].filter((entry) => !entry.startsWith(".."));
    expect([...RENDERER_ROOTS].sort()).toEqual([...new Set(["_build", ...assetPaths, pythonString("tags_output_dir")])].sort());
  });

  it("index reStructuredText pages under the same exclusions", () => {
    const docsRoot = path.join(workDir, "rst");
    for (const relative of ["kept.rst", "agent/x.rst", "_static/y.rst", "sub/_sources/z.rst", "sub/.#lock.rst", "sub/page.rst"]) {
      mkdirSync(path.dirname(path.join(docsRoot, relative)), { recursive: true });
      writeFileSync(path.join(docsRoot, relative), "T\n=\n");
    }
    writeFileSync(path.join(docsRoot, EXCLUSIONS_FILE), "# comment\nagent/\n");
    expect(listDocSources(docsRoot, ".rst").map((source) => source.relative)).toEqual(["kept.rst", "sub/page.rst"]);
  });
});

function pagesUnder(docsRoot: string, root: string): string[] {
  const directory = path.join(docsRoot, root);
  if (!existsSync(directory)) return [];
  return readdirSync(directory, { recursive: true, encoding: "utf-8" })
    .filter((entry) => entry.endsWith(".md"))
    .map((entry) => `${root}/${entry.split(path.sep).join("/")}`)
    .sort();
}

function unclassifiedPages(docsRoot: string): string[] {
  const listed = readPublishList(docsRoot);
  return PUBLISH_LIST_ROOTS.flatMap((root) => pagesUnder(docsRoot, root)).filter((page) => !listed.has(page) && !readPublishExclusions(docsRoot).files.has(page));
}

const HOW_TO_FIX = `Decide whether each page is for people who use BenchBox or for outside contributors. If it is, add it to docs/${PUBLISH_LIST_FILE}. If not, move it to docs/internal/ or list it in docs/${EXCLUSIONS_FILE}.`;

describe("publish list for docs/development and docs/operations", () => {
  it("classifies every page as published or excluded", () => {
    expect(unclassifiedPages(docsDir), HOW_TO_FIX).toEqual([]);
  });

  it("names only existing pages, none of them excluded", () => {
    const listed = [...readPublishList(docsDir)];
    expect(listed.length).toBeGreaterThan(0);
    expect(listed.filter((page) => !existsSync(path.join(docsDir, page)))).toEqual([]);
    expect(listed.filter((page) => exclusions.files.has(page) || !PUBLISH_LIST_ROOTS.some((root) => page.startsWith(`${root}/`)))).toEqual([]);
  });

  it("flags and leaves out a new page that is on neither list", () => {
    const docsRoot = path.join(workDir, "gated");
    for (const relative of ["development/kept.md", "development/new-page.md", "operations/runbook.md", "guides/user.md"]) {
      mkdirSync(path.dirname(path.join(docsRoot, relative)), { recursive: true });
      writeFileSync(path.join(docsRoot, relative), "# Page\n");
    }
    writeFileSync(path.join(docsRoot, PUBLISH_LIST_FILE), "# comment\ndevelopment/kept.md\n");
    writeFileSync(path.join(docsRoot, EXCLUSIONS_FILE), "");
    expect(unclassifiedPages(docsRoot)).toEqual(["development/new-page.md", "operations/runbook.md"]);
    expect(listDocSources(docsRoot).map((source) => source.relative)).toEqual(["development/kept.md", "guides/user.md"]);
  });

  it("refuses to list sources when the exclusion list is missing", () => {
    const docsRoot = path.join(workDir, "no-exclusions");
    mkdirSync(path.join(docsRoot, "agent"), { recursive: true });
    writeFileSync(path.join(docsRoot, "agent", "notes.md"), "# Notes\n");
    expect(() => listDocSources(docsRoot)).toThrow(EXCLUSIONS_FILE);
  });

  it("publishes nothing from those directories when the list is missing", () => {
    const docsRoot = path.join(workDir, "unlisted");
    mkdirSync(path.join(docsRoot, "operations"), { recursive: true });
    writeFileSync(path.join(docsRoot, "operations", "runbook.md"), "# Runbook\n");
    writeFileSync(path.join(docsRoot, "index.md"), "# Home\n");
    writeFileSync(path.join(docsRoot, EXCLUSIONS_FILE), "");
    expect(listDocSources(docsRoot).map((source) => source.relative)).toEqual(["index.md"]);
  });
});
