/**
 * measurementBasis - the explorer's measurement-basis model.
 *
 * Every timing figure on every comparison surface is a function of
 * `(run, passes, statistic)`. Before this module the explorer had exactly one
 * reduction -- the median of measurement passes, precomputed by the pipeline
 * into `display_timings[].display_ms` -- and no vocabulary for saying so. This
 * module names it, generalises it, and enforces the two invariants that make
 * the generalisation safe.
 *
 * INVARIANT 1 - one basis per cross-run comparison.
 *   Reading one run's min against another run's median measures the statistic,
 *   not the engine. A cross-run comparison therefore holds N runs and exactly
 *   ONE basis. Only a within-run comparison may vary the basis per series;
 *   there the engine and hardware are fixed by construction, so the basis
 *   variation is the subject rather than a confound.
 *
 *   This is enforced by the SHAPE of the types, not by a validator. A
 *   `CrossRunSeries` has no basis field, so "series A at median, series B at
 *   min" is not a state this module can represent -- see
 *   `__tests__/measurementBasis.types.test.ts` for the compile-failure proof.
 *   A validator only fires where someone remembered to call it; a type that
 *   cannot express the illegal state removes the bug class from every current
 *   and future call site.
 *
 * INVARIANT 2 - compared geomeans share one query set.
 *   A query missing a pass on one series is excluded from EVERY series'
 *   geomean, not just its own. Geomeans over different query sets are not
 *   comparable. See `sharedQueryGeomeans` in the value-resolution section.
 *
 * Python reference for the default basis:
 *   _project/scripts/explorer_pipeline/transformer.py::_query_display_ms
 */

// ---------------------------------------------------------------------------
// Pass selection and statistic
// ---------------------------------------------------------------------------

/**
 * Which executions of a logical query a figure is computed over.
 *
 * - `all_warm`  every passing warm (measurement) pass
 * - `warmup`    the single warmup pass
 * - `warm_pass` one named warm pass, 1-indexed to match the pipeline's `iter`
 */
export type PassSelection =
  | { readonly kind: "all_warm" }
  | { readonly kind: "warmup" }
  | { readonly kind: "warm_pass"; readonly pass: number };

/** How multiple executions collapse to one value. */
export type BasisStatistic = "median" | "min";

export interface MeasurementBasis {
  readonly passes: PassSelection;
  readonly statistic: BasisStatistic;
}

export const ALL_WARM: PassSelection = { kind: "all_warm" };
export const WARMUP: PassSelection = { kind: "warmup" };
export const warmPass = (pass: number): PassSelection => ({ kind: "warm_pass", pass });

/**
 * The published basis: median over all warm passes, per unique query.
 *
 * This is the basis whose values the pipeline precomputes into `display_ms`
 * and publishes on the leaderboard. `resolveQueryValue` reads `display_ms`
 * for it rather than recomputing from raw rows -- see the note on that
 * function for why that distinction is load-bearing.
 */
export const DEFAULT_BASIS: MeasurementBasis = { passes: ALL_WARM, statistic: "median" };

/** True when `basis` is the published default basis. */
export function isDefaultBasis(basis: MeasurementBasis): boolean {
  return basis.passes.kind === "all_warm" && basis.statistic === "median";
}

/**
 * True when the pass selection names a single pass, so the statistic is not
 * expected to be a live choice.
 *
 * This is the a-priori signal, for a control that must decide whether to offer
 * a median/min toggle before it has any rows in hand. The authority for a
 * given query is `BasisValue.collapsed`, which reports the sample that was
 * actually reduced.
 */
export function isCollapsedStatistic(basis: MeasurementBasis): boolean {
  return basis.passes.kind !== "all_warm";
}

/**
 * Whether two bases select the same executions, ignoring the statistic.
 *
 * Availability is a property of the PASS SELECTION alone: a run either
 * recorded those executions or it did not. The statistic is applied
 * client-side over whatever the selection yields, so a run that can serve
 * `all_warm` can serve both the median and the min over it.
 */
