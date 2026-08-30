import type { RoutableProps } from "preact-router";
import { useEffect, useMemo, useState } from "preact/hooks";

import type { DetailResult, QueryTiming } from "@/types";
import { getDetailResult } from "@/lib/duckdbQueries";
import { errMsg, fmtMs } from "@/utils";
import { ErrorMessage } from "@/components/ErrorMessage";
import { CompareSummarySkeleton } from "@/components/LoadingSpinner";
import { StatusBadge } from "@/components/StatusBadge";
import { Select } from "@/components/Select";
import { summarizeQueryPasses } from "@/components/PassStrip";
import { clampReferenceIndex, withinRunCompareHref, MAX_WITHIN_RUN_BASES, MIN_WITHIN_RUN_BASES } from "@/lib/resultLinks";
import { paletteColor } from "@/lib/chartTheme";
import { geomeanMs } from "@/lib/chartMath";
import {
  ALL_WARM,
  DEFAULT_BASIS,
  WARMUP,
  basesEqual,
  basesSerde,
  decodeBasis,
  encodeBasis,
  formatBasisLabel,
  passSelectionsEqual,
  resolveQueryValue,
  warmPass,
  type BasisExecution,
  type MeasurementBasis,
  type PassSelection,
} from "@/lib/measurementBasis";

/**
 * Within-run comparison: one run, several measurement bases as columns.
 *
 * THE ONLY PLACE A STATISTIC MAY VARY BETWEEN SERIES. Everywhere else that
 * would measure the statistic rather than the engine; here engine, hardware,
 * corpus and scale are fixed by construction, so the basis IS the subject and
 * nothing is confounded.
 *
 * For the same reason its figures are not platform results. A number here says
 * "this run is X% faster read one way than another", which is a statement about
 * measurement methodology, not about an engine. `isRankable` is exported as
 * `false` so a ranking surface cannot consume this page's output by accident.
 */
interface CompareWithinRunProps extends RoutableProps {
  resultId?: string;
}

/** Structural exclusion from ranking. Not a policy flag; a fact about the page. */
export const WITHIN_RUN_FIGURES_ARE_RANKABLE = false;

/** Drop duplicate bases to ensure each column represents a distinct measurement basis. */
export function deduplicateBases(bases: readonly MeasurementBasis[]): MeasurementBasis[] {
  const unique: MeasurementBasis[] = [];
  for (const b of bases) {
    if (!unique.some((u) => basesEqual(u, b))) {
      unique.push(b);
    }
  }
  return unique;
}

export function parseBasesParam(search: string): { bases: MeasurementBasis[]; referenceIndex: number } {
  const params = new URLSearchParams(search);
  const raw = params.get("bases");
  const decoded = raw !== null ? basesSerde.decode(raw) : null;
  const unique = decoded ? deduplicateBases(decoded) : [];
  const bases =
    unique.length >= MIN_WITHIN_RUN_BASES
      ? unique.slice(0, MAX_WITHIN_RUN_BASES)
      : [DEFAULT_BASIS, { passes: warmPass(1), statistic: "median" as const }];
  const refRaw = Number(params.get("ref") ?? "0");
  return { bases, referenceIndex: clampReferenceIndex(refRaw, bases.length) };
}

function hasMultipleSamples(queries: readonly QueryTiming[], passes: PassSelection): boolean {
  const counts = new Map<string, number>();
  for (const q of queries) {
    if (q.status !== "pass") continue;
    let matches = false;
    if (passes.kind === "all_warm") {
      matches = q.run_type === "iteration" || q.run_type === "warm";
    } else if (passes.kind === "warmup") {
      matches = q.run_type === "warmup";
    } else if (passes.kind === "warm_pass") {
      matches = (q.run_type === "iteration" || q.run_type === "warm") && q.iter === passes.pass;
    }
    if (matches) {
      const c = (counts.get(q.query_id) ?? 0) + 1;
      if (c > 1) return true;
      counts.set(q.query_id, c);
    }
  }
  return false;
}

export function formatWithinRunBasisLabel(
  basis: MeasurementBasis,
  allBases?: readonly MeasurementBasis[],
): string {
  const hasSiblingWithDiffStat = allBases?.some(
    (b) => passSelectionsEqual(b.passes, basis.passes) && b.statistic !== basis.statistic,
  );
  if (hasSiblingWithDiffStat) {
    if (basis.passes.kind === "warmup") {
      return `warmup pass (${basis.statistic})`;
    }
    if (basis.passes.kind === "warm_pass") {
      return `warm pass ${basis.passes.pass} (${basis.statistic})`;
    }
    if (basis.passes.kind === "all_warm") {
      return basis.statistic === "min" ? "fastest warm pass" : "warm passes (median)";
    }
  }
  return formatBasisLabel(basis);
}

