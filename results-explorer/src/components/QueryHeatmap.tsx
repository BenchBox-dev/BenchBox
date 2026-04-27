/**
 * QueryHeatmap - Platform × Query matrix leaderboard.
 *
 * Renders a BenchmarkSummary as a heat-colored table where each cell shows
 * the canonical display_ms value for (platform, query), colored per column
 * using a log10(ratio-to-fastest) scale clamped at 10× (green → red).
 *
 * Accessibility:
 *   - role="grid" on the table; role="gridcell" on data cells.
 *   - Roving tabindex: only one query cell has tabIndex=0; arrow keys navigate.
 *   - aria-live region announces the focused cell value.
 *   - Reduced-color mode (highContrast prop or prefers-contrast CSS) uses
 *     grayscale lightness steps instead of hue so CVD users see structure.
 *
 * Color is emitted via --cell-hue and --cell-lightness CSS custom properties
 * so dark-mode and prefers-contrast media queries can override without
 * touching this component.
 */

import { useMemo, useRef, useState } from "preact/hooks";
import type { JSX } from "preact";
import type { BenchmarkSummary, PlatformRow } from "@/types";
import { TrustBadge } from "@/components/TrustBadge";
import { fmtMs, fmtScore, fmtGeomean, complianceLabel } from "@/utils";

// ---------------------------------------------------------------------------
// Color math - sourced from chartMath.ts (single source of truth for parity)
// Re-exported here so existing callers of `QueryHeatmap` don't need to change.
// ---------------------------------------------------------------------------
import { colorForCell, lightnessForCell } from "@/lib/chartMath";
export { colorForCell, lightnessForCell };

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface QueryHeatmapProps {
  summary: BenchmarkSummary;
  /** Currently selected result_ids; undefined = selection disabled. */
  selectedIds?: Set<string>;
  onSelectionChange?: (ids: Set<string>) => void;
  /**
   * Activates reduced-color (grayscale lightness) mode for color-vision
   * accessibility. Also activates automatically via the CSS
   * `prefers-contrast: more` media query.
   */
  highContrast?: boolean;
}