export function passSelectionsEqual(a: PassSelection, b: PassSelection): boolean {
  if (a.kind !== b.kind) return false;
  if (a.kind === "warm_pass" && b.kind === "warm_pass") return a.pass === b.pass;
  return true;
}

export function basesEqual(a: MeasurementBasis, b: MeasurementBasis): boolean {
  return a.statistic === b.statistic && passSelectionsEqual(a.passes, b.passes);
}

// ---------------------------------------------------------------------------
// The comparison model - where the invariant lives
// ---------------------------------------------------------------------------

/**
 * One run in a cross-run comparison.
 *
 * DELIBERATELY carries no basis. This absence IS invariant 1: there is no
 * field in which a caller could put a per-series basis, so a cross-run
 * comparison with heterogeneous bases is not a representable value. Adding a
 * basis field here would reduce the invariant to a convention.
 */
export interface CrossRunSeries {
  readonly resultId: string;
  readonly label?: string;
}

/** One series in a within-run comparison: the same run under a different basis. */
export interface WithinRunSeries {
  readonly basis: MeasurementBasis;
  readonly label?: string;
}

/** At least two of T. Enforces the lower cardinality bound at compile time. */
type TwoOrMore<T> = readonly [T, T, ...T[]];

/** The upper cardinality bound, checked by the constructors. */
export const MAX_COMPARISON_SERIES = 4;

/**
 * Two to four runs, all read through exactly ONE basis.
 *
 * `basis` is singular and lives on the comparison, not on the series. That is
 * the whole point: the basis is a property of the comparison because it must
 * be shared by everything the comparison puts side by side.
 */
export interface CrossRunComparison {
  readonly kind: "cross_run";
  readonly runs: TwoOrMore<CrossRunSeries>;
  readonly basis: MeasurementBasis;
}

/**
 * One run under two to four different bases.
 *
 * Here the basis varies per series and that is legitimate: engine, hardware
 * and corpus are fixed by construction, so the basis is the subject of the
 * comparison rather than a confound in it.
 */
export interface WithinRunComparison {
  readonly kind: "within_run";
  readonly resultId: string;
  readonly series: TwoOrMore<WithinRunSeries>;
}

export type BasisComparison = CrossRunComparison | WithinRunComparison;

export type ComparisonError =
  | { readonly kind: "too_few_series"; readonly count: number }
  | { readonly kind: "too_many_series"; readonly count: number; readonly max: number }
  | { readonly kind: "duplicate_basis" };

export type ComparisonResult<T> =
  | { readonly ok: true; readonly comparison: T }
  | { readonly ok: false; readonly error: ComparisonError };

function cardinalityError(count: number): ComparisonError | null {
  if (count < 2) return { kind: "too_few_series", count };
  if (count > MAX_COMPARISON_SERIES) {
    return { kind: "too_many_series", count, max: MAX_COMPARISON_SERIES };
  }
  return null;
}

/**
 * Build a cross-run comparison from a runtime-sized list.
 *
 * The compile-time type already forbids fewer than two runs and has nowhere to
 * put a second basis; this constructor exists for the runtime path, where the
 * run list comes from user selection or a URL and its length is not known
 * statically.
 */
export function crossRunComparison(
  runs: readonly CrossRunSeries[],
  basis: MeasurementBasis,
): ComparisonResult<CrossRunComparison> {
  const error = cardinalityError(runs.length);
  if (error) return { ok: false, error };
  // Destructure into a real tuple rather than asserting one with a cast. A
  // constructor whose job is to guarantee "at least two" should not reach that
  // guarantee by telling the compiler to assume it.
  const [first, second, ...rest] = runs;
  if (!first || !second) return { ok: false, error: { kind: "too_few_series", count: runs.length } };
  return { ok: true, comparison: { kind: "cross_run", runs: [first, second, ...rest], basis } };
}

/**
 * Build a within-run comparison from a runtime-sized list of bases.
 *
 * Duplicate bases are rejected: two identical series would render as two
 * identical bars, which reads as corroboration rather than as the same figure
 * drawn twice.
 */
