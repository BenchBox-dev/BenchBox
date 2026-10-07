import { afterEach, describe, expect, it } from "vitest";
import { closeQuotesAfterWords, smarten, SMARTYPANTS } from "../src/lib/smartypants.ts";
import { build, cleanup, frontMatterOf } from "./support.ts";

afterEach(cleanup);

describe("docutils smart quotes and dashes", () => {
  it("matches what Sphinx renders for dashes, ellipses and quotes", () => {
    expect(smarten("Home -- en --- em \"quotes\" 'single' it's ... dialect=\"standard\" x='y'")).toBe("Home – en — em “quotes” ‘single’ it’s … dialect=”standard” x=’y’");
    expect(SMARTYPANTS.dashes).toBe("oldschool");
  });

  it("closes a quote that follows a word character, as docutils does", () => {
    expect(closeQuotesAfterWords("a=“b” (“c”) “d”")).toBe("a=”b” (“c”) “d”");
  });

  it("leaves inline code in a page title alone", () => {
    const result = build({ "a.md": '# Using `--scale` -- "x"\n' });
    expect(frontMatterOf(result, "docs/a.md")).toContain("title: Using --scale – “x”");
  });

  it("applies to page titles and sidebar labels", () => {
    const result = build({
      "index.md": '# Home\n\n```{toctree}\n:caption: Guides -- "all"\n\nPage -- one <a>\nb\n```\n',
      "a.md": '# A "title" -- here\n',
      "b.md": "# B --- it's\n",
    });
    expect(result.errors).toEqual([]);
    expect(frontMatterOf(result, "docs/a.md")).toContain("title: A “title” – here");
    const sidebar = JSON.parse(result.files.get("manifest/sidebar.json") ?? "{}") as { groups: { label: string; items: { label: string }[] }[] };
    expect(sidebar.groups[0].label).toBe("Guides – “all”");
    expect(sidebar.groups[0].items.map((item) => item.label)).toEqual(["Page – one", "B — it’s"]);
  });
});
