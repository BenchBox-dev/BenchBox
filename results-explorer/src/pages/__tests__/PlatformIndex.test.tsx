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
    tuning_mode: null,
    execution_mode: null,
    compliance_class: null,
    cost_usd: null,
    ...overrides,
  };
}

const ROWS: PlatformIndexRowRow[] = [
  makeRow({ result_id: "r-tpch-fast", benchmark: "tpch", run_date: "2026-04-03", power_score: 5000, geomean_ms: 5 }),
  makeRow({ result_id: "r-ssb-mid", benchmark: "star_schema", run_date: "2026-04-01", power_score: 3000, geomean_ms: 15 }),
  makeRow({ result_id: "r-tpch-slow", benchmark: "tpch", run_date: "2026-04-02", power_score: 1000, geomean_ms: 50 }),
  makeRow({ result_id: "r-null-geo", benchmark: "tpch", run_date: "2026-04-04", power_score: null, geomean_ms: null }),
];

function getRowOrder(): string[] {
  // The first <td> in each row is the checkbox cell; aria-label embeds the result_id.
  const checkboxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
  return checkboxes.map((cb) => cb.getAttribute("aria-label") ?? "").map((l) => l.replace(/^Select | for comparison$/g, ""));
}

describe("PlatformIndex - sortable table headers", () => {
  beforeEach(() => {
    vi.mocked(getPlatformIndexRows).mockResolvedValue(ROWS);
  });

  it("default sort is geomean_ms ascending with nulls last", async () => {
    render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());
    const order = getRowOrder();
    expect(order).toEqual(["r-tpch-fast", "r-ssb-mid", "r-tpch-slow", "r-null-geo"]);
  });

  it("clicking the Geomean header twice flips ascending → descending (nulls still last)", async () => {
    render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());
    // First click switches the active sort key + direction. Geomean defaults
    // to asc, so a single click flips direction (asc → desc) once we treat
    // a same-key click as direction-toggle.
    fireEvent.click(screen.getByRole("button", { name: /Geomean/ }));
    const order = getRowOrder();
    expect(order).toEqual(["r-tpch-slow", "r-ssb-mid", "r-tpch-fast", "r-null-geo"]);
  });

  it("clicking the Benchmark header sorts alphabetically ascending", async () => {
    render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Benchmark/ }));
    const order = getRowOrder();
    // star_schema < tpch alphabetically. Within tpch, geomean_ms order is
    // unstable wrt the secondary key but JS sort is stable so original
    // order is preserved.
    expect(order[0]).toBe("r-ssb-mid");
    expect(order.slice(1)).toEqual(["r-tpch-fast", "r-tpch-slow", "r-null-geo"]);
  });

  it("clicking Power Score puts nulls last in both directions", async () => {
    render(<PlatformIndex platform="duckdb" />);
    await waitFor(() => expect(screen.getByText("DuckDB Results")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Power Score/ }));
    expect(getRowOrder().slice(-1)[0]).toBe("r-null-geo");
    fireEvent.click(screen.getByRole("button", { name: /Power Score/ }));
    expect(getRowOrder().slice(-1)[0]).toBe("r-null-geo");
  });
});