export function withinRunComparison(
  resultId: string,
  series: readonly WithinRunSeries[],
): ComparisonResult<WithinRunComparison> {
  const error = cardinalityError(series.length);
  if (error) return { ok: false, error };
  for (let i = 0; i < series.length; i += 1) {
    for (let j = i + 1; j < series.length; j += 1) {
      const a = series[i];
      const b = series[j];
      if (a && b && basesEqual(a.basis, b.basis)) {
        return { ok: false, error: { kind: "duplicate_basis" } };
      }
    }
  }
  const [first, second, ...rest] = series;
  if (!first || !second) {
    return { ok: false, error: { kind: "too_few_series", count: series.length } };
  }
  return {
    ok: true,
    comparison: { kind: "within_run", resultId, series: [first, second, ...rest] },
  };
}

/** Every basis a comparison reads, deduplicated. Length is 1 for cross-run. */
export function basesInComparison(comparison: BasisComparison): MeasurementBasis[] {
  if (comparison.kind === "cross_run") return [comparison.basis];
  const out: MeasurementBasis[] = [];
  for (const s of comparison.series) {
    if (!out.some((b) => basesEqual(b, s.basis))) out.push(s.basis);
  }
  return out;
}

// ---------------------------------------------------------------------------
// URL serde
// ---------------------------------------------------------------------------
//
// Grammar, pinned here so every surface spells a basis the same way and a
// shared link reproduces exactly the figures the sender saw:
//
//   basis-token := "default"
//                | ("all_warm" | "warmup" | "warm_pass_" <positive integer>)
//                  [":" statistic]
//   statistic   := "median" | "min"
//
// The pass vocabulary is deliberately the same as the read model's
// `result_basis_availability.available_bases`, so an availability check is a
// token comparison rather than a translation. The read model publishes pass
// selections only; the statistic is a client-side choice and is spelled here.
//
// `median` is the default and is left implicit, so `all_warm:median` and
// `warmup:median` canonicalise to `default` and `warmup` on encode. One
// spelling per basis keeps shared links stable and comparable.
//
// EVERY pass selection takes a statistic suffix, including the single-pass
// ones. An earlier version of this grammar rejected `warmup:min` on the
// reasoning that median and min over a sample of one are the same number --
// but nothing guarantees a sample of one. A throughput run records one warmup
// execution PER STREAM, so `warmup` can select several rows and median and min
// genuinely differ. Dropping the statistic there made `{warmup, min}`
// encode to `warmup` and decode back as `{warmup, median}`, so a shared link
// silently showed different numbers than the sender saw -- exactly the
// must-preserve rule this grammar exists to satisfy.
//
// `default` names one specific basis, so it takes no suffix; write
// `all_warm:min` for the other statistic over the same passes.
//
// Cross-run surfaces carry ONE `basis` parameter. The `bases` list parameter
// belongs only to the within-run route -- the URL grammar mirrors the type
// grammar, so a cross-run link cannot even spell a second basis.

import { geomeanMs } from "@/lib/chartMath";
import type { UrlSerde } from "@/lib/useUrlState";
import type { DetailResult, QueryDisplayTiming } from "@/types";

export const BASIS_URL_KEY = "basis";
export const BASES_URL_KEY = "bases";

const STATISTICS: readonly BasisStatistic[] = ["median", "min"];
const WARM_PASS_TOKEN = /^warm_pass_(\d+)$/;

function passToken(passes: PassSelection): string {
  switch (passes.kind) {
    case "all_warm":
      return "all_warm";
    case "warmup":
      return "warmup";
    case "warm_pass":
      return `warm_pass_${passes.pass}`;
  }
}

export function encodeBasis(basis: MeasurementBasis): string {
  if (isDefaultBasis(basis)) return "default";
  const token = passToken(basis.passes);
  // median is implicit; anything else must be spelled or the link lies.
  return basis.statistic === "median" ? token : `${token}:${basis.statistic}`;
}

