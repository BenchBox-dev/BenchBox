import { describe, expect, it, vi } from "vitest";
import {
  MAX_ATTEMPTS,
  MAX_GROUP_COMMITS,
  MAX_RETRY_WAIT_MS,
  RETRY_BASE_DELAY_MS,
  createGithubGet,
  isTransientGithubError,
  mergeGroupPullRequests,
  rateLimitWaitMs,
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

  it("surfaces the last transient error to the caller after exhausting retries", async () => {
    const github = vi.fn(async () => {
      throw new Error("GitHub API 503 for /compare");
    });
    await expect(mergeGroupPullRequests({ github, repository, baseSha: base, headSha: head, sleep })).rejects.toThrow(
      "503",
    );
    expect(github).toHaveBeenCalledTimes(MAX_ATTEMPTS);
  });
});

describe("createGithubGet", () => {
  const reply = (status: number, headers: Record<string, string> = {}, body: unknown = {}, text = "") => ({
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name: string) => headers[name.toLowerCase()] ?? null },
    json: async () => body,
    text: async () => text,
  });
  const getWith = (response: ReturnType<typeof reply>) => {
    const fetchImpl = vi.fn(async (_url: string, _init?: any) => response);
    return { fetchImpl, github: createGithubGet({ token: "secret-token", apiUrl: "https://api.example", fetchImpl }) };
  };

  it("returns the JSON body and sends the token and API version", async () => {
    const { github, fetchImpl } = getWith(reply(200, {}, { status: "ahead" }));
    expect(await github("/repos/o/r/compare/a...b")).toEqual({ status: "ahead" });
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe("https://api.example/repos/o/r/compare/a...b");
    expect(init.headers.Authorization).toBe("Bearer secret-token");
    expect(init.headers["X-GitHub-Api-Version"]).toBe("2022-11-28");
  });

  it.each([
    ["a 429", 429, {}],
    ["a 403 whose rate limit is spent", 403, { "x-ratelimit-remaining": "0" }],
    ["a 403 with a retry-after", 403, { "retry-after": "30" }],
  ])("raises %s as a retryable rate-limit error", async (_label, status, headers) => {
    const { github } = getWith(reply(status, headers));
    const error = await github("/x").catch((caught) => caught);
    expect(error.message).toBe("GitHub API 429 for /x (rate limited)");
    expect(isTransientGithubError(error)).toBe(true);
  });

  it.each([
    ["a 403 with calls remaining", 403, { "x-ratelimit-remaining": "4999" }],
    ["a bare 403", 403, {}],
    ["a 404", 404, {}],
    ["a 422", 422, {}],
  ])("keeps %s a permanent client error", async (_label, status, headers) => {
    const { github } = getWith(reply(status, headers));
    const error = await github("/x").catch((caught) => caught);
    expect(error.message).toBe(`GitHub API ${status} for /x`);
    expect(isTransientGithubError(error)).toBe(false);
  });

  it("raises a 5xx as a retryable error and never puts the token in an error message", async () => {
    const { github } = getWith(reply(503));
    const error = await github("/x").catch((caught) => caught);
    expect(isTransientGithubError(error)).toBe(true);
    expect(error.message).not.toContain("secret-token");
  });
});

