import { afterEach, describe, expect, it } from "vitest";
import { bodyOf, build, cleanup, STUB } from "./support.ts";

afterEach(cleanup);

const wrap = (options: string, body: string): string => `# Page\n\n\`\`\`{list-table}\n${options}\n\n${body}\n\`\`\`\n`;

describe("list-table", () => {
  it("emits a GFM table for inline cells with one header row", () => {
    const result = build({
      "a.md": wrap(":header-rows: 1\n:widths: 30 70", "* - Name\n  - Detail\n* - {doc}`b`\n  - **bold** text\n"),
      "b.md": STUB,
    });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body).toContain("| Name");
    expect(body).toMatch(/\| -+ \| -+ \|/);
    expect(body).toContain("**bold** text");
    expect(body).not.toContain("{doc}");
    expect(body).not.toContain("<table>");
  });

  it("emits an HTML table when a cell has block content", () => {
    const result = build({ "a.md": wrap(":header-rows: 1", "* - Head\n  - Other\n* - - item one\n    - item two\n  - plain\n") });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body).toContain("<table>");
    expect(body).toContain("<thead>");
    expect(body).toContain("<th>");
    expect(body).toContain("<tbody>");
    expect(body).toContain("<td>");
    expect(body).toContain("- item one");
  });

  it("emits an HTML table without thead when there are no header rows", () => {
    const result = build({ "a.md": wrap("", "* - a\n  - b\n") });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body).toContain("<table>");
    expect(body).not.toContain("<thead>");
  });

  it("supports more than one header row as HTML", () => {
    const result = build({ "a.md": wrap(":header-rows: 2", "* - a\n  - b\n* - c\n  - d\n* - e\n  - f\n") });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body.match(/<th>/g)).toHaveLength(4);
    expect(body.match(/<td>/g)).toHaveLength(2);
  });

  it("flattens soft line breaks inside GFM cells", () => {
    const result = build({ "a.md": wrap(":header-rows: 1", "* - h1\n  - h2\n* - first\n    second\n  - x\n") });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/a.md")).toContain("first second");
  });

  it("rejects ragged rows, bad widths and too many header rows", () => {
    expect(build({ "a.md": wrap("", "* - a\n  - b\n* - c\n") }).errors[0].message).toContain("same number of cells");
    expect(build({ "a.md": wrap(":widths: 1 2 3", "* - a\n  - b\n") }).errors[0].message).toContain(":widths:");
    expect(build({ "a.md": wrap(":header-rows: 3", "* - a\n  - b\n") }).errors[0].message).toContain(":header-rows:");
  });

  it("rejects unknown options", () => {
    expect(build({ "a.md": wrap(":class: wide", "* - a\n  - b\n") }).errors[0].message).toContain("directive-option:list-table:class");
  });
});
