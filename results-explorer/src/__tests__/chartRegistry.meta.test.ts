/**
 * Registry parity meta-test.
 *
 * Asserts that chartRegistry.ts stays in sync with the canonical Python list
 * in benchbox/core/visualization/chart_types.py.
 *
 * The 16 IDs and their order are the contract - edit chart_types.py first,
 * then update chartRegistry.ts to match.
 *
 * Python source: benchbox/core/visualization/chart_types.py (ALL_CHART_TYPES)
 * TS source:     results-explorer/src/lib/chartRegistry.ts (ALL_CHART_IDS)
 */

import { describe, it, expect } from "vitest";
import { CHART_REGISTRY, ALL_CHART_IDS, isValidChartId } from "@/lib/chartRegistry";

// Hard-coded canonical list from chart_types.py _CHART_SPECS (order matters).
// chart_types.py is the SINGLE SOURCE OF TRUTH. This list must be kept in sync
// manually - the test cannot parse Python source, so adding a 17th type to
// chart_types.py without also updating this list and chartRegistry.ts will NOT
// cause a CI failure. When you add a chart type, update ALL THREE: chart_types.py,
// chartRegistry.ts (ALL_CHART_IDS), and CANONICAL_IDS here.
const CANONICAL_IDS = [
  "performance_bar",
  "power_bar",
  "distribution_box",
  "query_heatmap",
  "query_histogram",
  "cost_scatter",
  "time_series",
  "comparison_bar",
  "diverging_bar",
  "summary_box",
  "percentile_ladder",
  "normalized_speedup",
  "stacked_phase",
  "sparkline_table",
  "cdf_chart",
  "rank_table",
] as const;

describe("chartRegistry parity with chart_types.py", () => {
  it("has exactly 16 entries", () => {
    expect(CHART_REGISTRY.length).toBe(16);
  });

  it("ALL_CHART_IDS matches canonical order", () => {
    expect(ALL_CHART_IDS).toStrictEqual(CANONICAL_IDS);
  });

  it("every canonical ID is a valid chart id", () => {
    for (const id of CANONICAL_IDS) {
      expect(isValidChartId(id), `${id} should be valid`).toBe(true);
    }
  });

  it("no extra IDs beyond canonical list", () => {
    const extra = ALL_CHART_IDS.filter((id) => !(CANONICAL_IDS as readonly string[]).includes(id));
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
});
