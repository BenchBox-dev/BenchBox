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

  it("fires render-mode changes through the toggle buttons", () => {
    const onModeChange = vi.fn();
    render(<MetaLeaderboard data={DATA} mode="times" onModeChange={onModeChange} />);

    fireEvent.click(screen.getByRole("button", { name: "Speedup" }));
    expect(onModeChange).toHaveBeenCalledWith("speedup");
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

  it("shows em-dash for platform missing a cohort rank entry", () => {
    const dataWithNa = {
      ...DATA,
      platforms: [
        DATA.platforms[0]!,
        {
          platform_id: "polars",
          platform: "Polars",
          ranks: {},
          avg_rank: null as unknown as number,
          n_cohorts: 0,
        },
      ],
    };
    render(<MetaLeaderboard data={dataWithNa} mode="ranks" onModeChange={vi.fn()} />);
    const dashes = screen.getAllByText("-");
    expect(dashes.length).toBeGreaterThan(0);
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
