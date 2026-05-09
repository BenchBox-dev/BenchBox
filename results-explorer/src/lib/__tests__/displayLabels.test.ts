import { describe, expect, it } from "vitest";
import {
  formatBenchmarkLabel,
  formatCostStatus,
  formatEnumLabel,
  formatTrustLabel,
  formatValidationStatus,
  formatVisibility,
} from "@/lib/displayLabels";

describe("formatTrustLabel", () => {
  it("humanizes the canonical trust labels", () => {
    expect(formatTrustLabel("maintainer-run")).toBe("maintainer run");
    expect(formatTrustLabel("community-submission")).toBe("community submission");
  });

  it("returns 'unknown' for null/empty values", () => {
    expect(formatTrustLabel(null)).toBe("unknown");
    expect(formatTrustLabel("")).toBe("unknown");
    expect(formatTrustLabel(undefined)).toBe("unknown");
  });

  it("falls back to underscore/dash humanization for unknown values", () => {
    expect(formatTrustLabel("future_tier")).toBe("future tier");
    expect(formatTrustLabel("some-new-tier")).toBe("some new tier");
  });
});

describe("formatValidationStatus", () => {
  it("humanizes known statuses including not_applicable", () => {
    expect(formatValidationStatus("passed")).toBe("passed");
    expect(formatValidationStatus("not_applicable")).toBe("not applicable");
  });

  it("returns 'unknown' for missing values", () => {
    expect(formatValidationStatus(null)).toBe("unknown");
  });
});

describe("formatVisibility", () => {
  it("turns internal slug into a public-readable label", () => {
    expect(formatVisibility("public-curated")).toBe("public (curated)");
    expect(formatVisibility("public-community")).toBe("public (community)");
    expect(formatVisibility("internal")).toBe("internal");
  });
});

describe("formatCostStatus", () => {
  it("formats common statuses", () => {
    expect(formatCostStatus("normalized")).toBe("normalized");
    expect(formatCostStatus("not_applicable_local")).toBe("not applicable (local)");
    expect(formatCostStatus("not_applicable")).toBe("not applicable");
    expect(formatCostStatus("unavailable")).toBe("unavailable");
  });
});

describe("formatEnumLabel", () => {
  it("replaces underscores and dashes with spaces", () => {
    expect(formatEnumLabel("foo_bar")).toBe("foo bar");
    expect(formatEnumLabel("foo-bar-baz")).toBe("foo bar baz");
    expect(formatEnumLabel("mixed_dash-and_underscore")).toBe("mixed dash and underscore");
  });
});

describe("formatBenchmarkLabel", () => {
  it("disambiguates the legacy ssb slug from canonical star_schema", () => {
    expect(formatBenchmarkLabel("star_schema")).toBe("SSB");
    expect(formatBenchmarkLabel("ssb")).toBe("SSB (legacy slug)");
    // The two slugs MUST yield distinguishable labels; that's the whole
    // point of this helper.
    expect(formatBenchmarkLabel("star_schema")).not.toBe(formatBenchmarkLabel("ssb"));
  });

  it("falls through to humanizeBenchmark for other slugs", () => {
    expect(formatBenchmarkLabel("tpch")).toBe("TPC-H");
    expect(formatBenchmarkLabel("clickbench")).toBe("ClickBench");
  });
});
