/**
 * Registry parity meta-test.
 *
 * Asserts that chartRegistry.ts stays in sync with the generated Python
 * chart-type fixture from benchbox/core/visualization/chart_types.py.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";
import {
  CHART_REGISTRY,
  ALL_CHART_IDS,
  CHART_QUESTION_GROUPS,
  groupChartsByQuestion,
  isValidChartId,
} from "@/lib/chartRegistry";

function loadCanonicalChartIds(): string[] {
  const fixturePath = resolve(import.meta.dirname, "../../../tests/parity/fixtures/chart_ids.json");
  const fixture = JSON.parse(readFileSync(fixturePath, "utf8")) as { chart_ids: string[] };
  return fixture.chart_ids;
}

describe("chartRegistry parity with chart_types.py", () => {
  const canonicalIds = loadCanonicalChartIds();

  it("has no missing or extra entries", () => {
    const canonicalSet = new Set(canonicalIds);
    const registrySet = new Set(ALL_CHART_IDS);

    const missingFromRegistry = canonicalIds.filter((id) => !registrySet.has(id));
    const extrasInRegistry = ALL_CHART_IDS.filter((id) => !canonicalSet.has(id));

    expect(missingFromRegistry).toStrictEqual([]);
    expect(extrasInRegistry).toStrictEqual([]);
    expect(CHART_REGISTRY.length).toBe(canonicalIds.length);
  });

  it("ALL_CHART_IDS matches canonical order", () => {
    expect(ALL_CHART_IDS).toStrictEqual(canonicalIds);
  });

  it("every canonical ID is a valid chart id", () => {
    for (const id of canonicalIds) {
      expect(isValidChartId(id), `${id} should be valid`).toBe(true);
    }
  });

  it("no extra IDs beyond canonical list", () => {
    const extra = ALL_CHART_IDS.filter((id) => !canonicalIds.includes(id));
    expect(extra).toStrictEqual([]);
  });

  it("requires_two_results entries match Python requires_two_results=True", () => {
    // Python: comparison_bar, diverging_bar, normalized_speedup have requires_two_results=True
    const twoResultIds = ["comparison_bar", "diverging_bar", "normalized_speedup"];
    for (const id of twoResultIds) {
      const entry = CHART_REGISTRY.find((e) => e.id === id);
      expect(entry?.requires.requiresTwoResults, `${id} should requiresTwoResults`).toBe(true);
    }
  });

  it("assigns every chart to a known analytical question group", () => {
    const groupIds = new Set(CHART_QUESTION_GROUPS.map((group) => group.id));

    for (const entry of CHART_REGISTRY) {
      expect(groupIds.has(entry.questionGroup), `${entry.id} has a known question group`).toBe(true);
    }
  });

  it("declares an eligibility class for every chart dataset", () => {
    expect(Object.fromEntries(CHART_REGISTRY.map((entry) => [entry.id, entry.eligibilityClass]))).toStrictEqual({
      performance_bar: "display_safe",
      power_bar: "rank_safe",
      distribution_box: "display_safe",
      query_heatmap: "display_safe",
      query_histogram: "display_safe",
      cost_scatter: "cost_safe",
      time_series: "trend_safe",
      comparison_bar: "compare_safe",
      diverging_bar: "compare_safe",
      summary_box: "provenance_only",
      percentile_ladder: "display_safe",
      normalized_speedup: "compare_safe",
      stacked_phase: "display_safe",
      sparkline_table: "display_safe",
      cdf_chart: "display_safe",
      rank_table: "rank_safe",
    });
  });

  it("groups charts by Explorer analytical question without changing registry order", () => {
    const grouped = groupChartsByQuestion(CHART_REGISTRY);

    expect(grouped.map((group) => group.label)).toStrictEqual([
      "Overview",
      "Per-query",
      "Distribution",
      "Cost",
      "Trend",
      "Rank",
    ]);
    expect(grouped.find((group) => group.id === "overview")?.charts.map((chart) => chart.id)).toStrictEqual([
      "performance_bar",
      "power_bar",
      "summary_box",
      "stacked_phase",
      "sparkline_table",
    ]);
    expect(grouped.find((group) => group.id === "per_query")?.charts.map((chart) => chart.id)).toStrictEqual([
      "query_heatmap",
      "query_histogram",
      "comparison_bar",
      "diverging_bar",
      "normalized_speedup",
    ]);
  });
});
