/**
 * The three-to-four run layout: diverging heatmap and standings.
 *
 * A multi-run selection is a ranking problem, not a diff. These tests pin the
 * two properties that make the ranking honest -- one shared query set, and a
 * scale that preserves polarity.
 */

import { describe, expect, it } from "vitest";

import {
  DIVERGING_RATIO_CLAMP,
  divergingRatioPosition,
  queryDisagreementSpread,
} from "@/lib/chartMath";
import {
  buildHeatmapRows,
  filterHeatmapRows,
  orderRowsByDisagreement,
} from "@/components/MultiRunHeatmap";
import { buildStandings, sharedQueryIdsFor } from "@/components/MultiRunStandings";
import type { DetailResult } from "@/types";

function run(id: string, timings: [string, number | null][]): DetailResult {
  return {
    result_id: id,
    platform: id,
    display_timings: timings.map(([query_id, display_ms]) => ({
      query_id,
      display_ms,
      sample_count: 3,
      is_valid_display_timing: display_ms !== null,
      timing_exclusion_reason: display_ms === null ? "missing_timing" : null,
    })),
  } as unknown as DetailResult;
}

describe("the diverging scale", () => {
  it("puts parity at the neutral midpoint", () => {
    expect(divergingRatioPosition(1)).toBe(0);
  });

  it("signs faster negative and slower positive", () => {
    expect(divergingRatioPosition(0.5)).toBeLessThan(0);
    expect(divergingRatioPosition(2)).toBeGreaterThan(0);
  });

  it("is symmetric in log space, so a 2x speedup and 2x slowdown are equal and opposite", () => {
    // On a linear ratio scale they would not be: 0.5 is 0.5 below parity while
    // 2.0 is 1.0 above it, which would render slowdowns as visually larger.
    const faster = divergingRatioPosition(0.5)!;
    const slower = divergingRatioPosition(2)!;
    expect(faster).toBeCloseTo(-slower, 12);
  });

  it("saturates rather than compressing everything near parity", () => {
    expect(divergingRatioPosition(DIVERGING_RATIO_CLAMP)).toBeCloseTo(1, 12);
    expect(divergingRatioPosition(1000)).toBe(1);
    expect(divergingRatioPosition(0.0001)).toBe(-1);
  });

  it("returns null for an unanswerable ratio rather than parity", () => {
    // Defaulting to 0 would paint "we do not know" in the same colour as
    // "identical to baseline" -- the specific misreading this must not invite.
    expect(divergingRatioPosition(null)).toBeNull();
    expect(divergingRatioPosition(0)).toBeNull();
    expect(divergingRatioPosition(Number.NaN)).toBeNull();
    expect(divergingRatioPosition(-1)).toBeNull();
  });
});

describe("disagreement spread", () => {
  it("measures the log-space spread across runs", () => {
    expect(queryDisagreementSpread([1, 2])).toBeCloseTo(1, 12);
    expect(queryDisagreementSpread([0.5, 2])).toBeCloseTo(2, 12);
  });

  it("has no value when only one run could answer", () => {
    // Reporting 0 would rank a query only one run answered as perfect
    // consensus, putting it above genuinely-agreed queries.
    expect(queryDisagreementSpread([1, null])).toBeNull();
    expect(queryDisagreementSpread([])).toBeNull();
  });
});

describe("the heatmap grid", () => {
  const results = [
    run("a", [["Q1", 10], ["Q2", 20]]),
    run("b", [["Q1", 20], ["Q2", 20]]),
    run("c", [["Q1", 5], ["Q2", null]]),
  ];

  it("expresses every cell as a ratio against the chosen baseline", () => {
    const rows = buildHeatmapRows(results, 0);
    const q1 = rows.find((r) => r.queryId === "Q1")!;
    expect(q1.cells.map((c) => c.ratio)).toEqual([1, 2, 0.5]);
  });

  it("re-bases when the baseline changes", () => {
    // Baseline drives everything downstream; no panel may keep the old one.
    const rebased = buildHeatmapRows(results, 1);
    const q1 = rebased.find((r) => r.queryId === "Q1")!;
    expect(q1.cells.map((c) => c.ratio)).toEqual([0.5, 1, 0.25]);
  });

  it("marks a cell the run cannot answer as unrecorded, not parity", () => {
    const rows = buildHeatmapRows(results, 0);
    const q2 = rows.find((r) => r.queryId === "Q2")!;
    expect(q2.cells[2]!.ratio).toBeNull();
    expect(q2.cells[2]!.position).toBeNull();
  });

  it("orders by disagreement when asked, with unanswerable rows last", () => {
    const ordered = orderRowsByDisagreement(buildHeatmapRows(results, 0));
    expect(ordered[0]!.queryId).toBe("Q1");
  });
});

