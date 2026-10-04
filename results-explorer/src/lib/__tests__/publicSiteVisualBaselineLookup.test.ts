// @vitest-environment node
import { describe, expect, it } from "vitest";

import {
  baselineShaOrder,
  findTrustedBaseline,
  JOBS_PAGE_SIZE,
  MAX_BASELINE_SHAS,
  MAX_JOB_PAGES,
  trustedBaselineSource,
  waitForTrustedBaseline,
} from "../../../scripts/public-site-visual-baseline-lookup.mjs";

const REPO = "BenchBox-dev/BenchBox";
const BASE = "f8f38867676f96d4e36e9d7e1dbdf84800da11f1";
const OTHER = "7214e982a1a78d13caf15b0893c487be9048d19e";
const NAME = `public-site-visual-baseline-${BASE}`;
const CI = ".github/workflows/ci.yml";
const VISUAL = "Public-site visual regression";

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

function fakeGithub(
  artifacts: Array<{ id: number; name: string; runId: number; headSha?: string }>,
  runs: Record<number, Run>,
  jobs: Record<number, Array<{ name: string; status: string; conclusion: string }>> = {},
) {
  const calls: string[] = [];
  const github = async (path: string) => {
    calls.push(path);
    const jobsMatch = path.match(/\/actions\/runs\/(\d+)\/jobs(?:\?(.*))?$/);
    if (jobsMatch) {
      const query = new URLSearchParams(jobsMatch[2] ?? "");
      const perPage = Math.min(Number(query.get("per_page") ?? 30), 100);
      const page = Number(query.get("page") ?? 1);
      const all = jobs[Number(jobsMatch[1])] ?? [];
      return { total_count: all.length, jobs: all.slice((page - 1) * perPage, page * perPage) };
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

  it.each([
    ["pull_request event", developRun({ event: "pull_request" })],
    ["merge_group event on a queue branch", developRun({ event: "merge_group", head_branch: `gh-readonly-queue/develop/pr-2351-${OTHER}` })],
    ["other workflow", developRun({ path: ".github/workflows/test.yml" })],
    ["other workflow on develop", developRun({ path: ".github/workflows/other.yml" })],
    ["push to another branch", developRun({ head_branch: "release" })],
    ["in-progress develop run", developRun({ status: "in_progress", conclusion: null })],
    ["failed develop run", developRun({ conclusion: "failure" })],
    ["develop run from another repository", developRun({ repository: { full_name: "someone/BenchBox" } })],
    ["CI workflow run on develop: develop baselines come from the Documentation workflow only", developRun({ path: CI })],
  ])("rejects %s", (_label, run) => {
    expect(trustedBaselineSource(run, context)).toBeUndefined();
  });
});

describe("findTrustedBaseline", () => {
  it("ignores a same-named artifact uploaded by a pull_request run", async () => {
    const { github } = fakeGithub([{ id: 1, name: NAME, runId: 10 }], {
      10: developRun({ event: "pull_request", head_branch: "fix/forged" }),
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

describe("findTrustedBaseline job pagination for a failed develop run", () => {
  const find = (github: (path: string) => Promise<unknown>) =>
    findTrustedBaseline({ github: github as never, repository: REPO, baseSha: BASE });
  const filler = (count: number) =>
    Array.from({ length: count }, (_unused, index) => ({
      name: `filler-${index}`,
      status: "completed",
      conclusion: "success",
    }));
  const failedRun = { 10: developRun({ conclusion: "failure" }) };
  const visual = (status: string, conclusion: string) => ({ name: VISUAL, status, conclusion });

  it("finds a successful visual job beyond the endpoint's default page of 30", async () => {
    const { github, calls } = fakeGithub([{ id: 1, name: NAME, runId: 10 }], failedRun, {
      10: [...filler(40), visual("completed", "success")],
    });
    expect(await find(github)).toMatchObject({ source: "develop", artifact: { id: 1 } });
    expect(calls.some((path) => path.includes("/jobs?per_page=100"))).toBe(true);
  });

  it("follows further pages when the first full page of 100 does not contain it", async () => {
    const { github, calls } = fakeGithub([{ id: 1, name: NAME, runId: 10 }], failedRun, {
      10: [...filler(150), visual("completed", "success")],
    });
    expect(await find(github)).toMatchObject({ source: "develop" });
    expect(calls.some((path) => path.endsWith("page=2"))).toBe(true);
  });

  it("does not trust a run when a later duplicate of the visual job failed", async () => {
    const { github } = fakeGithub([{ id: 1, name: NAME, runId: 10 }], failedRun, {
      10: [visual("completed", "success"), ...filler(120), visual("completed", "failure")],
    });
    expect(await find(github)).toBeUndefined();
  });

  it("fails closed rather than paging without bound", async () => {
    const { github, calls } = fakeGithub([{ id: 1, name: NAME, runId: 10 }], failedRun, {
      10: [...filler(MAX_JOB_PAGES * JOBS_PAGE_SIZE), visual("completed", "success")],
    });
    expect(await find(github)).toBeUndefined();
    expect(calls.filter((path) => path.includes("/jobs?")).length).toBe(MAX_JOB_PAGES);
  });

  it("does not trust a run whose job list cannot be read", async () => {
    const { github: inner } = fakeGithub([{ id: 1, name: NAME, runId: 10 }], failedRun);
    const github = async (path: string) => {
      if (/\/jobs(\?|$)/.test(path)) throw new Error("jobs unavailable");
      return inner(path);
    };
    expect(await find(github)).toBeUndefined();
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
      { 10: developRun(), 70: developRun({ head_sha: ANCESTOR }) },
    );
    const found = await findTrustedBaseline({ github, repository: REPO, baseSha: BASE, candidateShas: [ANCESTOR] });
    expect(found).toMatchObject({ source: "develop", baselineSha: BASE, artifact: { id: 1 } });
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

  it("waits for a develop baseline that appears after the short retry", async () => {
    const artifacts: Array<{ id: number; name: string; runId: number }> = [];
    const { github } = fakeGithub(artifacts, { 10: developRun() });
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
    expect(result).toMatchObject({ source: "develop", artifact: { id: 1 } });
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
