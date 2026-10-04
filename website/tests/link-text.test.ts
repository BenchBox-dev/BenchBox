import { afterEach, describe, expect, it } from "vitest";
import { build, bodyOf, cleanup } from "./support.ts";

afterEach(cleanup);

function messages(files: Record<string, string>): string[] {
  return build(files).errors.map((error) => error.message);
}

describe("links without text", () => {
  it("take the page title or the heading label title, as MyST does", () => {
    const result = build({
      "a.md": "# A\n\n(lbl)=\n## Labeled Sec\n\n[](other.md) | [](#lbl) | [](other)\n",
      "other.md": '# Other -- "Quoted" Title\n',
    });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/a.md")).toContain("[Other – “Quoted” Title](/docs/other.html) | [Labeled Sec](#lbl) | [Other – “Quoted” Title](/docs/other.html)");
  });

  it("fail where MyST renders empty or unresolved text", () => {
    expect(messages({ "a.md": "# A\n\n## Sec\n\n[](other.md#sec)\n", "other.md": "# Other\n\n## Sec\n" })).toEqual([
      "a.md:5: link:other.md#sec has no link text and MyST fills empty text only for a whole page; write the text",
    ]);
    expect(messages({ "a.md": "# A\n\n## Local Sec\n\n[](#local-sec)\n" })).toEqual([expect.stringContaining("a.md:5: link:#local-sec has no link text")]);
    expect(messages({ "a.md": "# A\n\n(plbl)=\nPara.\n\n[](#plbl)\n" })).toEqual([expect.stringContaining("a.md:6: link:#plbl has no link text")]);
    expect(messages({ "a.md": "# A\n\n[](https://example.com)\n" })).toEqual([expect.stringContaining("a.md:3: link:https://example.com has no link text")]);
  });
});
