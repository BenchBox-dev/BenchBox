import type { DetailResult } from "@/types";
import { queryDisagreementSpread } from "@/lib/chartMath";
import { isValidTimingValue, timingValueForQuery } from "@/lib/displayEligibility";
import { formatSpeedup } from "@/lib/metricFormatters";
import { formatRunIdentitiesForCohort } from "@/lib/runIdentity";
import { fmtMs } from "@/utils";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { TableScrollHint } from "@/components/TableScrollHint";
import { useRef } from "preact/hooks";

export type QueryDiffStatus = "faster" | "slower" | "tie" | "missing";

export interface QueryDiffRow {
  queryId: string;
  candidateResultId: string;
  candidatePlatform: string;
  baselineMs: number | null;
  candidateMs: number | null;
  ratio: number | null;
  deltaMs: number | null;
  status: QueryDiffStatus;
  /** Executions behind each side's value under the current basis. */
  baselineSamples: number | null;
  candidateSamples: number | null;
  /**
   * False when one side cannot answer the current basis.
   *
   * The row is still rendered. A query dropped for being unanswerable is a
   * query the reader never learns was excluded, and the count they see stops
   * matching the corpus.
   */
  comparable: boolean;
}

/**
 * Which subset of the per-query rows to show.
 *
 * Applied to the chart and the table through this ONE function, so the two can
 * never show different subsets of the same comparison.
 */
export type QueryDiffLimiter = "all" | "speedups" | "slowdowns" | "movement";

export const QUERY_DIFF_LIMITER_LABELS: Record<QueryDiffLimiter, string> = {
  all: "All queries",
  speedups: "Largest speedups",
  slowdowns: "Largest slowdowns",
  movement: "Largest movement",
};

/** Product contract: largest-query views show at most ten logical queries. */
export const DEFAULT_QUERY_DIFF_LIMIT = 10;

/**
 * Rank and cap the rows for a limiter.
 *
 * Rows that cannot be compared under the current basis are never ranked into a
 * "largest" view -- they have no magnitude to rank by -- but `all` keeps them,
 * so they stay visible and marked rather than disappearing.
 */
export function applyQueryDiffLimiter(
  rows: readonly QueryDiffRow[],
  limiter: QueryDiffLimiter,
  topN: number,
): QueryDiffRow[] {
  if (limiter === "all") return [...rows];
  const ranked = rows.filter((row) => row.comparable && row.deltaMs !== null);
  const sorted = (() => {
    switch (limiter) {
      case "speedups":
        return ranked.filter((r) => (r.deltaMs ?? 0) < 0).sort((a, b) => (a.deltaMs ?? 0) - (b.deltaMs ?? 0));
      case "slowdowns":
        return ranked.filter((r) => (r.deltaMs ?? 0) > 0).sort((a, b) => (b.deltaMs ?? 0) - (a.deltaMs ?? 0));
      case "movement":
        return [...ranked].sort((a, b) => Math.abs(b.deltaMs ?? 0) - Math.abs(a.deltaMs ?? 0));
    }
  })();
  return sorted.slice(0, Math.max(0, topN));
}

/**
 * Select and rank query IDs for a given limiter across comparison results.
 *
 * Provides a single shared query selection for the chart, the heatmap, and the table.
 */
export function selectQueryIdsForLimiter(
  results: readonly DetailResult[],
  baselineIndex: number,
  limiter: QueryDiffLimiter,
  topN: number = DEFAULT_QUERY_DIFF_LIMIT,
): { queryIds: string[]; totalQueryCount: number } {
  const allQueryIds = [
    ...new Set(results.flatMap((r) => (r.display_timings ?? []).map((t) => t.query_id))),
  ].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

  if (limiter === "all" || results.length < 2) {
    return { queryIds: allQueryIds, totalQueryCount: allQueryIds.length };
  }

  const normalizedBaselineIndex = normalizeBaselineIndex(results, baselineIndex);
  const baseline = results[normalizedBaselineIndex];
  const candidates = results.filter((_, i) => i !== normalizedBaselineIndex);

  // Queries where baseline has a valid timing and at least one candidate has a valid timing
  const comparable = allQueryIds.filter((queryId) => {
    const baseMs = baseline ? timingValueForQuery(baseline, queryId) : null;
    if (baseMs === null || baseMs <= 0) return false;
    return candidates.some((c) => {
      const ms = timingValueForQuery(c, queryId);
      return ms !== null && ms > 0;
    });
  });

  const scored = comparable.map((queryId) => {
    const baseMs = timingValueForQuery(baseline!, queryId)!;
    const candidateTimings = candidates
      .map((c) => timingValueForQuery(c, queryId))
      .filter((ms): ms is number => ms !== null && ms > 0);

    const ratios = candidateTimings.map((ms) => ms / baseMs);
    const deltas = candidateTimings.map((ms) => ms - baseMs);

    const bestRatio = Math.min(...ratios);
    const worstRatio = Math.max(...ratios);
    const maxDisagreement =
      queryDisagreementSpread([1, ...ratios]) ??
      Math.max(...ratios.map((r) => Math.abs(Math.log2(r))));
    const maxDelta = Math.max(...deltas.map((d) => Math.abs(d)));

    return {
      queryId,
      bestRatio,
      worstRatio,
      maxDisagreement,
      maxDelta,
    };
  });

  let filtered: typeof scored = [];
  switch (limiter) {
    case "speedups":
      filtered = scored
        .filter((s) => s.bestRatio < 1.0)
        .sort((a, b) => a.bestRatio - b.bestRatio);
      break;
    case "slowdowns":
      filtered = scored
        .filter((s) => s.worstRatio > 1.0)
        .sort((a, b) => b.worstRatio - a.worstRatio);
      break;
    case "movement":
      filtered = [...scored].sort((a, b) => b.maxDisagreement - a.maxDisagreement || b.maxDelta - a.maxDelta);
      break;
  }

  return {
    queryIds: filtered.slice(0, Math.max(0, topN)).map((s) => s.queryId),
    totalQueryCount: allQueryIds.length,
  };
}