export function decodeBasis(raw: string): MeasurementBasis | null {
  const [passTokenRaw, statisticToken, ...rest] = raw.split(":");
  if (rest.length > 0 || passTokenRaw === undefined) return null;
  const passToken = passTokenRaw;

  if (statisticToken !== undefined && !STATISTICS.includes(statisticToken as BasisStatistic)) {
    return null;
  }
  const statistic = (statisticToken ?? "median") as BasisStatistic;

  if (passToken === "default") {
    // `default` names one specific basis; a suffix would be redundant or a lie.
    return statisticToken === undefined ? DEFAULT_BASIS : null;
  }
  if (passToken === "all_warm") return { passes: ALL_WARM, statistic };
  if (passToken === "warmup") return { passes: WARMUP, statistic };
  const match = WARM_PASS_TOKEN.exec(passToken);
  if (match?.[1] !== undefined) {
    const pass = Number(match[1]);
    if (!Number.isInteger(pass) || pass < 1) return null;
    return { passes: warmPass(pass), statistic };
  }
  return null;
}

/** Serde for the single `basis` parameter that cross-run surfaces carry. */
export const basisSerde: UrlSerde<MeasurementBasis> = {
  encode: encodeBasis,
  decode: decodeBasis,
};

/**
 * Serde for the within-run route's `bases` list.
 *
 * Decoding is all-or-nothing: one unparseable token invalidates the whole
 * parameter rather than silently dropping a series, which would render a
 * three-series link as two series with no indication anything was lost.
 */
export const basesSerde: UrlSerde<MeasurementBasis[]> = {
  encode: (bases) => bases.map(encodeBasis).join(","),
  decode: (raw) => {
    if (raw === "") return [];
    const decoded = raw.split(",").map(decodeBasis);
    if (decoded.some((b) => b === null)) return null;
    return decoded as MeasurementBasis[];
  },
};

// ---------------------------------------------------------------------------
// Value resolution
// ---------------------------------------------------------------------------

/**
 * The execution-row shape this module reads.
 *
 * Structurally compatible with `QueryExecutionRow` from duckdbQueries, but
 * declared independently so the model stays a pure function of its inputs and
 * unit tests can build rows without a database.
 */
export interface BasisExecution {
  readonly query_id: string;
  readonly duration_ms: number;
  readonly status: string;
  readonly run_type: string | null;
  readonly iter: number | null;
}

/** The published per-query value, as read from `query_display_timings`. */
export interface BasisDisplayTiming {
  readonly query_id: string;
  readonly display_ms: number | null;
  readonly is_valid_display_timing?: boolean;
}

export type BasisUnavailableReason =
  | "no_warmup_recorded"
  | "no_warm_passes_recorded"
  | "pass_not_recorded"
  | "no_passing_executions"
  | "display_value_excluded";

const UNAVAILABLE_LABELS: Record<BasisUnavailableReason, string> = {
  no_warmup_recorded: "This run did not record a warmup pass.",
  no_warm_passes_recorded: "This run did not record any warm passes.",
  pass_not_recorded: "This run did not record that warm pass.",
  no_passing_executions: "No execution of this query passed under that basis.",
  display_value_excluded: "The published value for this query is excluded from display evidence.",
};

export function basisUnavailableLabel(reason: BasisUnavailableReason): string {
  return UNAVAILABLE_LABELS[reason];
}

/**
 * The value a run reports for one query under one basis.
 *
 * `unavailable` is a first-class outcome rather than a null, because the two
 * mean different things to a reader: "this run cannot answer that question"
 * is a fact worth showing, and the must-preserve rule forbids answering it
 * with some other basis's number instead.
 */
export type BasisValue =
  | { readonly kind: "value"; readonly ms: number; readonly sampleCount: number; readonly collapsed: boolean }
  | { readonly kind: "unavailable"; readonly reason: BasisUnavailableReason };

function isPassing(row: BasisExecution): boolean {
  return row.status === "pass";
}

/**
 * Warm (measurement) executions of a query.
 *
 * Mirrors `_query_display_ms`: prefer rows explicitly labelled `measurement`,
 * and fall back to unlabelled legacy rows only when no labelled ones exist.
 * Warmup rows are NEVER picked up by the fallback -- doing so would let a
 * warmup figure stand in for a measurement one in bundles whose measurement
 * executions all failed.
 */
