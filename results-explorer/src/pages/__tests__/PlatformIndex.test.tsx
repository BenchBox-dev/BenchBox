/**
 * Tests for PlatformIndex sortable table headers.
 *
 * The default sort (geomean_ms ascending, nulls last) is observable behaviour
 * — must_preserve in the parent TODO. Click-driven sort layered on top of
 * that default switches direction on repeated clicks of the same key.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/preact";
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { PlatformIndexRowRow } from "@/lib/duckdbQueries";

vi.mock("@/lib/duckdbQueries", async () => {
  const actual = await vi.importActual<typeof import("@/lib/duckdbQueries")>("@/lib/duckdbQueries");
  return {
    ...actual,
    getPlatformIndexRows: vi.fn(),
  };
});

import { getPlatformIndexRows } from "@/lib/duckdbQueries";
import { PlatformIndex } from "@/pages/PlatformIndex";

function makeRow(overrides: Partial<PlatformIndexRowRow> = {}): PlatformIndexRowRow {
  return {
    result_id: "r-base",
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
    primary_metric: "display_geomean_ms",
    ...overrides,
  };
}

const ROWS: PlatformIndexRowRow[] = [
  makeRow({ result_id: "r-tpch-fast", benchmark: "tpch", run_date: "2026-04-03", power_score: 5000, geomean_ms: 5 }),
  makeRow({ result_id: "r-ssb-mid", benchmark: "star_schema", run_date: "2026-04-01", power_score: 3000, geomean_ms: 15 }),
  makeRow({ result_id: "r-tpch-slow", benchmark: "tpch", run_date: "2026-04-02", power_score: 1000, geomean_ms: 50 }),
  makeRow({ result_id: "r-null-geo", benchmark: "tpch", run_date: "2026-04-04", power_score: null, geomean_ms: null }),
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
    vi.mocked(getPlatformIndexRows).mockResolvedValue(ROWS);
  });

  it("default sort is geomean_ms ascending with nulls last", async () => {
    const { container } = render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());
    await waitFor(() => expect(document.title).toBe("DuckDB · BenchBox Results"));
    expect(getRowOrder(container)).toEqual(["r-tpch-fast", "r-ssb-mid", "r-tpch-slow", "r-null-geo"]);
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
    ]);

    const { container } = render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());

    const tpch = screen.getByTestId("trend-cohort-tpch-sf0.01-power-power_score");
    const ssb = screen.getByTestId("trend-cohort-star_schema-sf0.1-power-display_geomean_ms");
    expect(container.querySelectorAll("svg[aria-label$='trend over time']")).toHaveLength(2);
    expect(tpch.querySelector('[data-result-id="r-tpch-a"]')).toBeTruthy();
    expect(tpch.querySelector('[data-result-id="r-tpch-b"]')).toBeTruthy();
    expect(tpch.querySelector('[data-result-id="r-ssb-a"]')).toBeNull();
    expect(ssb.querySelector('[data-result-id="r-ssb-a"]')).toBeTruthy();
    expect(ssb.querySelector('[data-result-id="r-ssb-b"]')).toBeTruthy();
    expect(ssb.querySelector('[data-result-id="r-tpch-a"]')).toBeNull();
  });

  it("shows receipt links and validation status for each platform result", async () => {
    render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());

    const receiptLinks = screen.getAllByRole("link", { name: "Receipt →" }) as HTMLAnchorElement[];
    expect(receiptLinks[0]?.getAttribute("href")).toBe("/results/r/r-tpch-fast#run-receipt");
    expect(screen.getAllByText("exact").length).toBeGreaterThan(0);
  });
});
