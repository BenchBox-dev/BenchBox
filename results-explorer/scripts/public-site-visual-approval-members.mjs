/**
 * Which pull requests a public-site visual approval may name.
 *
 * A merge group can compose several pull requests, and the queue branch is named for only the last one.
 * The group's commits are the reliable list: each is a squash commit whose subject ends with the
 * `(#<number>)` that GitHub appends, so the PRs the group contains are read from the commits it adds on
 * top of its base.
 */

// The queue merges at most three entries per group; this bound only guards a malformed comparison.
export const MAX_GROUP_COMMITS = 100;

const FULL_SHA = /^[0-9a-f]{40}$/;

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
export async function mergeGroupPullRequests({ github, repository, baseSha, headSha }) {
  if (!FULL_SHA.test(baseSha ?? "") || !FULL_SHA.test(headSha ?? "")) return [];
  const comparison = await github(
    `/repos/${repository}/compare/${baseSha}...${headSha}?per_page=${MAX_GROUP_COMMITS}`,
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
