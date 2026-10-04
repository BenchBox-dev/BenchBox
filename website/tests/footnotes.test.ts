import { afterEach, describe, expect, it } from "vitest";
import { bodyOf, build, cleanup } from "./support.ts";

afterEach(cleanup);

function anchors(body: string): string[] {
  return [...body.matchAll(/<span id="([^"]+)"><\/span>/g)].map((match) => match[1]);
}

describe("footnote ids", () => {
  it("numbers references in document order and gives numeric definitions the following ids", () => {
    const result = build({ "a.md": "# A\n\nFirst.[^1] Second.[^2] Again.[^1]\n\n[^1]: One.\n[^2]: Two.\n" });
    expect(result.errors).toEqual([]);
    expect(anchors(bodyOf(result, "docs/a.md"))).toEqual(["a", "id1", "id2", "id3", "id4", "id5"]);
    expect(result.infos[0].ids).toEqual(expect.arrayContaining(["id1", "id2", "id3", "id4", "id5"]));
  });

  it("names definitions after their label when the label is a valid id", () => {
    const result = build({ "a.md": "# A\n\nClaim.[^issue-289] More.[^job-2015]\n\n[^issue-289]: Issue text.\n[^job-2015]: Paper text.\n" });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.md");
    expect(anchors(body)).toEqual(["a", "id1", "id2", "issue-289", "job-2015"]);
    expect(body).toContain('[^issue-289]: <span id="issue-289"></span>Issue text.');
  });

  it("keeps heading ids stable beside footnote ids", () => {
    const result = build({ "a.md": "# A\n\n## Section\n\nText.[^1]\n\n[^1]: Note.\n" });
    expect(result.infos[0].ids).toEqual(["a", "id1", "id2", "section"]);
  });
});
