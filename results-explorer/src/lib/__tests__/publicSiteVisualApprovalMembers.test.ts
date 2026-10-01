import { describe, expect, it, vi } from "vitest";
import {
  MAX_GROUP_COMMITS,
  mergeGroupPullRequests,
  pullRequestFromCommitMessage,
} from "../../../scripts/public-site-visual-approval-members.mjs";

const base = "a".repeat(40);
const head = "b".repeat(40);
const repository = "BenchBox-dev/BenchBox";

const commit = (message: string) => ({ commit: { message } });
const compare = (messages: string[], overrides: Record<string, unknown> = {}) => ({
  status: "ahead",
  total_commits: messages.length,
  commits: messages.map(commit),
  ...overrides,
});
const members = (response: unknown, shas: { baseSha?: string; headSha?: string } = {}) => {
  const github = vi.fn(async () => response);
  return mergeGroupPullRequests({ github, repository, baseSha: base, headSha: head, ...shas }).then((result) => ({
    result,
    github,
  }));
};

describe("pullRequestFromCommitMessage", () => {
  it.each([
    ["fix(tpcds): render get_queries at the data's scale factor (#2509)", "2509"],
    ["title (#17)\n\nbody that mentions (#99)", "17"],
    // A title that already names another PR is followed by the number GitHub appends.
    ["revert the change from (#2385) (#2400)", "2400"],
    ["trailing space after the number (#2509)  ", "2509"],
  ])("reads the number from %j", (message, expected) => {
    expect(pullRequestFromCommitMessage(message)).toBe(expected);
  });

  it.each([
    undefined,
    null,
    "",
    "no number here",
    "(#0)",
    "(#-4)",
    "(#12abc)",
    "mentions (#2385) but does not end with it",
    "first line has none\n(#2385)",
    "Merge branch 'develop' into feature",
  ])("reads nothing from %j", (message) => {
    expect(pullRequestFromCommitMessage(message)).toBe("");
  });
});

describe("mergeGroupPullRequests", () => {
  it("lists every PR a composed group adds, not only the one in the branch name", async () => {
    const { result, github } = await members(compare(["one (#2384)", "two (#2385)", "three (#2386)"]));
    expect(result).toEqual(["2384", "2385", "2386"]);
    expect(github).toHaveBeenCalledWith(`/repos/${repository}/compare/${base}...${head}?per_page=${MAX_GROUP_COMMITS}`);
  });

  it("lists a single-entry group's one PR", async () => {
    expect((await members(compare(["only (#2385)"]))).result).toEqual(["2385"]);
  });

  it("lists a PR once", async () => {
    expect((await members(compare(["a (#2385)", "b (#2385)"]))).result).toEqual(["2385"]);
  });

  it.each([
    ["a commit with no PR number", compare(["one (#2384)", "a merge of develop"])],
    ["no commits", compare([])],
    ["a head that is not ahead of the base", compare(["one (#2384)"], { status: "diverged" })],
    ["a head behind the base", compare(["one (#2384)"], { status: "behind" })],
    ["a truncated commit list", compare(["one (#2384)"], { total_commits: 2 })],
    ["a missing commit list", { status: "ahead", total_commits: 1 }],
    ["a commit without a message", { status: "ahead", total_commits: 1, commits: [{}] }],
    ["no response body", undefined],
  ])("returns nothing for %s, so no approval applies", async (_label, response) => {
    expect((await members(response)).result).toEqual([]);
  });

  it("returns nothing for more commits than a group can hold", async () => {
    const many = Array.from({ length: MAX_GROUP_COMMITS + 1 }, (_, index) => `change (#${index + 1})`);
    expect((await members(compare(many))).result).toEqual([]);
  });

  it.each([
    ["a short base", { baseSha: "abc123" }],
    ["an uppercase head", { headSha: "B".repeat(40) }],
    ["a missing base", { baseSha: "" }],
    ["a missing head", { headSha: undefined }],
  ])("does not query GitHub for %s", async (_label, shas) => {
    const { result, github } = await members(compare(["one (#2384)"]), shas);
    expect(result).toEqual([]);
    expect(github).not.toHaveBeenCalled();
  });

  it("lets a failed request surface to the caller", async () => {
    const github = vi.fn(async () => {
      throw new Error("GitHub API 502");
    });
    await expect(mergeGroupPullRequests({ github, repository, baseSha: base, headSha: head })).rejects.toThrow("502");
  });
});
