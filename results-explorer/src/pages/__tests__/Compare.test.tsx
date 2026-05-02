/**
 * Tests for Compare page.
 *
 * Cases:
 *   (a) Summary cards and query diff table values agree for the same row
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

import { getDetailResult, getPrimaryMetricForBenchmark, resolveShortId, toShortIds } from "@/lib/duckdbQueries";
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

const POSTGRES = makeResult({
  result_id: "r3",
  platform: "PostgreSQL",
  platform_id: "postgresql",
  display_geomean_ms: 50,
  power_score: 1000,
  display_timings: [
    { query_id: "Q1", display_ms: 50, sample_count: 3 },
    { query_id: "Q2", display_ms: 80, sample_count: 3 },
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
// (a) Summary card "vs worst" value agrees with query diff evidence
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

  it("renders a computed decision summary before charts and query evidence", async () => {
    render(<Compare />);
    await waitFor(() => {
      expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);
    });

    const summary = screen.getByRole("heading", { name: "Decision Summary" });
    const chartsHeading = screen.getByText("Charts");
    const queryDiffHeading = screen.getByRole("heading", { name: "Query-Level Diff" });

    expect(summary.closest("section")).toHaveTextContent("DuckDB leads by 10.00x on power score.");
    expect(summary.closest("section")).toHaveTextContent("2/2 fastest");
    expect(summary.compareDocumentPosition(chartsHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(summary.compareDocumentPosition(queryDiffHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(queryDiffHeading.compareDocumentPosition(chartsHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("omits summary cost context when normalized costs are absent", async () => {
    render(<Compare />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Decision Summary" })).toBeTruthy();
    });

    const summary = screen.getByRole("heading", { name: "Decision Summary" }).closest("section");
    expect(summary).not.toHaveTextContent("Cost/performance:");
  });

  it("renders normalized cost/performance context when cost fields are available", async () => {
    const duckdb = makeResult({
      result_id: "r1",
      platform: "DuckDB",
      normalized_cost_usd: 0.5,
      cost_status: "normalized",
    });
    const sqlite = makeResult({
      result_id: "r2",
      platform: "SQLite",
      platform_id: "sqlite",
      power_score: 300,
      display_timings: SQLITE.display_timings,
      normalized_cost_usd: 1.5,
      cost_status: "normalized",
    });
    vi.mocked(getDetailResult).mockImplementation((id) =>
      id === "r1" ? Promise.resolve(duckdb) : Promise.resolve(sqlite),
    );

    render(<Compare />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Decision Summary" })).toBeTruthy();
    });

    const summary = screen.getByRole("heading", { name: "Decision Summary" }).closest("section");
    expect(summary).toHaveTextContent("Cost/performance:");
    expect(summary).toHaveTextContent("winner cost $0.50");
    expect(summary).toHaveTextContent("30.00x cost/performance");
  });

  it("keeps missing query evidence visible in the summary and query diff table", async () => {
    const missingSqlite = makeResult({
      result_id: "r2",
      platform: "SQLite",
      platform_id: "sqlite",
      power_score: 300,
      display_timings: [
        { query_id: "Q1", display_ms: 100, sample_count: 3 },
        { query_id: "Q3", display_ms: 300, sample_count: 3 },
      ],
    });
    vi.mocked(getDetailResult).mockImplementation((id) =>
      id === "r1" ? Promise.resolve(DUCKDB) : Promise.resolve(missingSqlite),
    );

    render(<Compare />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Decision Summary" })).toBeTruthy();
    });

    const summary = screen.getByRole("heading", { name: "Decision Summary" }).closest("section");
    const queryDiff = screen.getByRole("heading", { name: "Query-Level Diff" }).closest("section");
    expect(summary).toHaveTextContent("1/1 fastest");
    expect(summary).toHaveTextContent("2 missing");
    expect(queryDiff).toHaveTextContent("3 comparisons");
    expect(queryDiff).toHaveTextContent("Missing");
  });

  it("summary card speedup and query diff ratio are consistent for 2-platform fixture", async () => {
    // DUCKDB Q1=10ms, Q2=20ms; SQLITE Q1=100ms, Q2=200ms -> per-query ratio = 10.00x for both
    // DuckDB summary card: power_score 3000 vs worst 300 → 10.00x
    render(<Compare />);
    await waitFor(() => {
      expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);
    });
    // Both the summary card and query diff table show 10.00x.
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

  it("preserves facet URL params when canonicalizing long compare IDs", async () => {
    setupUrl(["tpch-duckdb-long-id", "tpch-sqlite-long-id"], {
      benchmark: "tpch",
      cost_status: "normalized",
    });
    vi.mocked(resolveShortId).mockImplementation((id) =>
      Promise.resolve(id.includes("duckdb") ? "r1" : "r2"),
    );
    vi.mocked(toShortIds).mockResolvedValue(["short1", "short2"]);

    render(<Compare />);

    await waitFor(() =>
      expect(new URL(window.location.href).searchParams.get("ids")).toBe("short1,short2"),
    );
    const params = new URL(window.location.href).searchParams;
    expect(params.get("benchmark")).toBe("tpch");
    expect(params.get("cost_status")).toBe("normalized");
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

  it("baseline selector updates query diffs and chart baseline without changing compare URL membership", async () => {
    render(<Compare />);
    await waitFor(() => {
      expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);
    });

    const beforeIds = new URL(window.location.href).searchParams.get("ids");
    const select = screen.getByLabelText("Baseline") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "1" } });

    const diffTable = screen.getByRole("heading", { name: "Query-Level Diff" }).closest("section");
    expect(select.value).toBe("1");
    expect(diffTable).toHaveTextContent("Baseline: SQLite");
    expect(diffTable).toHaveTextContent("DuckDB");
    expect(diffTable).toHaveTextContent("0.10x");
    expect(new URL(window.location.href).searchParams.get("ids")).toBe(beforeIds);
    expect(screen.getAllByText("SQLite").length).toBeGreaterThan(0);
  });

  it("supports three-result compare and baseline switching without changing URL membership", async () => {
    setupUrl(["r1", "r2", "r3"]);
    vi.mocked(getDetailResult).mockImplementation((id) => {
      if (id === "r1") return Promise.resolve(DUCKDB);
      if (id === "r2") return Promise.resolve(SQLITE);
      if (id === "r3") return Promise.resolve(POSTGRES);
      return Promise.resolve(null);
    });

    render(<Compare />);
    await waitFor(() => {
      expect(screen.getAllByText("PostgreSQL").length).toBeGreaterThan(0);
    });

    await waitFor(() => expect(document.title).toBe("Compare (3) · BenchBox Results"));
    const summary = screen.getByRole("heading", { name: "Decision Summary" }).closest("section");
    const select = screen.getByLabelText("Baseline") as HTMLSelectElement;
    const options = Array.from(select.options).map((option) => option.text);
    const beforeIds = new URL(window.location.href).searchParams.get("ids");

    expect(summary).toHaveTextContent("DuckDB leads by 10.00x on power score.");
    expect(options).toEqual(["DuckDB", "SQLite", "PostgreSQL"]);
    expect(screen.getByRole("heading", { name: "Query-Level Diff" }).closest("section")).toHaveTextContent(
      "4 comparisons",
    );

    fireEvent.change(select, { target: { value: "2" } });

    const queryDiff = screen.getByRole("heading", { name: "Query-Level Diff" }).closest("section");
    expect(select.value).toBe("2");
    expect(queryDiff).toHaveTextContent("Baseline: PostgreSQL");
    expect(queryDiff).toHaveTextContent("DuckDB");
    expect(queryDiff).toHaveTextContent("SQLite");
    expect(new URL(window.location.href).searchParams.get("ids")).toBe(beforeIds);
  });

  it("renders severe cohort mismatches with guardrails and no winner claim", async () => {
    const clickbench = makeResult({
      result_id: "r2",
      benchmark: "clickbench",
      scale_factor: 1,
      platform: "SQLite",
      platform_id: "sqlite",
      power_score: 300,
      display_timings: [
        { query_id: "Q1", display_ms: 100, sample_count: 3 },
        { query_id: "Q2", display_ms: 200, sample_count: 3 },
      ],
    });
    vi.mocked(getDetailResult).mockImplementation((id) =>
      id === "r1" ? Promise.resolve(DUCKDB) : Promise.resolve(clickbench),
    );

    render(<Compare />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Decision Summary" })).toBeTruthy();
    });

    expect(screen.queryByText(/Cannot compare results from different benchmarks/)).toBeNull();
    const receipt = screen.getByRole("region", { name: "Comparability receipt" });
    const summary = screen.getByRole("heading", { name: "Decision Summary" }).closest("section");
    expect(receipt).toHaveTextContent("Benchmark");
    expect(receipt).toHaveTextContent("Scale factor");
    expect(summary).toHaveTextContent("Not directly comparable: benchmarks differ and scale factors differ.");
    expect(summary).toHaveTextContent("Claims suppressed");
    expect(summary).not.toHaveTextContent("DuckDB leads by");
    expect(summary).not.toHaveTextContent("fastest");
    expect(screen.queryByText("vs worst")).toBeNull();
    expect(screen.getByRole("heading", { name: "Query-Level Diff" })).toBeTruthy();
  });

  it("renders the comparability receipt before charts and query diff evidence", async () => {
    render(<Compare />);
    await waitFor(() => {
      expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);
    });

    const receipt = screen.getByRole("region", { name: "Comparability receipt" });
    const chartsHeading = screen.getByText("Charts");
    const queryDiffHeading = screen.getByRole("heading", { name: "Query-Level Diff" });

    expect(receipt).toHaveTextContent("Benchmark");
    expect(receipt).toHaveTextContent("Query scope");
    expect(receipt).toHaveTextContent("Cost metadata not published");
    expect(receipt.compareDocumentPosition(chartsHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(receipt.compareDocumentPosition(queryDiffHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows compare receipt warnings for tuning and environment differences", async () => {
    const duckdb = makeResult({
      result_id: "r1",
      platform: "DuckDB",
      platform_id: "duckdb",
      driver_version: "1.0",
      environment: { os: "Linux", arch: "x64", cpu_count: 8 },
      tuning_mode: "default",
    });
    const sqlite = makeResult({
      result_id: "r2",
      platform: "SQLite",
      platform_id: "sqlite",
      driver_version: "2.0",
      environment: { os: "macOS", arch: "arm64", cpu_count: 10 },
      tuning_mode: "manual",
    });
    vi.mocked(getDetailResult).mockImplementation((id) =>
      id === "r1" ? Promise.resolve(duckdb) : Promise.resolve(sqlite)
    );

    render(<Compare />);
    await waitFor(() => {
      expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0);
    });

    const receipt = screen.getByRole("region", { name: "Comparability receipt" });
    expect(receipt).toHaveTextContent("Tuning");
    expect(receipt).toHaveTextContent("DuckDB: default; SQLite: manual");
    expect(receipt).toHaveTextContent("Environment");
    expect(receipt).toHaveTextContent("DuckDB: Linux, x64, 8 CPU");
    expect(receipt).toHaveTextContent("SQLite: macOS, arm64, 10 CPU");
  });
});
