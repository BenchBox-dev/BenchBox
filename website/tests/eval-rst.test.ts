import { afterEach, describe, expect, it } from "vitest";
import { build, bodyOf, cleanup } from "./support.ts";

afterEach(cleanup);

const wrap = (body: string) => `# A\n\n\`\`\`{eval-rst}\n${body}\n\`\`\`\n`;

describe("eval-rst directive", () => {
  it("resolves item targets like any link, with trailing descriptions", () => {
    const result = build({ "a.md": wrap("* `Guide <b.md>`_ - Read this\n* `Tags <https://example.com/t>`_"), "b.md": "# B\n" });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body).toContain("- [Guide](/docs/b.html) - Read this");
    expect(body).toContain("- [Tags](https://example.com/t)");
  });

  it("fails on an item target that is not built, with its line", () => {
    const result = build({ "a.md": wrap("* `Ok <https://example.com>`_\n* `Archive <archive.html>`_") });
    expect(result.errors.map((error) => error.message)).toEqual(["a.md:5: link:archive.html does not match a document or file under docs/"]);
  });

  it("links the ablog archive, tag and author pages to the routes the blog builds", () => {
    const result = build({ "blog/index.md": wrap("* `Archive <archive.html>`_ - by year\n* `Tags <tag.html>`_\n* `Authors <author.html>`_").replace("# A", "# Blog") });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "blog/index.md");
    expect(body).toContain("- [Archive](/blog/archive.html) - by year\n- [Tags](/blog/tag.html)\n- [Authors](/blog/author.html)");
  });

  it("rejects any other rst construct with the offending line", () => {
    const result = build({ "a.md": wrap("* `Ok <https://example.com>`_\n\n.. note:: hello") });
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
