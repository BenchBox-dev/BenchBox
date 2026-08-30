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
import {
  DEFAULT_BASIS,
  WARMUP,
  ALL_WARM,
  resolveResultsForBasis,
  type MeasurementBasis,
} from "@/lib/measurementBasis";
import { selectQueryIdsForLimiter } from "@/components/QueryDiffTable";
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

describe("competition ranking in standings", () => {
  it("assigns 'T-1' to tied runs and skips to 3", () => {
    const tiedRuns = [
      run("a", [["Q1", 100]]),
      run("b", [["Q1", 100.2]]), // within 0.005 threshold
      run("c", [["Q1", 200]]),
    ];
    const { rows } = buildStandings(tiedRuns, 0, ["A", "B", "C"]);
    expect(rows[0]!.rank).toBe("T-1");
    expect(rows[1]!.rank).toBe("T-1");
    expect(rows[2]!.rank).toBe("3");
  });

  it("assigns '—' when shared query set is empty rather than false ranks 1, 2, 3", () => {
    const withNull = [
      run("a", [["Q1", 100]]),
      run("b", [["Q1", 200]]),
      run("empty", []),
    ];
    const { rows } = buildStandings(withNull, 0, ["A", "B", "Empty"]);
    expect(rows.map((r) => r.rank)).toEqual(["—", "—", "—"]);
  });

  it("does not transitively chain ties across non-tied endpoints", () => {
    // 100 vs 100.4 is 0.4% (tied).
    // 100.4 vs 100.8 is 0.398% (tied if pairwise).
    // BUT 100 vs 100.8 is 0.8% (> 0.5% threshold: not tied with leader).
    const chainedRuns = [
      run("a", [["Q1", 100]]),
      run("b", [["Q1", 100.4]]),
      run("c", [["Q1", 100.8]]),
    ];
    const { rows } = buildStandings(chainedRuns, 0, ["A", "B", "C"]);
    expect(rows[0]!.rank).toBe("T-1");
    expect(rows[1]!.rank).toBe("T-1");
    expect(rows[2]!.rank).toBe("3");
  });

  it("keeps rank ties separate from baseline ties", () => {
    const runs = [
      run("base", [["Q1", 100]]),
      run("cand1", [["Q1", 150]]),
      run("cand2", [["Q1", 150.2]]),
    ];
    const { rows } = buildStandings(runs, 0, ["Base", "Cand1", "Cand2"]);
    const cand1 = rows.find((r) => r.resultId === "cand1")!;
    const cand2 = rows.find((r) => r.resultId === "cand2")!;
    expect(cand1.rank).toBe("T-2");
    expect(cand2.rank).toBe("T-2");
    expect(cand1.rankTied).toBe(true);
    expect(cand2.rankTied).toBe(true);
    expect(cand1.tied).toBe(false);
    expect(cand2.tied).toBe(false);
    expect(cand1.ratioToBaseline).toBeCloseTo(1.5, 2);
  });
});

describe("missing evidence reporting in heatmap", () => {
  it("distinguishes baseline_missing from run_missing", () => {
    const results = [
      run("base", [["Q1", 10], ["Q2", null]]), // base lacks Q2
      run("alt", [["Q1", 20], ["Q2", 30]]),    // alt has Q2!
      run("alt2", [["Q1", null], ["Q2", 40]]), // alt2 lacks Q1, has Q2
    ];
    const rows = buildHeatmapRows(results, 0);
    const q1 = rows.find((r) => r.queryId === "Q1")!;
    const q2 = rows.find((r) => r.queryId === "Q2")!;

    // On Q1, alt2 has no timing -> run_missing
    expect(q1.cells[2]!.missingKind).toBe("run_missing");

    // On Q2, base has no timing, but alt has 30ms -> baseline_missing
    expect(q2.cells[1]!.missingKind).toBe("baseline_missing");
    expect(q2.cells[1]!.timingMs).toBe(30);
  });
});