describe("rate limits that say how long to wait", () => {
  const reply = (status: number, headers: Record<string, string>, text = "") => ({
    ok: false,
    status,
    headers: { get: (name: string) => headers[name.toLowerCase()] ?? null },
    json: async () => ({}),
    text: async () => text,
  });
  const failure = async (response: ReturnType<typeof reply>) => {
    const github = createGithubGet({ token: "t", fetchImpl: async () => response });
    return (await github("/x").catch((caught) => caught)) as Error & { retryAfterMs?: number };
  };

  it("recognizes a secondary rate limit from the message when no header says so", async () => {
    const error = await failure(
      reply(403, { "x-ratelimit-remaining": "4990" }, '{"message":"You have exceeded a secondary rate limit."}'),
    );
    expect(error.message).toBe("GitHub API 429 for /x (rate limited)");
    expect(isTransientGithubError(error)).toBe(true);
    expect(error.retryAfterMs).toBeUndefined();
  });

  it("keeps a 403 with an unrelated message a permanent error", async () => {
    const error = await failure(reply(403, { "x-ratelimit-remaining": "4990" }, '{"message":"Resource not accessible"}'));
    expect(error.message).toBe("GitHub API 403 for /x");
    expect(isTransientGithubError(error)).toBe(false);
  });

  it("records the wait the server asked for in retry-after", async () => {
    expect((await failure(reply(429, { "retry-after": "30" }))).retryAfterMs).toBe(30000);
    expect((await failure(reply(403, { "retry-after": "7" }))).retryAfterMs).toBe(7000);
  });

  it("records the time until a spent primary limit resets", async () => {
    const reset = Math.floor(Date.now() / 1000) + 20;
    const error = await failure(reply(403, { "x-ratelimit-remaining": "0", "x-ratelimit-reset": String(reset) }));
    expect(error.retryAfterMs).toBeGreaterThan(15000);
    expect(error.retryAfterMs).toBeLessThanOrEqual(20000);
  });

  it("waits as long as the server asked, instead of the default backoff", async () => {
    const sleep = vi.fn(async (_ms: number) => undefined);
    let calls = 0;
    const result = await withRetries(
      async () => {
        calls += 1;
        if (calls === 1) throw Object.assign(new Error("GitHub API 429 for /x"), { retryAfterMs: 30000 });
        return "ok";
      },
      { sleep },
    );
    expect(result).toBe("ok");
    expect(sleep.mock.calls.map(([ms]) => ms)).toEqual([30000]);
  });

  it("does not retry when the server asks for longer than the cap", async () => {
    const sleep = vi.fn(async (_ms: number) => undefined);
    let calls = 0;
    const longWait = Object.assign(new Error("GitHub API 429 for /x"), { retryAfterMs: MAX_RETRY_WAIT_MS + 1 });
    expect(isTransientGithubError(longWait)).toBe(false);
    await expect(
      withRetries(
        async () => {
          calls += 1;
          throw longWait;
        },
        { sleep },
      ),
    ).rejects.toThrow("429");
    expect(calls).toBe(1);
    expect(sleep).not.toHaveBeenCalled();
  });

  it("never waits longer than the cap even for a transient error that asks for more", async () => {
    const sleep = vi.fn(async (_ms: number) => undefined);
    let calls = 0;
    await withRetries(
      async () => {
        calls += 1;
        if (calls === 1) throw Object.assign(new Error("GitHub API 429 for /x"), { retryAfterMs: MAX_RETRY_WAIT_MS });
        return "ok";
      },
      { sleep },
    );
    expect(sleep.mock.calls[0]![0]).toBeLessThanOrEqual(MAX_RETRY_WAIT_MS);
  });
});

describe("rateLimitWaitMs", () => {
  const now = 1_000_000_000_000;

  it.each([
    ["seconds in retry-after", { retryAfter: "30", reset: null, useReset: false }, 30000],
    ["zero seconds in retry-after", { retryAfter: "0", reset: null, useReset: false }, 0],
    ["an HTTP date in retry-after", { retryAfter: new Date(now + 45000).toUTCString(), reset: null, useReset: false }, 45000],
    ["an HTTP date already past", { retryAfter: new Date(now - 5000).toUTCString(), reset: null, useReset: false }, 0],
    ["a spent limit's reset time", { retryAfter: null, reset: String(Math.floor(now / 1000) + 20), useReset: true }, 20000],
    ["a reset time already past", { retryAfter: null, reset: String(Math.floor(now / 1000) - 20), useReset: true }, 0],
    ["retry-after over the reset time", { retryAfter: "5", reset: String(Math.floor(now / 1000) + 99), useReset: true }, 5000],
  ])("reads %s", (_label, input, expected) => {
    expect(rateLimitWaitMs({ ...input, now })).toBe(expected);
  });

  it.each([
    ["no header at all", { retryAfter: null, reset: null, useReset: true }],
    ["a missing reset header on a spent limit (Number(null) is 0, not a wait)", { retryAfter: null, reset: null, useReset: true }],
    ["a blank retry-after", { retryAfter: "   ", reset: null, useReset: false }],
    ["an unparseable retry-after", { retryAfter: "soon", reset: null, useReset: false }],
    ["a reset time that is not a number", { retryAfter: null, reset: "later", useReset: true }],
    ["a reset time when the limit is not spent", { retryAfter: null, reset: String(Math.floor(now / 1000) + 20), useReset: false }],
  ])("says nothing for %s", (_label, input) => {
    expect(rateLimitWaitMs({ ...input, now })).toBeUndefined();
  });
});