export function QueryHeatmap({
  summary,
  selectedIds,
  onSelectionChange,
  highContrast = false,
}: QueryHeatmapProps) {
  const { query_ids, platforms, ranking } = summary;
  const hasSelection = onSelectionChange !== undefined;
  const gridRef = useRef<HTMLTableElement>(null);

  // Roving tabindex state: which query cell [rowIdx, colIdx] has tabIndex=0.
  const [focusPos, setFocusPos] = useState({ row: 0, col: 0 });
  // aria-live announcement for the focused cell.
  const [announcement, setAnnouncement] = useState("");

  // Per-column minimum: fastest time across all platforms for each query.
  // Memoized on `summary` to avoid recomputing the full matrix on every render
  // (the for loop runs query_ids.length × platforms.length iterations).
  const colMins = useMemo<Record<string, number | null>>(() => {
    const mins: Record<string, number | null> = {};
    for (const qid of query_ids) {
      const vals = platforms
        .map((p) => p.timings[qid] ?? null)
        // Exclude zero/null cells; sub-ms values round to 0 in some runners.
        .filter((v): v is number => v !== null && v > 0);
      mins[qid] = vals.length > 0 ? Math.min(...vals) : null;
    }
    return mins;
  }, [summary]);

  // Determine primary display metric from the artifact's ranking config.
  const primaryMetric = ranking?.primary_metric ?? "display_geomean_ms";
  const higherIsBetter = ranking?.primary_order === "desc";

  function getPrimaryValue(row: PlatformRow): number | null {
    return primaryMetric === "power_score" ? row.power_score : row.display_geomean_ms;
  }

  function fmtPrimary(val: number | null): string {
    if (val === null) return "-";
    return primaryMetric === "power_score" ? fmtScore(val) : fmtGeomean(val);
  }

  // Sort: eligible rows first, then by primary metric.
  const sorted = [...platforms].sort((a, b) => {
    if (a.is_ranking_eligible !== b.is_ranking_eligible) {
      return a.is_ranking_eligible ? -1 : 1;
    }
    const av = getPrimaryValue(a);
    const bv = getPrimaryValue(b);
    if (av === null && bv === null) return 0;
    if (av === null) return 1;
    if (bv === null) return -1;
    return higherIsBetter ? bv - av : av - bv;
  });

  /** Returns the short_id for a row if available, otherwise falls back to result_id.
   *  The short_id is used for Compare URLs so bookmarks stay compact. */
  function rowKey(row: PlatformRow): string {
    return row.short_id || row.result_id;
  }

  function toggleRow(row: PlatformRow) {
    if (!onSelectionChange || !selectedIds) return;
    const key = rowKey(row);
    const next = new Set(selectedIds);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onSelectionChange(next);
  }

  /** Keyboard handler for query timing cells - implements roving tabindex. */
  function handleCellKey(e: KeyboardEvent, rowIdx: number, colIdx: number) {
    let nextRow = rowIdx;
    let nextCol = colIdx;
    switch (e.key) {
      case "ArrowRight":
        nextCol = Math.min(colIdx + 1, query_ids.length - 1);
        break;
      case "ArrowLeft":
        nextCol = Math.max(colIdx - 1, 0);
        break;
      case "ArrowDown":
        nextRow = Math.min(rowIdx + 1, sorted.length - 1);
        break;
      case "ArrowUp":
        nextRow = Math.max(rowIdx - 1, 0);
        break;
      case "Home":
        nextCol = 0;
        break;
      case "End":
        nextCol = query_ids.length - 1;
        break;
      default:
        return;
    }
    // Always prevent page scroll for arrow keys inside the grid, even at boundaries.
    e.preventDefault();
    if (nextRow === rowIdx && nextCol === colIdx) return;
    setFocusPos({ row: nextRow, col: nextCol });
    const target = gridRef.current?.querySelector(
      `[data-cell="${nextRow}-${nextCol}"]`,
    ) as HTMLElement | null;
    target?.focus();
  }

  if (platforms.length === 0) {
    return (
      <div class="rounded-lg border border-dashed border-gray-300 bg-white p-10 text-center text-gray-400">
        No results available for this configuration.
      </div>
    );
  }

  // Single-platform: suppress heat coloring (no relative comparison to show).
  const suppressHeat = sorted.length < 2;

  const primaryLabel = primaryMetric === "power_score" ? "Power Score" : "Geomean";
  // Show secondary geomean column when the artifact carries a secondary metric,
  // rather than hardcoding the power_score assumption.
  const showGeomeanCol = ranking?.secondary_metric === "display_geomean_ms";

  return (
    <div class={`relative ${highContrast ? "heatmap-reduced-color" : ""}`}>
      {/* aria-live region for cell focus announcements */}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        class="sr-only"
      >
        {announcement}
      </div>

      <div class="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
        <table
          ref={gridRef}
          role="grid"
          aria-label={`${summary.benchmark} SF${summary.scale_factor} ${summary.phase} results`}
          class="min-w-full text-sm"
        >
          <thead class="bg-gray-50">
            <tr role="row">
              {hasSelection && <th role="columnheader" scope="col" aria-label="Select for comparison" class="table-th w-8 px-2" />}
              <th role="columnheader" scope="col" class="table-th sticky left-0 z-10 min-w-44 bg-gray-50">
                Platform
              </th>
              <th role="columnheader" scope="col" class="table-th sticky left-44 z-10 whitespace-nowrap bg-gray-50">
                Trust
              </th>
              <th
                role="columnheader"
                scope="col"
                aria-sort={higherIsBetter ? "descending" : "ascending"}
                class="table-th whitespace-nowrap"
                title={primaryLabel}
              >
                {primaryLabel}
              </th>
              {showGeomeanCol && (
                <th
                  role="columnheader"
                  scope="col"
                  class="table-th whitespace-nowrap text-gray-400"
                  title="Geometric mean of per-query display times"
                >
                  Geomean
                </th>
              )}
              {query_ids.map((qid) => (
                <th
                  key={qid}
                  role="columnheader"
                  scope="col"
                  class="table-th whitespace-nowrap font-mono"
                >
                  {qid}
                </th>
              ))}
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-100">
            {sorted.map((row, rowIdx) => {
              const isSelected = selectedIds?.has(rowKey(row)) ?? false;
              return (
                <tr
                  key={row.result_id}
                  role="row"
                  class={`hover:bg-gray-50 ${isSelected ? "bg-blue-50" : ""}`}
                >
                  {hasSelection && (
                    <td role="gridcell" class="table-td w-8 px-2">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleRow(row)}
                        aria-label={`Select ${row.platform} for comparison`}
                        class="h-4 w-4 rounded border-gray-300 focus:ring-2 focus:ring-brand-500"
                      />
                    </td>
                  )}
                  <td role="gridcell" class="table-td sticky left-0 z-10 min-w-44 bg-white">
                    <div class="flex flex-wrap items-center gap-1.5">
                      <span class="font-medium text-gray-900">{row.platform}</span>
                      {!row.is_ranking_eligible && (
                        <span class="text-xs text-gray-400">{complianceLabel(row.compliance_class)}</span>
                      )}
                    </div>
                    {row.platform_version && (
                      <div class="mt-0.5 text-xs text-gray-400">{row.platform_version}</div>
                    )}
                  </td>
                  <td role="gridcell" class="table-td sticky left-44 z-10 whitespace-nowrap bg-white">
                    <TrustBadge trustLabel={row.trust_label} compact />
                  </td>
                  <td role="gridcell" class="table-td whitespace-nowrap font-mono">
                    {fmtPrimary(getPrimaryValue(row))}
                  </td>
                  {showGeomeanCol && (
                    <td role="gridcell" class="table-td whitespace-nowrap font-mono text-gray-500">
                      {fmtGeomean(row.display_geomean_ms)}
                    </td>
                  )}
                  {query_ids.map((qid, colIdx) => {
                    const ms = row.timings[qid] ?? null;
                    const minInCol = colMins[qid] ?? null;
                    const hue = suppressHeat ? null : colorForCell(ms, minInCol);
                    const lightness = suppressHeat ? null : lightnessForCell(ms, minInCol);
                    const ratio =
                      ms !== null && minInCol !== null && minInCol > 0 ? ms / minInCol : null;
                    const ariaLabel =
                      ms !== null
                        ? ratio !== null
                          ? ratio <= 1.005
                            ? `${fmtMs(ms)}, fastest in column`
                            : `${fmtMs(ms)}, ${ratio.toFixed(1)}× fastest in column`
                          : fmtMs(ms)
                        : "no data";

                    const isFocused = focusPos.row === rowIdx && focusPos.col === colIdx;

                    const cellStyle: JSX.CSSProperties | undefined =
                      hue !== null
                        ? ({
                            "--cell-hue": String(hue),
                            "--cell-lightness": lightness ?? "95%",
                          } as JSX.CSSProperties)
                        : undefined;

                    return (
                      <td
                        key={qid}
                        role="gridcell"
                        data-cell={`${rowIdx}-${colIdx}`}
                        tabIndex={isFocused ? 0 : -1}
                        class={`table-td whitespace-nowrap text-right font-mono focus:outline focus:outline-2 focus:outline-brand-500 ${
                          hue !== null ? "heatmap-cell" : ms === null ? "text-gray-400" : ""
                        }`}
                        style={cellStyle}
                        aria-label={ariaLabel}
                        onKeyDown={(e) => handleCellKey(e as KeyboardEvent, rowIdx, colIdx)}
                        onFocus={() => setAnnouncement(`${qid}: ${ariaLabel}`)}
                      >
                        {ms !== null ? fmtMs(ms) : "-"}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
