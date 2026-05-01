/**
 * Tests for Compare page.
 *
 * Cases:
 *   (a) Summary cards and breakdown table "vs slowest" values agree for the same row
 *   (b) For a tpch benchmark (power_score primary), Compare shows power_score,
 *       not geomean_ms, as the primary metric label
 *   (c) For a clickbench benchmark (display_geomean_ms primary), Compare shows
 *       geomean as the primary label
 *   (d) Baseline selector changes which result is treated as baseline in chart section
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/preact";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { route } from "preact-router";
import type { DetailResult } from "@/types";

// ---------------------------------------------------------------------------
// Mock manifest module
// ---------------------------------------------------------------------------

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
  };
});

import { getDetailResult, getPrimaryMetricForBenchmark, resolveShortId } from "@/lib/duckdbQueries";
import { Compare } from "@/pages/Compare";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeResult(overrides: Partial<DetailResult> = {}): DetailResult {
  return {
    result_id: "r1",
    benchmark: "tpch",
    scale_factor: 0.1,
    platform: "DuckDB",
    platform_id: "duckdb",
    driver_version: null,
    run_date: "2026-04-01",
    total_duration_s: 60,
    geomean_ms: 10,
    display_geomean_ms: 10,
    power_score: 3000,
    environment: {},
    queries: [],
    display_timings: [
      { query_id: "Q1", display_ms: 10, sample_count: 3 },
      { query_id: "Q2", display_ms: 20, sample_count: 3 },
    ],
    has_plans: false,
    has_tuning: false,
    bundle_download_url: "",
    trust_label: "maintainer-run",
    visibility: "public-curated",
    platform_version: null,
    execution_mode: null,
    tuning_mode: null,
    tuning_hash: null,
    test_type: null,
    validation_status: null,
    compliance_class: null,
    cost_usd: null,
    ...overrides,
  };
}

const DUCKDB = makeResult({
  result_id: "r1",
  platform: "DuckDB",
  display_geomean_ms: 10,
  power_score: 3000,
});

const SQLITE = makeResult({
  result_id: "r2",
  platform: "SQLite",
  platform_id: "sqlite",
  display_geomean_ms: 100,
  power_score: 300,
  display_timings: [
    { query_id: "Q1", display_ms: 100, sample_count: 3 },
    { query_id: "Q2", display_ms: 200, sample_count: 3 },
  ],
});

function setupUrl(ids: string[], extraParams: Record<string, string> = {}) {
  const params = new URLSearchParams({ ids: ids.join(","), ...extraParams });
  window.history.replaceState(null, "", `/results/compare?${params.toString()}`);
}

beforeEach(() => {
  vi.clearAllMocks();
  setupUrl(["r1", "r2"]);
  vi.mocked(resolveShortId).mockImplementation((id) => Promise.resolve(id));
  vi.mocked(getPrimaryMetricForBenchmark).mockResolvedValue("power_score");
  vi.mocked(getDetailResult).mockImplementation((id) =>
    id === "r1" ? Promise.resolve(DUCKDB) : Promise.resolve(SQLITE)
  );
});

// ---------------------------------------------------------------------------
// (a) Summary card "vs worst" value agrees with breakdown table Δ fastest
// ---------------------------------------------------------------------------

describe("Compare", () => {
  it("redirects a single compare ID to its result detail page", async () => {
    setupUrl(["a556e716"]);
    vi.mocked(resolveShortId).mockResolvedValue("tpch-duckdb-sf0.01-20260403-7fe93365");

    render(<Compare />);

    await waitFor(() =>
      expect(route).toHaveBeenCalledWith(
        "/results/r/tpch-duckdb-sf0.01-20260403-7fe93365",
        true,
      ),
    );
    expect(getDetailResult).toHaveBeenCalledWith("tpch-duckdb-sf0.01-20260403-7fe93365");
  });

  it("keeps a single unknown compare ID on the Compare error path", async () => {
    setupUrl(["does-not-exist"]);
    vi.mocked(getDetailResult).mockResolvedValue(null);

    render(<Compare />);

    await waitFor(() =>
      expect(screen.getByText(/No result found for: does-not-exist/)).toBeTruthy(),
    );
    expect(route).not.toHaveBeenCalled();
  });

  it("keeps the empty ids error on the Compare page", async () => {
    setupUrl([]);

    render(<Compare />);

    await waitFor(() =>
      expect(screen.getByText(/No result IDs provided/)).toBeTruthy(),
    );
    expect(route).not.toHaveBeenCalled();
  });

  it("shows 'vs worst' speedup of 10.00x in the DuckDB summary card (power_score primary)", async () => {
    // DUCKDB power_score=3000, SQLITE power_score=300 → DuckDB vs worst = 3000/300 = 10.00x
    render(<Compare />);
    await waitFor(() => {
      expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);
    });
    await waitFor(() => expect(document.title).toBe("Compare (2) · BenchBox Results"));
    // The summary card dt label
    expect(screen.getAllByText(/vs worst/i).length).toBeGreaterThan(0);
    // The computed ratio: 10.00x
    expect(screen.getAllByText("10.00x").length).toBeGreaterThan(0);
  });

  it("summary card speedup and breakdown table Δ fastest are consistent for 2-platform fixture", async () => {
    // DUCKDB Q1=10ms, Q2=20ms; SQLITE Q1=100ms, Q2=200ms → per-query Δ fastest = 10.00x for both
    // DuckDB summary card: power_score 3000 vs worst 300 → 10.00x
    render(<Compare />);
    await waitFor(() => {
      expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);
    });
    // Both the summary card and breakdown table show 10.00x - count must be ≥2
    const cells = screen.getAllByText("10.00x");
    expect(cells.length).toBeGreaterThanOrEqual(2);
  });

  // -----------------------------------------------------------------------
  // (b) tpch: power_score is primary
  // -----------------------------------------------------------------------
  it("shows 'Power score' as the primary metric label for tpch", async () => {
    render(<Compare />);
    // Wait until data has loaded - results appear as card headings
    await waitFor(() => {
      const spans = screen.getAllByText("DuckDB");
      // At least one span (card heading) must be present
      expect(spans.length).toBeGreaterThan(0);
    });
    // Primary label should be "Power score" (not "Geomean query time")
    const labels = screen.getAllByText(/Power score/i);
    expect(labels.length).toBeGreaterThan(0);
  });

  it("ignores metric URL params and uses the canonical benchmark metric", async () => {
    setupUrl(["r1", "r2"], { metric: "display_geomean_ms" });

    render(<Compare />);

    await waitFor(() => {
      expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);
    });
    expect(getPrimaryMetricForBenchmark).toHaveBeenCalledWith("tpch");
    const labels = screen.getAllByText(/Power score/i);
    expect(labels.length).toBeGreaterThan(0);
  });

  it("shows a secondary Geomean row when power_score is primary", async () => {
    render(<Compare />);
    await waitFor(() => {
      expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);
    });
    // The secondary geomean row should also be present in the cards
    const geomeans = screen.getAllByText(/Geomean/i);
    expect(geomeans.length).toBeGreaterThan(0);
  });

  // -----------------------------------------------------------------------
  // (c) clickbench: display_geomean_ms is primary
  // -----------------------------------------------------------------------

  it("shows 'Geomean query time' as the primary label for clickbench", async () => {
    const cbDuck = makeResult({ result_id: "r1", benchmark: "clickbench", platform: "DuckDB" });
    const cbSq = makeResult({
      result_id: "r2",
      benchmark: "clickbench",
      platform: "SQLite",
      platform_id: "sqlite",
    });
    vi.mocked(getDetailResult).mockImplementation((id) =>
      id === "r1" ? Promise.resolve(cbDuck) : Promise.resolve(cbSq)
    );

    render(<Compare />);
    await waitFor(() => {
      expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);
    });
    const labels = screen.getAllByText(/Geomean query time/i);
    expect(labels.length).toBeGreaterThan(0);
  });

  // -----------------------------------------------------------------------
  // (d) Baseline selector changes baseline in chart section
  // -----------------------------------------------------------------------

  it("baseline selector shows both platforms as options when Normalized Speedup tab is active", async () => {
    render(<Compare />);
    await waitFor(() => {
      expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);
    });
    // Click the Normalized Speedup chart tab to reveal the baseline selector
    const speedupTab = screen.getByRole("button", { name: /Normalized Speedup/i });
    fireEvent.click(speedupTab);
    // The baseline selector should now be visible
    await waitFor(() => {
      expect(screen.getByLabelText(/Baseline/i)).toBeTruthy();
    });
    const select = screen.getByLabelText(/Baseline/i) as HTMLSelectElement;
    // Both platforms should appear as options
    const options = Array.from(select.options).map((o) => o.text);
    expect(options).toContain("DuckDB");
    expect(options).toContain("SQLite");
  });

  it("baseline selector defaults to index 0 (first platform is baseline)", async () => {
    render(<Compare />);
    await waitFor(() => {
      expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);
    });
    const speedupTab = screen.getByRole("button", { name: /Normalized Speedup/i });
    fireEvent.click(speedupTab);
    await waitFor(() => {
      expect(screen.getByLabelText(/Baseline/i)).toBeTruthy();
    });
    const select = screen.getByLabelText(/Baseline/i) as HTMLSelectElement;
    // Default baseline is index 0 (DuckDB - first result in the fixture)
    expect(select.value).toBe("0");
    expect(select.options[0]!.text).toBe("DuckDB");
  });

  it("renders the comparability receipt before charts and query breakdown", async () => {
    render(<Compare />);
    await waitFor(() => {
      expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);
    });

    const receipt = screen.getByRole("region", { name: "Comparability receipt" });
    const chartsHeading = screen.getByText("Charts");
    const queryBreakdownHeading = screen.getByRole("heading", { name: "Query Breakdown" });

    expect(receipt).toHaveTextContent("Benchmark");
    expect(receipt).toHaveTextContent("Query scope");
    expect(receipt).toHaveTextContent("Cost metadata not published");
    expect(receipt.compareDocumentPosition(chartsHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(receipt.compareDocumentPosition(queryBreakdownHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