describe("standings", () => {
  const results = [
    run("fast", [["Q1", 10], ["Q2", 10]]),
    run("mid", [["Q1", 20], ["Q2", 20]]),
    run("slow", [["Q1", 40], ["Q2", 40]]),
  ];

  it("ranks by geomean, faster first", () => {
    const { rows } = buildStandings(results, 0, ["fast", "mid", "slow"]);
    expect(rows.map((r) => r.resultId)).toEqual(["fast", "mid", "slow"]);
  });

  it("computes every geomean over the same shared query set", () => {
    const withGap = [...results, run("gap", [["Q1", 15], ["Q2", null]])];
    const { sharedQueryIds, totalQueryIds } = buildStandings(withGap, 0, ["a", "b", "c", "d"]);
    // Q2 leaves EVERY run's denominator, not just the run that lacked it.
    expect(sharedQueryIds).toEqual(["Q1"]);
    expect(totalQueryIds).toBe(2);
  });

  it("re-bases the ratio column when the baseline changes", () => {
    const first = buildStandings(results, 0, ["fast", "mid", "slow"]).rows;
    const second = buildStandings(results, 1, ["fast", "mid", "slow"]).rows;
    expect(first.find((r) => r.resultId === "mid")!.ratioToBaseline).toBeCloseTo(2, 12);
    expect(second.find((r) => r.resultId === "mid")!.ratioToBaseline).toBeCloseTo(1, 12);
    expect(second.find((r) => r.resultId === "mid")!.isBaseline).toBe(true);
  });

  it("awards a query to a single fastest run and no one on a tie", () => {
    // Ties awarding a win to each would let the counts exceed the query count
    // and overstate every tied run.
    const tied = [run("x", [["Q1", 10]]), run("y", [["Q1", 10]]), run("z", [["Q1", 20]])];
    const { rows } = buildStandings(tied, 0, ["x", "y", "z"]);
    expect(rows.reduce((n, r) => n + r.queriesWon, 0)).toBe(0);
  });

  it("applies the head-to-head tie band so a near-parity run is not called faster", () => {
    const near = [
      run("a", [["Q1", 100]]),
      run("b", [["Q1", 100.2]]),
      run("c", [["Q1", 200]]),
    ];
    const { rows } = buildStandings(near, 0, ["a", "b", "c"]);
    expect(rows.find((r) => r.resultId === "b")!.tied).toBe(true);
    expect(rows.find((r) => r.resultId === "c")!.tied).toBe(false);
  });

  it("keeps a run with no geomean rather than dropping it", () => {
    const withNull = [...results, run("empty", [])];
    const { rows } = buildStandings(withNull, 0, ["a", "b", "c", "d"]);
    expect(rows).toHaveLength(4);
    expect(rows.at(-1)!.resultId).toBe("empty");
  });

  it("shares one query-set helper with the heatmap", () => {
    expect(sharedQueryIdsFor(results)).toEqual(["Q1", "Q2"]);
  });

  it("populates engine and hardware fields on standing rows", () => {
    const withHw = [
      {
        ...results[0],
        platform_version: "1.2.0",
        environment: { arch: "arm64", cpu_model: "Apple M4", memory_gb: 16 },
      } as DetailResult,
      results[1]!,
      results[2]!,
    ];
    const { rows } = buildStandings(withHw, 0, ["fast", "mid", "slow"]);
    const first = rows.find((r) => r.resultId === "fast")!;
    expect(first.engine).toBe("fast v1.2.0");
    expect(first.hardware).toBe("Apple M4 · 16 GB");
  });
});

