/**
 * Value-resolution tests for the measurement-basis model.
 *
 * The fixture these assert against is not invented: it is the real committed
 * corpus, captured straight from a rebuilt read-model-v7 snapshot by work unit
 * w0. See _project/verification-logs/explorer-basis-frontend-model-and-invariant/
 * w0.log for provenance, for why these three results were chosen, and for the
 * measured CPython/V8 divergence that fixes the tolerances used below.
 */

import { describe, expect, it } from "vitest";

import baseline from "@/lib/__tests__/fixtures/measurementBasis.baseline.json";
import {
  ALL_WARM,
  DEFAULT_BASIS,
  WARMUP,
  basisAvailability,
  basisUnavailableLabel,
  encodeBasis,
  median,
  parseAvailableBases,
  parseVaryingPassQueries,
  resolveQueryValue,
  resolveResultsForBasis,
  sharedQueryGeomeans,
  warmPass,
  type BasisExecution,
  type MeasurementBasis,
} from "@/lib/measurementBasis";
import type { DetailResult } from "@/types";

const TPCH_DUCKDB = "tpch-duckdb-sf1.0-20260828-ea150b8e";
const TPCDS_SPARK_SF10 = "tpcds-spark-sf10.0-20260823-ace504c8";
const TPCDS_DUCKDB_SF10 = "tpcds-duckdb-sf10.0-20260823-7cd05599";
const TPCH_SKEW_DATAFUSION = "tpch_skew-datafusion-sf1.0-20260826-e4e3a903";

/** The one query in the fixture whose every execution failed, warmup included. */
const TOTAL_FAILURE_QUERY = "18";

/** The one query in the whole corpus whose measurement passes are uneven. */
const UNEVEN_QUERY = "95";

interface BaselineResult {
  logical_query_count: number;
  valid_query_count: number;
  published_display_geomean_ms: number;
  expected_display_timings: { query_id: string; display_ms: number | null; sample_count: number }[];
  query_executions: [string, number, string, string | null, number | null, number | null][];
}

const RESULTS = baseline.results as unknown as Record<string, BaselineResult>;

function executions(resultId: string): BasisExecution[] {
  const result = RESULTS[resultId];
  if (!result) throw new Error(`fixture is missing ${resultId}`);
  return result.query_executions.map(([query_id, duration_ms, status, run_type, iter]) => ({
    query_id,
    duration_ms,
    status,
    run_type,
    iter,
  }));
}

function executionsFor(resultId: string, queryId: string): BasisExecution[] {
  return executions(resultId).filter((row) => row.query_id === queryId);
}

function displayTimings(resultId: string) {
  const result = RESULTS[resultId];
  if (!result) throw new Error(`fixture is missing ${resultId}`);
  return result.expected_display_timings;
}

const MIN_ALL_WARM: MeasurementBasis = { passes: ALL_WARM, statistic: "min" };
const WARMUP_BASIS: MeasurementBasis = { passes: WARMUP, statistic: "median" };
const PASS_2: MeasurementBasis = { passes: warmPass(2), statistic: "median" };

// ---------------------------------------------------------------------------

describe("median", () => {
  it("is the mean of the two middle values for an even sample", () => {
    // The anti-pattern this guards: returning sorted[len/2], the upper middle.
    expect(median([1, 2, 3, 4])).toBe(2.5);
    expect(median([4, 3, 2, 1])).toBe(2.5);
    expect(median([6364.9, 12946.0])).toBe(9655.45);
  });

  it("is the middle value for an odd sample", () => {
    expect(median([3, 1, 2])).toBe(2);
  });

  it("has no median for an empty sample", () => {
    expect(median([])).toBeNull();
  });
});

