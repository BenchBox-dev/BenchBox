import { afterEach, describe, expect, it } from "vitest";
import { build, bodyOf, cleanup } from "./support.ts";

afterEach(cleanup);

const wrap = (body: string) => `# A\n\n\`\`\`{eval-rst}\n${body}\n\`\`\`\n`;

describe("eval-rst directive", () => {
  it("converts hyperlink bullet items with trailing descriptions", () => {
    const result = build({ "a.md": wrap("* `Archive <archive.html>`_ - Posts by year\n* `Tags <https://example.com/t>`_") });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body).toContain("- [Archive](archive.html) - Posts by year");
    expect(body).toContain("- [Tags](https://example.com/t)");
  });

  it("rejects any other rst construct with the offending line", () => {
    const result = build({ "a.md": wrap("* `Archive <archive.html>`_\n\n.. note:: hello") });
    expect(result.errors).toHaveLength(1);
    expect(result.errors[0].line).toBe(6);
    expect(result.errors[0].message).toContain("eval-rst supports only");
  });

  it("rejects markup inside the description", () => {
    const result = build({ "a.md": wrap("* `Archive <archive.html>`_ - **bold**") });
    expect(result.errors).toHaveLength(1);
  });

  it("rejects an empty block", () => {
    const result = build({ "a.md": wrap("") });
    expect(result.errors[0].message).toContain("empty");
  });
});
