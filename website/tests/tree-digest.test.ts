import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { treeDigest } from "../src/lib/tree-digest.ts";

const roots: string[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function tree(files: Record<string, string>): string {
  const root = mkdtempSync(path.join(os.tmpdir(), "benchbox-digest-"));
  roots.push(root);
  for (const [name, content] of Object.entries(files)) {
    mkdirSync(path.dirname(path.join(root, name)), { recursive: true });
    writeFileSync(path.join(root, name), content);
  }
  return root;
}

describe("tree digest", () => {
  it("matches the site-deploy assembler digest for the same tree", () => {
    const root = tree({
      "index.html": "one",
      "a/x.txt": "two",
      "a-b/y.txt": "three",
      "a/c/z.js": "four",
      "assets/Zed.css": "five",
      "assets/alpha.js": "six",
    });
    expect(treeDigest(root)).toEqual({
      sha256: "713b2a4eef78f8f3bfda5a39b752452dbfa7929742699845f7704d29a4508d14",
      totalBytes: 22,
      totalFiles: 6,
    });
  });

  it("changes when any file changes and ignores creation order", () => {
    const first = treeDigest(tree({ "a.txt": "1", "b/c.txt": "2" }));
    const second = treeDigest(tree({ "b/c.txt": "2", "a.txt": "1" }));
    const changed = treeDigest(tree({ "a.txt": "1", "b/c.txt": "3" }));
    expect(second).toEqual(first);
    expect(changed.sha256).not.toBe(first.sha256);
  });

  it("refuses a symlink anywhere in the tree", () => {
    const root = tree({ "a.txt": "1" });
    symlinkSync(path.join(root, "a.txt"), path.join(root, "link.txt"));
    expect(() => treeDigest(root)).toThrow(/symlink/);
  });
});