describe("rate-limit waits that are not real instructions", () => {
  const reply = (status: number, headers: Record<string, string>, text: () => Promise<string>) => ({
    ok: false,
    status,
    headers: { get: (name: string) => headers[name.toLowerCase()] ?? null },
    json: async () => ({}),
    text,
  });
  const failure = async (response: ReturnType<typeof reply>) => {
    const github = createGithubGet({ token: "t", fetchImpl: async () => response });
    return (await github("/x").catch((caught) => caught)) as Error & { retryAfterMs?: number };
  };

  it("does not turn a spent limit with no reset header into an instant retry", async () => {
    const error = await failure(reply(403, { "x-ratelimit-remaining": "0" }, async () => ""));
    expect(error.message).toBe("GitHub API 429 for /x (rate limited)");
    expect(error.retryAfterMs).toBeUndefined();
    const sleep = vi.fn(async (_ms: number) => undefined);
    let calls = 0;
    await withRetries(
      async () => {
        calls += 1;
        if (calls === 1) throw error;
        return "ok";
      },
      { sleep },
    );
    expect(sleep.mock.calls.map(([ms]) => ms)).toEqual([RETRY_BASE_DELAY_MS]);
  });

  it("backs off normally when the asked wait is zero or negative", async () => {
    const sleep = vi.fn(async (_ms: number) => undefined);
    let calls = 0;
    await withRetries(
      async () => {
        calls += 1;
        if (calls === 1) throw Object.assign(new Error("GitHub API 429 for /x"), { retryAfterMs: 0 });
        if (calls === 2) throw Object.assign(new Error("GitHub API 429 for /x"), { retryAfterMs: -50 });
        return "ok";
      },
      { sleep },
    );
    expect(sleep.mock.calls.map(([ms]) => ms)).toEqual([RETRY_BASE_DELAY_MS, RETRY_BASE_DELAY_MS * 2]);
  });

  it("uses the reset time for a 429 even when the remaining count is not reported", async () => {
    const reset = Math.floor(Date.now() / 1000) + 20;
    const error = await failure(reply(429, { "x-ratelimit-reset": String(reset) }, async () => ""));
    expect(error.retryAfterMs).toBeGreaterThan(15000);
  });

  it("fails at once for an HTTP-date retry-after beyond the cap", async () => {
    const error = await failure(reply(429, { "retry-after": new Date(Date.now() + 600000).toUTCString() }, async () => ""));
    expect(error.retryAfterMs).toBeGreaterThan(MAX_RETRY_WAIT_MS);
    expect(isTransientGithubError(error)).toBe(false);
  });

  it("treats a body that cannot be read as an ordinary 403, not a crash", async () => {
    const rejecting = await failure(reply(403, {}, async () => Promise.reject(new Error("stream closed"))));
    expect(rejecting.message).toBe("GitHub API 403 for /x");
    const throwing = await failure(
      reply(403, {}, () => {
        throw new Error("no body");
      }),
    );
    expect(throwing.message).toBe("GitHub API 403 for /x");
  });
});