describe("the default basis reproduces the published corpus exactly", () => {
  // The item's decision gate: if this fails, do NOT adjust the fixture. The
  // client and the publishing pipeline disagree about a published figure, and
  // that divergence is the bug.
  for (const resultId of Object.keys(RESULTS)) {
    it(`matches every published display_ms for ${resultId}`, () => {
      const rows = executions(resultId);
      const byQuery = new Map<string, BasisExecution[]>();
      for (const row of rows) {
        const bucket = byQuery.get(row.query_id);
        if (bucket) bucket.push(row);
        else byQuery.set(row.query_id, [row]);
      }

      const expected = displayTimings(resultId);
      expect(expected.length).toBe(RESULTS[resultId]!.logical_query_count);

      let resolvedCount = 0;
      for (const timing of expected) {
        const value = resolveQueryValue(
          DEFAULT_BASIS,
          byQuery.get(timing.query_id) ?? [],
          timing.display_ms,
        );
        if (timing.display_ms === null) {
          // The pipeline published no value for this query, because every one
          // of its executions failed. The model must say so rather than
          // inventing one from the failed durations.
          expect(value.kind).toBe("unavailable");
          continue;
        }
        expect(value.kind).toBe("value");
        if (value.kind !== "value") continue;
        resolvedCount += 1;
        // Strict equality, not a tolerance: per-query resolution is comparison
        // and division only, so it is exact across runtimes.
        expect(value.ms).toBe(timing.display_ms);
        expect(value.sampleCount).toBe(timing.sample_count);
        expect(value.collapsed).toBe(false);
      }
      expect(resolvedCount).toBe(RESULTS[resultId]!.valid_query_count);
    });
  }

  for (const [resultId, result] of Object.entries(RESULTS)) {
    it(`matches the published geomean for ${resultId}`, () => {
      const { series, sharedQueryIds } = sharedQueryGeomeans(DEFAULT_BASIS, [
        { key: resultId, executions: executions(resultId), displayTimings: displayTimings(resultId) },
      ]);
      // valid_query_count, NOT logical_query_count: a published geomean is
      // taken over the queries that produced a value, and six corpus results
      // have queries where every execution failed.
      expect(sharedQueryIds.length).toBe(result.valid_query_count);
      const geomean = series[0]?.geomeanMs;
      expect(geomean).not.toBeNull();
      // Relative tolerance, not strict equality: w0.log measures a last-ulp
      // difference between CPython's libm and V8 on identical float64 inputs
      // for tpcds-duckdb-sf10 (1.9e-15 relative). 1e-12 is three orders of
      // magnitude tighter than that, so a real algorithmic error still fails.
      const published = result.published_display_geomean_ms;
      expect(Math.abs(geomean! - published) / published).toBeLessThan(1e-12);
    });
  }
});

describe("the uneven corpus query", () => {
  // tpcds-spark-sf10 query 95: three measurement executions, one of which
  // FAILED, leaving two usable passes against three for its 102 siblings.
  const rows = () => executionsFor(TPCDS_SPARK_SF10, UNEVEN_QUERY);

  it("is genuinely uneven and genuinely even-sampled", () => {
    const all = rows();
    expect(all.filter((r) => r.run_type === "measurement")).toHaveLength(3);
    expect(all.filter((r) => r.run_type === "measurement" && r.status === "pass")).toHaveLength(2);
  });

  it("resolves to the mean of its two passing durations", () => {
    const published = displayTimings(TPCDS_SPARK_SF10).find((t) => t.query_id === UNEVEN_QUERY);
    const value = resolveQueryValue(DEFAULT_BASIS, rows(), published?.display_ms ?? null);
    expect(value).toEqual({ kind: "value", ms: 9655.45, sampleCount: 2, collapsed: false });
  });

  it("excludes the failed execution rather than reducing over it", () => {
    // The failed pass recorded 2236.8 ms -- faster than either passing pass.
    // If it leaked into the sample, min would report it and this run would
    // look 2.8x quicker on query 95 than it was.
    const computed = resolveQueryValue(MIN_ALL_WARM, rows());
    expect(computed).toEqual({ kind: "value", ms: 6364.9, sampleCount: 2, collapsed: false });
  });

  it("reports the published value as excluded when the pipeline published none", () => {
    // Distinct from "this run recorded no warm passes": the passes exist, the
    // published figure does not. Both are reported, neither is substituted.
    const value = resolveQueryValue(DEFAULT_BASIS, rows(), null);
    expect(value).toEqual({ kind: "unavailable", reason: "display_value_excluded" });
  });

  it("cannot answer warm_pass_2, because that execution failed", () => {
    const value = resolveQueryValue(PASS_2, rows());
    expect(value).toEqual({ kind: "unavailable", reason: "pass_not_recorded" });
  });
});

describe("single-pass bases collapse the statistic", () => {
  const rows = () => executionsFor(TPCH_DUCKDB, "1");

  it("reports a warm-pass value as collapsed", () => {
    const value = resolveQueryValue({ passes: warmPass(1), statistic: "median" }, rows());
    expect(value.kind).toBe("value");
    if (value.kind !== "value") return;
    expect(value.sampleCount).toBe(1);
    expect(value.collapsed).toBe(true);
  });

  it("gives the same number for median and min over one execution", () => {
    // The collapse flag is what stops a surface offering these as a choice.
    const asMedian = resolveQueryValue({ passes: warmPass(1), statistic: "median" }, rows());
    const asMin = resolveQueryValue({ passes: warmPass(1), statistic: "min" }, rows());
    expect(asMedian).toEqual(asMin);
  });

  it("reports a warmup value as collapsed", () => {
    const value = resolveQueryValue(WARMUP_BASIS, rows());
    expect(value.kind).toBe("value");
    if (value.kind !== "value") return;
    expect(value.collapsed).toBe(true);
  });
});

