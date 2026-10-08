import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { buildSite } from "../src/converter/build.ts";
import { EXCLUSIONS_FILE } from "../src/converter/sources.ts";

const roots: string[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function repository(files: Record<string, string>): string {
  const root = mkdtempSync(path.join(os.tmpdir(), "benchbox-repo-"));
  roots.push(root);
  for (const [relative, content] of Object.entries({ [`docs/${EXCLUSIONS_FILE}`]: "", ...files })) {
    mkdirSync(path.dirname(path.join(root, relative)), { recursive: true });
    writeFileSync(path.join(root, relative), content);
  }
  return path.join(root, "docs");
}

function bodyOf(docsRoot: string, name: string): string {
  const result = buildSite({ docsRoot });
  expect(result.errors).toEqual([]);
  return result.files.get(`content/${name}`) ?? "";
}

describe("links to repository files", () => {
  it("points files outside docs at the repository source with the fragment kept", () => {
    const docsRoot = repository({ "docs/guide/a.md": "# A\n\n[Source](../../benchbox/core/queries.py#L10)\n", "benchbox/core/queries.py": "x = 1\n" });
    expect(bodyOf(docsRoot, "docs/guide/a.md")).toContain("(https://github.com/BenchBox-dev/BenchBox/blob/develop/benchbox/core/queries.py#L10)");
  });

  it("points directories outside docs at the repository tree", () => {
    const docsRoot = repository({ "docs/a.md": "# A\n\n[Pkg](../benchbox/sql_compat/)\n", "benchbox/sql_compat/x.py": "" });
    expect(bodyOf(docsRoot, "docs/a.md")).toContain("(https://github.com/BenchBox-dev/BenchBox/tree/develop/benchbox/sql_compat)");
  });

  it("points Markdown files outside docs at the repository instead of a docs page", () => {
    const docsRoot = repository({ "docs/guide/a.md": "# A\n\n[Readme](../../README.md)\n", "docs/README.md": "# Docs readme\n", "README.md": "# Repo\n" });
    expect(bodyOf(docsRoot, "docs/guide/a.md")).toContain("(https://github.com/BenchBox-dev/BenchBox/blob/develop/README.md)");
  });

  it("points non-page files under docs at the repository and fails on a missing target", () => {
    const docsRoot = repository({ "docs/a.md": "# A\n\n[Gone](../nowhere.py) [Data](data.csv)\n", "docs/data.csv": "a\n" });
    const result = buildSite({ docsRoot });
    expect(result.errors.map((error) => error.message)).toEqual(["a.md:3: link:../nowhere.py does not match a file in the repository"]);
    const kept = repository({ "docs/guide/a.md": "# A\n\n[Data](../data/x.csv#L2)\n", "docs/data/x.csv": "a\n" });
    expect(bodyOf(kept, "docs/guide/a.md")).toContain("(https://github.com/BenchBox-dev/BenchBox/blob/develop/docs/data/x.csv#L2)");
  });
});
