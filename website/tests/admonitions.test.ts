import { afterEach, describe, expect, it } from "vitest";
import { UnknownConstructError } from "../src/converter/errors.ts";
import { build, bodyOf, cleanup, pageOf } from "./support.ts";

afterEach(cleanup);

describe("admonitions", () => {
  it.each([
    ["note", "note", "Note"],
    ["tip", "tip", "Tip"],
    ["warning", "caution", "Warning"],
    ["important", "caution", "Important"],
  ])("maps %s to a %s callout titled %s", (kind, type, title) => {
    const result = build({ "a.md": `# A\n\n\`\`\`{${kind}}\nBody **text**.\n\`\`\`\n` });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.mdx");
    expect(body).toContain(`<Callout type="${type}" title="${title}">`);
    expect(body).toContain("Body **text**.");
    expect(pageOf(result, "docs/a.mdx")).toContain('import Callout from "../../../src/components/docs/Callout.astro";');
  });

  it("includes the version for deprecated", () => {
    const result = build({ "a.md": "# A\n\n```{deprecated} v0.2.0\nGone.\n```\n" });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/a.mdx")).toContain('title="Deprecated since v0.2.0"');
  });

  it("requires a version for deprecated", () => {
    const result = build({ "a.md": "# A\n\n```{deprecated}\nGone.\n```\n" });
    expect(result.errors[0]).toBeInstanceOf(UnknownConstructError);
    expect(result.errors[0].line).toBe(3);
  });

  it("rejects deprecated without a version at its file and line", () => {
    const result = build({ "a.md": "# A\n\n```{deprecated}\nGone.\n```\n" });
    expect(result.errors[0].message).toContain("a.md:3");
  });

  it("converts links and lists inside the body", () => {
    const result = build({ "a.md": "# A\n\n```{note}\n- see {doc}`b`\n- [ext](https://example.com)\n```\n", "b.md": "# B\n" });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.mdx");
    expect(body).toContain("- [");
    expect(body).toContain("(https://example.com)");
    expect(body).not.toContain("{doc}");
  });

  it("converts nested directives and roles in the body", () => {
    const result = build({ "a.md": "# A\n\n````{note}\nSee {doc}`b`.\n\n```{tip}\nInner\n```\n````\n", "b.md": "# B\n" });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.mdx");
    expect(body).toContain("<Callout");
    expect(body.match(/<Callout /g)).toHaveLength(2);
    expect(body).not.toContain("{doc}");
  });

  it("rejects unknown options with the directive line", () => {
    const result = build({ "a.md": "# A\n\ntext\n\n```{note}\n:class: x\nBody\n```\n" });
    expect(result.errors).toHaveLength(1);
    expect(result.errors[0]).toBeInstanceOf(UnknownConstructError);
    expect(result.errors[0].line).toBe(5);
  });
});
