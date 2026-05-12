import { render, screen, waitFor } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/testing/axe-helper";
import type { ResultRow } from "@/lib/duckdbQueries";

vi.mock("preact-router", () => ({
  route: vi.fn(),
}));

vi.mock("@/lib/duckdbQueries", async () => {
  const actual = await vi.importActual<typeof import("@/lib/duckdbQueries")>("@/lib/duckdbQueries");
  return {
    ...actual,
    getDetailResult: vi.fn(),
    resolveShortId: vi.fn((id: string) => Promise.resolve(id)),
    toShortIds: vi.fn((ids: string[]) => Promise.resolve(ids)),
    getPrimaryMetricForBenchmark: vi.fn().mockResolvedValue("power_score"),
    listResults: vi.fn(),
  };
});

import { listResults } from "@/lib/duckdbQueries";
import { Compare } from "@/pages/Compare";

function makeRow(overrides: Partial<ResultRow> = {}): ResultRow {
  return {
    result_id: "blocked-a",
    benchmark: "tpch",
    scale_factor: 0.1,
    platform: "DuckDB",
    platform_id: "duckdb",
    driver_version: null,
    run_date: "2026-04-17",
    power_score: null,
    total_duration_s: 60,
    geomean_ms: null,
    display_geomean_ms: null,
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
    compliance_class: null,
    is_ranking_eligible: false,
    has_plans: false,
    plans_published: false,
    has_tuning: false,
    bundle_download_url: "",
    ...overrides,
  };
}

describe("Compare visible disabled reasons accessibility", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState(null, "", "/results/compare");
    vi.mocked(listResults).mockResolvedValue([
      makeRow({ result_id: "blocked-a", platform: "DuckDB" }),
      makeRow({ result_id: "blocked-b", platform: "SQLite" }),
    ]);
  });

  it("keeps zero-selectable disabled reasons accessible", async () => {
    const { container } = render(<Compare />);

    await waitFor(() => expect(screen.getByTestId("compare-builder-zero-selectable")).toBeTruthy());
    expect(screen.getAllByTestId("compare-disabled-reason").length).toBeGreaterThan(0);
    await expectNoAxeViolations(container);
  });
});
