import { describe, expect, it } from "vitest";
import {
  BenchmarkSupportBadge,
  benchmarkSupportGroupLabel,
  benchmarkSupportRank,
  describeBenchmarkSupportStatus,
  isBenchmarkSupportStatus,
} from "@/lib/benchmarkSupport";

describe("isBenchmarkSupportStatus", () => {
  it.each(["stable", "beta", "experimental", "repo_only", "deprecated", "document_only"])(
    "accepts %s",
    (status) => {
      expect(isBenchmarkSupportStatus(status)).toBe(true);
    },
  );

  it.each([null, undefined, "", "unknown", "STABLE", "community"])("rejects %s", (status) => {
    expect(isBenchmarkSupportStatus(status)).toBe(false);
  });
});

describe("describeBenchmarkSupportStatus", () => {
  it.each([
    ["stable", "Stable"],
    ["beta", "Beta"],
    ["experimental", "Experimental"],
    ["deprecated", "Deprecated"],
    ["document_only", "Document-only"],
    ["repo_only", "Repo-only"],
  ])("labels %s as %s", (status, label) => {
    expect(describeBenchmarkSupportStatus(status)).toBe(label);
  });

  it("returns null for unclassified statuses", () => {
    expect(describeBenchmarkSupportStatus(null)).toBeNull();
    expect(describeBenchmarkSupportStatus("custom-thing")).toBeNull();
  });
});

describe("benchmarkSupportRank", () => {
  it("orders stable before beta before experimental before deprecated", () => {
    const ordered = ["stable", "beta", "experimental", "deprecated", "document_only", "repo_only"];
    const ranks = ordered.map(benchmarkSupportRank);
    expect([...ranks].sort((left, right) => left - right)).toEqual(ranks);
  });

  it("sorts unclassified statuses last", () => {
    expect(benchmarkSupportRank(null)).toBeGreaterThan(benchmarkSupportRank("repo_only"));
    expect(benchmarkSupportRank("custom-thing")).toBeGreaterThan(benchmarkSupportRank("deprecated"));
  });
});

describe("benchmarkSupportGroupLabel", () => {
  it("pluralizes known statuses and falls back to Other benchmarks", () => {
    expect(benchmarkSupportGroupLabel("stable")).toBe("Stable benchmarks");
    expect(benchmarkSupportGroupLabel("beta")).toBe("Beta benchmarks");
    expect(benchmarkSupportGroupLabel(null)).toBe("Other benchmarks");
    expect(benchmarkSupportGroupLabel("custom-thing")).toBe("Other benchmarks");
  });
});

describe("BenchmarkSupportBadge", () => {
  it("exposes the config for known statuses", () => {
    // The badge renders through StatusBadge; the contract that matters here
    // is the status-to-label mapping above plus a null for unknown.
    expect(BenchmarkSupportBadge({ status: "stable" })).not.toBeNull();
    expect(BenchmarkSupportBadge({ status: null })).toBeNull();
    expect(BenchmarkSupportBadge({ status: "custom-thing" })).toBeNull();
  });
});
