import { describe, expect, it } from "vitest";
import {
  formatRunIdentitiesForCohort,
  formatRunIdentityLabelsForCohort,
  formatRunIdentity,
  preserveUniqueAfterTruncation,
  truncateRunIdentityLabel,
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

  it("omits qualifiers that are invariant within the current cohort", () => {
    const cohort = [
      source({
        result_id: "amplab-datafusion-sf0.01-20260501-a276dae0",
        platform: "DataFusion",
        driver_version: "53.0.0",
        run_date: "2026-05-01",
        scale_factor: 0.01,
      }),
      source({
        result_id: "amplab-datafusion-sf0.01-20260502-bb1d4f90",
        platform: "DataFusion",
        driver_version: "53.0.0",
        run_date: "2026-05-02",
        scale_factor: 0.01,
      }),
    ];
    const labels = formatRunIdentitiesForCohort(cohort, "chart");

    expect(labels).toEqual(["DataFusion 2026-05-01", "DataFusion 2026-05-02"]);
    expect(labels.join(" ")).not.toContain("SF 0.01");
    expect(labels.join(" ")).not.toContain("v53.0.0");
  });

  it("keeps shared natural qualifiers ahead of the result id fallback", () => {
    const cohort = [
      source({
        result_id: "tpch-spark-sf0.01-20260501-1111aaaa",
        platform: "Spark",
        driver_version: "3.5.0",
        run_date: "2026-05-01",
        scale_factor: 0.01,
      }),
      source({
        result_id: "tpch-spark-sf0.01-20260501-2222bbbb",
        platform: "Spark",
        run_date: "2026-05-01",
        scale_factor: 0.01,
      }),
    ];
    const labels = formatRunIdentitiesForCohort(cohort, "chart");

    expect(labels).toEqual(["Spark v3.5.0", "Spark 2026-05-01"]);
    expect(labels.join(" ")).not.toMatch(/1111aaaa|2222bbbb/);
  });

  it("uses short result_id as the last-resort tiebreaker", () => {
    const cohort = [
      source({ result_id: "tpch-spark-sf0.01-20260403-1111aaaa", platform: "Spark" }),
      source({ result_id: "tpch-spark-sf0.01-20260403-2222bbbb", platform: "Spark" }),
    ];
    const labels = formatRunIdentitiesForCohort(cohort, "chart");
    expect(new Set(labels).size).toBe(2);
    expect(labels[0]).toContain("1111aaaa");
    expect(labels[1]).toContain("2222bbbb");
    expect(labels[0]).not.toContain("tpch-spark");
    expect(labels[1]).not.toContain("tpch-spark");
  });

  it("ignores non-hex short_id prefixes and preserves the trailing result-id token", () => {
    const cohort = [
      source({
        result_id: "tpch-datafusion-sf0.01-20260506-51d39a73",
        short_id: "tpch-dat",
        platform: "DataFusion",
      }),
      source({
        result_id: "tpch-datafusion-sf0.01-20260505-77daf86d",
        short_id: "tpch-dat",
        platform: "DataFusion",
      }),
    ];

    expect(formatRunIdentitiesForCohort(cohort, "chart")).toEqual([
      "DataFusion 51d39a73",
      "DataFusion 77daf86d",
    ]);
  });

  it("uses the trailing result_id token when 8-char prefixes collide", () => {
    // BenchBox result_ids usually share their benchmark/platform/date prefix;
    // the content hash lives at the end and is the compact distinguishing token.
    const cohort = [
      source({ result_id: "tpch-spark-sf0.01-20260403-aaaaaaaa", platform: "Spark" }),
      source({ result_id: "tpch-spark-sf0.01-20260403-bbbbbbbb", platform: "Spark" }),
    ];
    const labels = formatRunIdentitiesForCohort(cohort, "chart");
    expect(new Set(labels).size).toBe(2);
    expect(labels).toEqual(["Spark aaaaaaaa", "Spark bbbbbbbb"]);
  });

  it("falls through to the full result_id when trailing tokens collide", () => {
    const cohort = [
      source({ result_id: "left-shared", platform: "Spark" }),
      source({ result_id: "right-shared", platform: "Spark" }),
    ];
    const labels = formatRunIdentitiesForCohort(cohort, "chart");
    expect(new Set(labels).size).toBe(2);
    expect(labels[0]).toContain("left-shared");
    expect(labels[1]).toContain("right-shared");
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

  it("returns compact, full, and accessible identity labels for chart callers", () => {
    const cohort = [
      source({
        result_id: "tpch-datafusion-sf0.01-20260506-3b8bbc42",
        short_id: "3b8bbc42",
        platform: "DataFusion",
        driver_version: "53.0.0",
        run_date: "2026-05-06T12:00:00Z",
        scale_factor: 0.01,
        trust_label: "maintainer-run",
      }),
      source({
        result_id: "tpch-datafusion-sf0.01-20260507-deadbeef",
        short_id: "deadbeef",
        platform: "DataFusion",
        driver_version: "53.0.0",
        run_date: "2026-05-07T12:00:00Z",
        scale_factor: 0.01,
        trust_label: "maintainer-run",
      }),
    ];
    const labels = formatRunIdentityLabelsForCohort(cohort);

    expect(labels[0]?.compact).toBe("DataFusion 2026-05-06");
    expect(labels[1]?.compact).toBe("DataFusion 2026-05-07");
    expect(labels[0]?.full).toContain("v53.0.0");
    expect(labels[0]?.full).toContain("SF 0.01");
    expect(labels[0]?.full).toContain("maintainer-run");
    expect(labels[0]?.full).toContain("3b8bbc42");
    expect(labels[0]?.ariaLabel).toBe(labels[0]?.full);
  });

  it("suffix-truncates run labels so dates or short IDs remain visible", () => {
    expect(truncateRunIdentityLabel("DataFusion v53.0.0 2026-05-06", 20)).toBe(
      "DataFusi… 2026-05-06",
    );
    expect(truncateRunIdentityLabel("DataFusion v53.0.0 3b8bbc42", 20)).toBe(
      "DataFusion… 3b8bbc42",
    );
  });

  it("keeps truncated chart labels unique without expanding to full width", () => {
    const labels = preserveUniqueAfterTruncation(
      [
        "DataFusion v53.0.0 2026-05-06 3b8bbc42",
        "DataFusion v53.0.0 2026-05-07 deadbeef",
        "DataFusion v53.0.0 2026-05-08 cafefeed",
        "DataFusion v53.0.0 2026-05-09 feedface",
      ],
      20,
    );

    expect(new Set(labels).size).toBe(labels.length);
    expect(labels.every((label) => label.length <= 20)).toBe(true);
    expect(labels).toEqual([
      "DataFusion… 3b8bbc42",
      "DataFusion… deadbeef",
      "DataFusion… cafefeed",
      "DataFusion… feedface",
    ]);
  });
});
