// @vitest-environment node
import { describe, expect, it } from "vitest";

import { evaluateAudit, main } from "../../../scripts/audit-high.mjs";

const GHSA = "GHSA-vfj7-8cjw-p6xm";
const URL = `https://github.com/advisories/${GHSA}`;

const entry = {
  id: GHSA,
  package: "braces",
  reason: "no patched release",
  review_by: "2026-12-01",
  link: URL,
};

function bracesAdvisory(overrides: Record<string, unknown> = {}) {
  return {
    source: 1,
    name: "braces",
    title: "braces vulnerable to stack-exhaustion denial of service",
    url: URL,
    severity: "high",
    range: "<=3.0.3",
    ...overrides,
  };
}

// braces is reported directly; chokidar and tailwindcss are reached through it.
function auditWithBraces(extra: Record<string, unknown> = {}) {
  return {
    auditReportVersion: 2,
    vulnerabilities: {
      braces: { name: "braces", severity: "high", via: [bracesAdvisory()] },
      chokidar: { name: "chokidar", severity: "high", via: ["braces"] },
      tailwindcss: { name: "tailwindcss", severity: "high", via: ["chokidar"] },
      ...extra,
    },
  };
}

function run(audit: unknown, options: { allowlist?: unknown; now?: string; fixed?: string[] } = {}) {
  const out: string[] = [];
  const err: string[] = [];
  const code = main({
    audit: () => audit,
    allowlist: () => options.allowlist ?? [entry],
    versionsOutsideRange: () => options.fixed ?? [],
    now: new Date(`${options.now ?? "2026-10-02"}T12:00:00Z`),
    log: (message) => out.push(message),
    error: (message) => err.push(message),
  });
  return { code, out: out.join("\n"), err: err.join("\n") };
}

describe("audit:high gate", () => {
  it("passes and names the entry in force when only allowlisted advisories remain", () => {
    const result = run(auditWithBraces());
    expect(result.code).toBe(0);
    expect(result.out).toContain(GHSA);
    expect(result.out).toContain("2026-12-01");
    expect(result.err).toBe("");
  });

  it("fails for a high finding that is not allowlisted", () => {
    const other = {
      name: "left-pad",
      severity: "high",
      via: [bracesAdvisory({ name: "left-pad", url: "https://github.com/advisories/GHSA-aaaa-bbbb-cccc" })],
    };
    const result = run(auditWithBraces({ "left-pad": other }));
    expect(result.code).toBe(1);
    expect(result.err).toContain("left-pad");
    expect(result.err).toContain("ghsa-aaaa-bbbb-cccc");
  });

  it("fails for a critical finding in a package that also depends on an allowlisted one", () => {
    const mixed = {
      name: "mixed",
      severity: "critical",
      via: ["braces", bracesAdvisory({ name: "mixed", severity: "critical", url: "https://github.com/advisories/GHSA-dddd-eeee-ffff" })],
    };
    expect(run(auditWithBraces({ mixed })).code).toBe(1);
  });

  it("ignores findings below the high level", () => {
    const low = {
      name: "minor",
      severity: "moderate",
      via: [bracesAdvisory({ name: "minor", severity: "moderate", url: "https://github.com/advisories/GHSA-aaaa-bbbb-cccc" })],
    };
    expect(run(auditWithBraces({ minor: low })).code).toBe(0);
  });

  it("fails once the registry has a release outside the vulnerable range", () => {
    const result = run(auditWithBraces(), { fixed: ["3.0.4"] });
    expect(result.code).toBe(1);
    expect(result.err).toContain("3.0.4");
    expect(result.err).toContain("remove the entry");
  });

  it("fails after the review_by date has passed", () => {
    const result = run(auditWithBraces(), { now: "2026-12-02" });
    expect(result.code).toBe(1);
    expect(result.err).toContain("expired on 2026-12-01");
  });

  it("still passes on the review_by date itself", () => {
    expect(run(auditWithBraces(), { now: "2026-12-01" }).code).toBe(0);
  });

  it("fails for a malformed allowlist entry", () => {
    const { reason: _reason, ...incomplete } = entry;
    const result = run(auditWithBraces(), { allowlist: [incomplete] });
    expect(result.code).toBe(1);
    expect(result.err).toContain("missing: reason");
  });

  it("fails when npm audit reports an error instead of a report", () => {
    const result = run({ error: { code: "ENOTFOUND", summary: "network down" } });
    expect(result.code).toBe(1);
    expect(result.err).toContain("network down");
  });

  it("reports an entry that no longer matches any finding", () => {
    const result = run({ auditReportVersion: 2, vulnerabilities: {} });
    expect(result.code).toBe(0);
    expect(result.out).toContain("matches no current finding");
  });

  it("evaluateAudit does not query the registry for entries absent from the report", () => {
    const evaluation = evaluateAudit({
      audit: { vulnerabilities: {} },
      allowlist: [entry],
      today: "2026-10-02",
      versionsOutsideRange: () => {
        throw new Error("unexpected registry query");
      },
    });
    expect(evaluation.failures).toEqual([]);
    expect(evaluation.unused).toHaveLength(1);
  });
});
