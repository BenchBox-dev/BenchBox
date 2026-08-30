import type { RoutableProps } from "preact-router";
import { useEffect, useMemo, useState } from "preact/hooks";

import type { DetailResult } from "@/types";
import { getDetailResult } from "@/lib/duckdbQueries";
import { errMsg } from "@/utils";
import { ErrorMessage } from "@/components/ErrorMessage";
import { CompareSummarySkeleton } from "@/components/LoadingSpinner";
import { StatusBadge } from "@/components/StatusBadge";
import { summarizeQueryPasses } from "@/components/PassStrip";
import { clampReferenceIndex, MAX_WITHIN_RUN_BASES, MIN_WITHIN_RUN_BASES } from "@/lib/resultLinks";
import {
  DEFAULT_BASIS,
  basesSerde,
  encodeBasis,
  formatBasisLabel,
  resolveQueryValue,
  warmPass,
  type BasisExecution,
  type MeasurementBasis,
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

function parseBasesParam(search: string): { bases: MeasurementBasis[]; referenceIndex: number } {
  const params = new URLSearchParams(search);
  const raw = params.get("bases");
  const decoded = raw !== null ? basesSerde.decode(raw) : null;
  const bases =
    decoded && decoded.length >= MIN_WITHIN_RUN_BASES
      ? decoded.slice(0, MAX_WITHIN_RUN_BASES)
      : [DEFAULT_BASIS, { passes: warmPass(1), statistic: "median" as const }];
  const refRaw = Number(params.get("ref") ?? "0");
  return { bases, referenceIndex: clampReferenceIndex(refRaw, bases.length) };
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

export function CompareWithinRun({ resultId }: CompareWithinRunProps) {
  const [detail, setDetail] = useState<DetailResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const search = typeof window === "undefined" ? "" : window.location.search;
  const { bases, referenceIndex } = useMemo(() => parseBasesParam(search), [search]);

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

  const grid = useMemo(() => {
    if (!detail) return { rows: [], sharedQueryIds: [] };
    const displayMsByQuery = new Map<string, number | null>(
      detail.display_timings.map((t) => [t.query_id, t.is_valid_display_timing ? t.display_ms : null]),
    );
    return buildWithinRunRows(detail.queries, displayMsByQuery, bases);
  }, [detail, bases]);

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
            {`Reference: ${formatBasisLabel(reference)}`}
          </StatusBadge>
          <StatusBadge role="comparison" tone="neutral">
            {`${passSummaries.length} queries in this run`}
          </StatusBadge>
        </div>
      </section>

      <section class="card" aria-label="Per-query values by basis">
        <div class="overflow-x-auto">
          <table class="min-w-full w-max divide-y divide-[var(--bb-data-border)] text-sm">
            <thead class="bg-[var(--bb-surface-data-muted)]">
              <tr>
                <th class="table-th">Query</th>
                {bases.map((basis, i) => (
                  <th key={encodeBasis(basis)} class="table-th">
                    {formatBasisLabel(basis)}
                    {i === referenceIndex ? " (reference)" : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody class="divide-y divide-[var(--bb-data-border)] bg-[var(--bb-surface-data)]">
              {grid.rows.map((row) => (
                <tr key={row.queryId} class="hover:bg-[var(--bb-surface-data-muted)]">
                  <td class="table-td font-mono font-medium">{row.queryId}</td>
                  {row.cells.map((cell, i) => (
                    <td key={i} class="table-td font-mono">
                      {cell.ms !== null ? (
                        cell.ms.toFixed(1)
                      ) : (
                        <span class="text-[var(--bb-data-fg-subtle)]" data-testid="unrecorded-cell">
                          unrecorded
                        </span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