export function availableBasesForQueries(queries: readonly QueryTiming[]): MeasurementBasis[] {
  const list: MeasurementBasis[] = [];
  list.push(DEFAULT_BASIS);
  if (hasMultipleSamples(queries, ALL_WARM)) {
    list.push({ passes: ALL_WARM, statistic: "min" });
  }

  const hasWarmup = queries.some((q) => q.run_type === "warmup" && q.status === "pass");
  if (hasWarmup) {
    list.push({ passes: WARMUP, statistic: "median" });
    if (hasMultipleSamples(queries, WARMUP)) {
      list.push({ passes: WARMUP, statistic: "min" });
    }
  }

  const iters = new Set<number>();
  for (const q of queries) {
    if (q.status === "pass" && typeof q.iter === "number" && q.iter > 0) {
      iters.add(q.iter);
    }
  }
  const sortedIters = [...iters].sort((a, b) => a - b);
  for (const iter of sortedIters) {
    const p = warmPass(iter);
    list.push({ passes: p, statistic: "median" });
    if (hasMultipleSamples(queries, p)) {
      list.push({ passes: p, statistic: "min" });
    }
  }

  return deduplicateBases(list);
}

export interface WithinRunCell {
  ms: number | null;
  unavailableReason: string | null;
}

export interface WithinRunRow {
  queryId: string;
  cells: WithinRunCell[];
  /** True when every column produced a value for this query. */
  comparable: boolean;
}

/**
 * Build the grid, enforcing the same-query-set rule across columns.
 *
 * A query any column cannot answer is marked unrecorded in that column AND
 * excluded from every column's geomean. This is the case that produced a wrong
 * 1.18x reading in the design prototype: each column had silently averaged over
 * whichever queries it happened to have.
 */
export function buildWithinRunRows(
  executions: readonly BasisExecution[],
  displayMsByQuery: ReadonlyMap<string, number | null>,
  bases: readonly MeasurementBasis[],
): { rows: WithinRunRow[]; sharedQueryIds: string[] } {
  const byQuery = new Map<string, BasisExecution[]>();
  for (const row of executions) {
    const bucket = byQuery.get(row.query_id);
    if (bucket) bucket.push(row);
    else byQuery.set(row.query_id, [row]);
  }

  const rows: WithinRunRow[] = [...byQuery.entries()]
    .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
    .map(([queryId, queryRows]) => {
      const cells = bases.map((basis) => {
        const value = resolveQueryValue(basis, queryRows, displayMsByQuery.get(queryId) ?? null);
        return value.kind === "value"
          ? { ms: value.ms, unavailableReason: null }
          : { ms: null, unavailableReason: value.reason };
      });
      return { queryId, cells, comparable: cells.every((c) => c.ms !== null && c.ms > 0) };
    });

  return { rows, sharedQueryIds: rows.filter((r) => r.comparable).map((r) => r.queryId) };
}

/**
 * Calculate per-column geometric means over the queries present across all columns.
 */
export function calculateColumnGeomeans(
  rows: readonly WithinRunRow[],
  sharedQueryIds: readonly string[],
): (number | null)[] {
  if (rows.length === 0 || rows[0] === undefined) return [];
  const columnCount = rows[0].cells.length;
  const sharedSet = new Set(sharedQueryIds);
  const sharedRows = rows.filter((r) => sharedSet.has(r.queryId));

  const result: (number | null)[] = [];
  for (let col = 0; col < columnCount; col++) {
    const values = sharedRows
      .map((r) => r.cells[col]?.ms)
      .filter((v): v is number => v !== null && v !== undefined && Number.isFinite(v) && v > 0);
    result.push(values.length === sharedRows.length && sharedRows.length > 0 ? geomeanMs(values) : null);
  }
  return result;
}

export function calculateCellDelta(
  cellMs: number | null,
  refMs: number | null,
): { ratio: number | null; deltaMs: number | null } {
  if (cellMs === null || refMs === null || refMs <= 0 || cellMs <= 0) {
    return { ratio: null, deltaMs: null };
  }
  return {
    ratio: cellMs / refMs,
    deltaMs: cellMs - refMs,
  };
}

