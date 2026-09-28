/**
 * Locate the visual baseline for one base SHA.
 *
 * Two producers are trusted, and both capture the exact tree named by the SHA:
 *
 * - protected develop: a `push` or `workflow_dispatch` Documentation run on
 *   `develop`, uploaded after the commit landed;
 * - merge-queue candidate: a `merge_group` Documentation run on a
 *   `gh-readonly-queue/develop/*` branch in this repository, uploaded only after
 *   that group passed its own exact-base comparison. A queue follower's
 *   `merge_group.base_sha` is the leader group's head, and the follower can only
 *   merge on top of that head, so the candidate is the exact tree it lands on.
 *
 * Callers may pass site-equivalent SHAs after the base: first-parent ancestors
 * whose public-site inputs are byte-identical to the base (computed by the
 * workflow classifier). They render the same site, so their baseline is the
 * base's baseline. The exact base is always tried first, and the first SHA in
 * order that has a trusted artifact wins.
 *
 * Artifact names alone are untrusted because pull_request runs can upload any
 * name, so every candidate is checked against its producing run. For the same
 * SHA a protected develop artifact wins; across SHAs every landed develop
 * baseline wins over any merge-queue candidate, because a queue capture is a
 * speculative tree that may never land.
 */

export const DOCS_WORKFLOW_PATH = ".github/workflows/docs.yml";
export const MERGE_QUEUE_BRANCH_PREFIX = "gh-readonly-queue/develop/";
export const ARTIFACT_PAGE_SIZE = 100;
export const LEGACY_BASELINE_NAME = "public-site-visual-baseline";
// Bounds GitHub API use per lookup pass while several queue groups poll.
// Must cover every SHA the classifier can emit (base plus 25 ancestors).
export const MAX_BASELINE_SHAS = 26;
export const MAX_ARTIFACT_PAGES = 5;

/**
 * Classify the run that uploaded a baseline; returns "develop", "merge-queue", or undefined.
 *
 * Develop runs are not required to have `head_sha === baseSha`: a recovery
 * `workflow_dispatch` runs on the develop head while capturing an older
 * `baseline_source_sha`. The SHA-bound artifact name and the downloaded
 * manifest's `source_sha` bind those artifacts instead. A merge-queue run
 * has no recovery mode, so it must have run on exactly the requested SHA.
 */
/**
 * Runs must have completed successfully. An in-progress or failed run's
 * artifact was never certified by a passing comparison, so trusting it would
 * let an uncertified tree certify a merge. Completed-then-cancelled runs are
 * also rejected: only success means the comparison passed.
 */
export function trustedBaselineSource(run, { repository, baseSha }) {
  if (!run || run.path !== DOCS_WORKFLOW_PATH) return undefined;
  if (run.status !== "completed" || run.conclusion !== "success") return undefined;
  if (
    run.head_branch === "develop" &&
    (run.event === "push" || run.event === "workflow_dispatch") &&
    run.repository?.full_name === repository
  ) {
    return "develop";
  }
  if (
    run.event === "merge_group" &&
    run.head_sha === baseSha &&
    typeof run.head_branch === "string" &&
    run.head_branch.startsWith(MERGE_QUEUE_BRANCH_PREFIX) &&
    run.head_repository?.full_name === repository &&
    run.repository?.full_name === repository
  ) {
    return "merge-queue";
  }
  return undefined;
}

export function baselineNames(baseSha) {
  return [`public-site-visual-baseline-${baseSha}`, LEGACY_BASELINE_NAME];
}

/** Normalize the ordered SHA list: exact base first, unique, well-formed, bounded. */
export function baselineShaOrder(baseSha, candidateShas = []) {
  const ordered = [];
  for (const sha of [baseSha, ...candidateShas]) {
    if (typeof sha !== "string" || !/^[0-9a-f]{40}$/.test(sha) || ordered.includes(sha)) continue;
    ordered.push(sha);
    if (ordered.length >= MAX_BASELINE_SHAS) break;
  }
  return ordered;
}

