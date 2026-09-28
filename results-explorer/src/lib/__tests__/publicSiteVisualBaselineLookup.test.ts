// @vitest-environment node
import { describe, expect, it } from "vitest";

import {
  baselineShaOrder,
  findTrustedBaseline,
  MAX_BASELINE_SHAS,
  trustedBaselineSource,
  waitForTrustedBaseline,
} from "../../../scripts/public-site-visual-baseline-lookup.mjs";

const REPO = "BenchBox-dev/BenchBox";
const BASE = "f8f38867676f96d4e36e9d7e1dbdf84800da11f1";
const OTHER = "7214e982a1a78d13caf15b0893c487be9048d19e";
const NAME = `public-site-visual-baseline-${BASE}`;

type Run = Record<string, unknown>;

function developRun(overrides: Run = {}): Run {
  return {
    event: "push",
    head_branch: "develop",
    head_sha: BASE,
    path: ".github/workflows/docs.yml",
    status: "completed",
    conclusion: "success",
    repository: { full_name: REPO },
    head_repository: { full_name: REPO },
    ...overrides,
  };
}

function queueRun(overrides: Run = {}): Run {
  return developRun({
    event: "merge_group",
    head_branch: `gh-readonly-queue/develop/pr-2351-${OTHER}`,
    ...overrides,
  });
}

function fakeGithub(
  artifacts: Array<{ id: number; name: string; runId: number; headSha?: string }>,
  runs: Record<number, Run>,
  jobs: Record<number, Array<{ name: string; status: string; conclusion: string }>> = {},
) {
  const calls: string[] = [];
  const github = async (path: string) => {
    calls.push(path);
    const jobsMatch = path.match(/\/actions\/runs\/(\d+)\/jobs$/);
    if (jobsMatch) {
      const runId = Number(jobsMatch[1]);
      return { jobs: jobs[runId] ?? [] };
    }
    const runMatch = path.match(/\/actions\/runs\/(\d+)$/);
    if (runMatch) return runs[Number(runMatch[1])];
    const name = decodeURIComponent(new URL(`https://x${path}`).searchParams.get("name") ?? "");
    return {
      artifacts: artifacts
        .filter((artifact) => artifact.name === name)
        .map((artifact) => ({
          id: artifact.id,
          name: artifact.name,
          expired: false,
          workflow_run: { id: artifact.runId, head_sha: artifact.headSha ?? BASE },
        })),
    };
  };
  return { github, calls };
}

describe("trustedBaselineSource", () => {
  const context = { repository: REPO, baseSha: BASE };

  it("trusts develop push and dispatch runs of the Documentation workflow", () => {
    expect(trustedBaselineSource(developRun(), context)).toBe("develop");
    expect(trustedBaselineSource(developRun({ event: "workflow_dispatch" }), context)).toBe("develop");
  });

  it("trusts develop recovery dispatches whose run head differs from the captured SHA", () => {
    expect(trustedBaselineSource(developRun({ event: "workflow_dispatch", head_sha: OTHER }), context)).toBe(
      "develop",
    );
  });

  it("trusts a merge-queue run on this repository's develop queue at exactly the base SHA", () => {
    expect(trustedBaselineSource(queueRun(), context)).toBe("merge-queue");
  });

  it.each([
    ["pull_request event", queueRun({ event: "pull_request" })],
    ["pull_request on develop-named branch", developRun({ event: "pull_request" })],
    ["queue run on another SHA", queueRun({ head_sha: OTHER })],
    ["queue for another branch", queueRun({ head_branch: `gh-readonly-queue/release/pr-1-${OTHER}` })],
    ["queue branch lookalike", queueRun({ head_branch: "feature/gh-readonly-queue/develop/x" })],
    ["fork head repository", queueRun({ head_repository: { full_name: "someone/BenchBox" } })],
    ["other workflow", queueRun({ path: ".github/workflows/test.yml" })],
    ["other workflow on develop", developRun({ path: ".github/workflows/other.yml" })],
    ["push to another branch", developRun({ head_branch: "release" })],
    ["in-progress queue run", queueRun({ status: "in_progress", conclusion: null })],
    ["failed develop run", developRun({ conclusion: "failure" })],
    ["develop run from another repository", developRun({ repository: { full_name: "someone/BenchBox" } })],
  ])("rejects %s", (_label, run) => {
    expect(trustedBaselineSource(run, context)).toBeUndefined();
  });
});

