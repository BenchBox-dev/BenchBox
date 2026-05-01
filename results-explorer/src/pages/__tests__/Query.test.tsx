import { fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/db", () => ({
  getDb: vi.fn(),
  queryRows: vi.fn(),
}));

import { getDb, queryRows } from "@/db";
import { DEFAULT_ROW_LIMIT, UNLIMITED_ROW_LIMIT } from "@/lib/queryFilters";
import { Query } from "@/pages/Query";

const SCHEMA = {
  columns: [
    { name: "result_id", type: "VARCHAR" },
    { name: "benchmark", type: "VARCHAR" },
    { name: "platform", type: "VARCHAR" },
    { name: "scale_factor", type: "DOUBLE" },
    { name: "run_date", type: "VARCHAR" },
    { name: "power_score", type: "DOUBLE" },
    { name: "geomean_ms", type: "DOUBLE" },
    { name: "trust_label", type: "VARCHAR" },
    { name: "tuning_mode", type: "VARCHAR" },
    { name: "validation_status", type: "VARCHAR" },
    { name: "cost_usd", type: "DOUBLE" },
  ],
};

const BASE_ROWS = [
  {
    result_id: "r1",
    benchmark: "clickbench",
    platform: "DuckDB",
    scale_factor: 0.1,
    run_date: "2026-04-17T12:00:00Z",
    power_score: null,
    geomean_ms: 10,
    trust_label: "maintainer-run",
  },
  {
    result_id: "r2",
    benchmark: "clickbench",
    platform: "SQLite",
    scale_factor: 0.1,
    run_date: "2026-04-16T12:00:00Z",
    power_score: null,
    geomean_ms: 20,
    trust_label: "community-submission",
  },
];

function normalizeSql(sql: string): string {
  return sql.replace(/\s+/g, " ").trim();
}

beforeEach(() => {
  window.history.replaceState(null, "", "/results/query");
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => SCHEMA,
    }),
  );
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    disconnect() {}
  });
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:csv");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});

  const preparedQuery = vi.fn().mockResolvedValue(undefined);
  const preparedClose = vi.fn().mockResolvedValue(undefined);
  const prepare = vi.fn().mockResolvedValue({
    query: preparedQuery,
    close: preparedClose,
  });
  const close = vi.fn().mockResolvedValue(undefined);
  vi.mocked(getDb).mockResolvedValue({
    connect: vi.fn().mockResolvedValue({ prepare, close }),
    copyFileToBuffer: vi
      .fn()
      .mockResolvedValue(new TextEncoder().encode("benchmark,platform,scale_factor\nclickbench,DuckDB,0.1\n")),
    dropFile: vi.fn().mockResolvedValue(null),
  } as unknown as Awaited<ReturnType<typeof getDb>>);

  vi.mocked(queryRows).mockImplementation(async (sql: string) => {
    const normalized = normalizeSql(sql);

    if (normalized.includes("FROM duckdb_columns()")) {
      return SCHEMA.columns;
    }
    if (normalized.includes("SELECT COALESCE(CAST(benchmark AS VARCHAR), 'unknown') AS value")) {
      return [{ value: "clickbench", count: 2 }];
    }
    if (normalized.includes("SELECT COALESCE(CAST(platform AS VARCHAR), 'unknown') AS value")) {
      return [
        { value: "DuckDB", count: 1 },
        { value: "SQLite", count: 1 },
      ];
    }
    if (normalized.includes("SELECT COALESCE(CAST(scale_factor AS VARCHAR), 'unknown') AS value")) {
      return [{ value: "0.1", count: 2 }];
    }
    if (normalized.includes("SELECT COALESCE(CAST(tuning_mode AS VARCHAR), 'unknown') AS value")) {
      return [
        { value: "tuned", count: 1 },
        { value: "auto", count: 1 },
      ];
    }
    if (normalized.includes("SELECT COALESCE(CAST(trust_label AS VARCHAR), 'unknown') AS value")) {
      return [
        { value: "maintainer-run", count: 1 },
        { value: "community-submission", count: 1 },
      ];
    }
    if (normalized.includes("SELECT COALESCE(CAST(validation_status AS VARCHAR), 'unknown') AS value")) {
      return [{ value: "exact", count: 2 }];
    }
    if (normalized.includes("SELECT CASE WHEN cost_usd IS NULL THEN 'no' ELSE 'yes' END AS value")) {
      return [
        { value: "yes", count: 1 },
        { value: "no", count: 1 },
      ];
    }
    if (normalized.startsWith("CREATE TABLE")) {
      throw new Error("read-only connection");
    }
    if (normalized.startsWith("SELECT benchmark, platform, scale_factor")) {
      return BASE_ROWS;
    }
    if (normalized.startsWith("SELECT * FROM bench.results")) {
      return BASE_ROWS;
    }
    return BASE_ROWS;
  });
});