function warmExecutions(rows: readonly BasisExecution[]): BasisExecution[] {
  const passing = rows.filter(isPassing);
  const measurement = passing.filter((r) => r.run_type === "measurement");
  if (measurement.length > 0) return measurement;
  return passing.filter((r) => r.run_type === null);
}

function warmupExecutions(rows: readonly BasisExecution[]): BasisExecution[] {
  return rows.filter((r) => isPassing(r) && r.run_type === "warmup");
}

/**
 * True median. For an even sample this is the mean of the two middle values,
 * NOT the upper middle element -- see w0.log, where a real corpus query
 * (tpcds-spark-sf10 query 95, whose second pass failed) has exactly two usable
 * passes and whose published value is their mean.
 */
export function median(values: readonly number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) return sorted[mid] ?? null;
  const lower = sorted[mid - 1];
  const upper = sorted[mid];
  if (lower === undefined || upper === undefined) return null;
  return (lower + upper) / 2;
}

function applyStatistic(values: readonly number[], statistic: BasisStatistic): number | null {
  if (values.length === 0) return null;
  return statistic === "min" ? Math.min(...values) : median(values);
}

/** Executions of one query that a given pass selection admits. */
function selectExecutions(
  rows: readonly BasisExecution[],
  passes: PassSelection,
): { rows: BasisExecution[]; missingReason: BasisUnavailableReason | null } {
  switch (passes.kind) {
    case "all_warm": {
      const warm = warmExecutions(rows);
      return { rows: warm, missingReason: warm.length === 0 ? "no_warm_passes_recorded" : null };
    }
    case "warmup": {
      const warmup = warmupExecutions(rows);
      return { rows: warmup, missingReason: warmup.length === 0 ? "no_warmup_recorded" : null };
    }
    case "warm_pass": {
      const warm = warmExecutions(rows);
      if (warm.length === 0) return { rows: [], missingReason: "no_warm_passes_recorded" };
      const named = warm.filter((r) => r.iter === passes.pass);
      return { rows: named, missingReason: named.length === 0 ? "pass_not_recorded" : null };
    }
  }
}

/**
 * Resolve one query's value under one basis.
 *
 * THE DEFAULT BASIS READS `display_ms` AND DOES NOT RECOMPUTE IT. The
 * published leaderboard figure comes from the Python pipeline; recomputing it
 * in the browser would put a second, independently-rounded arithmetic path
 * behind the headline number, so any float-ordering difference between the two
 * would surface as the explorer disagreeing with the leaderboard for no
 * visible reason. w0.log measures exactly that class of divergence: the same
 * geomean over the same float64 inputs differs in the last ulp between CPython
 * and V8. Non-default bases have no published counterpart, so those are
 * computed from raw rows -- there is nothing to disagree with.
 *
 * @param displayMs  the published value for this query, or null when the
 *                   pipeline recorded none. Only consulted for the default basis.
 */
export function resolveQueryValue(
  basis: MeasurementBasis,
  rows: readonly BasisExecution[],
  displayMs: number | null = null,
): BasisValue {
  if (isDefaultBasis(basis)) {
    const warm = warmExecutions(rows);
    if (displayMs !== null && Number.isFinite(displayMs) && displayMs > 0) {
      return { kind: "value", ms: displayMs, sampleCount: warm.length, collapsed: warm.length <= 1 };
    }
    // No usable published value. Which of these is true matters to a reader:
    // "this run recorded no warm passes" is a property of the run, whereas
    // "the pipeline excluded the published value" (a zero timing, say) is a
    // property of that one query's evidence. Neither is answered by
    // substituting some other basis's number.
    return {
      kind: "unavailable",
      reason: warm.length === 0 ? "no_warm_passes_recorded" : "display_value_excluded",
    };
  }

  const { rows: selected, missingReason } = selectExecutions(rows, basis.passes);
  if (missingReason !== null) return { kind: "unavailable", reason: missingReason };

  const value = applyStatistic(
    selected.map((r) => r.duration_ms).filter((ms) => Number.isFinite(ms) && ms > 0),
    basis.statistic,
  );
  if (value === null) return { kind: "unavailable", reason: "no_passing_executions" };
  // Derived from the sample actually reduced, not from the pass kind. A
  // throughput run records one warmup execution PER STREAM, so a nominally
  // single-pass basis can still reduce several rows; and a run with only one
  // warm pass collapses under `all_warm` even though the basis is multi-pass.
  // Either way, median and min over one value are the same number and a
  // surface must not offer them as a live choice.
  return { kind: "value", ms: value, sampleCount: selected.length, collapsed: selected.length <= 1 };
}