describe("findTrustedBaseline", () => {
  it("prefers a protected develop artifact over a merge-queue candidate", async () => {
    const { github } = fakeGithub(
      [
        { id: 1, name: NAME, runId: 10 },
        { id: 2, name: NAME, runId: 20 },
      ],
      { 10: queueRun(), 20: developRun() },
    );
    const found = await findTrustedBaseline({ github, repository: REPO, baseSha: BASE });
    expect(found).toMatchObject({ source: "develop", artifact: { id: 2 } });
  });

  it("uses a merge-queue candidate when no develop artifact exists", async () => {
    const { github } = fakeGithub([{ id: 1, name: NAME, runId: 10 }], { 10: queueRun() });
    const found = await findTrustedBaseline({ github, repository: REPO, baseSha: BASE });
    expect(found).toMatchObject({ source: "merge-queue", artifact: { id: 1 } });
  });

  it("ignores a same-named artifact uploaded by a pull_request run", async () => {
    const { github } = fakeGithub([{ id: 1, name: NAME, runId: 10 }], {
      10: queueRun({ event: "pull_request", head_branch: "fix/forged" }),
    });
    expect(await findTrustedBaseline({ github, repository: REPO, baseSha: BASE })).toBeUndefined();
  });

  it("ignores legacy unsuffixed artifacts from another SHA without fetching their run", async () => {
    const { github, calls } = fakeGithub(
      [{ id: 1, name: "public-site-visual-baseline", runId: 10, headSha: OTHER }],
      { 10: developRun({ head_sha: OTHER }) },
    );
    expect(await findTrustedBaseline({ github, repository: REPO, baseSha: BASE })).toBeUndefined();
    expect(calls.some((path) => path.endsWith("/actions/runs/10"))).toBe(false);
  });

  it("trusts a develop baseline when the overall run failed but Public-site visual regression succeeded", async () => {
    const { github } = fakeGithub(
      [{ id: 1, name: NAME, runId: 10 }],
      { 10: developRun({ conclusion: "failure" }) },
      { 10: [{ name: "Public-site visual regression", status: "completed", conclusion: "success" }] },
    );
    const found = await findTrustedBaseline({ github, repository: REPO, baseSha: BASE });
    expect(found).toMatchObject({ source: "develop", artifact: { id: 1 } });
  });

  it("rejects a develop baseline when the overall run failed and Public-site visual regression failed", async () => {
    const { github } = fakeGithub(
      [{ id: 1, name: NAME, runId: 10 }],
      { 10: developRun({ conclusion: "failure" }) },
      { 10: [{ name: "Public-site visual regression", status: "completed", conclusion: "failure" }] },
    );
    const found = await findTrustedBaseline({ github, repository: REPO, baseSha: BASE });
    expect(found).toBeUndefined();
  });
});

describe("findTrustedBaseline with site-equivalent ancestors", () => {
  const ANCESTOR = "0f3fbebaa6a8a2a4b4c4d4e4f40404040404040a";
  const FAR = "1f3fbebaa6a8a2a4b4c4d4e4f40404040404040b";

  it("uses the nearest site-equivalent ancestor when the exact base has no baseline", async () => {
    const { github } = fakeGithub(
      [
        { id: 7, name: `public-site-visual-baseline-${ANCESTOR}`, runId: 70, headSha: ANCESTOR },
        { id: 8, name: `public-site-visual-baseline-${FAR}`, runId: 80, headSha: FAR },
      ],
      { 70: developRun({ head_sha: ANCESTOR }), 80: developRun({ head_sha: FAR }) },
    );
    const found = await findTrustedBaseline({ github, repository: REPO, baseSha: BASE, candidateShas: [ANCESTOR, FAR] });
    expect(found).toMatchObject({ source: "develop", baselineSha: ANCESTOR, artifact: { id: 7 } });
  });

  it("prefers the exact base over an ancestor", async () => {
    const { github } = fakeGithub(
      [
        { id: 1, name: NAME, runId: 10 },
        { id: 7, name: `public-site-visual-baseline-${ANCESTOR}`, runId: 70, headSha: ANCESTOR },
      ],
      { 10: queueRun(), 70: developRun({ head_sha: ANCESTOR }) },
    );
    const found = await findTrustedBaseline({ github, repository: REPO, baseSha: BASE, candidateShas: [ANCESTOR] });
    expect(found).toMatchObject({ source: "merge-queue", baselineSha: BASE, artifact: { id: 1 } });
  });

  it("prefers a landed develop baseline over an ancestor queue candidate", async () => {
    const { github } = fakeGithub(
      [
        { id: 7, name: `public-site-visual-baseline-${ANCESTOR}`, runId: 70, headSha: ANCESTOR },
        { id: 8, name: `public-site-visual-baseline-${FAR}`, runId: 80, headSha: FAR },
      ],
      {
        70: queueRun({ head_sha: ANCESTOR, head_branch: `gh-readonly-queue/develop/pr-2351-${ANCESTOR}` }),
        80: developRun({ head_sha: FAR }),
      },
    );
    const found = await findTrustedBaseline({ github, repository: REPO, baseSha: BASE, candidateShas: [ANCESTOR, FAR] });
    expect(found).toMatchObject({ source: "develop", baselineSha: FAR, artifact: { id: 8 } });
  });

  it("uses an ancestor queue candidate when nothing landed exists", async () => {
    const { github } = fakeGithub(
      [{ id: 7, name: `public-site-visual-baseline-${ANCESTOR}`, runId: 70, headSha: ANCESTOR }],
      { 70: queueRun({ head_sha: ANCESTOR }) },
    );
    const found = await findTrustedBaseline({ github, repository: REPO, baseSha: BASE, candidateShas: [ANCESTOR] });
    expect(found).toMatchObject({ source: "merge-queue", baselineSha: ANCESTOR });
  });

  it("never trusts an ancestor the caller did not list", async () => {
    const { github } = fakeGithub(
      [{ id: 7, name: `public-site-visual-baseline-${ANCESTOR}`, runId: 70, headSha: ANCESTOR }],
      { 70: developRun({ head_sha: ANCESTOR }) },
    );
    expect(await findTrustedBaseline({ github, repository: REPO, baseSha: BASE })).toBeUndefined();
  });
});