describe("Query", () => {
  it("loads facet counts and table rows from DuckDB", async () => {
    render(<Query />);
    await waitFor(() => expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0));
    expect(document.title).toBe("Query · BenchBox Results");
    const resultsTable = screen.getAllByRole("table")[0]!;

    expect(screen.getAllByText("SQLite").length).toBeGreaterThan(0);
    expect(within(resultsTable).getAllByText("clickbench").length).toBeGreaterThan(0);
    expect(within(resultsTable).getByText("maintainer-run")).toBeTruthy();
  });

  it("updates the select SQL when facet filters change and sort toggles", async () => {
    render(<Query />);
    await waitFor(() => expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0));
    const resultsTable = screen.getAllByRole("table")[0]!;

    fireEvent.click(screen.getByLabelText(/DuckDB/i));
    await waitFor(() => {
      const selectCalls = vi.mocked(queryRows).mock.calls.filter(([sql]) =>
        String(sql).includes("SELECT benchmark, platform, scale_factor"),
      );
      expect(selectCalls.at(-1)?.[0]).toContain("platform IN (?)");
    });

    fireEvent.click(within(resultsTable).getAllByText(/^benchmark(?:\s[↑↓])?$/)[0]!);
    await waitFor(() => {
      const selectCalls = vi.mocked(queryRows).mock.calls.filter(([sql]) =>
        String(sql).includes("SELECT benchmark, platform, scale_factor"),
      );
      expect(selectCalls.at(-1)?.[0]).toContain("ORDER BY benchmark ASC");
    });
  });

  it("switches the result table row limit through URL state", async () => {
    render(<Query />);
    await waitFor(() => expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0));

    const selectCallsBefore = vi.mocked(queryRows).mock.calls.filter(([sql]) =>
      String(sql).includes("SELECT benchmark, platform, scale_factor"),
    );
    expect(selectCallsBefore.at(-1)?.[0]).toContain(`LIMIT ${DEFAULT_ROW_LIMIT}`);

    fireEvent.click(screen.getByRole("button", { name: /^All$/ }));

    await waitFor(() =>
      expect(new URL(window.location.href).searchParams.get("limit")).toBe("all"),
    );
    await waitFor(() => {
      const selectCalls = vi.mocked(queryRows).mock.calls.filter(([sql]) =>
        String(sql).includes("SELECT benchmark, platform, scale_factor"),
      );
      expect(selectCalls.at(-1)?.[0]).toContain(`LIMIT ${UNLIMITED_ROW_LIMIT}`);
    });
    expect(screen.getByText("Showing all returned rows: 2")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /^Default$/ }));

    await waitFor(() =>
      expect(new URL(window.location.href).searchParams.get("limit")).toBeNull(),
    );
  });

  it("coerces invalid row-limit URL state back to the default", async () => {
    window.history.replaceState(null, "", "/results/query?limit=bogus");

    render(<Query />);
    await waitFor(() => expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0));

    await waitFor(() =>
      expect(new URL(window.location.href).searchParams.get("limit")).toBeNull(),
    );
    expect(screen.getByRole("button", { name: /^Default$/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("exports the current table rows as CSV", async () => {
    let capturedBlob: Blob | null = null;
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation(((tagName: string) => {
      if (tagName === "a") {
        return {
          click() {},
          set href(_: string) {},
          set download(_: string) {},
        } as unknown as HTMLAnchorElement;
      }
      return originalCreateElement(tagName);
    }) as typeof document.createElement);
    vi.spyOn(URL, "createObjectURL").mockImplementation((blob: Blob | MediaSource) => {
      if (blob instanceof Blob) capturedBlob = blob;
      return "blob:csv";
    });

    render(<Query />);
    await waitFor(() => expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0));

    fireEvent.click(screen.getByRole("button", { name: "Download CSV" }));
    await waitFor(() => expect(vi.mocked(getDb)).toHaveBeenCalled());
    await waitFor(() => expect(capturedBlob).not.toBeNull());
    expect(capturedBlob).toBeTruthy();
    const csvText = await capturedBlob!.text();
    expect(csvText).toContain("benchmark,platform,scale_factor");
  });

  it("loads a starter query into the SQL editor when its button is clicked", async () => {
    render(<Query />);
    await waitFor(() => expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0));

    fireEvent.click(screen.getByText("Advanced SQL"));
    const starterButton = screen.getByRole("button", { name: "Recent results" });
    fireEvent.click(starterButton);

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toContain("FROM bench.results");
    expect(textarea.value).toContain("ORDER BY run_date DESC");
  });

  it("exports the current table rows as JSON", async () => {
    let capturedBlob: Blob | null = null;
    vi.spyOn(URL, "createObjectURL").mockImplementation((blob: Blob | MediaSource) => {
      if (blob instanceof Blob) capturedBlob = blob;
      return "blob:json";
    });

    render(<Query />);
    await waitFor(() => expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0));

    fireEvent.click(screen.getByRole("button", { name: "Download JSON" }));
    await waitFor(() => expect(capturedBlob).not.toBeNull());
    const jsonText = await capturedBlob!.text();
    const parsed = JSON.parse(jsonText);
    expect(Array.isArray(parsed)).toBe(true);
    expect(parsed.length).toBeGreaterThan(0);
    expect(parsed[0]).toHaveProperty("benchmark");
  });

  it("runs read-only SQL and surfaces DDL errors", async () => {
    render(<Query />);
    await waitFor(() => expect(screen.getAllByText("DuckDB").length).toBeGreaterThan(0));

    fireEvent.click(screen.getByText("Advanced SQL"));
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.input(textarea, { target: { value: "CREATE TABLE x AS SELECT 1" } });
    fireEvent.click(screen.getByRole("button", { name: "Run SQL" }));

    await waitFor(() => expect(screen.getByText("read-only connection")).toBeTruthy());
  });
});
