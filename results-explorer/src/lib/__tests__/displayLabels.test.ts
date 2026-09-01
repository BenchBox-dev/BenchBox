import { describe, expect, it } from "vitest";
import {
  formatBenchmarkLabel,
  canonicalBenchmarkSlug,
  canonicalPhase,
  describeValidationStatus,
  formatCostStatus,
  formatEnumLabel,
  formatFunding,
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

describe("formatFunding", () => {
  it("humanizes every canonical funding source", () => {
    expect(formatFunding("employer")).toBe("employer funded");
    expect(formatFunding("personal")).toBe("personally funded");
    expect(formatFunding("free-trial")).toBe("free trial");
    expect(formatFunding("vendor-sponsored")).toBe("vendor sponsored");
    expect(formatFunding("grant")).toBe("grant funded");
    expect(formatFunding("unspecified")).toBe("unspecified");
  });

  // Unlike formatTrustLabel, a missing value maps to "unspecified" rather than
  // "unknown": `unspecified` is the producer default, so absent and declared
  // carry the same meaning.
  it("returns 'unspecified' for null/empty values", () => {
    expect(formatFunding(null)).toBe("unspecified");
    expect(formatFunding("")).toBe("unspecified");
    expect(formatFunding(undefined)).toBe("unspecified");
  });

  it("falls back to underscore/dash humanization for unknown values", () => {
    expect(formatFunding("crowd_funded")).toBe("crowd funded");
    expect(formatFunding("some-new-source")).toBe("some new source");
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

  // Full status set from benchbox/core/results/status.py
  // NON_CLEAN_VALIDATION_STATUSES - the raw enum used to be impossible for a
  // reader to interpret (e.g. a bare "not_run" chip); every one of these must
  // now render plain language.
  it("humanizes every NON_CLEAN_VALIDATION_STATUSES value", () => {
    expect(formatValidationStatus("failed")).toBe("failed");
    expect(formatValidationStatus("interrupted")).toBe("interrupted");
    expect(formatValidationStatus("partial")).toBe("partial pass");
    expect(formatValidationStatus("error")).toBe("validation error");
    expect(formatValidationStatus("not_run")).toBe("no validation");
    expect(formatValidationStatus("not_validated")).toBe("not validated");
    expect(formatValidationStatus("uncertain")).toBe("uncertain");
    expect(formatValidationStatus("unknown")).toBe("unknown");
  });
});

describe("describeValidationStatus", () => {
  it("returns the raw status alongside the reader-facing label", () => {
    const info = describeValidationStatus("not_run");
    expect(info.status).toBe("not_run");
    expect(info.label).toBe("no validation");
    expect(info.description.length).toBeGreaterThan(0);
    expect(info.isClean).toBe(false);
  });

  it("marks passed (and its aliases) as the only clean status", () => {
    expect(describeValidationStatus("passed").isClean).toBe(true);
    expect(describeValidationStatus("pass").isClean).toBe(true);
    expect(describeValidationStatus("exact").isClean).toBe(true);
    expect(describeValidationStatus("full").isClean).toBe(true);
    expect(describeValidationStatus("not_run").isClean).toBe(false);
    expect(describeValidationStatus("failed").isClean).toBe(false);
  });

  it("gives CLI-failure statuses a danger tone", () => {
    for (const status of ["failed", "interrupted", "partial", "error"]) {
      expect(describeValidationStatus(status).tone).toBe("danger");
    }
  });

  it("gives never-validated statuses a warning tone, never neutral", () => {
    for (const status of ["not_run", "not_validated", "uncertain", "unknown"]) {
      const info = describeValidationStatus(status);
      expect(info.tone).toBe("warning");
      expect(info.tone).not.toBe("neutral");
    }
  });

  it("normalizes case and whitespace before matching", () => {
    expect(describeValidationStatus("  Not_Run ").label).toBe("no validation");
  });

  it("handles a missing status without throwing", () => {
    const info = describeValidationStatus(null);
    expect(info.status).toBeNull();
    expect(info.isClean).toBe(false);
    expect(info.tone).toBe("neutral");
  });

  it("never gives an unrecognised non-null status the neutral tone", () => {
    expect(describeValidationStatus("some_future_status").tone).toBe("warning");
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
  it("marks the historical star_schema source while keeping ssb canonical", () => {
    expect(formatBenchmarkLabel("star_schema")).toBe("SSB (historical source)");
    expect(formatBenchmarkLabel("ssb")).toBe("SSB");
    // The two slugs MUST yield distinguishable labels; that's the whole
    // point of this helper.
    expect(formatBenchmarkLabel("star_schema")).not.toBe(formatBenchmarkLabel("ssb"));
  });

  it("canonicalizes aliases without changing raw evidence", () => {
    expect(canonicalBenchmarkSlug("star_schema")).toBe("ssb");
    expect(canonicalBenchmarkSlug(" SSB ")).toBe("ssb");
    expect(canonicalPhase(null)).toBe("unknown");
    expect(canonicalPhase(" POWER ")).toBe("power");
  });

  it("falls through to humanizeBenchmark for other slugs", () => {
    expect(formatBenchmarkLabel("tpch")).toBe("TPC-H");
    expect(formatBenchmarkLabel("clickbench")).toBe("ClickBench");
  });
});
