import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  importLocalResultFile,
  LocalResultImportError,
  MAX_LOCAL_RESULT_BYTES,
  parseLocalResultText,
} from "@/lib/localResult";

function bundle(overrides: Record<string, unknown> = {}) {
  return {
    version: "2.1",
    run: {
      id: "private-run-id",
      timestamp: "2026-09-05T12:34:56Z",
      total_duration_ms: 4_000,
    },
    benchmark: { id: "tpch", name: "TPC-H", scale_factor: 1, test_type: "power" },
    platform: {
      name: "DuckDB",
      version: "1.4.3",
      config: { execution_mode: "sql", database_path: "/private/customer.duckdb" },
    },
    config: { mode: "sql" },
    summary: {
      queries: { total: 44, passed: 44, failed: 0 },
      validation: "passed",
      tpc_metrics: { power_at_size: 1234.5 },
    },
    environment: {
      os: "macOS",
      arch: "arm64",
      cpu_count: 10,
      cpu_model: "Apple M4",
      machine_id: "secret-machine-id",
      database_path: "/private/customer.duckdb",
      client_link: {
        client_region: "us-east",
        client_cloud: "local",
        collection_status: "recorded",
        statement_overhead_ms: { min: 0.1, median: 0.2 },
      },
    },
    queries: [
      { id: "1", ms: 10, iter: 1, run_type: "measurement", status: "SUCCESS" },
      { id: "1", ms: 30, iter: 2, run_type: "measurement", status: "SUCCESS" },
      { id: "1", ms: 999, iter: 0, run_type: "warmup", status: "SUCCESS" },
      { id: "2", ms: 40, iter: 1, run_type: "measurement", status: "SUCCESS" },
      { id: "summary", ms: 0, run_type: "summary", status: "SKIPPED" },
    ],
    ...overrides,
  };
}

