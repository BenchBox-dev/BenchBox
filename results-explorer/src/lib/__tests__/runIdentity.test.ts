import { describe, expect, it } from "vitest";
import {
  formatRunIdentitiesForCohort,
  formatRunIdentity,
  type RunIdentitySource,
} from "@/lib/runIdentity";

function source(overrides: Partial<RunIdentitySource>): RunIdentitySource {
  return {
    result_id: "tpch-duckdb-sf0.01-20260403-7fe93365",
    platform: "DuckDB",
    platform_version: null,
    driver_version: null,
    run_date: null,
    scale_factor: null,
    deployment_class: null,
    instance_or_warehouse: null,
    trust_label: null,
    ...overrides,
  };
}

describe("formatRunIdentity", () => {
  it("returns the bare platform name when no qualifiers are present", () => {
    expect(formatRunIdentity(source({ platform: "DuckDB" }), "compact")).toBe("DuckDB");
    expect(formatRunIdentity(source({ platform: "DuckDB" }), "table")).toBe("DuckDB");
  });

  it("includes the version qualifier in compact and chart variants", () => {
    const s = source({ platform: "DuckDB", driver_version: "1.3.2" });
    expect(formatRunIdentity(s, "compact")).toBe("DuckDB v1.3.2");
    expect(formatRunIdentity(s, "chart")).toBe("DuckDB v1.3.2");
  });

  it("table variant uses bullet separators and the top-2 qualifiers", () => {
    const s = source({
      platform: "DuckDB",
      driver_version: "1.3.2",
      run_date: "2026-04-17",
    });
    expect(formatRunIdentity(s, "table")).toBe("DuckDB · v1.3.2 · 2026-04-17");
  });

  it("tooltip variant lists every qualifier on its own line", () => {
    const s = source({
      platform: "DuckDB",
      driver_version: "1.3.2",
      run_date: "2026-04-17",
      scale_factor: 0.1,
    });
    const tooltip = formatRunIdentity(s, "tooltip");
    expect(tooltip.split("\n")).toContain("DuckDB");
    expect(tooltip.split("\n")).toContain("v1.3.2");
    expect(tooltip.split("\n")).toContain("2026-04-17");
    expect(tooltip.split("\n")).toContain("SF 0.1");
  });
});

describe("formatRunIdentitiesForCohort", () => {
  it("keeps unambiguous platform names plain", () => {
    const cohort = [
      source({ result_id: "r1", platform: "DuckDB" }),
      source({ result_id: "r2", platform: "Polars" }),
      source({ result_id: "r3", platform: "ClickHouse" }),
    ];
    expect(formatRunIdentitiesForCohort(cohort, "chart")).toEqual([
      "DuckDB",
      "Polars",
      "ClickHouse",
    ]);
  });

  it("appends version qualifiers when two same-platform runs share the cohort", () => {
    const cohort = [
      source({ result_id: "r1", platform: "DataFusion", driver_version: "44" }),
      source({ result_id: "r2", platform: "DataFusion", driver_version: "53" }),
      source({ result_id: "r3", platform: "DuckDB" }),
    ];
    const labels = formatRunIdentitiesForCohort(cohort, "chart");
    // The two DataFusion runs must be distinguishable; DuckDB stays plain.
    expect(new Set(labels).size).toBe(3);
    expect(labels[2]).toBe("DuckDB");
    expect(labels[0]).toContain("v44");
    expect(labels[1]).toContain("v53");
  });

  it("falls through to run date when versions also match", () => {
    const cohort = [
      source({
        result_id: "r1",
        platform: "Polars",
        driver_version: "1.40.0",
        run_date: "2026-04-01",
      }),
      source({
        result_id: "r2",
        platform: "Polars",
        driver_version: "1.40.0",
        run_date: "2026-05-01",
      }),
    ];
    const labels = formatRunIdentitiesForCohort(cohort, "chart");
    expect(new Set(labels).size).toBe(2);
    expect(labels[0]).toContain("2026-04-01");
    expect(labels[1]).toContain("2026-05-01");
  });

  it("uses short result_id as the last-resort tiebreaker", () => {
    const cohort = [
      source({ result_id: "1111aaaa11111", platform: "Spark" }),
      source({ result_id: "2222bbbb22222", platform: "Spark" }),
    ];
    const labels = formatRunIdentitiesForCohort(cohort, "chart");
    expect(new Set(labels).size).toBe(2);
    expect(labels[0]).toContain("1111aaaa");
    expect(labels[1]).toContain("2222bbbb");
  });

  it("never produces duplicate visible labels for any cohort", () => {
    const cohort = [
      source({ result_id: "r1", platform: "Spark" }),
      source({ result_id: "r2", platform: "Spark" }),
      source({ result_id: "r3", platform: "Spark", driver_version: "3.5" }),
      source({ result_id: "r4", platform: "Spark", driver_version: "3.5", run_date: "2026-04-17" }),
    ];
    const labels = formatRunIdentitiesForCohort(cohort, "chart");
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("table variant uses bullet separators when disambiguating", () => {
    const cohort = [
      source({ result_id: "r1", platform: "PySpark", driver_version: "3.5" }),
      source({ result_id: "r2", platform: "PySpark", driver_version: "4.1" }),
    ];
    const labels = formatRunIdentitiesForCohort(cohort, "table");
    expect(labels[0]).toContain("·");
    expect(labels[1]).toContain("·");
  });
});
