import { render, screen, waitFor } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/testing/axe-helper";

vi.mock("@/db", () => ({
  queryRows: vi.fn(),
}));

vi.mock("preact-router", async () => {
  const actual = await vi.importActual<typeof import("preact-router")>("preact-router");
  return {
    ...actual,
    route: vi.fn(),
  };
});

import { queryRows } from "@/db";
import { clearDuckdbQueryCachesForTests } from "@/lib/duckdbQueries";
import { BenchmarkIndex } from "@/pages/BenchmarkIndex";

const ROW = {
  result_id: "blocked-a",
  benchmark: "tpch",
  scale_factor: 0.1,
  platform: "DuckDB",
  platform_id: "duckdb",
  driver_version: null,
  run_date: "2026-04-17",
  power_score: 1000,
  total_duration_s: 60,
  geomean_ms: 10,
  display_geomean_ms: 10,
  query_count: 22,
  has_display_timing: true,
  valid_query_count: 1,
  missing_query_count: 21,
  zero_timing_count: 0,
  display_exclusion_reason: null,
  comparison_exclusion_reason: "insufficient_query_coverage",
  ranking_exclusion_reason: "insufficient_query_coverage",
  trust_label: "maintainer-run",
  visibility: "public-curated",
  platform_version: null,
  execution_mode: null,
  tuning_mode: null,
  tuning_hash: null,
  test_type: "power",
  validation_status: "exact",
  cost_usd: null,
  normalized_cost_usd: null,
  cost_status: "not_applicable_local",
  cost_scope: null,
  cost_model_version: null,
  deployment_class: "local",
  cloud_provider: null,
  cloud_region: null,
  instance_or_warehouse: null,
  storage_format: null,
  compliance_class: null,
  is_ranking_eligible: false,
  has_plans: false,
  has_tuning: false,
  bundle_download_url: "",
};

const RANKING_ROW = {
  ...ROW,
  short_id: "blockeda",
  sample_geomean_ms: 10,
  primary_metric: "power_score",
  primary_order: "desc",
  rank: null,
  total_in_cohort: 1,
  cohort_ranked_count: 0,
  cohort_ranking_exclusion_reason: "no_rankable_results",
  percentile_p50: null,
  percentile_p90: null,
  percentile_p95: null,
  percentile_p99: null,
};

const CELL_ROW = {
  benchmark: "tpch",
  scale_factor: 0.1,
  phase: "power",
  result_id: "blocked-a",
  platform_id: "duckdb",
  query_id: "Q1",
  display_ms: 10,
  is_valid_display_timing: true,
  timing_exclusion_reason: null,
};

describe("BenchmarkIndex visible disabled reasons accessibility", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearDuckdbQueryCachesForTests();
    window.history.replaceState(null, "", "/results/tpch/");
    vi.mocked(queryRows).mockImplementation(async (sql: string) => {
      const normalized = String(sql).replace(/\s+/g, " ").trim();
      if (normalized.includes("FROM bench.results")) return [ROW];
      if (normalized.includes("FROM bench.benchmark_rankings")) return [RANKING_ROW];
      if (normalized.startsWith("SELECT benchmark, scale_factor, phase, result_id, platform_id, query_id")) {
        return [CELL_ROW];
      }
      if (normalized.startsWith("SELECT result_id, phase, duration_s FROM bench.result_phase_durations")) return [];
      return [];
    });
  });

  it("keeps zero-selectable benchmark matrix reasons accessible", async () => {
    const { container } = render(<BenchmarkIndex benchmark="tpch" />);

    await waitFor(() => expect(screen.getByTestId("benchmark-zero-selectable")).toBeTruthy());
    expect(screen.getAllByTestId("query-heatmap-disabled-reason").length).toBeGreaterThan(0);
    await expectNoAxeViolations(container);
  });
});
