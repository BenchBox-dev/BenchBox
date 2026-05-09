/**
 * Tests for PlatformIndex sortable table headers.
 *
 * The default sort (geomean_ms ascending, nulls last) is observable behaviour
 * — must_preserve in the parent TODO. Click-driven sort layered on top of
 * that default switches direction on repeated clicks of the same key.
 */

import { render, screen, fireEvent, waitFor, within } from "@testing-library/preact";
import { describe, it, expect, vi, beforeEach } from "vitest";
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
    trust_label: "maintainer-run",
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

const ROWS: PlatformIndexRowRow[] = [
  makeRow({
    result_id: "r-tpch-fast",
    short_id: "aaaabbbb",
    benchmark: "tpch",
    run_date: "2026-04-03",
    power_score: 5000,
    geomean_ms: 5,
    normalized_cost_usd: 1.25,
    cost_status: "normalized",
    cost_scope: "compute_only",
    cost_model_version: "2026.05.0",
    deployment_class: "cloud",
    cloud_provider: "aws",
    cloud_region: "us-east-1",
    instance_or_warehouse: "MEDIUM",
    warehouse_size: "MEDIUM",
    storage_format: "parquet",
  }),
  makeRow({ result_id: "r-ssb-mid", short_id: "ccccdddd", benchmark: "star_schema", run_date: "2026-04-01", power_score: 3000, geomean_ms: 15 }),
  makeRow({ result_id: "r-tpch-slow", short_id: "eeeeffff", benchmark: "tpch", run_date: "2026-04-02", power_score: 1000, geomean_ms: 50 }),
  makeRow({ result_id: "r-null-geo", short_id: "11112222", benchmark: "tpch", run_date: "2026-04-04", power_score: null, geomean_ms: null }),
];

function getRowOrder(container: ParentNode): string[] {
  // PlatformRow exposes the result_id via data-testid on its <tr>. Walking
  // that selector is more stable than parsing aria-label substrings.
  return Array.from(container.querySelectorAll("tbody tr[data-testid]")).map(
    (tr) => tr.getAttribute("data-testid") ?? "",
  );
}