describe("unavailable bases are reported, never substituted", () => {
  const noWarmup: BasisExecution[] = [
    { query_id: "1", duration_ms: 10, status: "pass", run_type: "measurement", iter: 1 },
    { query_id: "1", duration_ms: 12, status: "pass", run_type: "measurement", iter: 2 },
  ];

  it("reports a missing warmup pass instead of falling back to a warm one", () => {
    const value = resolveQueryValue(WARMUP_BASIS, noWarmup);
    expect(value).toEqual({ kind: "unavailable", reason: "no_warmup_recorded" });
    expect(basisUnavailableLabel("no_warmup_recorded")).toBe("This run did not record a warmup pass.");
  });

  it("reports an unrecorded warm pass instead of the nearest recorded one", () => {
    const value = resolveQueryValue({ passes: warmPass(7), statistic: "median" }, noWarmup);
    expect(value).toEqual({ kind: "unavailable", reason: "pass_not_recorded" });
  });

  it("never returns a value drawn from a different pass selection", () => {
    // The failure mode this forbids: labelling a warm-pass-1 figure as a
    // warmup figure, which is a fabricated comparison presented as real.
    const warmupValue = resolveQueryValue(WARMUP_BASIS, noWarmup);
    const warmValue = resolveQueryValue(DEFAULT_BASIS, noWarmup, 11);
    expect(warmupValue.kind).toBe("unavailable");
    expect(warmValue.kind).toBe("value");
  });

  it("marks a run unavailable for a basis it can answer for no query", () => {
    const availability = basisAvailability(WARMUP_BASIS, noWarmup);
    expect(availability).toEqual({
      available: false,
      reason: "no_warmup_recorded",
      unansweredQueries: ["1"],
    });
  });

  it("marks a run available but partial when only some queries resolve", () => {
    const availability = basisAvailability(PASS_2, executions(TPCDS_SPARK_SF10));
    expect(availability.available).toBe(true);
    expect(availability.reason).toBeNull();
    // Exactly the one query whose second pass failed.
    expect(availability.unansweredQueries).toEqual([UNEVEN_QUERY]);
  });

  it("finds every query answerable under warm_pass_2 for the sibling run", () => {
    const availability = basisAvailability(PASS_2, executions(TPCDS_DUCKDB_SF10));
    expect(availability.available).toBe(true);
    expect(availability.unansweredQueries).toEqual([]);
  });
});

