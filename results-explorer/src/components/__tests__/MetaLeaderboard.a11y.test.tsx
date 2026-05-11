import { render } from "@testing-library/preact";
import { describe, it, vi } from "vitest";
import { MetaLeaderboard } from "@/components/MetaLeaderboard";
import { expectNoAxeViolations } from "@/testing/axe-helper";
import type { MetaLeaderboard as MetaLeaderboardData } from "@/types";

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

describe("MetaLeaderboard accessibility", () => {
  it("has no serious or critical axe violations", async () => {
    const { container } = render(
      <MetaLeaderboard data={DATA} mode="times" onModeChange={vi.fn()} />,
    );
    await expectNoAxeViolations(container);
  });
});