/**
 * The sentence every limiter state must carry, including the empty one.
 *
 * "No queries match" without a denominator leaves a reader unable to tell an
 * empty filter from an empty comparison.
 */
export function queryDiffCountSentence(shown: number, total: number, limiter: QueryDiffLimiter): string {
  if (total === 0) return "No queries to compare.";
  if (shown === 0) {
    return `No queries match ${QUERY_DIFF_LIMITER_LABELS[limiter].toLowerCase()} — showing 0 of ${total}.`;
  }
  return `Showing ${shown} of ${total} ${total === 1 ? "query" : "queries"}.`;
}

interface QueryDiffTableProps {
  results: DetailResult[];
  baselineIndex?: number;
  suppressionReason?: string | null;
  limiter?: QueryDiffLimiter;
  topN?: number;
  queryFilter?: readonly string[];
}

export function QueryDiffTable({
  results,
  baselineIndex = 0,
  suppressionReason = null,
  limiter = "all",
  topN = DEFAULT_QUERY_DIFF_LIMIT,
  queryFilter,
}: QueryDiffTableProps) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  if (results.length < 2) return null;
  const normalizedBaselineIndex = normalizeBaselineIndex(results, baselineIndex);
  const baseline = results[normalizedBaselineIndex]!;
  const runLabels = formatRunIdentitiesForCohort(
    results.map((result) => ({
      result_id: result.result_id,
      platform: result.platform,
      platform_version: result.platform_version,
      driver_version: result.driver_version,
      run_date: result.run_date,
      scale_factor: result.scale_factor,
      trust_label: result.trust_label,
    })),
    "table",
  );
  const allRows = buildQueryDiffRows(results, normalizedBaselineIndex, runLabels);
  const rowsByQueryId = new Map<string, QueryDiffRow[]>();
  for (const row of allRows) {
    const list = rowsByQueryId.get(row.queryId) ?? [];
    list.push(row);
    rowsByQueryId.set(row.queryId, list);
  }
  const rows = queryFilter
    ? queryFilter.flatMap((queryId) => rowsByQueryId.get(queryId) ?? [])
    : applyQueryDiffLimiter(allRows, limiter, topN);
  const shownQueryCount = new Set(rows.map((row) => row.queryId)).size;
  const totalQueryCount = rowsByQueryId.size;
  const uncomparableShown = new Set(
    rows.filter((row) => !row.comparable).map((row) => row.queryId),
  ).size;

  return (
    <section class="card mb-8" aria-labelledby="query-diff-title">
      <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="query-diff-title" class="text-base font-semibold text-[var(--bb-data-fg-primary)]">
            Query-level differences
          </h2>
          <p class="mt-1 text-xs text-[var(--bb-data-fg-muted)]">
            Baseline: <span class="font-medium text-[var(--bb-data-fg-primary)]">{runLabels[normalizedBaselineIndex] ?? baseline.platform}</span>. Negative deltas mean the
            candidate is faster than baseline.
          </p>
        </div>
        <StatusBadge role="comparison" tone="neutral" title={queryDiffCountSentence(shownQueryCount, totalQueryCount, limiter)}>
          {queryDiffCountSentence(shownQueryCount, totalQueryCount, limiter)}
        </StatusBadge>
      </div>

      {suppressionReason && (
        <div class="mb-4 rounded-md tone-warning border border-[var(--bb-data-border)] px-3 py-2 text-xs">
          This page does not name a winner because {suppressionReason}. You can still review the individual query measurements.
        </div>
      )}

      {uncomparableShown > 0 && (
        <p class="mb-3 text-xs text-[var(--bb-data-fg-muted)]" data-testid="uncomparable-note">
          {uncomparableShown === 1
            ? "1 query is marked not comparable: one run cannot answer it under the current basis. It is shown rather than dropped, and is excluded from every geomean."
            : `${uncomparableShown} queries are marked not comparable: one run cannot answer them under the current basis. They are shown rather than dropped, and are excluded from every geomean.`}
        </p>
      )}

      <TableScrollHint scrollerRef={scrollerRef} testId="query-diff-scroll-hint" />
      <div ref={scrollerRef} class="overflow-x-auto" data-testid="query-diff-scroll-container">
        <table class="min-w-full w-max divide-y divide-[var(--bb-data-border)] text-sm">
          <thead class="bg-[var(--bb-surface-data-muted)]">
            <tr>
              <th class="table-th">Query</th>
              <th class="table-th">Candidate</th>
              <th class="table-th">Baseline latency</th>
              <th class="table-th">Candidate latency</th>
              <th class="table-th">Passes</th>
              <th class="table-th">Ratio</th>
              <th class="table-th">Delta</th>
              <th class="table-th">Status</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-[var(--bb-data-border)] bg-[var(--bb-surface-data)]">
            {rows.map((row) => (
              <tr key={`${row.queryId}-${row.candidateResultId}`} class="hover:bg-[var(--bb-surface-data-muted)]">
                <td class="table-td font-mono font-medium">{row.queryId}</td>
                <td class="table-td">{row.candidatePlatform}</td>
                <td class="table-td font-mono">{formatMsCell(row.baselineMs)}</td>
                <td class="table-td font-mono">{formatMsCell(row.candidateMs)}</td>
                <td class="table-td font-mono text-xs">{formatPasses(row)}</td>
                <td class="table-td font-mono">{row.ratio !== null ? formatSpeedup(row.ratio).valueText : "-"}</td>
                <td class="table-td font-mono">{formatDelta(row.deltaMs)}</td>
                <td class="table-td">
                  {row.comparable ? (
                    <StatusBadge role="comparison" tone={statusTone(row.status)}>{statusLabel(row.status)}</StatusBadge>
                  ) : (
                    <StatusBadge role="comparison" tone="danger" title="One run cannot answer this query under the current basis">
                      Not comparable
                    </StatusBadge>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function buildQueryDiffRows(
  results: DetailResult[],
  baselineIndex = 0,
  runLabels?: readonly string[],
): QueryDiffRow[] {
  if (results.length < 2) return [];
  const normalizedBaselineIndex = normalizeBaselineIndex(results, baselineIndex);
  const baseline = results[normalizedBaselineIndex]!;
  const candidates = results
    .map((result, index) => ({ result, index }))
    .filter(({ index }) => index !== normalizedBaselineIndex);
  const queryIds = [
    ...new Set(results.flatMap((result) => result.display_timings.map((timing) => timing.query_id))),
  ].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

  return queryIds.flatMap((queryId) => {
    const baselineMs = displayMsForQuery(baseline, queryId);
    return candidates.map(({ result: candidate, index }) => {
      const candidateMs = displayMsForQuery(candidate, queryId);
      const deltaMs = baselineMs !== null && candidateMs !== null ? candidateMs - baselineMs : null;
      return {
        queryId,
        candidateResultId: candidate.result_id,
        candidatePlatform: runLabels?.[index] ?? candidate.platform,
        baselineMs,
        candidateMs,
        ratio: isValidTimingValue(baselineMs) && isValidTimingValue(candidateMs) ? candidateMs / baselineMs : null,
        deltaMs,
        status: diffStatus(deltaMs),
        baselineSamples: sampleCountForQuery(baseline, queryId),
        candidateSamples: sampleCountForQuery(candidate, queryId),
        comparable: baselineMs !== null && candidateMs !== null,
      };
    });
  });
}

function normalizeBaselineIndex(results: readonly DetailResult[], baselineIndex: number) {
  return results[baselineIndex] ? baselineIndex : 0;
}

function displayMsForQuery(result: DetailResult, queryId: string): number | null {
  return timingValueForQuery(result, queryId);
}

function sampleCountForQuery(result: DetailResult, queryId: string): number | null {
  const timing = result.display_timings.find((t) => t.query_id === queryId);
  return timing ? timing.sample_count : null;
}

function diffStatus(deltaMs: number | null): QueryDiffStatus {
  if (deltaMs === null) return "missing";
  if (Math.abs(deltaMs) < 1e-9) return "tie";
  return deltaMs < 0 ? "faster" : "slower";
}

function formatMsCell(ms: number | null) {
  return ms !== null ? fmtMs(ms) : <span class="text-[var(--bb-data-fg-subtle)]">-</span>;
}

function formatPasses(row: QueryDiffRow) {
  const base = row.baselineSamples;
  const cand = row.candidateSamples;
  if (base === null && cand === null) return "-";
  return `${base ?? "-"} / ${cand ?? "-"}`;
}

function formatDelta(deltaMs: number | null) {
  if (deltaMs === null) return "-";
  if (Math.abs(deltaMs) < 1e-9) return "0 ms";
  return `${deltaMs > 0 ? "+" : "-"}${fmtMs(Math.abs(deltaMs))}`;
}

function statusLabel(status: QueryDiffStatus) {
  if (status === "faster") return "Faster";
  if (status === "slower") return "Slower";
  if (status === "tie") return "Tie";
  return "Missing";
}

function statusTone(status: QueryDiffStatus): StatusTone {
  if (status === "faster") return "success";
  if (status === "slower") return "warning";
  if (status === "tie") return "neutral";
  return "danger";
}
