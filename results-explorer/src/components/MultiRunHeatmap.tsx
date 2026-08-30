import type { DetailResult } from "@/types";
import { StatusBadge } from "@/components/StatusBadge";
import { type QueryDiffLimiter, QUERY_DIFF_LIMITER_LABELS } from "@/components/QueryDiffTable";
import {
  DIVERGING_RATIO_CLAMP,
  divergingRatioPosition,
  queryDisagreementSpread,
} from "@/lib/chartMath";
import { timingValueForQuery } from "@/lib/displayEligibility";

/**
 * Query x run heatmap of ratios against the chosen baseline.
 *
 * DIVERGING, not sequential, and that is the whole reason this is a separate
 * component from QueryHeatmap rather than a mode of it. QueryHeatmap encodes
 * magnitude from a floor (ratio-to-fastest, always >= 1), where a single-hue
 * ramp is correct. This encodes direction from a midpoint, where polarity --
 * faster or slower than baseline -- is the point. A sequential ramp would paint
 * 0.5x and 2.0x as different intensities of one hue and lose the sign, which is
 * the one thing this chart exists to show. See w0.log for the full decision.
 *
 * Reused from QueryHeatmap deliberately: role="grid" / role="gridcell"
 * semantics and the practice of carrying the value as TEXT in every cell, so
 * colour is never the only encoding.
 */
export interface MultiRunHeatmapProps {
  results: DetailResult[];
  baselineIndex: number;
  runLabels: readonly string[];
  /** How many query rows to render; the caption always names the total. */
  limit?: number;
  /** Filter or ordering to apply to query rows. */
  limiter?: QueryDiffLimiter;
  /** Order rows by where the runs disagree most, rather than by query id. */
  orderByDisagreement?: boolean;
}

export interface HeatmapCell {
  ratio: number | null;
  /** [-1, 1] position on the diverging scale, or null when unanswerable. */
  position: number | null;
}

export interface HeatmapRow {
  queryId: string;
  cells: HeatmapCell[];
  /** Log-space spread across runs; null when fewer than two could answer. */
  disagreement: number | null;
}

export function buildHeatmapRows(
  results: readonly DetailResult[],
  baselineIndex: number,
): HeatmapRow[] {
  const queryIds = new Set<string>();
  for (const r of results) for (const t of r.display_timings) queryIds.add(t.query_id);
  const baseline = results[baselineIndex];

  return [...queryIds]
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
    .map((queryId) => {
      const baseMs = baseline ? timingValueForQuery(baseline, queryId) : null;
      const cells: HeatmapCell[] = results.map((r) => {
        const ms = timingValueForQuery(r, queryId);
        const ratio = ms !== null && baseMs !== null && baseMs > 0 ? ms / baseMs : null;
        return { ratio, position: divergingRatioPosition(ratio) };
      });
      return {
        queryId,
        cells,
        disagreement: queryDisagreementSpread(cells.map((c) => c.ratio)),
      };
    });
}

/** Rows ordered by disagreement, unanswerable-heavy rows last. */
export function orderRowsByDisagreement(rows: readonly HeatmapRow[]): HeatmapRow[] {
  return [...rows].sort((a, b) => {
    if (a.disagreement === null && b.disagreement === null) return 0;
    if (a.disagreement === null) return 1;
    if (b.disagreement === null) return -1;
    return b.disagreement - a.disagreement;
  });
}

/** Filter and rank heatmap rows according to the chosen limiter. */
export function filterHeatmapRows(
  rows: readonly HeatmapRow[],
  limiter: QueryDiffLimiter = "all",
  baselineIndex: number = 0,
): HeatmapRow[] {
  if (limiter === "all") return [...rows];
  if (limiter === "movement") return orderRowsByDisagreement(rows);

  if (limiter === "speedups") {
    const speedupRows = rows.filter((r) =>
      r.cells.some((c, i) => i !== baselineIndex && c.ratio !== null && c.ratio < 1),
    );
    return speedupRows.sort((a, b) => {
      const minA = Math.min(...a.cells.map((c, i) => (i !== baselineIndex && c.ratio !== null ? c.ratio : 1)));
      const minB = Math.min(...b.cells.map((c, i) => (i !== baselineIndex && c.ratio !== null ? c.ratio : 1)));
      return minA - minB;
    });
  }

  if (limiter === "slowdowns") {
    const slowdownRows = rows.filter((r) =>
      r.cells.some((c, i) => i !== baselineIndex && c.ratio !== null && c.ratio > 1),
    );
    return slowdownRows.sort((a, b) => {
      const maxA = Math.max(...a.cells.map((c, i) => (i !== baselineIndex && c.ratio !== null ? c.ratio : 1)));
      const maxB = Math.max(...b.cells.map((c, i) => (i !== baselineIndex && c.ratio !== null ? c.ratio : 1)));
      return maxB - maxA;
    });
  }

  return [...rows];
}