describe("heatmap limiter filtering", () => {
  const results = [
    run("base", [
      ["Q1", 100],
      ["Q2", 100],
      ["Q3", 100],
    ]),
    run("alt1", [
      ["Q1", 50], // 0.5x speedup
      ["Q2", 200], // 2.0x slowdown
      ["Q3", 100], // 1.0x parity
    ]),
    run("alt2", [
      ["Q1", 40], // 0.4x speedup
      ["Q2", 150], // 1.5x slowdown
      ["Q3", 100], // 1.0x parity
    ]),
  ];

  it("filters to speedup queries when limiter is 'speedups'", () => {
    const rows = buildHeatmapRows(results, 0);
    const speedups = filterHeatmapRows(rows, "speedups", 0);
    expect(speedups.map((r) => r.queryId)).toEqual(["Q1"]);
  });

  it("filters to slowdown queries when limiter is 'slowdowns'", () => {
    const rows = buildHeatmapRows(results, 0);
    const slowdowns = filterHeatmapRows(rows, "slowdowns", 0);
    expect(slowdowns.map((r) => r.queryId)).toEqual(["Q2"]);
  });

  it("orders by disagreement when limiter is 'movement'", () => {
    const rows = buildHeatmapRows(results, 0);
    const movement = filterHeatmapRows(rows, "movement", 0);
    expect(movement[0]!.queryId).toBe("Q1"); // spread between 0.4x and 1.0x (1.32) > 1.0x and 2.0x (1.0)
  });
});

describe("coordinated baseline re-basing across panels", () => {
  const results = [
    run("runA", [
      ["Q1", 10],
      ["Q2", 100],
    ]),
    run("runB", [
      ["Q1", 20],
      ["Q2", 50],
    ]),
    run("runC", [
      ["Q1", 30],
      ["Q2", 200],
    ]),
  ];

  it("re-bases heatmap ratios, standings, and speedup filters together when baseline switches", () => {
    // Baseline = runA (index 0)
    const heatmapA = buildHeatmapRows(results, 0);
    const standingsA = buildStandings(results, 0, ["A", "B", "C"]);
    const speedupsA = filterHeatmapRows(heatmapA, "speedups", 0);

    expect(standingsA.rows.find((r) => r.resultId === "runA")!.isBaseline).toBe(true);
    expect(standingsA.rows.find((r) => r.resultId === "runA")!.ratioToBaseline).toBe(1);
    // On Q2: runA=100, runB=50 (0.5x, speedup), runC=200 (2.0x, slowdown)
    expect(speedupsA.map((r) => r.queryId)).toContain("Q2");

    // Baseline switches to runB (index 1)
    const heatmapB = buildHeatmapRows(results, 1);
    const standingsB = buildStandings(results, 1, ["A", "B", "C"]);
    const speedupsB = filterHeatmapRows(heatmapB, "speedups", 1);

    // Standings panel: runB is now baseline, runA is not
    expect(standingsB.rows.find((r) => r.resultId === "runB")!.isBaseline).toBe(true);
    expect(standingsB.rows.find((r) => r.resultId === "runA")!.isBaseline).toBe(false);

    // Heatmap panel: Q2 relative to runB (50ms): runA=100ms (2.0x, slowdown!), runB=1.0x, runC=200ms (4.0x, slowdown)
    const q2HeatmapB = heatmapB.find((r) => r.queryId === "Q2")!;
    expect(q2HeatmapB.cells[0]!.ratio).toBeCloseTo(2, 6); // runA is now 2x slower than runB
    expect(q2HeatmapB.cells[1]!.ratio).toBeCloseTo(1, 6); // runB is baseline

    // Limiter panel: Q2 is no longer a speedup against runB!
    expect(speedupsB.map((r) => r.queryId)).not.toContain("Q2");
    // But Q1 relative to runB (20ms): runA is 10ms (0.5x, speedup!)
    expect(speedupsB.map((r) => r.queryId)).toContain("Q1");
  });
});
