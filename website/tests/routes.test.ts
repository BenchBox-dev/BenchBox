import { describe, expect, it } from "vitest";
import { docIndexDir } from "../src/lib/doc-index-route.ts";

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
