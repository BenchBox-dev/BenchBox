import type { DetailResult } from "@/types";
import { fmtMs } from "@/utils";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { TableScrollHint } from "@/components/TableScrollHint";

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
}

interface QueryDiffTableProps {
  results: DetailResult[];
  baselineIndex?: number;
  suppressionReason?: string | null;
}

export function QueryDiffTable({ results, baselineIndex = 0, suppressionReason = null }: QueryDiffTableProps) {
  if (results.length < 2) return null;
  const normalizedBaselineIndex = normalizeBaselineIndex(results, baselineIndex);
  const baseline = results[normalizedBaselineIndex]!;
  const rows = buildQueryDiffRows(results, normalizedBaselineIndex);

  return (
    <section class="card mb-8" aria-labelledby="query-diff-title">
      <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="query-diff-title" class="text-base font-semibold text-[var(--bb-data-fg-primary)]">
            Query-Level Diff
          </h2>
          <p class="mt-1 text-xs text-[var(--bb-data-fg-muted)]">
            Baseline: <span class="font-medium text-[var(--bb-data-fg-primary)]">{baseline.platform}</span>. Negative deltas mean the
            candidate is faster than baseline.
          </p>
        </div>
        <StatusBadge role="comparison" tone="neutral">{rows.length} comparisons</StatusBadge>
      </div>

      {suppressionReason && (
        <div class="mb-4 rounded-md tone-warning border border-[var(--bb-data-border)] px-3 py-2 text-xs">
          Winner claims are suppressed because {suppressionReason}; use these query values as raw evidence only.
        </div>
      )}

      <TableScrollHint testId="query-diff-scroll-hint" />
      <div class="overflow-x-auto" data-testid="query-diff-scroll-container">
        <table class="min-w-full w-max divide-y divide-[var(--bb-data-border)] text-sm">
          <thead class="bg-[var(--bb-surface-data-muted)]">
            <tr>
              <th class="table-th">Query</th>
              <th class="table-th">Candidate</th>
              <th class="table-th">Baseline latency</th>
              <th class="table-th">Candidate latency</th>
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
                <td class="table-td font-mono">{row.ratio !== null ? `${row.ratio.toFixed(2)}x` : "-"}</td>
                <td class="table-td font-mono">{formatDelta(row.deltaMs)}</td>
                <td class="table-td">
                  <StatusBadge role="comparison" tone={statusTone(row.status)}>{statusLabel(row.status)}</StatusBadge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function buildQueryDiffRows(results: DetailResult[], baselineIndex = 0): QueryDiffRow[] {
  if (results.length < 2) return [];
  const normalizedBaselineIndex = normalizeBaselineIndex(results, baselineIndex);
  const baseline = results[normalizedBaselineIndex]!;
  const candidates = results.filter((_, index) => index !== normalizedBaselineIndex);
  const queryIds = [
    ...new Set(results.flatMap((result) => result.display_timings.map((timing) => timing.query_id))),
  ].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

  return queryIds.flatMap((queryId) => {
    const baselineMs = displayMsForQuery(baseline, queryId);
    return candidates.map((candidate) => {
      const candidateMs = displayMsForQuery(candidate, queryId);
      const deltaMs = baselineMs !== null && candidateMs !== null ? candidateMs - baselineMs : null;
      return {
        queryId,
        candidateResultId: candidate.result_id,
        candidatePlatform: candidate.platform,
        baselineMs,
        candidateMs,
        ratio: baselineMs !== null && baselineMs > 0 && candidateMs !== null ? candidateMs / baselineMs : null,
        deltaMs,
        status: diffStatus(deltaMs),
      };
    });
  });
}

function normalizeBaselineIndex(results: DetailResult[], baselineIndex: number) {
  return results[baselineIndex] ? baselineIndex : 0;
}

function displayMsForQuery(result: DetailResult, queryId: string): number | null {
  return result.display_timings.find((timing) => timing.query_id === queryId)?.display_ms ?? null;
}

function diffStatus(deltaMs: number | null): QueryDiffStatus {
  if (deltaMs === null) return "missing";
  if (Math.abs(deltaMs) < 1e-9) return "tie";
  return deltaMs < 0 ? "faster" : "slower";
}

function formatMsCell(ms: number | null) {
  return ms !== null ? fmtMs(ms) : <span class="text-[var(--bb-data-fg-subtle)]">-</span>;
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
