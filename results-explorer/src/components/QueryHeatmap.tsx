/**
 * QueryHeatmap - Platform × Query matrix leaderboard.
 *
 * Renders a BenchmarkSummary as a heat-colored table where each cell shows
 * the canonical display_ms value for (platform, query), colored per column
 * using a log10(ratio-to-fastest) scale clamped at 10×. The default CSS path
 * uses a single-hue sequential palette, with grayscale lightness for reduced
 * color / high-contrast contexts.
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
import type { BenchmarkSummary, PlatformRow, SortDirection, SortState } from "@/types";
import { TrustBadge, ValidationBadge } from "@/components/TrustBadge";
import { fmtMs, fmtScore, fmtGeomean, complianceLabel } from "@/utils";
import { queryDisplayLabel, sortQueryIds } from "@/lib/queryLabels";

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

const MOBILE_OUTLIER_LIMIT = 3;

export function QueryHeatmap({
  summary,
  selectedIds,
  onSelectionChange,
  highContrast = false,
}: QueryHeatmapProps) {
  const { query_ids, platforms, ranking } = summary;
  const sortedQueryIds = useMemo(() => sortQueryIds(query_ids), [query_ids]);
  const hasSelection = onSelectionChange !== undefined;
  const gridRef = useRef<HTMLTableElement>(null);

  // Roving tabindex state: which query cell [rowIdx, colIdx] has tabIndex=0.
  const [focusPos, setFocusPos] = useState({ row: 0, col: 0 });
  // aria-live announcement for the focused cell.
  const [announcement, setAnnouncement] = useState("");

  // Per-column minimum: fastest time across all platforms for each query.
  // Memoized on `summary` to avoid recomputing the full matrix on every render
  // (the for loop runs sortedQueryIds.length × platforms.length iterations).
  const colMins = useMemo<Record<string, number | null>>(() => {
    const mins: Record<string, number | null> = {};
    for (const qid of sortedQueryIds) {
      const vals = platforms
        .map((p) => p.timings[qid] ?? null)
        // Exclude zero/null cells; sub-ms values round to 0 in some runners.
        .filter((v): v is number => v !== null && v > 0);
      mins[qid] = vals.length > 0 ? Math.min(...vals) : null;
    }
    return mins;
  }, [platforms, sortedQueryIds]);

  // Determine primary display metric from the artifact's ranking config.
  const primaryMetric = ranking?.primary_metric ?? "display_geomean_ms";
  const higherIsBetter = ranking?.primary_order === "desc";
  const defaultPrimaryDirection: SortDirection = higherIsBetter ? "desc" : "asc";
  type MatrixSortKey = "platform" | "primary" | "geomean" | `query:${string}`;
  const [sort, setSort] = useState<SortState<MatrixSortKey> | null>(null);
  const activeSort = sort ?? { key: "primary", direction: defaultPrimaryDirection };

  function getPrimaryValue(row: PlatformRow): number | null {
    return primaryMetric === "power_score" ? row.power_score : row.display_geomean_ms;
  }

  function fmtPrimary(val: number | null): string {
    if (val === null) return "-";
    return primaryMetric === "power_score" ? fmtScore(val) : fmtGeomean(val);
  }

  function compareNullableNumber(a: number | null, b: number | null, direction: SortDirection): number {
    // Keep missing metrics last in both directions so sorting never hides
    // populated rows below gaps.
    if (a === null && b === null) return 0;
    if (a === null) return 1;
    if (b === null) return -1;
    return direction === "asc" ? a - b : b - a;
  }

  function compareMatrixRows(a: PlatformRow, b: PlatformRow, current: SortState<MatrixSortKey>): number {
    if (current.key === "platform") {
      return current.direction === "asc"
        ? a.platform.localeCompare(b.platform)
        : b.platform.localeCompare(a.platform);
    }
    if (current.key === "primary") {
      if (a.is_ranking_eligible !== b.is_ranking_eligible) {
        return a.is_ranking_eligible ? -1 : 1;
      }
      return compareNullableNumber(getPrimaryValue(a), getPrimaryValue(b), current.direction);
    }
    if (current.key === "geomean") {
      return compareNullableNumber(a.display_geomean_ms, b.display_geomean_ms, current.direction);
    }
    if (current.key.startsWith("query:")) {
      const queryId = current.key.slice("query:".length);
      return compareNullableNumber(a.timings[queryId] ?? null, b.timings[queryId] ?? null, current.direction);
    }
    return 0;
  }

  const sorted = useMemo(
    () => [...platforms].sort((a, b) => compareMatrixRows(a, b, activeSort)),
    [activeSort, platforms],
  );

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

  function toggleSort(key: MatrixSortKey, initialDirection: SortDirection = "asc") {
    setSort((prev) => {
      const current = prev ?? { key: "primary" as const, direction: defaultPrimaryDirection };
      if (current.key === key) {
        return { key, direction: current.direction === "asc" ? "desc" : "asc" };
      }
      return { key, direction: initialDirection };
    });
  }

  function ariaSort(key: MatrixSortKey): "ascending" | "descending" | "none" {
    if (activeSort.key !== key) return "none";
    return activeSort.direction === "asc" ? "ascending" : "descending";
  }

  function sortArrow(key: MatrixSortKey) {
    if (activeSort.key !== key) return " ↕";
    return activeSort.direction === "asc" ? " ↑" : " ↓";
  }

  function sortAnnouncement(key: MatrixSortKey) {
    if (activeSort.key !== key) return null;
    return (
      <span class="sr-only">
        {activeSort.direction === "asc" ? "sorted ascending" : "sorted descending"}
      </span>
    );
  }

  /** Keyboard handler for query timing cells - implements roving tabindex. */
  function handleCellKey(e: KeyboardEvent, rowIdx: number, colIdx: number) {
    let nextRow = rowIdx;
    let nextCol = colIdx;
    switch (e.key) {
      case "ArrowRight":
        nextCol = Math.min(colIdx + 1, sortedQueryIds.length - 1);
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
        nextCol = sortedQueryIds.length - 1;
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

      <div
        class="space-y-3 md:hidden"
        data-testid="query-heatmap-mobile-cards"
        role="list"
        aria-label={`${summary.benchmark} compact query result cards`}
      >
        {sorted.map((row) => {
          const isSelected = selectedIds?.has(rowKey(row)) ?? false;
          const outliers = queryOutliers(row, sortedQueryIds, colMins);
          return (
            <article
              key={row.result_id}
              data-testid={`query-heatmap-mobile-card-${row.result_id}`}
              role="listitem"
              class={`rounded-lg border border-gray-200 bg-white p-3 shadow-sm ${
                isSelected ? "border-brand-300 bg-blue-50" : ""
              }`}
            >
              <div class="flex items-start gap-3">
                {hasSelection && (
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggleRow(row)}
                    aria-label={`Select ${row.platform} for comparison`}
                    class="mt-1 h-4 w-4 shrink-0 rounded border-gray-300 focus:ring-2 focus:ring-brand-500"
                  />
                )}
                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-center gap-1.5">
                    <h2 class="text-sm font-semibold text-gray-900">{row.platform}</h2>
                    {!row.is_ranking_eligible && (
                      <span class="text-xs text-gray-400">{complianceLabel(row.compliance_class)}</span>
                    )}
                  </div>
                  {row.platform_version && (
                    <div class="mt-0.5 text-xs text-gray-400">{row.platform_version}</div>
                  )}
                  <a
                    href={`/results/r/${row.result_id}#run-receipt`}
                    class="mt-1 inline-block text-xs font-medium no-underline"
                  >
                    Receipt →
                  </a>
                </div>
                <dl class="shrink-0 text-right">
                  <dt class="text-[0.65rem] font-semibold uppercase text-gray-400">{primaryLabel}</dt>
                  <dd class="font-mono text-sm font-semibold text-gray-900">
                    {fmtPrimary(getPrimaryValue(row))}
                  </dd>
                </dl>
              </div>

              <div class="mt-3 flex flex-wrap gap-1.5">
                <TrustBadge trustLabel={row.trust_label} compact />
                <ValidationBadge validationStatus={row.validation_status} showMissing />
                {showGeomeanCol && (
                  <span class="rounded-full bg-gray-100 px-2 py-0.5 font-mono text-xs text-gray-600">
                    Geomean {fmtGeomean(row.display_geomean_ms)}
                  </span>
                )}
              </div>

              <div class="mt-3 border-t border-gray-100 pt-3">
                <div class="text-[0.65rem] font-semibold uppercase text-gray-400">Query outliers</div>
                {outliers.length > 0 ? (
                  <div class="mt-2 grid gap-2" role="list" aria-label={`${row.platform} query outliers`}>
                    {outliers.map((outlier) => (
                      <div
                        key={outlier.queryId}
                        role="listitem"
                        class="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-md bg-gray-50 px-2 py-1.5"
                      >
                        <div class="min-w-0">
                          <div class="truncate font-mono text-xs font-semibold text-gray-800">
                            {queryDisplayLabel(outlier.queryId)}
                          </div>
                          <div class="text-xs text-gray-500">{outlier.ratioLabel}</div>
                        </div>
                        <div class="font-mono text-xs font-semibold text-gray-900">
                          {fmtMs(outlier.ms)}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p class="mt-2 rounded-md bg-gray-50 px-2 py-1.5 text-xs text-gray-500">
                    No query timings published.
                  </p>
                )}
              </div>
            </article>
          );
        })}
      </div>

      <div class="hidden md:block">
        <div class="mb-2 flex items-center justify-between gap-3 text-xs text-gray-500">
          <span
            data-testid="query-heatmap-scroll-hint"
            class="inline-flex items-center rounded-full border border-gray-200 bg-white px-2.5 py-1 font-medium shadow-sm"
          >
            Query columns →
          </span>
          <span>{sortedQueryIds.length.toLocaleString()} queries</span>
        </div>
        <div
          class="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm"
          data-testid="query-heatmap-scroll-container"
        >
        <table
          ref={gridRef}
          role="grid"
          aria-label={`${summary.benchmark} SF${summary.scale_factor} ${summary.phase} results`}
          class="min-w-max text-sm"
        >
          <thead class="bg-gray-50">
            <tr role="row">
              {hasSelection && <th role="columnheader" scope="col" aria-label="Select for comparison" class="table-th w-12 min-w-12 px-2" />}
              <th
                role="columnheader"
                scope="col"
                class="sticky left-0 z-10 w-44 min-w-44 bg-gray-50 p-0"
                aria-sort={ariaSort("platform")}
              >
                <button
                  type="button"
                  class="table-th block w-full cursor-pointer select-none border-0 bg-transparent text-left"
                  onClick={() => toggleSort("platform")}
                >
                  Platform{sortArrow("platform")}
                  {sortAnnouncement("platform")}
                </button>
              </th>
              <th role="columnheader" scope="col" class="table-th sticky left-44 z-10 w-36 min-w-36 whitespace-nowrap bg-gray-50">
                Trust
              </th>
              <th
                role="columnheader"
                scope="col"
                aria-sort={ariaSort("primary")}
                class="w-32 min-w-32 whitespace-nowrap p-0"
                title={primaryLabel}
              >
                <button
                  type="button"
                  class="table-th block w-full cursor-pointer select-none border-0 bg-transparent text-left"
                  onClick={() => toggleSort("primary", defaultPrimaryDirection)}
                >
                  {primaryLabel}{sortArrow("primary")}
                  {sortAnnouncement("primary")}
                </button>
              </th>
              {showGeomeanCol && (
                <th
                  role="columnheader"
                  scope="col"
                  class="w-32 min-w-32 whitespace-nowrap p-0"
                  aria-sort={ariaSort("geomean")}
                  title="Geometric mean of per-query display times"
                >
                  <button
                    type="button"
                    class="table-th block w-full cursor-pointer select-none border-0 bg-transparent text-left text-gray-400"
                    onClick={() => toggleSort("geomean")}
                  >
                    Geomean{sortArrow("geomean")}
                    {sortAnnouncement("geomean")}
                  </button>
                </th>
              )}
              {sortedQueryIds.map((qid) => (
                <th
                  key={qid}
                  role="columnheader"
                  scope="col"
                  class="min-w-[7rem] whitespace-nowrap p-0 font-mono"
                  aria-sort={ariaSort(`query:${qid}`)}
                >
                  <button
                    type="button"
                    class="table-th block w-full cursor-pointer select-none border-0 bg-transparent text-left font-mono"
                    data-query-label={qid}
                    onClick={() => toggleSort(`query:${qid}`)}
                  >
                    {queryDisplayLabel(qid)}{sortArrow(`query:${qid}`)}
                    {sortAnnouncement(`query:${qid}`)}
                  </button>
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
                  data-testid={row.result_id}
                  class={`hover:bg-gray-50 ${isSelected ? "bg-blue-50" : ""}`}
                >
                  {hasSelection && (
                    <td role="gridcell" class="table-td w-12 min-w-12 px-2">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleRow(row)}
                        aria-label={`Select ${row.platform} for comparison`}
                        class="h-4 w-4 rounded border-gray-300 focus:ring-2 focus:ring-brand-500"
                      />
                    </td>
                  )}
                  <td
                    role="gridcell"
                    class={`table-td sticky left-0 z-10 w-44 min-w-44 ${
                      isSelected ? "bg-blue-50" : "bg-white"
                    }`}
                  >
                    <div class="flex flex-wrap items-center gap-1.5">
                      <span class="font-medium text-gray-900">{row.platform}</span>
                      {!row.is_ranking_eligible && (
                        <span class="text-xs text-gray-400">{complianceLabel(row.compliance_class)}</span>
                      )}
                    </div>
                    {row.platform_version && (
                      <div class="mt-0.5 text-xs text-gray-400">{row.platform_version}</div>
                    )}
                    <a
                      href={`/results/r/${row.result_id}#run-receipt`}
                      class="mt-1 inline-block text-xs font-medium no-underline"
                    >
                      Receipt →
                    </a>
                  </td>
                  <td
                    role="gridcell"
                    class={`table-td sticky left-44 z-10 w-36 min-w-36 whitespace-nowrap ${
                      isSelected ? "bg-blue-50" : "bg-white"
                    }`}
                  >
                    <div class="flex flex-wrap gap-1">
                      <TrustBadge trustLabel={row.trust_label} compact />
                      <ValidationBadge validationStatus={row.validation_status} showMissing />
                    </div>
                  </td>
                  <td role="gridcell" class="table-td w-32 min-w-32 whitespace-nowrap font-mono">
                    {fmtPrimary(getPrimaryValue(row))}
                  </td>
                  {showGeomeanCol && (
                    <td role="gridcell" class="table-td w-32 min-w-32 whitespace-nowrap font-mono text-gray-500">
                      {fmtGeomean(row.display_geomean_ms)}
                    </td>
                  )}
                  {sortedQueryIds.map((qid, colIdx) => {
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
                        : `No published query run for ${row.platform} ${qid}`;

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
                        class={`table-td min-w-[7rem] whitespace-nowrap text-right font-mono focus:outline focus:outline-2 focus:outline-brand-500 ${
                          hue !== null ? "heatmap-cell" : ms === null ? "bg-gray-50 text-gray-400" : ""
                        }`}
                        style={cellStyle}
                        aria-label={ariaLabel}
                        title={ms === null ? "No published run for this query/platform cell." : undefined}
                        onKeyDown={(e) => handleCellKey(e as KeyboardEvent, rowIdx, colIdx)}
                        onFocus={() => setAnnouncement(`${queryDisplayLabel(qid)}: ${ariaLabel}`)}
                      >
                        {ms !== null ? fmtMs(ms) : "No run"}
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
    </div>
  );
}

interface QueryOutlier {
  queryId: string;
  ms: number;
  ratio: number;
  ratioLabel: string;
}

function queryOutliers(
  row: PlatformRow,
  sortedQueryIds: string[],
  colMins: Record<string, number | null>,
): QueryOutlier[] {
  return sortedQueryIds
    .map((queryId) => {
      const ms = row.timings[queryId] ?? null;
      if (ms === null) return null;
      const minInCol = colMins[queryId] ?? null;
      const ratio = minInCol !== null && minInCol > 0 ? ms / minInCol : null;
      return {
        queryId,
        ms,
        ratio: ratio ?? 0,
        ratioLabel: queryRatioLabel(ratio),
      };
    })
    .filter((item): item is QueryOutlier => item !== null)
    .sort((a, b) => b.ratio - a.ratio || b.ms - a.ms || a.queryId.localeCompare(b.queryId))
    .slice(0, MOBILE_OUTLIER_LIMIT);
}

function queryRatioLabel(ratio: number | null): string {
  if (ratio === null) return "No cohort baseline";
  if (ratio <= 1.005) return "Fastest in cohort";
  return `${ratio.toFixed(1)}× fastest`;
}