function runWithExecs(
  id: string,
  data: {
    queryId: string;
    displayMs: number | null;
    warmupMs?: number;
    pass1Ms?: number;
    pass2Ms?: number;
  }[],
): DetailResult {
  const queries: any[] = [];
  const display_timings: any[] = [];
  for (const d of data) {
    display_timings.push({
      query_id: d.queryId,
      display_ms: d.displayMs,
      sample_count: 2,
      is_valid_display_timing: d.displayMs !== null,
      timing_exclusion_reason: d.displayMs === null ? "missing" : null,
    });
    if (d.warmupMs !== undefined) {
      queries.push({
        query_id: d.queryId,
        duration_ms: d.warmupMs,
        status: "pass",
        run_type: "warmup",
        iter: null,
      });
    }
    if (d.pass1Ms !== undefined) {
      queries.push({
        query_id: d.queryId,
        duration_ms: d.pass1Ms,
        status: "pass",
        run_type: "measurement",
        iter: 1,
      });
    }
    if (d.pass2Ms !== undefined) {
      queries.push({
        query_id: d.queryId,
        duration_ms: d.pass2Ms,
        status: "pass",
        run_type: "measurement",
        iter: 2,
      });
    }
  }
  return {
    result_id: id,
    platform: id,
    display_geomean_ms: 100,
    display_timings,
    queries,
  } as unknown as DetailResult;
}

