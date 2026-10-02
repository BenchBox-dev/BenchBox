/**
 * Which pull requests a public-site visual approval may name.
 *
 * A merge group can compose several pull requests, and the queue branch is named for only the last one.
 * The group's commits are the reliable list: each is a squash commit whose subject ends with the
 * `(#<number>)` that GitHub appends, so the PRs the group contains are read from the commits it adds on
 * top of its base.
 *
 * This relies on the queue's merge method being SQUASH: GitHub then writes each commit's subject itself, so
 * the trailing number cannot be set by a PR author. The ruleset-drift check pins that method.
 */

// The queue merges at most three entries per group; this bound only guards a malformed comparison.
export const MAX_GROUP_COMMITS = 100;

const FULL_SHA = /^[0-9a-f]{40}$/;

// A failed lookup names no pull request, and a merge group that needs a digest approval is then rejected
// and ejected from the queue. Retry only failures a retry can cure, a few times, so one network blip or
// rate limit does not eject a group that was approved correctly.
export const MAX_ATTEMPTS = 3;
export const RETRY_BASE_DELAY_MS = 2000;
// A rate limit that asks for a longer wait than this is not worth holding a runner for: fail at once.
export const MAX_RETRY_WAIT_MS = 60000;

/** Whether an error from `github()` is worth retrying: a network failure, a short rate limit or a server error. */
export function isTransientGithubError(error) {
  if (typeof error?.retryAfterMs === "number" && error.retryAfterMs > MAX_RETRY_WAIT_MS) return false;
  const status = /^GitHub API (\d{3})\b/.exec(String(error?.message ?? ""))?.[1];
  if (!status) return true;
  return status === "429" || status.startsWith("5");
}

/**
 * Run `operation` up to MAX_ATTEMPTS times, retrying only transient errors. Wait as long as the server asked
 * (`retryAfterMs`, never more than MAX_RETRY_WAIT_MS) and otherwise 2 s then 4 s.
 */
export async function withRetries(operation, { sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) } = {}) {
  for (let attempt = 1; ; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      if (attempt >= MAX_ATTEMPTS || !isTransientGithubError(error)) throw error;
      // A wait of zero or less (a reset time already past, clock skew) is no real instruction: back off.
      const asked =
        typeof error?.retryAfterMs === "number" && error.retryAfterMs > 0 ? error.retryAfterMs : RETRY_BASE_DELAY_MS * attempt;
      await sleep(Math.min(Math.max(asked, 0), MAX_RETRY_WAIT_MS));
    }
  }
}

/**
 * How long a rate-limited response asks to wait, in milliseconds, or undefined when it does not say. `retry-after`
 * is either a number of seconds or an HTTP date; the reset header is an epoch time in seconds and counts only
 * when `useReset` is set (a spent primary limit, or a 429). Missing, blank or unparseable values say nothing.
 */
export function rateLimitWaitMs({ retryAfter, reset, useReset, now = Date.now() }) {
  const text = retryAfter === null || retryAfter === undefined ? "" : String(retryAfter).trim();
  if (text !== "") {
    const seconds = Number(text);
    if (Number.isFinite(seconds)) return seconds * 1000;
    const at = Date.parse(text);
    if (Number.isFinite(at)) return Math.max(at - now, 0);
  }
  const resetText = reset === null || reset === undefined ? "" : String(reset).trim();
  if (useReset && resetText !== "") {
    const epochSeconds = Number(resetText);
    if (Number.isFinite(epochSeconds)) return Math.max(epochSeconds * 1000 - now, 0);
  }
  return undefined;
}

/**
 * A `github(path)` function for the REST API. GitHub reports a spent rate limit as 429, or as 403 with
 * rate-limit headers or a "secondary rate limit" message, so all of those are raised as a 429 error a retry
 * can cure, carrying how long the server asked to wait; any other 403 stays a client error.
 */
export function createGithubGet({ token, apiUrl = "https://api.github.com", fetchImpl = globalThis.fetch }) {
  return async function github(path) {
    const response = await fetchImpl(`${apiUrl}${path}`, {
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "X-GitHub-Api-Version": "2022-11-28",
      },
    });
    if (!response.ok) {
      const header = (name) => response.headers?.get?.(name) ?? null;
      const retryAfter = header("retry-after");
      const exhausted = header("x-ratelimit-remaining") === "0";
      let secondary = false;
      if (response.status === 403) {
        try {
          secondary = /secondary rate limit/i.test(String((await response.text?.()) ?? ""));
        } catch {
          secondary = false;
        }
      }
      const limited = response.status === 429 || (response.status === 403 && (exhausted || retryAfter !== null || secondary));
      const error = new Error(`GitHub API ${limited ? 429 : response.status} for ${path}${limited ? " (rate limited)" : ""}`);
      if (limited) {
        const waitMs = rateLimitWaitMs({
          retryAfter,
          reset: header("x-ratelimit-reset"),
          useReset: exhausted || response.status === 429,
        });
        if (waitMs !== undefined) error.retryAfterMs = waitMs;
      }
      throw error;
    }
    return response.json();
  };
}

/** The pull request number GitHub appends to a squashed commit's subject, or "" when there is none. */
export function pullRequestFromCommitMessage(message) {
  const subject = String(message ?? "").split("\n", 1)[0].trimEnd();
  // Anchored at the end: a PR title that itself contains "(#123)" is followed by the real number.
  return /\(#([1-9]\d*)\)$/.exec(subject)?.[1] ?? "";
}

/**
 * The pull requests a merge group adds on top of `baseSha`, in commit order and without repeats.
 *
 * Returns [] unless every commit the group adds can be traced to a pull request, so a list that is
 * partial, truncated or unreadable never grants an approval.
 */
export async function mergeGroupPullRequests({ github, repository, baseSha, headSha, sleep }) {
  if (!FULL_SHA.test(baseSha ?? "") || !FULL_SHA.test(headSha ?? "")) return [];
  const comparison = await withRetries(
    () => github(`/repos/${repository}/compare/${baseSha}...${headSha}?per_page=${MAX_GROUP_COMMITS}`),
    { sleep },
  );
  const commits = comparison?.commits;
  // `ahead` means the group's head descends from its base, so the commits are exactly what it adds.
  if (comparison?.status !== "ahead" || !Array.isArray(commits)) return [];
  if (commits.length === 0 || commits.length > MAX_GROUP_COMMITS || comparison.total_commits !== commits.length) {
    return [];
  }
  const numbers = commits.map((commit) => pullRequestFromCommitMessage(commit?.commit?.message));
  if (numbers.some((number) => number === "")) return [];
  return [...new Set(numbers)];
}