// ---------------------------------------------------------------------------
// Availability
// ---------------------------------------------------------------------------

export interface BasisAvailability {
  readonly available: boolean;
  readonly reason: BasisUnavailableReason | null;
  /** Queries the run cannot answer under this basis, sorted. */
  readonly unansweredQueries: readonly string[];
}

function groupByQuery(rows: readonly BasisExecution[]): Map<string, BasisExecution[]> {
  const byQuery = new Map<string, BasisExecution[]>();
  for (const row of rows) {
    const bucket = byQuery.get(row.query_id);
    if (bucket) bucket.push(row);
    else byQuery.set(row.query_id, [row]);
  }
  return byQuery;
}

/**
 * Whether a run can answer a basis, and for which queries it cannot.
 *
 * A run is "available" for a basis when at least one query resolves under it.
 * Partial availability is still reported through `unansweredQueries` -- that
 * list is what makes the same-query-set geomean rule enforceable, because it
 * names the queries every series must then drop.
 *
 * A basis a run cannot answer is NEVER silently replaced with the nearest one
 * that it can. Substituting would label, say, a warm-pass-1 figure as a warmup
 * figure: a fabricated comparison presented as a real one.
 */
export function basisAvailability(
  basis: MeasurementBasis,
  rows: readonly BasisExecution[],
  displayTimings: readonly BasisDisplayTiming[] = [],
): BasisAvailability {
  const displayByQuery = new Map(displayTimings.map((t) => [t.query_id, t]));
  const byQuery = groupByQuery(rows);
  const unanswered: string[] = [];
  const reasons = new Set<BasisUnavailableReason>();
  let answered = 0;

  for (const [queryId, queryRows] of byQuery) {
    const timing = displayByQuery.get(queryId);
    const displayMs =
      timing && timing.is_valid_display_timing !== false ? (timing.display_ms ?? null) : null;
    const value = resolveQueryValue(basis, queryRows, displayMs);
    if (value.kind === "value") answered += 1;
    else {
      unanswered.push(queryId);
      reasons.add(value.reason);
    }
  }

  if (answered === 0) {
    // One shared reason reads better than a list when nothing resolved at all.
    const only = reasons.size === 1 ? [...reasons][0] : undefined;
    return {
      available: false,
      reason: only ?? "no_passing_executions",
      unansweredQueries: unanswered.sort(),
    };
  }
  return { available: true, reason: null, unansweredQueries: unanswered.sort() };
}

// ---------------------------------------------------------------------------
// Same-query-set geomean
// ---------------------------------------------------------------------------

/** One run's resolved values, keyed by query id. */
export interface BasisSeriesInput {
  readonly key: string;
  readonly executions: readonly BasisExecution[];
  readonly displayTimings?: readonly BasisDisplayTiming[];
}

export interface BasisSeriesGeomean {
  readonly key: string;
  readonly geomeanMs: number | null;
  /** Values that fed the geomean, in `sharedQueryIds` order. */
  readonly values: readonly number[];
}

export interface SharedQueryGeomeans {
  readonly series: readonly BasisSeriesGeomean[];
  /** The intersected query set every geomean above was computed over. */
  readonly sharedQueryIds: readonly string[];
  /** Queries dropped from EVERY series because some series could not answer them. */
  readonly excludedQueryIds: readonly string[];
}