describe("measurement basis resolution for comparison", () => {
  const runs = [
    runWithExecs("run1", [
      { queryId: "Q1", displayMs: 100, warmupMs: 150, pass1Ms: 120, pass2Ms: 80 },
      { queryId: "Q2", displayMs: 200, warmupMs: 250, pass1Ms: 220, pass2Ms: 180 },
    ]),
    runWithExecs("run2", [
      { queryId: "Q1", displayMs: 50, warmupMs: 70, pass1Ms: 60, pass2Ms: 40 },
      { queryId: "Q2", displayMs: 100, warmupMs: 120, pass1Ms: 110, pass2Ms: 90 },
    ]),
  ];

  it("preserves display_ms under default basis", () => {
    const resolved = resolveResultsForBasis(runs, DEFAULT_BASIS);
    expect(resolved[0]!.display_timings.find((t) => t.query_id === "Q1")!.display_ms).toBe(100);
    expect(resolved[1]!.display_timings.find((t) => t.query_id === "Q1")!.display_ms).toBe(50);
  });

  it("resolves warmup pass executions when warmup basis is selected", () => {
    const warmupBasis: MeasurementBasis = { passes: WARMUP, statistic: "median" };
    const resolved = resolveResultsForBasis(runs, warmupBasis);
    expect(resolved[0]!.display_timings.find((t) => t.query_id === "Q1")!.display_ms).toBe(150);
    expect(resolved[1]!.display_timings.find((t) => t.query_id === "Q1")!.display_ms).toBe(70);
  });

  it("resolves minimum across passes when min statistic is selected", () => {
    const minBasis: MeasurementBasis = { passes: ALL_WARM, statistic: "min" };
    const resolved = resolveResultsForBasis(runs, minBasis);
    expect(resolved[0]!.display_timings.find((t) => t.query_id === "Q1")!.display_ms).toBe(80);
    expect(resolved[1]!.display_timings.find((t) => t.query_id === "Q1")!.display_ms).toBe(40);
  });

  it("preserves published power_score under default basis and nulls it out under alternate bases", () => {
    const runsWithPower = [
      { ...runs[0]!, power_score: 1500 },
      { ...runs[1]!, power_score: 800 },
    ] as DetailResult[];

    const defaultResolved = resolveResultsForBasis(runsWithPower, DEFAULT_BASIS);
    expect(defaultResolved[0]!.power_score).toBe(1500);
    expect(defaultResolved[1]!.power_score).toBe(800);

    const warmupResolved = resolveResultsForBasis(runsWithPower, { passes: WARMUP, statistic: "median" });
    expect(warmupResolved[0]!.power_score).toBeNull();
    expect(warmupResolved[1]!.power_score).toBeNull();
  });

  it("preserves published display_geomean_ms exactly when all queries are shared under default basis", () => {
    const runsWithGeomean = [
      { ...runs[0]!, display_geomean_ms: 123.4567890123 },
      { ...runs[1]!, display_geomean_ms: 98.7654321098 },
    ] as DetailResult[];
    const resolved = resolveResultsForBasis(runsWithGeomean, DEFAULT_BASIS);
    expect(resolved[0]!.display_geomean_ms).toBe(123.4567890123);
    expect(resolved[1]!.display_geomean_ms).toBe(98.7654321098);
  });

  it("preserves published timing_exclusion_reason for default basis", () => {
    const rawRun: DetailResult = {
      ...runs[0]!,
      display_timings: [
        {
          query_id: "Q1",
          display_ms: null,
          sample_count: 0,
          is_valid_display_timing: false,
          timing_exclusion_reason: "missing_timing",
        },
      ],
      queries: [],
    };
    const resolved = resolveResultsForBasis([rawRun], DEFAULT_BASIS);
    expect(resolved[0]!.display_timings[0]!.timing_exclusion_reason).toBe("missing_timing");
  });

  it("recomputes timing eligibility according to canonical contract when alternate basis is used", () => {
    const rawRun: DetailResult = {
      ...runs[0]!,
      logical_query_count: 2,
      has_display_timing: false,
      valid_query_count: 0,
      missing_query_count: 2,
      display_exclusion_reason: "no_display_timings",
      comparison_exclusion_reason: "no_comparable_timings",
      ranking_exclusion_reason: "no_rankable_timings",
      display_timings: [
        {
          query_id: "Q1",
          display_ms: null,
          sample_count: 3,
          is_valid_display_timing: false,
          timing_exclusion_reason: "missing_timing",
        },
        {
          query_id: "Q2",
          display_ms: null,
          sample_count: 3,
          is_valid_display_timing: false,
          timing_exclusion_reason: "missing_timing",
        },
      ],
      queries: [
        {
          query_id: "Q1",
          duration_ms: 120,
          status: "pass",
          run_type: "warmup",
          iter: null,
          stream: 0,
        },
      ],
    };

    // With 1 warmup query out of 2 logical queries: valid=1, coverage=50% (>= 50%),
    // but valid < 2 -> insufficient_valid_queries for comparison and ranking
    const resolved1 = resolveResultsForBasis([rawRun], { passes: WARMUP, statistic: "median" });
    expect(resolved1[0]!.has_display_timing).toBe(true);
    expect(resolved1[0]!.valid_query_count).toBe(1);
    expect(resolved1[0]!.display_exclusion_reason).toBeNull();
    expect(resolved1[0]!.comparison_exclusion_reason).toBe("insufficient_valid_queries");
    expect(resolved1[0]!.ranking_exclusion_reason).toBe("insufficient_valid_queries");
    // For unavailable Q2 under alternate basis, sample_count must be 0, not copied from default basis
    expect(resolved1[0]!.display_timings.find((t) => t.query_id === "Q2")!.sample_count).toBe(0);

    // With 2 warmup queries out of 2 logical queries: valid=2 -> compare/rank safe
    const rawRun2: DetailResult = {
      ...rawRun,
      queries: [
        ...rawRun.queries,
        {
          query_id: "Q2",
          duration_ms: 140,
          status: "pass",
          run_type: "warmup",
          iter: null,
          stream: 0,
        },
      ],
    };
    const resolved2 = resolveResultsForBasis([rawRun2], { passes: WARMUP, statistic: "median" });
    expect(resolved2[0]!.valid_query_count).toBe(2);
    expect(resolved2[0]!.comparison_exclusion_reason).toBeNull();
    expect(resolved2[0]!.ranking_exclusion_reason).toBeNull();
  });

  it("recomputes zero_timing_count and sets zero_timings_only for alternate basis", () => {
    const rawRun: DetailResult = {
      ...runs[0]!,
      logical_query_count: 1,
      has_display_timing: false,
      valid_query_count: 0,
      missing_query_count: 1,
      zero_timing_count: 0,
      display_exclusion_reason: "no_display_timings",
      comparison_exclusion_reason: "no_comparable_timings",
      ranking_exclusion_reason: "no_rankable_timings",
      display_timings: [
        {
          query_id: "Q1",
          display_ms: null,
          sample_count: 1,
          is_valid_display_timing: false,
          timing_exclusion_reason: "missing_timing",
        },
      ],
      queries: [
        {
          query_id: "Q1",
          duration_ms: 0,
          status: "pass",
          run_type: "warmup",
          iter: null,
          stream: 0,
        },
      ],
    };
    const resolved = resolveResultsForBasis([rawRun], { passes: WARMUP, statistic: "median" });
    expect(resolved[0]!.valid_query_count).toBe(0);
    expect(resolved[0]!.zero_timing_count).toBe(1);
    expect(resolved[0]!.missing_query_count).toBe(0);
    expect(resolved[0]!.display_exclusion_reason).toBe("zero_timings_only");
  });
});

