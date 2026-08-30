import type { QueryTiming } from "@/types";
import { median } from "@/lib/measurementBasis";
import { fmtMs } from "@/utils";

/**
 * Per-query pass view: what actually happened inside one run.
 *
 * The explorer could not previously answer two questions: how stable were the
 * passes, and what does the warmup pass actually cost. `run_type`, `iter` and
 * `stream` reached the page and rendered nowhere, so every execution looked
 * alike whether it was the warmup or warm pass 3.
 *
 * Every figure here is COMPUTED from the run's own executions and captioned
 * with the reduction it performed. None is carried over from the read model,
 * so nothing on this view can disagree with the executions displayed beside it.
 */
export interface PassStripProps {
  queries: QueryTiming[];
  /** Cap on rows rendered; the caption always names the full total. */
  limit?: number;
}

export interface QueryPassSummary {
  queryId: string;
  executions: QueryTiming[];
  warmValues: number[];
  warmupMs: number | null;
  warmMedian: number | null;
  warmMin: number | null;
  /** Max − min across warm passes; null when fewer than two are usable. */
  spreadMs: number | null;
  /**
   * warmup ÷ warm median. Null when either side is missing.
   *
   * Deliberately NOT defaulted to 1.0 or to any estimate: a run with no
   * recorded warmup has no penalty to report, and inventing one would fabricate
   * the measurement this view exists to expose.
   */
  warmupRatio: number | null;
}

function passing(rows: QueryTiming[]): QueryTiming[] {
  return rows.filter((row) => row.status === "pass");
}

export function summarizeQueryPasses(queries: QueryTiming[]): QueryPassSummary[] {
  const byQuery = new Map<string, QueryTiming[]>();
  for (const row of queries) {
    const bucket = byQuery.get(row.query_id);
    if (bucket) bucket.push(row);
    else byQuery.set(row.query_id, [row]);
  }

  return [...byQuery.entries()]
    .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
    .map(([queryId, executions]) => {
      const warm = passing(executions).filter((r) => r.run_type === "measurement" || r.run_type === null);
      const warmup = passing(executions).find((r) => r.run_type === "warmup");
      const warmValues = warm.map((r) => r.duration_ms).filter((ms) => Number.isFinite(ms) && ms > 0);
      const warmMedian = median(warmValues);
      const warmMin = warmValues.length > 0 ? Math.min(...warmValues) : null;
      const spreadMs =
        warmValues.length > 1 ? Math.max(...warmValues) - Math.min(...warmValues) : null;
      const warmupMs = warmup ? warmup.duration_ms : null;
      return {
        queryId,
        executions,
        warmValues,
        warmupMs,
        warmMedian,
        warmMin,
        spreadMs,
        warmupRatio:
          warmupMs !== null && warmMedian !== null && warmMedian > 0 ? warmupMs / warmMedian : null,
      };
    });
}

/** True when no query in the run recorded a warmup pass. */
export function hasNoRecordedWarmup(summaries: readonly QueryPassSummary[]): boolean {
  return summaries.every((s) => s.warmupMs === null);
}

function ratioText(ratio: number | null): string {
  if (ratio === null) return "—";
  return `${ratio.toFixed(2)}x`;
}

export function PassStrip({ queries, limit = 25 }: PassStripProps) {
  const summaries = summarizeQueryPasses(queries);
  if (summaries.length === 0) return null;
  const shown = summaries.slice(0, limit);
  const noWarmup = hasNoRecordedWarmup(summaries);

  return (
    <section class="card mb-8" aria-labelledby="pass-view-title">
      <div class="mb-3">
        <h2 id="pass-view-title" class="text-base font-semibold text-[var(--bb-data-fg-primary)]">
          Passes within this run
        </h2>
        {/*
          Names the reduction actually performed. w0 measured the corpus-wide
          warmup penalty at a p50 of 1.01x, with a third of warmups FASTER than
          the warm median -- so a caption promising a penalty would leave a
          reader thinking a column reading 1.00x was broken. The exclusion is
          justified by the tail (p99 3.18x, max 61.5x), not by a typical cost.
        */}
        <p class="mt-1 text-xs text-[var(--bb-data-fg-muted)]">
          {`Warm median is the median of this run's passing measurement passes, per query — the same reduction the published figure uses. Warmup is shown for comparison and is excluded from it. Showing ${shown.length} of ${summaries.length} ${summaries.length === 1 ? "query" : "queries"}.`}
        </p>
        {noWarmup ? (
          <p class="mt-1 text-xs text-[var(--bb-data-fg-subtle)]" data-testid="no-warmup-note">
            This run recorded no warmup pass, so no warmup penalty is shown. It is absent, not zero.
          </p>
        ) : null}
      </div>

      <div class="overflow-x-auto">
        <table class="min-w-full w-max divide-y divide-[var(--bb-data-border)] text-sm">
          <thead class="bg-[var(--bb-surface-data-muted)]">
            <tr>
              <th class="table-th">Query</th>
              <th class="table-th">Passes</th>
              <th class="table-th">Warm median</th>
              <th class="table-th">Warm min</th>
              <th class="table-th">Spread</th>
              <th class="table-th">Warmup</th>
              <th class="table-th">Warmup vs warm</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-[var(--bb-data-border)] bg-[var(--bb-surface-data)]">
            {shown.map((s) => (
              <tr key={s.queryId} class="hover:bg-[var(--bb-surface-data-muted)]">
                <td class="table-td font-mono font-medium">{s.queryId}</td>
                <td class="table-td font-mono text-xs">{s.warmValues.length}</td>
                <td class="table-td font-mono">{s.warmMedian !== null ? fmtMs(s.warmMedian) : "—"}</td>
                <td class="table-td font-mono">{s.warmMin !== null ? fmtMs(s.warmMin) : "—"}</td>
                <td class="table-td font-mono">{s.spreadMs !== null ? fmtMs(s.spreadMs) : "—"}</td>
                <td class="table-td font-mono">{s.warmupMs !== null ? fmtMs(s.warmupMs) : "—"}</td>
                <td class="table-td font-mono" data-testid={`warmup-ratio-${s.queryId}`}>
                  {ratioText(s.warmupRatio)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
