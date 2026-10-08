export const DOCS_WORKFLOW_PATH = ".github/workflows/docs.yml";
export const VISUAL_JOB_NAME = "Public-site visual regression";
export const ARTIFACT_PAGE_SIZE = 100;
export const JOBS_PAGE_SIZE = 100;
export const MAX_JOB_PAGES = 5;
export const LEGACY_BASELINE_NAME = "public-site-visual-baseline";
export const MAX_BASELINE_SHAS = 26;
export const MAX_ARTIFACT_PAGES = 5;

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
    if (!data.jobs.every((job) => typeof job?.name === "string" && typeof job.status === "string")) {
      throw new Error("GitHub API returned an invalid job entry");
    }
    jobs.push(...data.jobs);
    if (data.jobs.length < JOBS_PAGE_SIZE) return jobs;
  }
  throw new Error(`Run ${runId} has more than ${MAX_JOB_PAGES * JOBS_PAGE_SIZE} jobs`);
}

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

export async function findTrustedBaseline({ github, repository, baseSha, candidateShas = [] }) {
  const shas = baselineShaOrder(baseSha, candidateShas);
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
