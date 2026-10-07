import { afterEach, describe, expect, it } from "vitest";
import { build, bodyOf, cleanup } from "./support.ts";

afterEach(cleanup);

describe("raw html syntax", () => {
  it("turns placeholder tags into literal text", () => {
    const result = build({ "a.md": '# A\n\nReply "pass-<N> ready, N=<count>" now.\n' });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(body).toContain("\\<N>");
    expect(body).toContain("\\<count>");
  });

  it("passes known html elements through", () => {
    const result = build({ "a.md": "# A\n\nPress <kbd>Ctrl</kbd> now.\n" });
    expect(result.errors).toEqual([]);
    expect(bodyOf(result, "docs/a.md")).toContain("<kbd>Ctrl</kbd>");
  });

  it("rejects event handler attributes", () => {
    const result = build({ "a.md": '# A\n\nText <span onclick="x()">y</span> end.\n' });
    expect(result.errors[0].message).toContain("unsafe attribute");
    expect(result.errors[0].line).toBe(3);
  });

  it("rejects script elements", () => {
    const result = build({ "a.md": "# A\n\n<script>alert(1)</script>\n" });
    expect(result.errors).not.toEqual([]);
  });
});
