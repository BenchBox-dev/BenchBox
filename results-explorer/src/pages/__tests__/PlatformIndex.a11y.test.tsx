import { render, screen, waitFor } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/testing/axe-helper";
import type { PlatformIndexRowRow } from "@/lib/duckdbQueries";

vi.mock("@/lib/duckdbQueries", async () => {
  const actual = await vi.importActual<typeof import("@/lib/duckdbQueries")>("@/lib/duckdbQueries");
  return {
    ...actual,
    getPlatformIndexRows: vi.fn(),
  };
});

vi.mock("preact-router", async () => {
  const actual = await vi.importActual<typeof import("preact-router")>("preact-router");
  return {
    ...actual,
    route: vi.fn(),
  };
});

import { getPlatformIndexRows } from "@/lib/duckdbQueries";
import { PlatformIndex } from "@/pages/PlatformIndex";

function makeRow(overrides: Partial<PlatformIndexRowRow> = {}): PlatformIndexRowRow {
  return {
    result_id: "blocked-a",
    short_id: "blockeda",
    benchmark: "tpch",
    scale_factor: 0.1,
    phase: "power",
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
    funding: "unspecified",
    validation_status: "exact",
    tuning_mode: null,
    execution_mode: null,
    compliance_class: null,
    cost_usd: null,
    primary_metric: "power_score",
    ...overrides,
  };
}

describe("PlatformIndex visible disabled reasons accessibility", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getPlatformIndexRows).mockResolvedValue([
      makeRow({ result_id: "blocked-a", short_id: "blockeda" }),
      makeRow({ result_id: "blocked-b", short_id: "blockedb" }),
    ]);
  });

  it("keeps zero-selectable disabled reasons accessible", async () => {
    const { container } = render(<PlatformIndex platform="duckdb" />);

    await waitFor(() => expect(screen.getByTestId("platform-zero-selectable")).toBeTruthy());
    expect(screen.getAllByTestId("platform-disabled-reason").length).toBeGreaterThan(0);
    await expectNoAxeViolations(container);
  });
});