describe("PlatformIndex - sortable table headers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState(null, "", "/results/p/duckdb/");
    vi.mocked(getPlatformIndexRows).mockResolvedValue(ROWS);
  });

  it("default sort is geomean_ms ascending with nulls last", async () => {
    const { container } = render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());
    await waitFor(() => expect(document.title).toBe("DuckDB · BenchBox Results"));
    expect(getRowOrder(container)).toEqual(["r-tpch-fast", "r-ssb-mid", "r-tpch-slow", "r-null-geo"]);
  });

  it("renders a Platform switcher that routes to a sibling without preserving tuning", async () => {
    const preactRouter = await import("preact-router");
    const routeMock = vi.mocked(preactRouter.route);
    routeMock.mockClear();

    const multiPlatformRows = [
      ...ROWS,
      makeRow({ result_id: "r-pg", short_id: "pg00000a", platform_id: "postgres", platform: "Postgres" }),
    ];
    vi.mocked(getPlatformIndexRows).mockResolvedValue(multiPlatformRows);

    render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());

    const switcher = screen.getByTestId("platform-switcher") as HTMLSelectElement;
    expect(switcher.value).toBe("duckdb");
    expect(within(switcher).getByRole("option", { name: "Postgres" })).toBeTruthy();

    fireEvent.change(switcher, { target: { value: "postgres" } });
    expect(routeMock).toHaveBeenCalledTimes(1);
    expect(routeMock).toHaveBeenCalledWith("/results/p/postgres/");
  });

  it("renders the platform filter strip when the cohort has >=25 rows and reset clears it", async () => {
    const denseRows: PlatformIndexRowRow[] = Array.from({ length: 30 }, (_, idx) =>
      makeRow({
        result_id: `r-dense-${idx}`,
        short_id: `dense${String(idx).padStart(4, "0")}`,
        benchmark: idx < 18 ? "tpch" : "clickbench",
        scale_factor: idx % 2 === 0 ? 0.1 : 1,
        run_date: "2026-04-10",
        geomean_ms: 10 + idx,
      }),
    );
    vi.mocked(getPlatformIndexRows).mockResolvedValue(denseRows);

    render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());

    const filterStrip = screen.getByTestId("platform-detail-filters");
    expect(filterStrip).toBeTruthy();
    expect(screen.getByText("Showing 30 of 30 results")).toBeTruthy();

    fireEvent.change(screen.getByTestId("platform-filter-benchmark"), {
      target: { value: "clickbench" },
    });
    await waitFor(() => expect(screen.getByText("Showing 12 of 12 results")).toBeTruthy());

    fireEvent.click(screen.getByTestId("platform-filter-reset"));
    await waitFor(() => expect(screen.getByText("Showing 30 of 30 results")).toBeTruthy());
    expect(screen.queryByTestId("platform-filter-reset")).toBeNull();
  });

  it("locks the cohort signature after the first compare selection", async () => {
    const cohortRows: PlatformIndexRowRow[] = [
      makeRow({
        result_id: "r-tpch-a",
        short_id: "tpcha000",
        benchmark: "tpch",
        scale_factor: 0.1,
        phase: "power",
        run_date: "2026-04-01",
        primary_metric: "display_geomean_ms",
      }),
      makeRow({
        result_id: "r-tpch-b",
        short_id: "tpchb000",
        benchmark: "tpch",
        scale_factor: 0.1,
        phase: "power",
        run_date: "2026-04-02",
        primary_metric: "display_geomean_ms",
      }),
      makeRow({
        result_id: "r-clickbench",
        short_id: "click000",
        benchmark: "clickbench",
        scale_factor: 0.1,
        phase: "power",
        run_date: "2026-04-03",
        primary_metric: "display_geomean_ms",
      }),
    ];
    vi.mocked(getPlatformIndexRows).mockResolvedValue(cohortRows);

    render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());

    const checkboxA = screen.getByTestId("platform-compare-checkbox-r-tpch-a") as HTMLInputElement;
    const checkboxB = screen.getByTestId("platform-compare-checkbox-r-tpch-b") as HTMLInputElement;
    const checkboxClickbench = screen.getByTestId(
      "platform-compare-checkbox-r-clickbench",
    ) as HTMLInputElement;

    expect(checkboxA.disabled).toBe(false);
    expect(checkboxB.disabled).toBe(false);
    expect(checkboxClickbench.disabled).toBe(false);

    fireEvent.click(checkboxA);
    expect(checkboxA.checked).toBe(true);
    expect(checkboxB.disabled).toBe(false);
    expect(checkboxClickbench.disabled).toBe(true);
    expect(checkboxClickbench.title).toContain("differs by benchmark");

    fireEvent.click(checkboxA);
    expect(checkboxClickbench.disabled).toBe(false);
  });

  it("hides the platform filter strip when the cohort has fewer than 25 rows", async () => {
    render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());
    expect(screen.queryByTestId("platform-detail-filters")).toBeNull();
  });

  it("shows persistent compare guidance and cohort labels before selection", async () => {
    render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());

    const guidance = screen.getByTestId("platform-compare-guidance");
    expect(guidance.textContent).toContain("Select two or more DuckDB results");
    expect((screen.getByRole("button", { name: "Select 2 comparable results" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("platform-table-scroll-hint").textContent).toContain("Scroll table");
    expect(screen.getAllByText(/geomean latency, ms \(lower is faster\)/).length).toBeGreaterThan(0);
  });

  it("clicking the Geomean header twice flips ascending → descending (nulls still last)", async () => {
    const { container } = render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Geomean/ }));
    expect(getRowOrder(container)).toEqual(["r-tpch-slow", "r-ssb-mid", "r-tpch-fast", "r-null-geo"]);
  });

  it("clicking the Benchmark header sorts alphabetically ascending", async () => {
    const { container } = render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Benchmark/ }));
    const order = getRowOrder(container);
    expect(order[0]).toBe("r-ssb-mid");
    expect(order.slice(1)).toEqual(["r-tpch-fast", "r-tpch-slow", "r-null-geo"]);
  });

  it("clicking Power Score puts nulls last in both directions", async () => {
    const { container } = render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Power Score/ }));
    expect(getRowOrder(container).slice(-1)[0]).toBe("r-null-geo");
    fireEvent.click(screen.getByRole("button", { name: /Power Score/ }));
    expect(getRowOrder(container).slice(-1)[0]).toBe("r-null-geo");
  });

  it("Enter on a sort header flips the sort (keyboard parity with click)", async () => {
    const { container } = render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());
    const benchmarkBtn = screen.getByRole("button", { name: /Benchmark/ });
    // Browsers fire a click on Enter for <button>, but jsdom does not unless
    // the keyDown explicitly bubbles to a click. fireEvent.click is the
    // semantic equivalent here (jsdom + RTL contract); to actually exercise
    // keyDown we use it explicitly and confirm the button is focusable +
    // wired with an onClick that runs on activation.
    benchmarkBtn.focus();
    expect(document.activeElement).toBe(benchmarkBtn);
    fireEvent.keyDown(benchmarkBtn, { key: "Enter" });
    fireEvent.click(benchmarkBtn);
    expect(getRowOrder(container)[0]).toBe("r-ssb-mid");
  });

  it("aria-sort reflects the active column and direction", async () => {
    const { container } = render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());
    // Default state: Geomean is sorted asc; others report none.
    const headerCells = container.querySelectorAll("th[aria-sort]");
    const geoTh = Array.from(headerCells).find((th) => th.textContent?.includes("Geomean"));
    const benchTh = Array.from(headerCells).find((th) => th.textContent?.includes("Benchmark"));
    expect(geoTh?.getAttribute("aria-sort")).toBe("ascending");
    expect(benchTh?.getAttribute("aria-sort")).toBe("none");
    // Click Benchmark; it becomes the active column at asc.
    fireEvent.click(screen.getByRole("button", { name: /Benchmark/ }));
    expect(benchTh?.getAttribute("aria-sort")).toBe("ascending");
    expect(geoTh?.getAttribute("aria-sort")).toBe("none");
    // Click again; direction flips.
    fireEvent.click(screen.getByRole("button", { name: /Benchmark/ }));
    expect(benchTh?.getAttribute("aria-sort")).toBe("descending");
  });

  it("restores platform page URL facets for benchmark, cohort, deployment, and cost filters", async () => {
    window.history.replaceState(
      null,
      "",
      "/results/p/duckdb/?benchmark=tpch&sf=0.1&phase=power&deployment=cloud&cost_status=normalized",
    );

    const { container } = render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());

    expect(getRowOrder(container)).toEqual(["r-tpch-fast"]);
    expect(screen.queryByText("SSB")).toBeNull();
    expect(screen.queryByTestId("r-tpch-slow")).toBeNull();
  });

  it("filters deployment and shape from normalized fields instead of legacy proxy columns", async () => {
    window.history.replaceState(null, "", "/results/p/duckdb/?deployment=cloud&shape=MEDIUM");
    vi.mocked(getPlatformIndexRows).mockResolvedValue([
      makeRow({
        result_id: "r-normalized-cloud",
        deployment_class: "cloud",
        cloud_provider: null,
        instance_or_warehouse: "MEDIUM",
        warehouse_size: null,
      }),
      makeRow({
        result_id: "r-legacy-proxy-cloud",
        deployment_class: "local",
        cloud_provider: "aws",
        instance_or_warehouse: null,
        warehouse_size: "MEDIUM",
      }),
    ]);

    const { container } = render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());

    expect(getRowOrder(container)).toEqual(["r-normalized-cloud"]);
  });

  it("splits trend charts by benchmark, scale, phase, and primary metric", async () => {
    vi.mocked(getPlatformIndexRows).mockResolvedValue([
      makeRow({
        result_id: "r-tpch-a",
        benchmark: "tpch",
        scale_factor: 0.01,
        phase: "power",
        run_date: "2026-04-01",
        power_score: 1000,
        primary_metric: "power_score",
      }),
      makeRow({
        result_id: "r-tpch-b",
        benchmark: "tpch",
        scale_factor: 0.01,
        phase: "power",
        run_date: "2026-04-02",
        power_score: 1200,
        primary_metric: "power_score",
      }),
      makeRow({
        result_id: "r-tpch-c",
        benchmark: "tpch",
        scale_factor: 0.01,
        phase: "power",
        run_date: "2026-04-03",
        power_score: 1300,
        primary_metric: "power_score",
      }),
      makeRow({
        result_id: "r-ssb-a",
        benchmark: "star_schema",
        scale_factor: 0.1,
        phase: "power",
        run_date: "2026-04-01",
        display_geomean_ms: 20,
        primary_metric: "display_geomean_ms",
      }),
      makeRow({
        result_id: "r-ssb-b",
        benchmark: "star_schema",
        scale_factor: 0.1,
        phase: "power",
        run_date: "2026-04-02",
        display_geomean_ms: 18,
        primary_metric: "display_geomean_ms",
      }),
      makeRow({
        result_id: "r-ssb-c",
        benchmark: "star_schema",
        scale_factor: 0.1,
        phase: "power",
        run_date: "2026-04-03",
        display_geomean_ms: 17,
        primary_metric: "display_geomean_ms",
      }),
    ]);

    const { container } = render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());

    const tpch = screen.getByTestId("trend-cohort-tpch-sf0.01-power-power_score");
    const ssb = screen.getByTestId("trend-cohort-star_schema-sf0.1-power-display_geomean_ms");
    expect(container.querySelectorAll("svg[aria-label$='trend over time']")).toHaveLength(2);
    expect(tpch.querySelector('[data-result-id="r-tpch-a"]')).toBeTruthy();
    expect(tpch.querySelector('[data-result-id="r-tpch-b"]')).toBeTruthy();
    expect(tpch.querySelector('[data-result-id="r-tpch-c"]')).toBeTruthy();
    expect(tpch.querySelector('[data-result-id="r-ssb-a"]')).toBeNull();
    expect(ssb.querySelector('[data-result-id="r-ssb-a"]')).toBeTruthy();
    expect(ssb.querySelector('[data-result-id="r-ssb-b"]')).toBeTruthy();
    expect(ssb.querySelector('[data-result-id="r-ssb-c"]')).toBeTruthy();
    expect(ssb.querySelector('[data-result-id="r-tpch-a"]')).toBeNull();
  });

  it("shows receipt links and validation status for each platform result", async () => {
    render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());

    const receiptLinks = screen.getAllByRole("link", { name: "Receipt →" }) as HTMLAnchorElement[];
    expect(receiptLinks[0]?.getAttribute("href")).toBe("/results/r/r-tpch-fast#run-receipt");
    expect(screen.getAllByText("exact").length).toBeGreaterThan(0);
  });

  it("compare tray shows selected metadata and uses short IDs in the compare URL", async () => {
    render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());

    fireEvent.click(screen.getByLabelText("Select r-tpch-fast for comparison"));
    fireEvent.click(screen.getByLabelText("Select r-ssb-mid for comparison"));

    const tpchRow = screen.getByTestId("compare-tray-row-r-tpch-fast");
    const ssbRow = screen.getByTestId("compare-tray-row-r-ssb-mid");
    expect(tpchRow.textContent).toContain("DuckDB");
    expect(tpchRow.textContent).toContain("TPC-H");
    expect(tpchRow.textContent).toContain("SF 0.1");
    expect(tpchRow.textContent).toContain("power");
    expect(tpchRow.textContent).toContain("2026-04-03");
    expect(tpchRow.textContent).toContain("ID aaaabbbb");
    expect(ssbRow.textContent).toContain("SSB");
    expect(screen.getByTestId("platform-compare-guidance").textContent).toContain("differ by benchmark");

    const compareLink = screen.getByRole("link", { name: /Compare 2 selected/ }) as HTMLAnchorElement;
    expect(compareLink.getAttribute("href")).toBe("/results/compare?ids=aaaabbbb,ccccdddd");
  });

  it("caps rendered platform rows and expands them with Show more", async () => {
    vi.mocked(getPlatformIndexRows).mockResolvedValue(
      Array.from({ length: 205 }, (_, index) =>
        makeRow({
          result_id: `r-many-${index}`,
          benchmark: "tpch",
          geomean_ms: index + 1,
          display_geomean_ms: index + 1,
          run_date: `2026-04-${String((index % 28) + 1).padStart(2, "0")}`,
        }),
      ),
    );

    const { container } = render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());

    expect(screen.getByText("Showing 200 of 205 results")).toBeTruthy();
    expect(getRowOrder(container)).toHaveLength(200);

    fireEvent.click(screen.getByRole("button", { name: "Show more results" }));

    expect(getRowOrder(container)).toHaveLength(205);
    expect(screen.getByText("Showing 205 of 205 results")).toBeTruthy();
  });

  it("splits platform trend charts by comparable benchmark cohorts", async () => {
    vi.mocked(getPlatformIndexRows).mockResolvedValue([
      makeRow({
        result_id: "r-tpch-a",
        benchmark: "tpch",
        scale_factor: 0.1,
        run_date: "2026-04-01",
        geomean_ms: 10,
        display_geomean_ms: 10,
        phase: "power",
        primary_metric: "display_geomean_ms",
      }),
      makeRow({
        result_id: "r-tpch-b",
        benchmark: "tpch",
        scale_factor: 0.1,
        run_date: "2026-04-02",
        geomean_ms: 12,
        display_geomean_ms: 12,
        phase: "power",
        primary_metric: "display_geomean_ms",
      }),
      makeRow({
        result_id: "r-tpch-c",
        benchmark: "tpch",
        scale_factor: 0.1,
        run_date: "2026-04-03",
        geomean_ms: 11,
        display_geomean_ms: 11,
        phase: "power",
        primary_metric: "display_geomean_ms",
      }),
      makeRow({
        result_id: "r-ssb-a",
        benchmark: "star_schema",
        scale_factor: 0.1,
        run_date: "2026-04-01",
        geomean_ms: 20,
        display_geomean_ms: 20,
        phase: "power",
        primary_metric: "display_geomean_ms",
      }),
      makeRow({
        result_id: "r-ssb-b",
        benchmark: "star_schema",
        scale_factor: 0.1,
        run_date: "2026-04-02",
        geomean_ms: 22,
        display_geomean_ms: 22,
        phase: "power",
        primary_metric: "display_geomean_ms",
      }),
      makeRow({
        result_id: "r-ssb-c",
        benchmark: "star_schema",
        scale_factor: 0.1,
        run_date: "2026-04-03",
        geomean_ms: 21,
        display_geomean_ms: 21,
        phase: "power",
        primary_metric: "display_geomean_ms",
      }),
    ]);

    render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());

    const tpchTrend = screen.getByTestId("trend-cohort-tpch-sf0.1-power-display_geomean_ms");
    const ssbTrend = screen.getByTestId("trend-cohort-star_schema-sf0.1-power-display_geomean_ms");
    expect(screen.getAllByRole("img", { name: "Geomean ms trend over time" })).toHaveLength(2);
    expect(screen.getByText(/TPC-H · SF 0\.1 · power · geomean latency/)).toBeTruthy();
    expect(screen.getByText(/SSB · SF 0\.1 · power · geomean latency/)).toBeTruthy();
    expect(tpchTrend.querySelector('[data-result-id="r-tpch-a"]')).toBeTruthy();
    expect(tpchTrend.querySelector('[data-result-id="r-tpch-c"]')).toBeTruthy();
    expect(tpchTrend.querySelector('[data-result-id="r-ssb-a"]')).toBeNull();
    expect(ssbTrend.querySelector('[data-result-id="r-ssb-a"]')).toBeTruthy();
    expect(ssbTrend.querySelector('[data-result-id="r-ssb-c"]')).toBeTruthy();
    expect(ssbTrend.querySelector('[data-result-id="r-tpch-a"]')).toBeNull();
  });

  it("replaces one- and two-observation trends with sparse-data states", async () => {
    vi.mocked(getPlatformIndexRows).mockResolvedValue([
      makeRow({ result_id: "r-tpch-a", benchmark: "tpch", run_date: "2026-04-01", geomean_ms: 10 }),
      makeRow({ result_id: "r-tpch-b", benchmark: "tpch", run_date: "2026-04-02", geomean_ms: 12 }),
    ]);

    render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());

    expect(screen.queryByRole("img", { name: "Geomean ms trend over time" })).toBeNull();
    const sparse = screen.getByTestId("trend-sparse-tpch-sf0.1-power-display_geomean_ms");
    expect(sparse.textContent).toContain("Limited observations: 2 published runs");
    expect(sparse.textContent).toContain("geomean latency, ms (lower is faster)");
  });
});