describe("local result import", () => {
  it("matches the publication transform for the canonical browser fixture", async () => {
    const fixturePath = resolve(
      import.meta.dirname,
      "../../../test-fixtures/source/bundles/tpch-duckdb-sf0.01-20260403-7fe93365.json",
    );
    const preview = await parseLocalResultText(readFileSync(fixturePath, "utf8"), "fixture.json");

    expect(preview.detail).toMatchObject({
      benchmark: "tpch",
      scale_factor: 0.01,
      platform: "DuckDB",
      platform_id: "duckdb",
      driver_version: "1.4.3",
      run_date: "2026-04-03",
      total_duration_s: 2.815,
      power_score: 3184.897098661065,
      logical_query_count: 22,
      valid_query_count: 22,
      missing_query_count: 0,
      zero_timing_count: 0,
      display_exclusion_reason: null,
      comparison_exclusion_reason: null,
      execution_mode: "sql",
      validation_status: "passed",
    });
    expect(preview.detail.geomean_ms).toBeCloseTo(11.516422021051456);
    expect(preview.detail.display_geomean_ms).toBeCloseTo(11.335852721901425);
    expect(preview.detail.display_timings.find((timing) => timing.query_id === "14")).toMatchObject({
      display_ms: 12,
      sample_count: 4,
    });
    expect(preview.detail.display_timings).toHaveLength(22);
    expect(preview.detail.queries).toHaveLength(88);
  });

  it("projects a schema-v2 bundle into a private detail result", async () => {
    const text = JSON.stringify(bundle());
    const preview = await parseLocalResultText(text, "my-run.json");

    expect(preview.fileName).toBe("my-run.json");
    expect(preview.detail.result_id).toMatch(/^local-[0-9a-f]{12}$/);
    expect(preview.detail.result_id).not.toContain("private-run-id");
    expect(preview.detail.trust_label).toBe("local-run");
    expect(preview.detail.visibility).toBe("local-preview");
    expect(preview.detail.ranking_exclusion_reason).toBe("local_result");
    expect(preview.detail.display_timings).toEqual([
      {
        query_id: "1",
        display_ms: 20,
        sample_count: 2,
        is_valid_display_timing: true,
        timing_exclusion_reason: null,
      },
      {
        query_id: "2",
        display_ms: 40,
        sample_count: 1,
        is_valid_display_timing: true,
        timing_exclusion_reason: null,
      },
    ]);
    expect(preview.detail.logical_query_count).toBe(22);
    expect(preview.detail.missing_query_count).toBe(20);
    expect(preview.primaryMetric).toBe("power_score");
    expect(preview.detail.environment).toMatchObject({
      os: "macOS",
      arch: "arm64",
      cpu_count: 10,
      cpu_model: "Apple M4",
      client_region: "us-east",
      statement_overhead_median_ms: 0.2,
    });
    expect(preview.detail.environment).not.toHaveProperty("machine_id");
    expect(preview.detail.environment).not.toHaveProperty("database_path");
    expect(JSON.stringify(preview.detail)).not.toContain("/private/customer.duckdb");
  });

  it("uses an opaque per-import ID rather than a bundle fingerprint", async () => {
    const text = JSON.stringify(bundle());
    const first = await parseLocalResultText(text);
    const second = await parseLocalResultText(text);

    expect(first.detail.result_id).toMatch(/^local-[0-9a-f]{12}$/);
    expect(second.detail.result_id).toMatch(/^local-[0-9a-f]{12}$/);
    expect(second.detail.result_id).not.toBe(first.detail.result_id);
  });

  it("marks an otherwise passing summary partial when queries failed", async () => {
    const value = bundle({
      summary: {
        queries: { total: 2, passed: 1, failed: 1 },
        validation: { status: "passed" },
      },
    });
    const preview = await parseLocalResultText(JSON.stringify(value));
    expect(preview.detail.validation_status).toBe("partial");
  });

  it("uses publication fallbacks when summary.queries.failed is absent", async () => {
    const fromSummary = bundle({
      summary: {
        queries: { total: 2, passed: 1, skipped: 0 },
        validation: "passed",
      },
    });
    const fromRows = bundle({
      summary: {
        queries: {},
        validation: "passed",
      },
      queries: [{ id: "1", ms: 10, run_type: "measurement", status: "ERROR" }],
    });

    await expect(parseLocalResultText(JSON.stringify(fromSummary))).resolves.toMatchObject({
      detail: { validation_status: "partial" },
    });
    await expect(parseLocalResultText(JSON.stringify(fromRows))).resolves.toMatchObject({
      detail: { validation_status: "partial" },
    });
  });

  it("marks translation fallback as uncertain like the publication transform", async () => {
    const value = bundle({
      execution: { translation: { status: "fallback" } },
    });
    const preview = await parseLocalResultText(JSON.stringify(value));
    expect(preview.detail.validation_status).toBe("uncertain");
  });

  it("matches publication fallbacks for optional display fields", async () => {
    const value = bundle({
      benchmark: { id: "tpch", name: "TPC-H", scale_factor: 1 },
      platform: { name: "Example  Engine", driver_resolved_version: "platform-only" },
      execution: {},
      phases: { power_test: { duration_ms: 1 } },
      cost: { total_usd: 99 },
    });
    const preview = await parseLocalResultText(JSON.stringify(value));

    expect(preview.detail.platform_id).toBe("example--engine");
    expect(preview.detail.driver_version).toBeNull();
    expect(preview.detail.test_type).toBe("power");
    expect(preview.detail.cost_usd).toBeNull();
  });

  it.each(["2.0", "2.1", "2.2"])("accepts supported schema %s", async (version) => {
    await expect(parseLocalResultText(JSON.stringify(bundle({ version })))).resolves.toBeTruthy();
  });

  it("rejects malformed and unsupported input with actionable errors", async () => {
    await expect(parseLocalResultText("not json")).rejects.toThrow("not valid JSON");
    await expect(parseLocalResultText(JSON.stringify(bundle({ version: "3.0" })))).rejects.toThrow(
      "Schema 3.0 is not supported",
    );
    await expect(parseLocalResultText(JSON.stringify(bundle({ queries: null })))).rejects.toThrow(
      "missing its query list",
    );
  });

  it("rejects a non-JSON file before reading it", async () => {
    const file = new File(["unused"], "result.txt", { type: "text/plain" });
    await expect(importLocalResultFile(file)).rejects.toEqual(
      expect.objectContaining<Partial<LocalResultImportError>>({ name: "LocalResultImportError" }),
    );
  });

  it("rejects an oversized file before reading it", async () => {
    const file = {
      name: "result.json",
      size: MAX_LOCAL_RESULT_BYTES + 1,
      text: () => Promise.resolve("unused"),
    } as File;
    await expect(importLocalResultFile(file)).rejects.toThrow("larger than the 10 MiB");
  });
});
