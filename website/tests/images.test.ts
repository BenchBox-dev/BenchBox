import { afterEach, describe, expect, it } from "vitest";
import { build, bodyOf, cleanup } from "./support.ts";

afterEach(cleanup);

const PNG = "png-bytes";

describe("image syntax", () => {
  it("rewrites a relative blog image to the published _images url and keeps alt and title", () => {
    const result = build({ "blog/images/chart.png": PNG, "blog/post.md": '# Post\n\n![A chart](./images/chart.png "Chart title")\n' });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "blog/post.md")).toContain('![A chart](/_images/chart.png "Chart title")');
  });

  it("accepts images without a leading dot-slash and leaves external urls alone", () => {
    const result = build({ "blog/images/a b.png": PNG, "blog/post.md": "# Post\n\n![One](images/a%20b.png)\n\n![Two](https://example.com/x.png)\n" });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "blog/post.md");
    expect(body).toContain("/_images/a%20b.png");
    expect(body).toContain("https://example.com/x.png");
  });

  it("reports a missing image with file and line", () => {
    const result = build({ "blog/post.md": "# Post\n\ntext\n\n![Gone](./images/missing.png)\n" });
    expect(result.errors).toHaveLength(1);
    expect(result.errors[0].file).toBe("blog/post.md");
    expect(result.errors[0].line).toBe(5);
    expect(result.errors[0].message).toContain("image file not found");
  });

  it("rejects images that would not be published", () => {
    const result = build({ "docs-img/x.png": PNG, "blog/post.md": "# Post\n\n![X](../docs-img/x.png)\n" });
    expect(result.errors[0].message).toContain("not published");
  });

  it("rejects reference-style images", () => {
    const result = build({ "blog/post.md": "# Post\n\n![X][ref]\n\n[ref]: ./images/x.png\n" });
    expect(result.errors[0].message).toContain("syntax:image-reference");
  });
});
