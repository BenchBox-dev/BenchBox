import { afterEach, describe, expect, it } from "vitest";
import { bodyOf, build, cleanup, STUB } from "./support.ts";

afterEach(cleanup);

const FRONT = "---\nmyst:\n  enable_extensions:\n    - deflist\n---\n\n# Page\n\n";

describe("deflist", () => {
  it("emits dl, dt and dd with converted inline content", () => {
    const result = build({
      "a.md": `${FRONT}**Term** one\n: Defined with [a link](b.md) and {doc}\`b\`.\n\nPlain.\n`,
      "b.md": STUB,
    });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body).toContain("<dl>\n\n<dt><strong>Term</strong> one</dt>\n\n<dd>");
    expect(body).toContain("</dd>\n\n</dl>");
    expect(body).not.toContain("{doc}");
    expect(body).not.toContain("<dt>\n");
    expect(body).not.toContain("b.md");
    expect(body).toContain("Plain.");
  });

  it("joins lazy continuation lines", () => {
    const result = build({ "a.md": `${FRONT}Term\n: First\ncontinued\n` });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body.match(/<dd>/g)).toHaveLength(1);
    expect(body).toContain("First\ncontinued");
  });

  it("emits one dd per definition line", () => {
    const result = build({ "a.md": `${FRONT}Term\n: First\n: Second\n` });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/a.md").match(/<dd>/g)).toHaveLength(2);
  });

  it("supports several terms in one block", () => {
    const result = build({ "a.md": `${FRONT}One\n: first\nTwo\n: second\n` });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body.match(/<dt>/g)).toHaveLength(2);
    expect(body.match(/<dd>/g)).toHaveLength(2);
    expect(body.match(/<dl>/g)).toHaveLength(1);
  });

  it("merges items separated by blank lines into one dl", () => {
    const result = build({ "a.md": `${FRONT}One\n: first\n\nTwo\n: second\n\nThree\n: third\n` });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body.match(/<dl>/g)).toHaveLength(1);
    expect(body.match(/<dt>/g)).toHaveLength(3);
  });

  it("renders term links as inline html", () => {
    const result = build({ "a.md": `${FRONT}*Term* [x](https://e.com/?a=1&b=2) \`c{d}\`\n: def\n` });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/a.md")).toContain('<dt><em>Term</em> <a href="https://e.com/?a=1&amp;b=2">x</a> <code>c&#123;d&#125;</code></dt>');
  });

  it("keeps text before the term as a paragraph", () => {
    const result = build({ "a.md": `${FRONT}Intro line\nTerm\n: Definition\n` });
    const body = bodyOf(result, "docs/a.md");
    expect(body.indexOf("Intro line")).toBeLessThan(body.indexOf("<dl>"));
  });

  it("does not treat colon lines as definitions without the extension", () => {
    const result = build({ "a.md": "# Page\n\nTerm\n: Not a definition\n" });
    expect(bodyOf(result, "docs/a.md")).not.toContain("<dl>");
  });
  it("renders a definition that starts with a bullet as a list, as MyST does", () => {
    const result = build({ "a.md": `${FRONT}**Issue**\n: - **Cause**: missing\n` });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/a.md")).toContain("<dd>\n\n- **Cause**: missing\n\n</dd>");
  });

  it("rejects a definition that starts with another block construct", () => {
    expect(build({ "a.md": `${FRONT}Term\n: 1. first\n` }).errors[0].message).toContain("deflist: a definition that starts with");
  });
  it("keeps a backslash-escaped colon line as paragraph text, as MyST does", () => {
    const result = build({ "a.md": `${FRONT}Term\n\\: not a definition\n` });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body).not.toContain("<dl>");
    expect(body).toContain("Term\n: not a definition");
  });

  it("finds definitions inside a blockquote from the raw lines", () => {
    const result = build({ "a.md": `${FRONT}> Term\n> : Definition\n` });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/a.md")).toContain("<dt>Term</dt>");
  });

  it("rejects an escaped colon line mixed into a definition list", () => {
    expect(build({ "a.md": `${FRONT}Term\n: Definition\n\\: escaped\n` }).errors.map((error) => error.message)).toEqual([expect.stringContaining("backslash-escaped colon line")]);
  });
});
