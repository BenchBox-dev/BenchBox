import { fireEvent, render, screen } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MetaLeaderboard } from "@/components/MetaLeaderboard";
import type { MetaLeaderboard as MetaLeaderboardData } from "@/types";

const routeMock = vi.fn();
vi.mock("preact-router", () => ({
  route: (path: string) => routeMock(path),
}));

const META_TIMING_ELIGIBLE = {
  has_display_timing: true,
  valid_query_count: 2,
  missing_query_count: 0,
  zero_timing_count: 0,
  display_exclusion_reason: null,
  comparison_exclusion_reason: null,
  ranking_exclusion_reason: null,
};

const DATA: MetaLeaderboardData = {
  generated_at: "2026-04-17T00:00:00Z",
  cohorts: [
    {
      key: "clickbench-sf0.1-power",
      benchmark: "clickbench",
      scale_factor: 0.1,
      phase: "power",
      label: "ClickBench SF0.1",
      href: "/results/clickbench/",
      platform_count: 2,
      cohort_ranked_count: 2,
      cohort_ranking_exclusion_reason: null,
      primary_metric: "display_geomean_ms",
      primary_order: "asc",
      platforms: [
        {
          platform_id: "duckdb",
          platform: "DuckDB",
          result_id: "r1",
          rank: 1,
          metric_value: 10,
          speedup_vs_best: 1,
          primary_metric: "display_geomean_ms",
          primary_order: "asc",
          ...META_TIMING_ELIGIBLE,
        },
        {
          platform_id: "sqlite",
          platform: "SQLite",
          result_id: "r2",
          rank: 2,
          metric_value: 20,
          speedup_vs_best: 0.5,
          primary_metric: "display_geomean_ms",
          primary_order: "asc",
          ...META_TIMING_ELIGIBLE,
        },
      ],
    },
  ],
  platforms: [
    {
      platform_id: "duckdb",
      platform: "DuckDB",
      ranks: {
        "clickbench-sf0.1-power": {
          rank: 1,
          total: 2,
          metric_value: 10,
          speedup_vs_best: 1,
        },
      },
      avg_rank: 1,
      n_cohorts: 1,
    },
    {
      platform_id: "sqlite",
      platform: "SQLite",
      ranks: {
        "clickbench-sf0.1-power": {
          rank: 2,
          total: 2,
          metric_value: 20,
          speedup_vs_best: 0.5,
        },
      },
      avg_rank: 2,
      n_cohorts: 1,
    },
  ],
};