/**
 * Compute one geomean per series over the SAME query set.
 *
 * INVARIANT 2. Intersect first, then reduce. A query that any series cannot
 * answer under the basis is excluded from every series, not just from its own.
 * This is not fussiness: in the design prototype a single query missing one
 * pass made a same-run comparison read 18% instead of 7%, because each side
 * had silently averaged over a different query set.
 *
 * `sharedQueryIds.length` is the number every surface must display next to the
 * figure, so a reader can see what the geomean was actually taken over.
 */
export function sharedQueryGeomeans(
  basis: MeasurementBasis,
  series: readonly BasisSeriesInput[],
): SharedQueryGeomeans {
  const resolved = series.map((s) => {
    const displayByQuery = new Map((s.displayTimings ?? []).map((t) => [t.query_id, t]));
    const execsByQuery = groupByQuery(s.executions ?? []);
    const queryIds = new Set<string>([...execsByQuery.keys(), ...displayByQuery.keys()]);
    const values = new Map<string, number>();
    for (const queryId of queryIds) {
      const rows = execsByQuery.get(queryId) ?? [];
      const timing = displayByQuery.get(queryId);
      const displayMs =
        timing && timing.is_valid_display_timing !== false ? (timing.display_ms ?? null) : null;
      const value = resolveQueryValue(basis, rows, displayMs);
      if (value.kind === "value" && Number.isFinite(value.ms) && value.ms > 0) {
        values.set(queryId, value.ms);
      }
    }
    return { key: s.key, values };
  });

  const allQueryIds = new Set<string>();
  for (const s of series) {
    for (const row of s.executions ?? []) allQueryIds.add(row.query_id);
    for (const t of s.displayTimings ?? []) allQueryIds.add(t.query_id);
  }

  const shared: string[] = [];
  const excluded: string[] = [];
  for (const queryId of [...allQueryIds].sort()) {
    if (resolved.length > 0 && resolved.every((s) => s.values.has(queryId))) shared.push(queryId);
    else excluded.push(queryId);
  }

  return {
    series: resolved.map((s) => {
      const values = shared.map((q) => s.values.get(q)!);
      return { key: s.key, geomeanMs: geomeanOf(values), values };
    }),
    sharedQueryIds: shared,
    excludedQueryIds: excluded,
  };
}

/**
 * Projects a selection of DetailResult objects for a chosen MeasurementBasis.
 *
 * Recomputes `display_timings` for every query and `display_geomean_ms` over the
 * intersected shared query set across all selected runs.
 *
 * For DEFAULT_BASIS, preserves precomputed display_ms directly while recalculating
 * display_geomean_ms over the shared query set so no run averages over unshared queries.
 *
 * For non-default bases (warmup, individual warm passes, min), resolves each query's
 * timing from raw execution rows according to the pass selection and statistic.
 */
export function resolveResultsForBasis(
  results: readonly DetailResult[],
  basis: MeasurementBasis,
): DetailResult[] {
  if (results.length === 0) return [];

  const seriesInputs: BasisSeriesInput[] = results.map((r) => ({
    key: r.result_id,
    executions: r.queries ?? [],
    displayTimings: r.display_timings ?? [],
  }));
  const geomeanData = sharedQueryGeomeans(basis, seriesInputs);
  const geomeanByResultId = new Map(geomeanData.series.map((s) => [s.key, s.geomeanMs]));

  return results.map((r) => {
    const displayByQuery = new Map((r.display_timings ?? []).map((t) => [t.query_id, t]));
    const execsByQuery = groupByQuery(r.queries ?? []);

    const allQueryIds = new Set<string>();
    for (const t of r.display_timings ?? []) allQueryIds.add(t.query_id);
    for (const q of r.queries ?? []) allQueryIds.add(q.query_id);

    const newDisplayTimings: QueryDisplayTiming[] = [...allQueryIds]
      .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
      .map((queryId) => {
        const rows = execsByQuery.get(queryId) ?? [];
        const existing = displayByQuery.get(queryId);
        const displayMs =
          existing && existing.is_valid_display_timing !== false ? (existing.display_ms ?? null) : null;
        const val = resolveQueryValue(basis, rows, displayMs);
        const ms = val.kind === "value" && Number.isFinite(val.ms) && val.ms > 0 ? val.ms : null;
        const timingExclusionReason =
          isDefaultBasis(basis) && existing?.timing_exclusion_reason
            ? existing.timing_exclusion_reason
            : val.kind === "unavailable"
              ? val.reason
              : null;
        return {
          query_id: queryId,
          display_ms: ms,
          sample_count: val.kind === "value" ? val.sampleCount : (existing?.sample_count ?? 0),
          is_valid_display_timing: ms !== null,
          timing_exclusion_reason: timingExclusionReason,
        };
      });

    const newGeomean = geomeanByResultId.get(r.result_id) ?? null;

    return {
      ...r,
      display_geomean_ms: newGeomean,
      display_timings: newDisplayTimings,
      power_score: isDefaultBasis(basis) ? r.power_score : null,
    };
  });
}