function cellStyle(position: number | null): string {
  if (position === null) return "";
  // Two hues around a neutral midpoint. Emitted as CSS custom properties for
  // the same reason QueryHeatmap does it: dark mode and prefers-contrast
  // override without touching this component.
  const hue = position < 0 ? 150 : 15;
  const lightness = 95 - Math.abs(position) * 35;
  return `--cell-hue:${hue}; --cell-lightness:${lightness.toFixed(1)}%; background-color: hsl(${hue} 60% ${lightness.toFixed(1)}%);`;
}

function cellText(cell: HeatmapCell): string {
  if (cell.ratio === null) return "—";
  return `${cell.ratio.toFixed(2)}x`;
}

export function MultiRunHeatmap({
  results,
  baselineIndex,
  runLabels,
  limit = 25,
  limiter,
  orderByDisagreement = false,
}: MultiRunHeatmapProps) {
  if (results.length < 3) return null;
  const effectiveLimiter: QueryDiffLimiter = limiter ?? (orderByDisagreement ? "movement" : "all");
  const all = buildHeatmapRows(results, baselineIndex);
  const ordered = filterHeatmapRows(all, effectiveLimiter, baselineIndex);
  const shown = ordered.slice(0, limit);
  const unrecorded = shown.reduce(
    (n, row) => n + row.cells.filter((c) => c.ratio === null).length,
    0,
  );

  return (
    <section class="card mb-8" aria-labelledby="multi-run-heatmap-title">
      <div class="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="multi-run-heatmap-title" class="text-base font-semibold text-[var(--bb-data-fg-primary)]">
            Query by run
          </h2>
          <p class="mt-1 text-xs text-[var(--bb-data-fg-muted)]" data-testid="heatmap-caption">
            {shown.length === 0 && effectiveLimiter !== "all"
              ? `No queries match ${QUERY_DIFF_LIMITER_LABELS[effectiveLimiter].toLowerCase()} — showing 0 of ${all.length}.`
              : `Ratio against ${runLabels[baselineIndex] ?? "the baseline"} — below 1.00x is faster. Showing ${shown.length} of ${all.length} ${all.length === 1 ? "query" : "queries"}.`}
          </p>
        </div>
        <StatusBadge role="comparison" tone="neutral">
          {`Scale saturates at ${DIVERGING_RATIO_CLAMP}x`}
        </StatusBadge>
      </div>

      {unrecorded > 0 ? (
        <p class="mb-2 text-xs text-[var(--bb-data-fg-subtle)]" data-testid="heatmap-unrecorded-note">
          {`${unrecorded} ${unrecorded === 1 ? "cell is" : "cells are"} unrecorded: that run cannot answer the query under the current basis. Unrecorded is not parity, and is left uncoloured.`}
        </p>
      ) : null}

      <div class="overflow-x-auto">
        <table role="grid" class="min-w-full w-max divide-y divide-[var(--bb-data-border)] text-sm">
          <thead class="bg-[var(--bb-surface-data-muted)]">
            <tr role="row">
              <th role="columnheader" class="table-th">Query</th>
              {results.map((r, i) => (
                <th key={r.result_id} role="columnheader" class="table-th">
                  {runLabels[i] ?? r.platform}
                  {i === baselineIndex ? " (baseline)" : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody class="divide-y divide-[var(--bb-data-border)] bg-[var(--bb-surface-data)]">
            {shown.map((row) => (
              <tr role="row" key={row.queryId}>
                <td class="table-td font-mono font-medium">{row.queryId}</td>
                {row.cells.map((cell, i) => (
                  <td
                    key={i}
                    role="gridcell"
                    class="table-td font-mono text-xs"
                    style={cellStyle(cell.position)}
                    data-testid={`cell-${row.queryId}-${i}`}
                  >
                    {/* Value as text in every cell: colour is never the only encoding. */}
                    {cellText(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
