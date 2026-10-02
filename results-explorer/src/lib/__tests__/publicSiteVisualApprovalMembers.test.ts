import { describe, expect, it, vi } from "vitest";
import {
  MAX_ATTEMPTS,
  MAX_GROUP_COMMITS,
  RETRY_BASE_DELAY_MS,
  isTransientGithubError,
  mergeGroupPullRequests,
  pullRequestFromCommitMessage,
  withRetries,
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
      throw new Error("GitHub API 404 for /compare");
    });
    await expect(mergeGroupPullRequests({ github, repository, baseSha: base, headSha: head })).rejects.toThrow("404");
    expect(github).toHaveBeenCalledTimes(1);
  });
});

describe("isTransientGithubError", () => {
  it.each([
    ["GitHub API 429 for /repos/x/compare/a...b", true],
    ["GitHub API 500 for /repos/x/compare/a...b", true],
    ["GitHub API 502 for /repos/x/compare/a...b", true],
    ["GitHub API 503 for /repos/x/compare/a...b", true],
    ["fetch failed", true],
    ["connect ETIMEDOUT 140.82.112.5:443", true],
    ["GitHub API 404", false],
    ["GitHub API 502", true],
    ["GitHub API 400 for /repos/x/compare/a...b", false],
    ["GitHub API 401 for /repos/x/compare/a...b", false],
    ["GitHub API 403 for /repos/x/compare/a...b", false],
    ["GitHub API 404 for /repos/x/compare/a...b", false],
    ["GitHub API 422 for /repos/x/compare/a...b", false],
  ])("treats %j as transient=%s", (message, expected) => {
    expect(isTransientGithubError(new Error(message))).toBe(expected);
  });
});

describe("withRetries", () => {
  const noSleep = () => vi.fn(async (_ms: number) => undefined);

  it("returns the first success without waiting", async () => {
    const sleep = noSleep();
    expect(await withRetries(async () => "ok", { sleep })).toBe("ok");
    expect(sleep).not.toHaveBeenCalled();
  });

  it("retries a transient failure and returns the later success, waiting longer each time", async () => {
    const sleep = noSleep();
    let calls = 0;
    const result = await withRetries(
      async () => {
        calls += 1;
        if (calls < MAX_ATTEMPTS) throw new Error("GitHub API 502 for /x");
        return "recovered";
      },
      { sleep },
    );
    expect(result).toBe("recovered");
    expect(calls).toBe(MAX_ATTEMPTS);
    expect(sleep.mock.calls.map(([ms]) => ms)).toEqual([RETRY_BASE_DELAY_MS, RETRY_BASE_DELAY_MS * 2]);
  });

  it("gives up after the maximum number of attempts and surfaces the last error", async () => {
    const sleep = noSleep();
    let calls = 0;
    await expect(
      withRetries(
        async () => {
          calls += 1;
          throw new Error(`GitHub API 503 attempt ${calls}`);
        },
        { sleep },
      ),
    ).rejects.toThrow("attempt 3");
    expect(calls).toBe(MAX_ATTEMPTS);
  });

  it.each(["GitHub API 403 for /x", "GitHub API 404 for /x", "GitHub API 422 for /x"])(
    "does not retry a permanent failure (%s)",
    async (message) => {
      const sleep = noSleep();
      let calls = 0;
      await expect(
        withRetries(
          async () => {
            calls += 1;
            throw new Error(message);
          },
          { sleep },
        ),
      ).rejects.toThrow(message);
      expect(calls).toBe(1);
      expect(sleep).not.toHaveBeenCalled();
    },
  );
});

describe("mergeGroupPullRequests retries", () => {
  const sleep = vi.fn(async (_ms: number) => undefined);

  it("recovers from one transient failure and still names the group's PRs", async () => {
    let calls = 0;
    const github = vi.fn(async () => {
      calls += 1;
      if (calls === 1) throw new Error("GitHub API 502 for /compare");
      return compare(["one (#2384)", "two (#2385)"]);
    });
    const result = await mergeGroupPullRequests({ github, repository, baseSha: base, headSha: head, sleep });
    expect(result).toEqual(["2384", "2385"]);
    expect(github).toHaveBeenCalledTimes(2);
  });

  it("still names nothing when the lookup keeps failing", async () => {
    const github = vi.fn(async () => {
      throw new Error("GitHub API 503 for /compare");
    });
    await expect(mergeGroupPullRequests({ github, repository, baseSha: base, headSha: head, sleep })).rejects.toThrow(
      "503",
    );
    expect(github).toHaveBeenCalledTimes(MAX_ATTEMPTS);
  });
});