/**
 * Geometric mean.
 *
 * Delegates to the explorer's single geomean implementation rather than adding
 * a second one; `chartMath.geomeanMs` already mirrors the Python
 * `_display_geomean_ms` and is what every chart uses.
 */
function geomeanOf(values: readonly number[]): number | null {
  return geomeanMs([...values]);
}

// ---------------------------------------------------------------------------
// Read-model bridge
// ---------------------------------------------------------------------------

/**
 * Parse `result_basis_availability.available_bases` into model values.
 *
 * The read model and the URL grammar share one vocabulary on purpose, so this
 * is `decodeBasis` over a comma-separated list rather than a second parser.
 * Unknown tokens are dropped rather than fatal: a snapshot built by a newer
 * pipeline may name a basis this client does not implement yet, and the right
 * response is to offer the bases we do understand, not to blank the control.
 */
/**
 * Parse `available_bases` into the PASS SELECTIONS a run can serve.
 *
 * This is the honest shape of what the read model publishes. The pipeline
 * records which executions exist; which statistic to reduce them with is a
 * client-side choice that needs no snapshot support.
 */
export function parseAvailablePassSelections(raw: string | null | undefined): PassSelection[] {
  const out: PassSelection[] = [];
  for (const basis of parseAvailableBases(raw)) {
    if (!out.some((p) => passSelectionsEqual(p, basis.passes))) out.push(basis.passes);
  }
  return out;
}

export function parseAvailableBases(raw: string | null | undefined): MeasurementBasis[] {
  if (!raw) return [];
  const out: MeasurementBasis[] = [];
  for (const token of raw.split(",")) {
    const trimmed = token.trim();
    if (trimmed === "") continue;
    const basis = decodeBasis(trimmed);
    if (basis && !out.some((b) => basesEqual(b, basis))) out.push(basis);
  }
  return out;
}

/**
 * Parse `result_basis_availability.varying_pass_queries` into a query-id to
 * usable-pass-count map.
 *
 * Null is the common case and means every query has the same pass count. A
 * malformed value yields an empty map rather than throwing: this field drives
 * an advisory annotation, and losing it must not take a page down.
 */
export function parseVaryingPassQueries(raw: string | null | undefined): Map<string, number> {
  if (!raw) return new Map();
  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return new Map();
    const out = new Map<string, number>();
    for (const [queryId, count] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof count === "number" && Number.isFinite(count)) out.set(queryId, count);
    }
    return out;
  } catch {
    return new Map();
  }
}

// ---------------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------------

/**
 * Human-readable name for a basis, for lock reasons and control labels.
 *
 * The default basis is named "published median" rather than "median over all
 * warm passes" because that is what a reader is comparing against: the figure
 * on the leaderboard. The longer phrasing describes the algorithm, which is
 * not the thing they need to recognise.
 */
export function formatBasisLabel(basis: MeasurementBasis): string {
  switch (basis.passes.kind) {
    case "all_warm":
      return basis.statistic === "median" ? "published median" : "fastest warm pass";
    case "warmup":
      return "warmup pass";
    case "warm_pass":
      return `warm pass ${basis.passes.pass}`;
  }
}