describe("MetaLeaderboard", () => {
  beforeEach(() => {
    routeMock.mockClear();
  });

  it("renders times, ranks, and speedup views from the same widened cells", () => {
    const { rerender } = render(
      <MetaLeaderboard data={DATA} mode="times" onModeChange={vi.fn()} />,
    );
    expect(screen.getByText("10 ms")).toBeTruthy();

    rerender(<MetaLeaderboard data={DATA} mode="ranks" onModeChange={vi.fn()} />);
    expect(screen.getByText("1/2")).toBeTruthy();

    rerender(<MetaLeaderboard data={DATA} mode="speedup" onModeChange={vi.fn()} />);
    expect(screen.getByText("1.00x")).toBeTruthy();
    expect(screen.getByText("0.50x")).toBeTruthy();
  });

  it("formats large power scores for scanning while preserving the exact value in titles", () => {
    const data: MetaLeaderboardData = {
      ...DATA,
      cohorts: [
        {
          ...DATA.cohorts[0]!,
          primary_metric: "power_score",
          primary_order: "desc",
          platforms: [
            {
              ...DATA.cohorts[0]!.platforms![0]!,
              metric_value: 3000.42,
              primary_metric: "power_score",
              primary_order: "desc" as const,
            },
          ],
        },
      ],
      platforms: [
        {
          ...DATA.platforms[0]!,
          ranks: {
            "clickbench-sf0.1-power": {
              rank: 1,
              total: 1,
              metric_value: 3000.42,
              speedup_vs_best: 1,
            },
          },
        },
      ],
    };

    render(<MetaLeaderboard data={data} mode="times" onModeChange={vi.fn()} />);

    expect(screen.getByText("3,000")).toBeTruthy();
    const cell = screen.getByRole("gridcell", {
      name: "DuckDB times for ClickBench SF0.1: 3,000",
    });
    expect(cell.getAttribute("title")).toContain("Exact power score: 3,000.42");
  });

  it("renders interpretable heatmap cells without relying only on color", () => {
    const { container } = render(
      <MetaLeaderboard data={DATA} mode="times" onModeChange={vi.fn()} />,
    );

    const cells = container.querySelectorAll<HTMLElement>("[data-cell]");
    expect(cells).toHaveLength(2);
    expect(cells[0]?.textContent).toContain("10 ms");
    expect(cells[0]?.getAttribute("aria-label")).toBe("DuckDB times for ClickBench SF0.1: 10 ms");
    expect(cells[0]?.className).toContain("meta-heatmap-cell");
    expect(cells[0]?.style.getPropertyValue("--cell-hue")).toBeTruthy();
    expect(cells[0]?.style.getPropertyValue("--cell-lightness")).toBeTruthy();
  });

  it("fires render-mode changes through the toggle buttons", () => {
    const onModeChange = vi.fn();
    render(<MetaLeaderboard data={DATA} mode="times" onModeChange={onModeChange} />);

    fireEvent.click(screen.getByRole("radio", { name: "Speedup" }));
    expect(onModeChange).toHaveBeenCalledWith("speedup");
  });

  it("links metric cells to run receipts with compact methodology metadata", () => {
    render(
      <MetaLeaderboard
        data={DATA}
        mode="times"
        onModeChange={vi.fn()}
        resultMetadataById={new Map([
          ["r1", { trust_label: "maintainer-run", validation_status: "exact" }],
          ["r2", { trust_label: "community-submission", validation_status: "loose" }],
        ])}
      />,
    );

    const receiptLink = screen.getByRole("link", { name: "10 ms" }) as HTMLAnchorElement;
    expect(receiptLink.getAttribute("href")).toBe("/results/r/r1#run-receipt");
    expect(screen.getByText("Maintainer")).toBeTruthy();
    expect(screen.getByText("Community")).toBeTruthy();
    expect(screen.getByText("exact")).toBeTruthy();
    expect(screen.getByText("loose")).toBeTruthy();
  });

  it("shows coverage counts and can sort by covered cohort count", () => {
    const data: MetaLeaderboardData = {
      ...DATA,
      cohorts: [
        DATA.cohorts[0]!,
        {
          ...DATA.cohorts[0]!,
          key: "tpch-sf0.1-power",
          benchmark: "tpch",
          label: "TPC-H SF0.1",
          href: "/results/tpch/",
          platform_count: 2,
          platforms: [
            {
              platform_id: "duckdb",
              platform: "DuckDB",
              result_id: "r3",
              rank: 2,
              metric_value: 30,
              speedup_vs_best: 0.5,
              primary_metric: "display_geomean_ms",
              primary_order: "asc" as const,
              ...META_TIMING_ELIGIBLE,
            },
            {
              platform_id: "polars",
              platform: "Polars",
              result_id: "r4",
              rank: 1,
              metric_value: 15,
              speedup_vs_best: 1,
              primary_metric: "display_geomean_ms",
              primary_order: "asc" as const,
              ...META_TIMING_ELIGIBLE,
            },
          ],
        },
      ],
      platforms: [
        {
          platform_id: "duckdb",
          platform: "DuckDB",
          ranks: {
            ...DATA.platforms[0]!.ranks,
            "tpch-sf0.1-power": {
              rank: 2,
              total: 2,
              metric_value: 30,
              speedup_vs_best: 0.5,
            },
          },
          avg_rank: 1.5,
          n_cohorts: 2,
        },
        DATA.platforms[1]!,
        {
          platform_id: "polars",
          platform: "Polars",
          ranks: {
            "tpch-sf0.1-power": {
              rank: 1,
              total: 2,
              metric_value: 15,
              speedup_vs_best: 1,
            },
          },
          avg_rank: 1,
          n_cohorts: 1,
        },
      ],
    };
    const { container } = render(<MetaLeaderboard data={data} mode="ranks" onModeChange={vi.fn()} />);
    const rowOrder = () =>
      Array.from(container.querySelectorAll("tbody tr")).map((row) => row.textContent ?? "");

    expect(screen.getByRole("group", { name: "Leaderboard display controls" })).toBeTruthy();
    expect(screen.getByText("Sort")).toBeTruthy();
    expect(screen.getByText("Mode")).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Avg rank" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radio", { name: "Best cohort" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Recent" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: /Avg rank over covered cohorts/ })).toBeTruthy();
    expect(rowOrder()[0]).toContain("Polars");

    fireEvent.click(screen.getByRole("radio", { name: "Coverage" }));

    expect(screen.getByRole("radio", { name: "Coverage" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText("2/2 cohorts")).toBeTruthy();
    expect(screen.getByText("over 2/2")).toBeTruthy();
    expect(rowOrder()[0]).toContain("DuckDB");
  });

  it("shows visible cohort phase, metric, unit, and direction labels", () => {
    render(<MetaLeaderboard data={DATA} mode="times" onModeChange={vi.fn()} />);

    const header = screen.getByRole("columnheader", { name: /ClickBench SF0\.1/ });
    expect(header.textContent).toContain("power · Geomean · ms · lower is faster");
  });

  it("does not focus the first leaderboard cell on initial render", () => {
    render(<MetaLeaderboard data={DATA} mode="times" onModeChange={vi.fn()} />);

    const firstCell = screen.getAllByRole("gridcell")[0] as HTMLElement;
    expect(firstCell.tabIndex).toBe(0);
    expect(document.activeElement).not.toBe(firstCell);
  });

  it("speedup mode visibly explains below-1.00x values", () => {
    render(<MetaLeaderboard data={DATA} mode="speedup" onModeChange={vi.fn()} />);

    expect(screen.getByText(/Values < 1\.00x are slower than baseline/)).toBeTruthy();
    expect(screen.getByText("0.50x")).toBeTruthy();
  });

  it("keeps avg-rank sorting over covered cohorts instead of penalizing missing coverage", () => {
    const data: MetaLeaderboardData = {
      ...DATA,
      cohorts: [
        DATA.cohorts[0]!,
        {
          ...DATA.cohorts[0]!,
          key: "tpch-sf0.1-power",
          benchmark: "tpch",
          label: "TPC-H SF0.1",
          href: "/results/tpch/",
          platform_count: 2,
          platforms: [
            {
              platform_id: "duckdb",
              platform: "DuckDB",
              result_id: "r3",
              rank: 2,
              metric_value: 30,
              speedup_vs_best: 0.5,
              primary_metric: "display_geomean_ms",
              primary_order: "asc" as const,
              ...META_TIMING_ELIGIBLE,
            },
          ],
        },
      ],
      platforms: [
        {
          platform_id: "duckdb",
          platform: "DuckDB",
          ranks: {
            ...DATA.platforms[0]!.ranks,
            "tpch-sf0.1-power": {
              rank: 2,
              total: 2,
              metric_value: 30,
              speedup_vs_best: 0.5,
            },
          },
          avg_rank: 1.5,
          n_cohorts: 2,
        },
        {
          platform_id: "polars",
          platform: "Polars",
          ranks: {
            "clickbench-sf0.1-power": {
              rank: 1,
              total: 2,
              metric_value: 8,
              speedup_vs_best: 1,
            },
          },
          avg_rank: 1,
          n_cohorts: 1,
        },
      ],
    };
    const { container } = render(<MetaLeaderboard data={data} mode="ranks" onModeChange={vi.fn()} />);
    const rowOrder = () =>
      Array.from(container.querySelectorAll("tbody tr")).map((row) => row.textContent ?? "");

    expect(rowOrder()[0]).toContain("Polars");
    expect(rowOrder()[0]).toContain("1.0");
    expect(rowOrder()[0]).toContain("over 1/2");
    expect(rowOrder()[0]).toContain("No run");
  });


  it("renders null when platforms list is empty", () => {
    const { container } = render(
      <MetaLeaderboard data={{ ...DATA, platforms: [] }} mode="times" onModeChange={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders both rank cells correctly in ranks mode (1/2 and 2/2)", () => {
    render(<MetaLeaderboard data={DATA} mode="ranks" onModeChange={vi.fn()} />);
    expect(screen.getByText("1/2")).toBeTruthy();
    expect(screen.getByText("2/2")).toBeTruthy();
  });

  it("shows explicit no-run copy for a platform missing a cohort rank entry", () => {
    const dataWithNa = {
      ...DATA,
      platforms: [
        DATA.platforms[0]!,
        {
          platform_id: "polars",
          platform: "Polars",
          ranks: {},
          avg_rank: null,
          n_cohorts: 0,
        },
      ],
    };
    render(<MetaLeaderboard data={dataWithNa} mode="ranks" onModeChange={vi.fn()} />);
    // "No run" appears both in a missing-cell and in the legend caption; assert
    // both surfaces are present rather than relying on a single-match query.
    expect(screen.getAllByText("No run").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("0/1 cohorts")).toBeTruthy();
    expect(screen.getByText("No score")).toBeTruthy();
    const missingCell = screen.getByRole("gridcell", {
      name: /Polars has no published run for ClickBench SF0\.1\. Missing cohorts are not scored; coverage is shown separately\./,
    });
    expect(missingCell.getAttribute("title")).toContain("Missing cohorts are not scored");
    expect(missingCell.querySelector("a")).toBeNull();
    expect(missingCell.textContent).not.toContain("Maintainer");
    expect(missingCell.textContent).not.toContain("exact");
  });

  it("formats avg_rank with 2 decimal places", () => {
    const dataWithDecimal = {
      ...DATA,
      platforms: [
        { ...DATA.platforms[0]!, avg_rank: 1.5 },
        DATA.platforms[1]!,
      ],
    };
    render(<MetaLeaderboard data={dataWithDecimal} mode="ranks" onModeChange={vi.fn()} />);
    expect(screen.getByText("1.5")).toBeTruthy();
  });

  it("caps rendered platform rows and expands them with Show more", () => {
    const platforms = Array.from({ length: 205 }).map((_, index) => ({
      platform_id: `platform-${index}`,
      platform: `Platform ${index}`,
      ranks: {
        "clickbench-sf0.1-power": {
          rank: index + 1,
          total: 205,
          metric_value: index + 1,
          speedup_vs_best: 1 / (index + 1),
        },
      },
      avg_rank: index + 1,
      n_cohorts: 1,
    }));
    const data: MetaLeaderboardData = {
      ...DATA,
      cohorts: [
        {
          ...DATA.cohorts[0]!,
          platform_count: 205,
          cohort_ranked_count: 205,
          platforms: platforms.map((platform, index) => ({
            platform_id: platform.platform_id,
            platform: platform.platform,
            result_id: `result-${index}`,
            rank: index + 1,
            metric_value: index + 1,
            speedup_vs_best: 1 / (index + 1),
            primary_metric: "display_geomean_ms",
            primary_order: "asc" as const,
            ...META_TIMING_ELIGIBLE,
          })),
        },
      ],
      platforms,
    };

    const { container } = render(<MetaLeaderboard data={data} mode="times" onModeChange={vi.fn()} />);

    expect(screen.getByText("Showing 200 of 205 platforms across 1 leaderboard cohort")).toBeTruthy();
    expect(container.querySelectorAll("tbody tr")).toHaveLength(200);
    expect(screen.queryByText("Platform 204")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Show more platforms" }));

    expect(screen.getByText("Showing 205 of 205 platforms across 1 leaderboard cohort")).toBeTruthy();
    expect(container.querySelectorAll("tbody tr")).toHaveLength(205);
    expect(screen.getByText("Platform 204")).toBeTruthy();
  });

  it("Enter and Space on a focused cell navigate to the row's platform page", () => {
    render(
      <MetaLeaderboard
        data={DATA}
        mode="times"
        onModeChange={vi.fn()}
        platformHref={(id) => `/results/p/${id}/`}
      />,
    );

    const cells = screen.getAllByRole("gridcell");
    const firstRowCell = cells[0]!;
    firstRowCell.focus();

    fireEvent.keyDown(firstRowCell, { key: "Enter" });
    expect(routeMock).toHaveBeenLastCalledWith("/results/p/duckdb/");

    fireEvent.keyDown(firstRowCell, { key: " " });
    expect(routeMock).toHaveBeenLastCalledWith("/results/p/duckdb/");

    // Arrow down into SQLite row, Enter should navigate to sqlite - matches
    // the row's mouse-click destination.
    fireEvent.keyDown(firstRowCell, { key: "ArrowDown" });
    const activeCell = document.querySelector<HTMLElement>('[data-cell="1-0"]');
    expect(activeCell).not.toBeNull();
    fireEvent.keyDown(activeCell!, { key: "Enter" });
    expect(routeMock).toHaveBeenLastCalledWith("/results/p/sqlite/");
  });

  it("labels published but unranked evidence instead of treating it as missing", () => {
    const data: MetaLeaderboardData = {
      ...DATA,
      cohorts: [
        {
          ...DATA.cohorts[0]!,
          key: "tpch-sf0.1-power",
          benchmark: "tpch",
          label: "TPC-H SF0.1",
          href: "/results/tpch/",
          primary_metric: "power_score",
          primary_order: "desc" as const,
          platforms: [
            {
              platform_id: "polars",
              platform: "Polars",
              result_id: "polars-tpch-r1",
              rank: null,
              metric_value: 9001,
              speedup_vs_best: null,
              primary_metric: "power_score",
              primary_order: "desc" as const,
              ...META_TIMING_ELIGIBLE,
              ranking_exclusion_reason: "trust_not_rankable",
            },
          ],
        },
      ],
      platforms: [
        {
          platform_id: "polars",
          platform: "Polars",
          ranks: {},
          avg_rank: null,
          n_cohorts: 0,
        },
      ],
    };
    render(
      <MetaLeaderboard
        data={data}
        mode="times"
        onModeChange={vi.fn()}
        resultMetadataById={new Map([
          ["polars-tpch-r1", { trust_label: "community-submission", validation_status: "passed" }],
        ])}
      />,
    );

    const cell = screen.getByRole("gridcell", {
      name: /Polars has published evidence for TPC-H SF0\.1, but it is excluded: Trust policy excludes this result from ranking\./,
    });
    expect(cell.textContent).toContain("Excluded");
    expect(cell.textContent).toContain("Trust policy excludes this result from ranking.");
    expect(cell.textContent).not.toContain("No run");
    expect((cell.querySelector("a") as HTMLAnchorElement | null)?.getAttribute("href")).toBe(
      "/results/r/polars-tpch-r1#run-receipt",
    );
    expect(cell.textContent).toContain("Community");
    expect(cell.textContent).toContain("passed");
  });

  it("recovers ranked cells from cohort evidence when the pivot map is stale", () => {
    const data: MetaLeaderboardData = {
      ...DATA,
      cohorts: [
        {
          ...DATA.cohorts[0]!,
          key: "tpch-sf0.1-power",
          benchmark: "tpch",
          label: "TPC-H SF0.1",
          href: "/results/tpch/",
          primary_metric: "power_score",
          primary_order: "desc" as const,
          platforms: [
            {
              platform_id: "polars",
              platform: "Polars",
              result_id: "polars-tpch-r1",
              rank: 1,
              metric_value: 9001,
              speedup_vs_best: 1,
              primary_metric: "power_score",
              primary_order: "desc" as const,
              ...META_TIMING_ELIGIBLE,
            },
          ],
        },
      ],
      platforms: [
        {
          platform_id: "polars",
          platform: "Polars",
          ranks: {}, // <- the contradiction: result exists, ranks map is empty
          avg_rank: 0,
          n_cohorts: 0,
        },
      ],
    };
    render(<MetaLeaderboard data={data} mode="times" onModeChange={vi.fn()} />);

    const cell = screen.getByRole("gridcell", {
      name: "Polars times for TPC-H SF0.1: 9,001",
    });
    expect(cell.textContent).toContain("9,001");
    expect(cell.textContent).not.toContain("No run");
    expect((cell.querySelector("a") as HTMLAnchorElement | null)?.getAttribute("href")).toBe(
      "/results/r/polars-tpch-r1#run-receipt",
    );
  });
});