export function CompareWithinRun({ resultId }: CompareWithinRunProps) {
  const [detail, setDetail] = useState<DetailResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const search = typeof window === "undefined" ? "" : window.location.search;
  const parsed = useMemo(() => parseBasesParam(search), [search]);
  const [bases, setBases] = useState<MeasurementBasis[]>(parsed.bases);
  const [referenceIndex, setReferenceIndex] = useState<number>(parsed.referenceIndex);

  useEffect(() => {
    setBases(parsed.bases);
    setReferenceIndex(parsed.referenceIndex);
  }, [parsed]);

  useEffect(() => {
    let cancelled = false;
    if (!resultId) return;
    setLoading(true);
    getDetailResult(resultId)
      .then((result) => {
        if (cancelled) return;
        setDetail(result);
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(errMsg(e));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [resultId]);

  function updateBasesAndRef(nextBases: MeasurementBasis[], nextRef: number) {
    const unique = deduplicateBases(nextBases);
    const clampedBases = unique.slice(0, MAX_WITHIN_RUN_BASES);
    const clampedRef = clampReferenceIndex(nextRef, clampedBases.length);
    setBases(clampedBases);
    setReferenceIndex(clampedRef);
    if (resultId && typeof window !== "undefined") {
      const href = withinRunCompareHref(resultId, clampedBases.map(encodeBasis), clampedRef);
      window.history.replaceState(null, "", href);
    }
  }

  const availableBases = useMemo(
    () => (detail ? availableBasesForQueries(detail.queries) : []),
    [detail],
  );
  const addableBases = useMemo(
    () => availableBases.filter((b) => !bases.some((existing) => basesEqual(existing, b))),
    [availableBases, bases],
  );
  const [selectedAddKey, setSelectedAddKey] = useState<string>("");

  useEffect(() => {
    if (addableBases.length > 0 && (!selectedAddKey || !addableBases.some((b) => encodeBasis(b) === selectedAddKey))) {
      setSelectedAddKey(encodeBasis(addableBases[0]!));
    }
  }, [addableBases, selectedAddKey]);

  const effectiveAddKey =
    selectedAddKey || (addableBases[0] ? encodeBasis(addableBases[0]) : "");

  function handleAddBasis() {
    if (!effectiveAddKey) return;
    const basisToAdd = decodeBasis(effectiveAddKey);
    if (!basisToAdd) return;
    if (bases.some((b) => basesEqual(b, basisToAdd))) return;
    updateBasesAndRef([...bases, basisToAdd], referenceIndex);
  }

  function handleRemoveBasis(colIndex: number) {
    if (bases.length <= MIN_WITHIN_RUN_BASES) return;
    const nextBases = bases.filter((_, idx) => idx !== colIndex);
    const nextRef =
      colIndex === referenceIndex
        ? 0
        : colIndex < referenceIndex
          ? referenceIndex - 1
          : referenceIndex;
    updateBasesAndRef(nextBases, nextRef);
  }

  function handleSetReference(colIndex: number) {
    updateBasesAndRef(bases, colIndex);
  }

  const grid = useMemo(() => {
    if (!detail) return { rows: [], sharedQueryIds: [] };
    const displayMsByQuery = new Map<string, number | null>(
      detail.display_timings.map((t) => [t.query_id, t.is_valid_display_timing ? t.display_ms : null]),
    );
    return buildWithinRunRows(detail.queries, displayMsByQuery, bases);
  }, [detail, bases]);

  const columnGeomeans = useMemo(
    () => calculateColumnGeomeans(grid.rows, grid.sharedQueryIds),
    [grid.rows, grid.sharedQueryIds],
  );
  const refGeomean = columnGeomeans[referenceIndex] ?? null;

  if (loading) return <CompareSummarySkeleton />;
  if (error) return <ErrorMessage message={error} />;
  if (!detail) return <ErrorMessage message="Result not found." />;

  const passSummaries = summarizeQueryPasses(detail.queries);
  const reference = bases[referenceIndex] ?? bases[0]!;

  return (
    <div class="mx-auto max-w-7xl px-4 py-6">
      <section class="mb-6 panel-elevated p-5" aria-label="Within-run comparison">
        <p class="text-xs font-semibold uppercase tracking-wide text-[var(--bb-data-fg-subtle)]">
          Within one run
        </p>
        <h1 class="mt-1 text-2xl font-bold text-[var(--bb-data-fg-primary)]">
          {detail.platform} — measurement bases compared
        </h1>
        {/*
          The reason this page may do what no other compare surface may. Stated
          on the page, not just in a comment, because it is also the reason its
          numbers must not travel.
        */}
        <p class="mt-2 text-sm text-[var(--bb-data-fg-muted)]">
          Every column is the same run on the same hardware and engine, so no engine or hardware
          varies here. Only the measurement basis does — which is why the statistic may differ
          between columns on this page and nowhere else.
        </p>
        <p class="mt-1 text-xs text-[var(--bb-data-fg-subtle)]" data-testid="not-a-platform-result">
          These figures describe measurement methodology, not engine performance. They are excluded
          from rankings and must not be quoted as platform results.
        </p>
        <div class="mt-3 flex flex-wrap items-center gap-2">
          <StatusBadge role="comparison" tone="neutral">
            {`${grid.sharedQueryIds.length} of ${grid.rows.length} queries comparable`}
          </StatusBadge>
          <StatusBadge role="comparison" tone="neutral">
            {`Reference: ${formatWithinRunBasisLabel(reference, bases)}`}
          </StatusBadge>
          <StatusBadge role="comparison" tone="neutral">
            {`${passSummaries.length} queries in this run`}
          </StatusBadge>
        </div>
      </section>

      {/* Basis Cards */}
      <div class="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {bases.map((basis, i) => {
          const color = paletteColor(i);
          const isRef = i === referenceIndex;
          const geomean = columnGeomeans[i] ?? null;
          const ratio = refGeomean !== null && geomean !== null && refGeomean > 0 ? geomean / refGeomean : null;
          const deltaMs = refGeomean !== null && geomean !== null ? geomean - refGeomean : null;
          const canRemove = bases.length > MIN_WITHIN_RUN_BASES;

          return (
            <div
              key={encodeBasis(basis)}
              class="card relative overflow-hidden"
              style={{ borderTopColor: color, borderTopWidth: "3px" }}
            >
              <div class="mb-2 flex items-center justify-between">
                <label class="flex items-center gap-1.5 cursor-pointer text-xs font-semibold text-[var(--bb-data-fg-primary)]">
                  <input
                    type="radio"
                    name="within-run-reference-radio"
                    checked={isRef}
                    onChange={() => handleSetReference(i)}
                    aria-label={`Set ${formatWithinRunBasisLabel(basis, bases)} as reference`}
                    data-testid={`reference-radio-${encodeBasis(basis)}`}
                  />
                  <span>{formatWithinRunBasisLabel(basis, bases)}</span>
                </label>
                <div class="flex items-center gap-1">
                  {isRef ? (
                    <StatusBadge role="ranking" tone="info">reference</StatusBadge>
                  ) : ratio !== null ? (
                    <StatusBadge
                      role="ranking"
                      tone={ratio < 1 ? "success" : ratio > 1 ? "neutral" : "neutral"}
                    >
                      {ratio < 1 ? "faster" : ratio > 1 ? "slower" : "parity"}
                    </StatusBadge>
                  ) : null}
                  {canRemove && (
                    <button
                      type="button"
                      class="text-xs text-[var(--bb-data-fg-subtle)] hover:text-[var(--bb-tone-critical-fg)] px-1 rounded"
                      onClick={() => handleRemoveBasis(i)}
                      aria-label={`Remove ${formatWithinRunBasisLabel(basis, bases)}`}
                      title="Remove column"
                    >
                      ✕
                    </button>
                  )}
                </div>
              </div>

              <dl class="space-y-1 text-sm mt-3">
                <div class="flex justify-between">
                  <dt class="text-[var(--bb-data-fg-muted)]">Geomean query time</dt>
                  <dd class="font-mono font-medium">
                    {geomean !== null ? fmtMs(geomean) : "—"}
                  </dd>
                </div>
                {!isRef && (
                  <>
                    <div class="flex justify-between">
                      <dt class="text-[var(--bb-data-fg-muted)]">Ratio vs reference</dt>
                      <dd class="font-mono font-medium">
                        {ratio !== null ? `${ratio.toFixed(2)}x` : "—"}
                      </dd>
                    </div>
                    <div class="flex justify-between">
                      <dt class="text-[var(--bb-data-fg-muted)]">Delta vs reference</dt>
                      <dd class="font-mono text-xs">
                        {deltaMs !== null ? `${deltaMs > 0 ? "+" : ""}${deltaMs.toFixed(1)} ms` : "—"}
                      </dd>
                    </div>
                  </>
                )}
              </dl>
            </div>
          );
        })}
      </div>

      {/* Add Basis Controls */}
      {bases.length < MAX_WITHIN_RUN_BASES && addableBases.length > 0 && (
        <div class="panel mb-6 flex flex-wrap items-center justify-between gap-3 px-4 py-3 shadow-sm">
          <div>
            <label class="text-sm font-medium text-[var(--bb-data-fg-primary)]" for="add-basis-select">
              Add measurement basis
            </label>
            <p class="text-xs text-[var(--bb-data-fg-muted)]">
              Compare another pass or reduction from this run (up to {MAX_WITHIN_RUN_BASES} columns).
            </p>
          </div>
          <div class="flex items-center gap-2">
            <Select
              id="add-basis-select"
              ariaLabel="Available measurement bases"
              size="sm"
              value={effectiveAddKey}
              onChange={setSelectedAddKey}
              options={addableBases.map((b) => ({
                value: encodeBasis(b),
                label: formatWithinRunBasisLabel(b, availableBases),
              }))}
            />
            <button
              type="button"
              class="rounded bg-[var(--bb-accent)] px-3 py-1.5 text-xs font-medium text-white hover:bg-[var(--bb-accent-hover)] transition-colors"
              onClick={handleAddBasis}
            >
              + Add basis
            </button>
          </div>
        </div>
      )}

      {/* Grid Table */}
      <section class="card" aria-label="Per-query values by basis">
        <div class="overflow-x-auto">
          <table class="min-w-full w-max divide-y divide-[var(--bb-data-border)] text-sm">
            <thead class="bg-[var(--bb-surface-data-muted)]">
              <tr>
                <th scope="col" class="table-th text-left">Query</th>
                {bases.map((basis, i) => (
                  <th key={encodeBasis(basis)} scope="col" class="table-th text-right">
                    <div class="flex items-center justify-end gap-1.5">
                      <span>{formatWithinRunBasisLabel(basis, bases)}</span>
                      {i === referenceIndex && (
                        <StatusBadge role="ranking" tone="info">ref</StatusBadge>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody class="divide-y divide-[var(--bb-data-border)] bg-[var(--bb-surface-data)]">
              {grid.rows.map((row) => {
                const refCell = row.cells[referenceIndex];
                return (
                  <tr key={row.queryId} class="hover:bg-[var(--bb-surface-data-muted)]">
                    <td class="table-td font-mono font-medium text-left">{row.queryId}</td>
                    {row.cells.map((cell, i) => {
                      const isRef = i === referenceIndex;
                      const { ratio, deltaMs } = calculateCellDelta(cell.ms, refCell?.ms ?? null);
                      return (
                        <td key={i} class="table-td font-mono text-right">
                          {cell.ms !== null ? (
                            <div>
                              <div class="font-medium text-[var(--bb-data-fg-primary)]">
                                {cell.ms.toFixed(1)} ms
                              </div>
                              {!isRef && ratio !== null && deltaMs !== null && (
                                <div
                                  class={`text-xs ${
                                    ratio < 1
                                      ? "text-[var(--bb-tone-success-fg)] font-medium"
                                      : ratio > 1
                                        ? "text-[var(--bb-data-fg-muted)]"
                                        : "text-[var(--bb-data-fg-subtle)]"
                                  }`}
                                >
                                  {ratio.toFixed(2)}x ({deltaMs > 0 ? "+" : ""}{deltaMs.toFixed(1)} ms)
                                </div>
                              )}
                              {!isRef && (ratio === null || deltaMs === null) && (
                                <div class="text-xs text-[var(--bb-data-fg-subtle)]">no ref</div>
                              )}
                              {isRef && (
                                <div class="text-xs text-[var(--bb-data-fg-subtle)]">reference</div>
                              )}
                            </div>
                          ) : (
                            <span class="text-[var(--bb-data-fg-subtle)]" data-testid="unrecorded-cell">
                              unrecorded
                            </span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
            <tfoot class="border-t-2 border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] font-semibold">
              <tr>
                <td class="table-td font-mono text-left">
                  Geomean ({grid.sharedQueryIds.length} shared)
                </td>
                {columnGeomeans.map((g, i) => {
                  const isRef = i === referenceIndex;
                  const ratio = refGeomean !== null && g !== null && refGeomean > 0 ? g / refGeomean : null;
                  const deltaMs = refGeomean !== null && g !== null ? g - refGeomean : null;
                  return (
                    <td key={i} class="table-td font-mono text-right">
                      {g !== null ? (
                        <div>
                          <div>{fmtMs(g)}</div>
                          {!isRef && ratio !== null && deltaMs !== null && (
                            <div class="text-xs font-normal text-[var(--bb-data-fg-muted)]">
                              {ratio.toFixed(2)}x ({deltaMs > 0 ? "+" : ""}{deltaMs.toFixed(1)} ms)
                            </div>
                          )}
                          {isRef && (
                            <div class="text-xs font-normal text-[var(--bb-data-fg-subtle)]">reference</div>
                          )}
                        </div>
                      ) : (
                        "—"
                      )}
                    </td>
                  );
                })}
              </tr>
            </tfoot>
          </table>
        </div>
      </section>
    </div>
  );
}