async function listValidArtifacts(github, repository, name) {
  const validArtifacts = [];
  for (let page = 1; page <= MAX_ARTIFACT_PAGES; page += 1) {
    const data = await github(
      `/repos/${repository}/actions/artifacts?name=${encodeURIComponent(name)}&per_page=${ARTIFACT_PAGE_SIZE}&page=${page}`,
    );
    if (!Array.isArray(data.artifacts)) {
      throw new Error("GitHub API returned an invalid artifact list");
    }
    validArtifacts.push(...data.artifacts.filter((candidate) => !candidate.expired && candidate.name === name));
    if (data.artifacts.length < ARTIFACT_PAGE_SIZE) break;
  }
  return validArtifacts;
}

async function trustedFromCandidates(github, repository, sha, candidates) {
  let queueCandidate;
  for (const candidate of candidates) {
    const runId = candidate.workflow_run?.id;
    if (!Number.isInteger(runId)) continue;
    if (candidate.name === LEGACY_BASELINE_NAME && candidate.workflow_run.head_sha !== sha) continue;
    const run = await github(`/repos/${repository}/actions/runs/${runId}`);
    const source = trustedBaselineSource(run, { repository, baseSha: sha });
    if (source === "develop") return { artifact: candidate, source, baselineSha: sha };
    if (source === "merge-queue" && !queueCandidate) queueCandidate = { artifact: candidate, source, baselineSha: sha };
  }
  return queueCandidate;
}

/**
 * One lookup pass. Returns `{ artifact, source, baselineSha }` or undefined; API errors propagate.
 *
 * `candidateShas` are site-equivalent ancestors of `baseSha`, nearest first.
 */
export async function findTrustedBaseline({ github, repository, baseSha, candidateShas = [] }) {
  const shas = baselineShaOrder(baseSha, candidateShas);
  // The legacy unsuffixed name is listed once and matched to SHAs by run head.
  const legacy = await listValidArtifacts(github, repository, LEGACY_BASELINE_NAME);
  const namedBySha = await Promise.all(
    shas.map((sha) => listValidArtifacts(github, repository, `public-site-visual-baseline-${sha}`)),
  );
  let queueCandidate;
  for (const [index, sha] of shas.entries()) {
    const found = await trustedFromCandidates(github, repository, sha, [...namedBySha[index], ...legacy]);
    // A trusted merge-queue candidate for the exact base wins at once. For an
    // ancestor, a queue capture of a speculative head is not a landed tree, so
    // keep walking in case a landed develop baseline exists further down.
    if (!found) continue;
    if (found.source === "develop" || sha === baseSha) return found;
    if (!queueCandidate) queueCandidate = found;
  }
  return queueCandidate;
}

/**
 * Poll until a trusted baseline appears or the deadline passes.
 *
 * `minAttempts` keeps the short retry for transient API errors even when no
 * wait is configured; `waitMs` bounds the total time spent waiting for a
 * leader group or develop push to publish the exact base. After the short
 * retries, polling slows to `waitDelayMs` so several waiting followers stay
 * well inside the per-repository GITHUB_TOKEN API budget.
 */
export async function waitForTrustedBaseline({
  github,
  repository,
  baseSha,
  candidateShas = [],
  waitMs = 0,
  minAttempts = 6,
  delayMs = 2_000,
  waitDelayMs = 60_000,
  now = () => Date.now(),
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  log = () => {},
}) {
  const deadline = now() + waitMs;
  let lastLookupError;
  let attempts = 0;
  for (;;) {
    attempts += 1;
    try {
      const found = await findTrustedBaseline({ github, repository, baseSha, candidateShas });
      lastLookupError = undefined;
      if (found) return { ...found, attempts };
    } catch (error) {
      lastLookupError = error;
    }
    if (attempts >= minAttempts && now() >= deadline) break;
    if (attempts === minAttempts && waitMs > 0) {
      log(`Waiting up to ${Math.round(waitMs / 1000)}s for a baseline bound to base SHA ${baseSha}`);
    }
    await sleep(attempts < minAttempts ? delayMs : Math.max(0, Math.min(waitDelayMs, deadline - now())));
  }
  if (lastLookupError) {
    throw new Error(`Unable to list protected public-site visual baselines after ${attempts} attempts`, {
      cause: lastLookupError,
    });
  }
  return { artifact: undefined, source: undefined, baselineSha: undefined, attempts };
}