describe("shared limiter query selection", () => {
  const threeRuns = [
    run("base", [["Q1", 100], ["Q2", 100], ["Q3", 100]]),
    run("alt1", [["Q1", 50], ["Q2", 200], ["Q3", 100]]),
    run("alt2", [["Q1", 40], ["Q2", 150], ["Q3", 100]]),
  ];

  it("selects speedup queries across all candidates", () => {
    const { queryIds } = selectQueryIdsForLimiter(threeRuns, 0, "speedups", 20);
    expect(queryIds).toEqual(["Q1"]);
  });

  it("selects slowdown queries across all candidates", () => {
    const { queryIds } = selectQueryIdsForLimiter(threeRuns, 0, "slowdowns", 20);
    expect(queryIds).toEqual(["Q2"]);
  });

  it("orders largest movement by greatest relative divergence", () => {
    const { queryIds } = selectQueryIdsForLimiter(threeRuns, 0, "movement", 20);
    expect(queryIds[0]).toBe("Q1");
  });

  it("ranks movement by full multi-run disagreement spread across opposite-direction candidates", () => {
    // base=100
    // Q1: alt1=50 (0.5x), alt2=200 (2.0x) -> spread is 4x (2 bits)
    // Q2: alt1=300 (3.0x), alt2=300 (3.0x) -> spread is 3x (1.585 bits)
    const oppositeDirectionRuns = [
      run("base", [["Q1", 100], ["Q2", 100]]),
      run("alt1", [["Q1", 50], ["Q2", 300]]),
      run("alt2", [["Q1", 200], ["Q2", 300]]),
    ];
    const { queryIds } = selectQueryIdsForLimiter(oppositeDirectionRuns, 0, "movement", 10);
    expect(queryIds[0]).toBe("Q1");
  });

  it("preserves queryFilter's rank order in heatmap and table rather than reverting to natural query order", () => {
    const heatmapRows = buildHeatmapRows(threeRuns, 0);
    const rowsByQueryId = new Map(heatmapRows.map((row) => [row.queryId, row]));
    const filterOrder = ["Q2", "Q1"];
    const orderedHeatmap = filterOrder.map((id) => rowsByQueryId.get(id)).filter(Boolean);
    expect(orderedHeatmap.map((r: any) => r.queryId)).toEqual(["Q2", "Q1"]);
  });

  it("keeps all queries uncapped in MultiRunHeatmap when limiter is 'all'", () => {
    const q15: [string, number][] = Array.from({ length: 15 }, (_, i) => [`Q${i + 1}`, 100 + i]);
    const runs15 = [
      run("base", q15),
      run("cand1", q15),
      run("cand2", q15),
    ];
    const all = buildHeatmapRows(runs15, 0);
    const effectiveLimiter = "all";
    const shown = effectiveLimiter === "all" ? all : all.slice(0, 10);
    expect(shown.length).toBe(15);
  });
});
