import { existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { clearOutput, OUTPUT_MARKER, UnownedOutputError, writeOutput } from "../src/converter/build.ts";
import { build, cleanup } from "./support.ts";

const roots: string[] = [];

afterEach(() => {
  cleanup();
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function scratch(): string {
  const root = mkdtempSync(path.join(os.tmpdir(), "benchbox-out-"));
  roots.push(root);
  return root;
}

describe("converter output directory", () => {
  it("writes into a missing or empty directory and marks it as converter output", () => {
    const out = path.join(scratch(), "generated");
    writeOutput(out, new Map([["content/a.md", "x"]]));
    expect(readdirSync(out).sort()).toEqual([OUTPUT_MARKER, "content"]);
    writeOutput(out, new Map([["content/b.md", "y"]]));
    expect(readdirSync(path.join(out, "content"))).toEqual(["b.md"]);
  });

  it("refuses a non-empty directory without the marker and never deletes from it", () => {
    const out = scratch();
    writeFileSync(path.join(out, "keep.txt"), "mine");
    expect(() => writeOutput(out, new Map([["content/a.md", "x"]]))).toThrow(UnownedOutputError);
    expect(() => clearOutput(out)).toThrow(UnownedOutputError);
    expect(readdirSync(out)).toEqual(["keep.txt"]);
  });

  it("clears only a marked directory", () => {
    const out = path.join(scratch(), "generated");
    mkdirSync(out);
    writeOutput(out, new Map([["content/a.md", "x"]]));
    clearOutput(out);
    expect(existsSync(out)).toBe(false);
  });
});

describe("MDX validity", () => {
  it("fails with file and line on raw html that would break a page using a component", () => {
    const result = build({ "a.md": "# A\n\n```{note}\nhi\n```\n\nText\n\n<div>\nopen <br> here\n</div>\n" });
    expect(result.errors.map((error) => error.message)).toEqual([expect.stringMatching(/^a\.md:9: content is not valid MDX on this page, which uses a component: Expected a closing tag for `<br>`/)]);
  });
});