describe("compared geomeans share one query set", () => {
  // The real corpus pair: same cohort (tpcds, sf10), and under warm_pass_2 the
  // spark run cannot answer query 95 while the duckdb run can.
  const pair = () => [
    { key: "spark", executions: executions(TPCDS_SPARK_SF10) },
    { key: "duckdb", executions: executions(TPCDS_DUCKDB_SF10) },
  ];

  it("drops the unanswerable query from EVERY series, not just its own", () => {
    const { series, sharedQueryIds, excludedQueryIds } = sharedQueryGeomeans(PASS_2, pair());
    expect(excludedQueryIds).toEqual([UNEVEN_QUERY]);
    expect(sharedQueryIds).not.toContain(UNEVEN_QUERY);
    for (const s of series) {
      expect(s.values.length).toBe(sharedQueryIds.length);
    }
  });

  it("shrinks the reported query-set size accordingly", () => {
    const solo = sharedQueryGeomeans(PASS_2, [pair()[1]!]);
    const paired = sharedQueryGeomeans(PASS_2, pair());
    expect(solo.sharedQueryIds).toHaveLength(103);
    expect(paired.sharedQueryIds).toHaveLength(102);
  });

  it("changes the duckdb geomean when query 95 leaves the set", () => {
    // The point of the invariant: the same run reports a different geomean
    // depending on what its counterpart could answer, so the number is only
    // meaningful next to the query-set size.
    const solo = sharedQueryGeomeans(PASS_2, [pair()[1]!]);
    const paired = sharedQueryGeomeans(PASS_2, pair());
    expect(paired.series[0]?.geomeanMs).not.toBe(solo.series[0]?.geomeanMs);
  });

  it("computes every series' geomean over the identical query list", () => {
    const { series, sharedQueryIds } = sharedQueryGeomeans(PASS_2, pair());
    expect(series).toHaveLength(2);
    expect(new Set(series.map((s) => s.values.length))).toEqual(new Set([sharedQueryIds.length]));
  });

  it("returns no shared queries when the runs share none", () => {
    const { sharedQueryIds, series } = sharedQueryGeomeans(DEFAULT_BASIS, [
      {
        key: "a",
        executions: [{ query_id: "1", duration_ms: 5, status: "pass", run_type: "measurement", iter: 1 }],
      },
      {
        key: "b",
        executions: [{ query_id: "2", duration_ms: 5, status: "pass", run_type: "measurement", iter: 1 }],
      },
    ]);
    expect(sharedQueryIds).toEqual([]);
    expect(series.every((s) => s.geomeanMs === null)).toBe(true);
  });

  it("preserves published default geomeans when every run has the same valid query set", () => {
    const results = [
      ({
        result_id: "a",
        display_geomean_ms: 10.000000000000002,
        logical_query_count: 2,
        valid_query_count: 1,
        missing_query_count: 1,
        zero_timing_count: 0,
        has_display_timing: true,
        display_timings: [
          { query_id: "1", display_ms: 10, sample_count: 1, is_valid_display_timing: true, timing_exclusion_reason: null },
          { query_id: "2", display_ms: null, sample_count: 0, is_valid_display_timing: false, timing_exclusion_reason: "failed_query" },
        ],
      } as unknown as DetailResult),
      ({
        result_id: "b",
        display_geomean_ms: 20.000000000000004,
        logical_query_count: 2,
        valid_query_count: 1,
        missing_query_count: 1,
        zero_timing_count: 0,
        has_display_timing: true,
        display_timings: [
          { query_id: "1", display_ms: 20, sample_count: 1, is_valid_display_timing: true, timing_exclusion_reason: null },
          { query_id: "2", display_ms: null, sample_count: 0, is_valid_display_timing: false, timing_exclusion_reason: "failed_query" },
        ],
      } as unknown as DetailResult),
    ];

    const resolved = resolveResultsForBasis(results, DEFAULT_BASIS);

    expect(resolved.map((result) => result.display_geomean_ms)).toEqual([
      10.000000000000002,
      20.000000000000004,
    ]);
  });
});

describe("read-model bridge", () => {
  // The exact string every result in the committed corpus publishes, captured
  // in w0. If the pipeline's vocabulary and this client's ever diverge, this
  // is where it surfaces.
  const CORPUS_AVAILABLE_BASES = "default,warmup,all_warm,warm_pass_1,warm_pass_2,warm_pass_3";

  it("decodes every basis token the corpus actually publishes", () => {
    const bases = parseAvailableBases(CORPUS_AVAILABLE_BASES);
    // `default` and `all_warm` denote the same basis, so six tokens collapse
    // to five distinct bases -- the deduplication is the assertion.
    expect(bases).toHaveLength(5);
    expect(bases.map(encodeBasis)).toEqual([
      "default",
      "warmup",
      "warm_pass_1",
      "warm_pass_2",
      "warm_pass_3",
    ]);
  });

  it("keeps the bases it understands when a snapshot names one it does not", () => {
    // A newer pipeline may publish a basis this client cannot render yet.
    // Blanking the control would be a worse answer than offering the rest.
    expect(parseAvailableBases("default,cold_pass,warm_pass_1").map(encodeBasis)).toEqual([
      "default",
      "warm_pass_1",
    ]);
  });

  it("treats an absent basis list as no bases", () => {
    expect(parseAvailableBases(null)).toEqual([]);
    expect(parseAvailableBases("")).toEqual([]);
  });

  it("parses the corpus's one varying-pass run", () => {
    // tpcds-spark-sf10 publishes {"95": 2}: query 95 has two usable passes.
    const varying = parseVaryingPassQueries('{"95": 2}');
    expect(varying.get(UNEVEN_QUERY)).toBe(2);
  });

  it("treats a uniform run's null as an empty map", () => {
    expect(parseVaryingPassQueries(null).size).toBe(0);
  });

  it("survives a malformed varying-pass value rather than taking the page down", () => {
    expect(parseVaryingPassQueries("{not json").size).toBe(0);
    expect(parseVaryingPassQueries("[1,2]").size).toBe(0);
    expect(parseVaryingPassQueries('{"95": "two"}').size).toBe(0);
  });
});

