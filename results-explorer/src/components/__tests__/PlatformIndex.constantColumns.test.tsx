import { fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PlatformIndexRowRow } from "@/lib/duckdbQueries";

vi.mock("@/lib/duckdbQueries", async () => {
  const actual = await vi.importActual<typeof import("@/lib/duckdbQueries")>("@/lib/duckdbQueries");
  return { ...actual, getPlatformIndexRows: vi.fn() };
});

vi.mock("preact-router", async () => {
  const actual = await vi.importActual<typeof import("preact-router")>("preact-router");
  return { ...actual, route: vi.fn() };
});

import { getPlatformIndexRows } from "@/lib/duckdbQueries";
import { PlatformIndex } from "@/pages/PlatformIndex";

function makeRow(overrides: Partial<PlatformIndexRowRow> = {}): PlatformIndexRowRow {
  return {
    result_id: "r-base",
    short_id: "base0001",
    benchmark: "tpch",
    scale_factor: 0.1,
    phase: "power",
    platform: "DuckDB",
    platform_id: "duckdb",
    driver_version: null,
    run_date: "2026-04-01",
    power_score: 3000,
    total_duration_s: 60,
    geomean_ms: 15,
    display_geomean_ms: 12,
    query_count: 22,
    has_display_timing: true,
    valid_query_count: 22,
    missing_query_count: 0,
    zero_timing_count: 0,
    display_exclusion_reason: null,
    comparison_exclusion_reason: null,
    ranking_exclusion_reason: null,
    trust_label: "maintainer-run",
    funding: "unspecified",
    validation_status: "exact",
    tuning_mode: null,
    execution_mode: null,
    compliance_class: null,
    cost_usd: null,
    normalized_cost_usd: null,
    cost_status: "not_applicable_local",
    cost_scope: null,
    cost_model_version: null,
    deployment_class: "local",
    cloud_provider: null,
    cloud_region: null,
    instance_or_warehouse: null,
    warehouse_size: null,
    storage_format: null,
    primary_metric: "display_geomean_ms",
    ...overrides,
  };
}

function rowCount(table: ParentNode): number {
  return table.querySelectorAll("tbody tr[data-testid]").length;
}

describe("PlatformIndex route-constant columns", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState(null, "", "/results/p/duckdb/");
  });

  it("hoists a route-wide metric contract while retaining the sparse power score column", async () => {
    vi.mocked(getPlatformIndexRows).mockResolvedValue([
      makeRow({ result_id: "r-power", power_score: 5000 }),
      makeRow({ result_id: "r-no-power", power_score: null }),
    ]);
    render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());

    const table = screen.getByRole("table", { name: "DuckDB results" });
    expect(table).toHaveAttribute("aria-colcount", "10");
    expect(screen.getByTestId("platform-hoisted-metric-contract")).toHaveTextContent(
      "Route-wide metric contract: Geomean latency (lower is better)",
    );
    expect(within(table).queryByRole("columnheader", { name: "Metric contract" })).toBeNull();
    expect(within(table).getByRole("button", { name: /Power score/ }).closest("th")).toHaveAttribute(
      "aria-colindex",
      "7",
    );
    expect(within(table).getByText("5,000")).toBeTruthy();
  });

  it("does not hoist a column that becomes constant only after filtering", async () => {
    const routeRows = Array.from({ length: 25 }, (_, index) =>
      makeRow({
        result_id: `r-filter-${index}`,
        short_id: `filter${String(index).padStart(2, "0")}`,
        benchmark: index < 13 ? "tpch" : "star_schema",
        primary_metric: index < 13 ? "display_geomean_ms" : "power_score",
        power_score: index === 0 ? 1234 : null,
      }),
    );
    vi.mocked(getPlatformIndexRows).mockResolvedValue(routeRows);
    render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());

    const table = screen.getByRole("table", { name: "DuckDB results" });
    const powerHeader = within(table).getByRole("button", { name: /Power score/ }).closest("th");
    expect(table).toHaveAttribute("aria-colcount", "11");
    expect(within(table).getByRole("columnheader", { name: "Metric contract" })).toBeTruthy();
    expect(powerHeader).toHaveAttribute("aria-colindex", "8");

    fireEvent.change(screen.getByLabelText("Benchmark"), { target: { value: "tpch" } });
    await waitFor(() => expect(rowCount(table)).toBe(13));
    expect(within(table).getByRole("columnheader", { name: "Metric contract" })).toBeTruthy();
    expect(powerHeader).toHaveAttribute("aria-colindex", "8");
    expect(within(table).getByText("1,234")).toBeTruthy();
  });
});
