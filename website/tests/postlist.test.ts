import { afterEach, describe, expect, it } from "vitest";
import { build, bodyOf, cleanup } from "./support.ts";

afterEach(cleanup);

const post = (title: string, date: string, body: string) => `---\nblogpost: true\ndate: ${date}\nauthor: Joe\n---\n\n# ${title}\n\n${body}\n`;

const LIST = "```{postlist}\n:date: %B %d, %Y\n:format: {date} - {title}\n:list-style: none\n:excerpts:\n```";

const files = {
  "blog/index.md": `---\norphan: true\n---\n\n# Blog\n\n${LIST}\n`,
  "blog/2026-01-01-old.md": post("Old post", "Jan 1, 2026", "First *old* paragraph with `code`.\n\nSecond paragraph."),
  "blog/2026-03-05-new.md": post("New post", "Mar 5, 2026", "![img](images/x.png)\n\nNew excerpt [link](https://example.com) here."),
  "blog/2026-03-05-newer.md": post("Newer same day", "Mar 5, 2026", "Same day."),
  "blog/images/x.png": "png",
};

describe("postlist directive", () => {
  it("lists posts by date then title, both descending as ablog does, with formatted dates, links and first-paragraph excerpts", () => {
    const result = build(files);
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "blog/index.md");
    const order = ["March 05, 2026 - [Newer same day](/blog/2026-03-05-newer.html)", "March 05, 2026 - [New post](/blog/2026-03-05-new.html)", "January 01, 2026 - [Old post](/blog/2026-01-01-old.html)"].map((line) => body.indexOf(line));
    expect(order.every((index) => index >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(body).toContain("New excerpt link here.");
    expect(body).toContain("First *old* paragraph with `code`.");
    expect(body).not.toContain("Second paragraph");
  });

  it("omits excerpts without the option", () => {
    const result = build({ ...files, "blog/index.md": "# Blog\n\n```{postlist}\n:format: {title}\n```\n" });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "blog/index.md")).not.toContain("Same day.");
  });

  it("rejects unsupported date directives, format fields and list styles", () => {
    expect(build({ ...files, "blog/index.md": "# Blog\n\n```{postlist}\n:date: %A\n```\n" }).errors[0].message).toContain("%A");
    expect(build({ ...files, "blog/index.md": "# Blog\n\n```{postlist}\n:format: {author}\n```\n" }).errors[0].message).toContain("{author}");
    expect(build({ ...files, "blog/index.md": "# Blog\n\n```{postlist}\n:list-style: disc\n```\n" }).errors[0].message).toContain("list-style");
  });

  it("reports an unparsable post date at the post's front matter line", () => {
    const result = build({ ...files, "blog/2026-01-01-old.md": post("Old post", "someday", "Text.") });
    expect(result.errors[0].file).toBe("blog/2026-01-01-old.md");
    expect(result.errors[0].line).toBe(3);
  });
});
