import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";
import { EXCLUDED_FILES, EXCLUDED_ROOTS, listDocSources, PUBLISH_LIST_FILE, PUBLISH_LIST_ROOTS, readPublishList } from "../src/converter/sources.ts";

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

describe("source exclusions", () => {
  const excludes = sphinxExcludes().filter((pattern) => !pattern.startsWith(".") && pattern !== "Thumbs.db");

  it("skip every Markdown page or directory that conf.py excludes", () => {
    const docsRoot = path.join(workDir, "docs");
    mkdirSync(docsRoot);
    writeFileSync(path.join(docsRoot, "kept.md"), "# Kept\n");
    const planted: string[] = [];
    for (const pattern of excludes) {
      if (pattern.endsWith(".md")) {
        mkdirSync(path.dirname(path.join(docsRoot, pattern)), { recursive: true });
        writeFileSync(path.join(docsRoot, pattern), "# Excluded\n");
        planted.push(pattern);
      } else if (!path.extname(pattern)) {
        mkdirSync(path.join(docsRoot, pattern), { recursive: true });
        writeFileSync(path.join(docsRoot, pattern, "page.md"), "# Excluded\n");
        planted.push(`${pattern}/page.md`);
      }
    }
    expect(planted.length).toBeGreaterThan(0);
    const listed = listDocSources(docsRoot).map((source) => source.relative);
    expect(listed).toEqual(["kept.md"]);
  });

  it("skip exactly what Sphinx skips, plus the tag pages the converter generates itself", () => {
    const assetPaths = [...pythonList("templates_path"), ...pythonList("html_static_path"), ...pythonList("html_extra_path")].filter((entry) => !entry.startsWith(".."));
    const directories = [...sphinxExcludes().filter((pattern) => !/[./]/.test(pattern)), ...assetPaths, pythonString("tags_output_dir")];
    expect([...EXCLUDED_ROOTS].sort()).toEqual([...new Set(directories)].sort());
    const files = sphinxExcludes().filter((pattern) => /\.(md|rst)$/.test(pattern));
    expect([...EXCLUDED_FILES].sort()).toEqual(files.sort());
  });

  it("index reStructuredText pages under the same exclusions", () => {
    const docsRoot = path.join(workDir, "rst");
    for (const relative of ["kept.rst", "agent/x.rst", "_static/y.rst", "sub/_sources/z.rst", "sub/.#lock.rst", "sub/page.rst"]) {
      mkdirSync(path.dirname(path.join(docsRoot, relative)), { recursive: true });
      writeFileSync(path.join(docsRoot, relative), "T\n=\n");
    }
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

// Pages under a publish-list directory that are on neither the publish list
// nor the exclusion list. Each one needs a decision before it can merge.
function unclassifiedPages(docsRoot: string): string[] {
  const listed = readPublishList(docsRoot);
  return PUBLISH_LIST_ROOTS.flatMap((root) => pagesUnder(docsRoot, root)).filter((page) => !listed.has(page) && !EXCLUDED_FILES.has(page));
}

const HOW_TO_FIX = `Decide whether each page is for people who use BenchBox or for outside contributors. If it is, add it to docs/${PUBLISH_LIST_FILE}. If not, move it to docs/internal/, or list it in EXCLUDED_FILES in website/src/converter/sources.ts and exclude_patterns in docs/conf.py.`;

describe("publish list for docs/development and docs/operations", () => {
  it("classifies every page as published or excluded", () => {
    expect(unclassifiedPages(docsDir), HOW_TO_FIX).toEqual([]);
  });

  it("names only existing pages, none of them excluded", () => {
    const listed = [...readPublishList(docsDir)];
    expect(listed.length).toBeGreaterThan(0);
    expect(listed.filter((page) => !existsSync(path.join(docsDir, page)))).toEqual([]);
    expect(listed.filter((page) => EXCLUDED_FILES.has(page) || !PUBLISH_LIST_ROOTS.some((root) => page.startsWith(`${root}/`)))).toEqual([]);
  });

  it("flags and leaves out a new page that is on neither list", () => {
    const docsRoot = path.join(workDir, "gated");
    for (const relative of ["development/kept.md", "development/new-page.md", "operations/runbook.md", "guides/user.md"]) {
      mkdirSync(path.dirname(path.join(docsRoot, relative)), { recursive: true });
      writeFileSync(path.join(docsRoot, relative), "# Page\n");
    }
    writeFileSync(path.join(docsRoot, PUBLISH_LIST_FILE), "# comment\ndevelopment/kept.md\n");
    expect(unclassifiedPages(docsRoot)).toEqual(["development/new-page.md", "operations/runbook.md"]);
    expect(listDocSources(docsRoot).map((source) => source.relative)).toEqual(["development/kept.md", "guides/user.md"]);
  });

  it("publishes nothing from those directories when the list is missing", () => {
    const docsRoot = path.join(workDir, "unlisted");
    mkdirSync(path.join(docsRoot, "operations"), { recursive: true });
    writeFileSync(path.join(docsRoot, "operations", "runbook.md"), "# Runbook\n");
    writeFileSync(path.join(docsRoot, "index.md"), "# Home\n");
    expect(listDocSources(docsRoot).map((source) => source.relative)).toEqual(["index.md"]);
  });
});