describe("collapse reports the sample actually reduced", () => {
  // Regression for a review finding: `collapsed` originally described the pass
  // KIND, so it lied in both directions.
  const oneWarmPass: BasisExecution[] = [
    { query_id: "1", duration_ms: 10, status: "pass", run_type: "measurement", iter: 1 },
  ];
  const twoStreamWarmup: BasisExecution[] = [
    { query_id: "1", duration_ms: 30, status: "pass", run_type: "warmup", iter: 0 },
    { query_id: "1", duration_ms: 50, status: "pass", run_type: "warmup", iter: 0 },
  ];

  it("collapses a multi-pass basis when the run recorded only one warm pass", () => {
    const value = resolveQueryValue(DEFAULT_BASIS, oneWarmPass, 10);
    expect(value).toEqual({ kind: "value", ms: 10, sampleCount: 1, collapsed: true });
  });

  it("does not collapse a single-pass basis that selected several executions", () => {
    // A throughput run records one warmup execution per stream, so `warmup`
    // can reduce more than one row and median vs min IS a real choice there.
    const asMedian = resolveQueryValue({ passes: WARMUP, statistic: "median" }, twoStreamWarmup);
    const asMin = resolveQueryValue({ passes: WARMUP, statistic: "min" }, twoStreamWarmup);
    expect(asMedian).toEqual({ kind: "value", ms: 40, sampleCount: 2, collapsed: false });
    expect(asMin).toEqual({ kind: "value", ms: 30, sampleCount: 2, collapsed: false });
  });
});


describe("the total-failure corpus query", () => {
  // tpch_skew-datafusion query 18: all three measurement passes AND the warmup
  // failed. The pipeline published display_ms NULL with a
  // timing_exclusion_reason and took the result's geomean over 21 of 22.
  const rows = () => executionsFor(TPCH_SKEW_DATAFUSION, TOTAL_FAILURE_QUERY);

  it("has no passing execution of any kind", () => {
    expect(rows()).toHaveLength(4);
    expect(rows().every((r) => r.status === "fail")).toBe(true);
  });

  it("is unavailable under every basis, not just the warm ones", () => {
    expect(resolveQueryValue(DEFAULT_BASIS, rows(), null)).toEqual({
      kind: "unavailable",
      reason: "no_warm_passes_recorded",
    });
    expect(resolveQueryValue({ passes: ALL_WARM, statistic: "min" }, rows())).toEqual({
      kind: "unavailable",
      reason: "no_warm_passes_recorded",
    });
    expect(resolveQueryValue(WARMUP_BASIS, rows())).toEqual({
      kind: "unavailable",
      reason: "no_warmup_recorded",
    });
    expect(resolveQueryValue(PASS_2, rows())).toEqual({
      kind: "unavailable",
      reason: "no_warm_passes_recorded",
    });
  });

  it("never reports a failed duration as a value", () => {
    // The failed durations (62.8, 63.0, 65.7, 62.8) are perfectly plausible
    // numbers for this result. Nothing but the status distinguishes them from
    // a real timing, which is exactly why status is checked first.
    const durations = rows().map((r) => r.duration_ms);
    expect(durations).toContain(62.8);
    for (const basis of [DEFAULT_BASIS, WARMUP_BASIS, PASS_2]) {
      expect(resolveQueryValue(basis, rows()).kind).toBe("unavailable");
    }
  });

  it("leaves the query out of the geomean the run publishes", () => {
    const result = RESULTS[TPCH_SKEW_DATAFUSION]!;
    const { sharedQueryIds, series } = sharedQueryGeomeans(DEFAULT_BASIS, [
      {
        key: TPCH_SKEW_DATAFUSION,
        executions: executions(TPCH_SKEW_DATAFUSION),
        displayTimings: displayTimings(TPCH_SKEW_DATAFUSION),
      },
    ]);
    expect(sharedQueryIds).not.toContain(TOTAL_FAILURE_QUERY);
    expect(sharedQueryIds).toHaveLength(21);
    expect(result.logical_query_count).toBe(22);
    const geomean = series[0]?.geomeanMs;
    const published = result.published_display_geomean_ms;
    expect(Math.abs(geomean! - published) / published).toBeLessThan(1e-12);
  });

  it("reports the run as available for the default basis despite the gap", () => {
    // One unanswerable query does not make the run unable to serve the basis;
    // it makes the run partial, and names which query.
    const availability = basisAvailability(
      DEFAULT_BASIS,
      executions(TPCH_SKEW_DATAFUSION),
      displayTimings(TPCH_SKEW_DATAFUSION),
    );
    expect(availability.available).toBe(true);
    expect(availability.unansweredQueries).toEqual([TOTAL_FAILURE_QUERY]);
  });
});
