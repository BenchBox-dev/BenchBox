/**
 * Locate the visual baseline for one base SHA.
 *
 * The only trusted producer is protected develop: a `push` or
 * `workflow_dispatch` Documentation run on `develop`, uploaded after the commit
 * landed, which captures the exact tree named by the SHA.
 *
 * Callers may pass site-equivalent SHAs after the base: first-parent ancestors
 * whose public-site inputs are byte-identical to the base (computed by the
 * workflow classifier). They render the same site, so their baseline is the
 * base's baseline. The exact base is always tried first, and the first SHA in
 * order that has a trusted artifact wins.
 *
 * Artifact names alone are untrusted because pull_request runs can upload any
 * name, so every candidate is checked against its producing run.
 */

export const DOCS_WORKFLOW_PATH = ".github/workflows/docs.yml";
export const VISUAL_JOB_NAME = "Public-site visual regression";
export const ARTIFACT_PAGE_SIZE = 100;
// The jobs endpoint returns 30 jobs by default and the CI workflow declares more than that, so the
// visual job can sit on a later page. Request the maximum page size and follow pages.
export const JOBS_PAGE_SIZE = 100;
export const MAX_JOB_PAGES = 5;
export const LEGACY_BASELINE_NAME = "public-site-visual-baseline";
// Bounds GitHub API use per lookup pass.
// Must cover every SHA the classifier can emit (base plus 25 ancestors).
export const MAX_BASELINE_SHAS = 26;
export const MAX_ARTIFACT_PAGES = 5;

/**
 * Classify the run that uploaded a baseline; returns "develop" or undefined.
 *
 * Develop runs are not required to have `head_sha === baseSha`: a recovery
 * `workflow_dispatch` runs on the develop head while capturing an older
 * `baseline_source_sha`. The SHA-bound artifact name and the downloaded
 * manifest's `source_sha` bind those artifacts instead.
 *
 * Runs must have completed successfully. An in-progress or failed run's
 * artifact was never certified by a passing comparison, so trusting it would
 * let an uncertified tree certify a merge. Completed-then-cancelled runs are
 * also rejected: only success means the comparison passed.
 */
export function trustedBaselineSource(run, { repository }) {
  if (!run) return undefined;
  if (run.status !== "completed" || run.conclusion !== "success") return undefined;
  if (
    run.path === DOCS_WORKFLOW_PATH &&
    run.head_branch === "develop" &&
    (run.event === "push" || run.event === "workflow_dispatch") &&
    run.repository?.full_name === repository
  ) {
    return "develop";
  }
  return undefined;
}

async function listRunJobs(github, repository, runId) {
  const jobs = [];
  for (let page = 1; page <= MAX_JOB_PAGES; page += 1) {
    const data = await github(
      `/repos/${repository}/actions/runs/${runId}/jobs?per_page=${JOBS_PAGE_SIZE}&page=${page}`,
    );
    if (!Array.isArray(data?.jobs)) throw new Error("GitHub API returned an invalid job list");
    // An entry that cannot be read is not a job that passed, so a malformed one invalidates the list.
    if (!data.jobs.every((job) => typeof job?.name === "string" && typeof job.status === "string")) {
      throw new Error("GitHub API returned an invalid job entry");
    }
    jobs.push(...data.jobs);
    if (data.jobs.length < JOBS_PAGE_SIZE) return jobs;
  }
  // Every allowed page was full, so jobs beyond the bound were never read and the list is incomplete.
  throw new Error(`Run ${runId} has more than ${MAX_JOB_PAGES * JOBS_PAGE_SIZE} jobs`);
}

/**
 * True only when the run has a visual job and every job carrying that name completed successfully.
 * An unreadable job list is not evidence of success, and neither is a name that matches no job.
 */
async function visualJobSucceeded(github, repository, runId) {
  try {
    const visualJobs = (await listRunJobs(github, repository, runId)).filter((job) => job.name === VISUAL_JOB_NAME);
    return (
      visualJobs.length > 0 && visualJobs.every((job) => job.status === "completed" && job.conclusion === "success")
    );
  } catch {
    return false;
  }
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
  for (const candidate of candidates) {
    const runId = candidate.workflow_run?.id;
    if (!Number.isInteger(runId)) continue;
    if (candidate.name === LEGACY_BASELINE_NAME && candidate.workflow_run.head_sha !== sha) continue;
    const run = await github(`/repos/${repository}/actions/runs/${runId}`);
    let source = trustedBaselineSource(run, { repository });
    if (
      !source &&
      run &&
      run.path === DOCS_WORKFLOW_PATH &&
      run.status === "completed" &&
      run.head_branch === "develop" &&
      (run.event === "push" || run.event === "workflow_dispatch") &&
      run.repository?.full_name === repository
    ) {
      if (await visualJobSucceeded(github, repository, runId)) source = "develop";
    }
    if (source === "develop") return { artifact: candidate, source, baselineSha: sha };
  }
  return undefined;
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
  for (const [index, sha] of shas.entries()) {
    const found = await trustedFromCandidates(github, repository, sha, [...namedBySha[index], ...legacy]);
    if (found) return found;
  }
  return undefined;
}

/**
 * Poll until a trusted baseline appears or the deadline passes.
 *
 * `minAttempts` keeps the short retry for transient API errors even when no
 * wait is configured; `waitMs` bounds the total time spent waiting for a
 * develop push to publish the exact base. After the short
 * retries, polling slows to `waitDelayMs` so several waiting jobs stay
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