describe("baselineShaOrder", () => {
  it("puts the base first, drops malformed and duplicate SHAs, and bounds the list", () => {
    const many = Array.from({ length: 40 }, (_, i) => i.toString(16).padStart(40, "a"));
    const order = baselineShaOrder(BASE, [BASE, "not-a-sha", ...many]);
    expect(order[0]).toBe(BASE);
    expect(order).not.toContain("not-a-sha");
    expect(new Set(order).size).toBe(order.length);
    // Covers every SHA the classifier can emit (base plus 25 ancestors).
    expect(order.length).toBe(MAX_BASELINE_SHAS);
  });
});

describe("waitForTrustedBaseline", () => {
  function clock() {
    let current = 0;
    return {
      now: () => current,
      sleep: async (ms: number) => {
        current += ms;
      },
    };
  }

  it("keeps the short retry and fails closed when no wait is configured", async () => {
    const { github } = fakeGithub([], {});
    const { now, sleep } = clock();
    const result = await waitForTrustedBaseline({ github, repository: REPO, baseSha: BASE, now, sleep });
    expect(result.artifact).toBeUndefined();
    expect(result.attempts).toBe(6);
  });

  it("waits for a leader's candidate that appears after the short retry", async () => {
    const artifacts: Array<{ id: number; name: string; runId: number }> = [];
    const { github } = fakeGithub(artifacts, { 10: queueRun() });
    const { now, sleep: tick } = clock();
    const sleep = async (ms: number) => {
      await tick(ms);
      if (now() >= 600_000 && artifacts.length === 0) artifacts.push({ id: 1, name: NAME, runId: 10 });
    };
    const result = await waitForTrustedBaseline({
      github,
      repository: REPO,
      baseSha: BASE,
      waitMs: 1_800_000,
      now,
      sleep,
    });
    expect(result).toMatchObject({ source: "merge-queue", artifact: { id: 1 } });
    expect(now()).toBeLessThan(1_800_000);
  });

  it("stops at the deadline and fails closed", async () => {
    const { github } = fakeGithub([], {});
    const { now, sleep } = clock();
    const result = await waitForTrustedBaseline({
      github,
      repository: REPO,
      baseSha: BASE,
      waitMs: 1_800_000,
      now,
      sleep,
    });
    expect(result.artifact).toBeUndefined();
    expect(now()).toBeGreaterThanOrEqual(1_800_000);
    expect(now()).toBeLessThan(1_800_000 + 60_000);
    // Short retries, then about one lookup per minute: bounded API use per follower.
    expect(result.attempts).toBeLessThan(45);
  });

  it("reports a lookup failure instead of a missing baseline when the API keeps failing", async () => {
    const github = async () => {
      throw new Error("GitHub API 502");
    };
    const { now, sleep } = clock();
    await expect(waitForTrustedBaseline({ github, repository: REPO, baseSha: BASE, now, sleep })).rejects.toThrow(
      /Unable to list protected public-site visual baselines after 6 attempts/,
    );
  });
});
