import { fireEvent, render, screen } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MetaLeaderboard } from "@/components/MetaLeaderboard";
import type { MetaLeaderboard as MetaLeaderboardData } from "@/types";

const routeMock = vi.fn();
vi.mock("preact-router", () => ({
  route: (path: string) => routeMock(path),
}));

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

    fireEvent.click(screen.getByRole("button", { name: "Speedup" }));
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

    expect(screen.getByRole("button", { name: "Avg rank over covered cohorts" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Best cohort" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Recent" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Avg rank over covered cohorts" })).toBeTruthy();
    expect(rowOrder()[0]).toContain("Polars");

    fireEvent.click(screen.getByRole("button", { name: "Coverage" }));

    expect(screen.getByRole("button", { name: "Coverage" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("2/2 cohorts")).toBeTruthy();
    expect(screen.getByText("over 2/2")).toBeTruthy();
    expect(rowOrder()[0]).toContain("DuckDB");
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
    expect(screen.getByText("No run")).toBeTruthy();
    expect(screen.getByText("0/1 cohorts")).toBeTruthy();
    expect(screen.getByText("No score")).toBeTruthy();
    const missingCell = screen.getByRole("gridcell", {
      name: /Polars has no published run for ClickBench SF0\.1\. Missing cohorts are not scored; coverage is shown separately\./,
    });
    expect(missingCell.getAttribute("title")).toContain("Missing cohorts are not scored");
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
          platforms: platforms.map((platform, index) => ({
            platform_id: platform.platform_id,
            platform: platform.platform,
            result_id: `result-${index}`,
            rank: index + 1,
            metric_value: index + 1,
            speedup_vs_best: 1 / (index + 1),
            primary_metric: "display_geomean_ms",
            primary_order: "asc" as const,
          })),
        },
      ],
      platforms,
    };

    const { container } = render(<MetaLeaderboard data={data} mode="times" onModeChange={vi.fn()} />);

    expect(screen.getByText("Showing 200 of 205 platforms")).toBeTruthy();
    expect(container.querySelectorAll("tbody tr")).toHaveLength(200);
    expect(screen.queryByText("Platform 204")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Show more platforms" }));

    expect(screen.getByText("Showing 205 of 205 platforms")).toBeTruthy();
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
});
