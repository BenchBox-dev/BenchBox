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

import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { JSX } from "preact";
import type { BenchmarkSummary, PlatformRow, SortDirection, SortState } from "@/types";
import { TrustBadge, ValidationBadge } from "@/components/TrustBadge";
import { fmtMs as formatDurationMs, fmtGeomean } from "@/utils";
import { formatLatencyMs, formatPowerScore, formatSpeedup } from "@/lib/metricFormatters";
import { queryDisplayLabel, sortQueryIds } from "@/lib/queryLabels";
import { compareSelectionLabel } from "@/lib/compareCohort";
import {
  describeCompareExclusionReason,
  type CompareExclusionReasonCopy,
} from "@/lib/compareExclusionReasons";
import {
  formatTimingExclusion,
  isComparable,
  isRankable,
  platformTimingValue,
  validPrimaryMetricValue,
} from "@/lib/displayEligibility";

// ---------------------------------------------------------------------------
// Color math - sourced from chartMath.ts (single source of truth for parity)
// Re-exported here so existing callers of `QueryHeatmap` don't need to change.
// ---------------------------------------------------------------------------
import { colorForCell, lightnessForCell } from "@/lib/chartMath";
export { colorForCell, lightnessForCell };

// ---------------------------------------------------------------------------
// Sticky-left offset table
//
// Each frozen column maps to a width in rem so the cumulative offset for the
// next sticky column can be computed exactly without relying on hard-coded
// Tailwind classes (`left-44` etc.) that desync when an earlier column is
// hidden — most notably the optional compare-checkbox column.
// ---------------------------------------------------------------------------

const STICKY_COL_REM = {
  checkbox: 3, // w-12
  platform: 11, // w-44
  primary: 8, // w-32
  geomean: 8, // w-32
} as const;

type StickyColKey = keyof typeof STICKY_COL_REM;

export const BENCHMARK_MATRIX_DENSITY_CONTRACT = {
  maxCollapsedRowHeightPx: 72,
  frozenColumns: ["selection", "platform identity", "primary metric", "secondary geomean"] as const,
  secondaryMetadataAffordance: "Receipt and metadata",
} as const;

function cumulativeStickyLeft(
  options: { hasSelection: boolean; showGeomeanCol: boolean },
  target: StickyColKey,
): number {
  let offset = 0;
  if (target === "checkbox") return offset;
  if (options.hasSelection) offset += STICKY_COL_REM.checkbox;
  if (target === "platform") return offset;
  offset += STICKY_COL_REM.platform;
  if (target === "primary") return offset;
  offset += STICKY_COL_REM.primary;
  if (target === "geomean") return offset;
  if (options.showGeomeanCol) offset += STICKY_COL_REM.geomean;
  return offset;
}

function stickyLeftStyle(rem: number): JSX.CSSProperties {
  return { left: `${rem}rem` };
}

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

function fmtQueryMs(ms: number): string {
  return formatLatencyMs(ms, { subMillisecond: "compact" }).valueText;
}

function CompareDisabledReason({ id, copy }: { id?: string; copy: CompareExclusionReasonCopy }) {
  return (
    <div id={id} class="mt-1 text-xs text-[var(--bb-data-fg-muted)]" data-testid="query-heatmap-disabled-reason">
      <span class="font-medium text-[var(--bb-tone-warning-fg)]">Disabled reason: {copy.shortText}</span>
      <span class="block">{copy.recoveryHint}</span>
    </div>
  );
}

function formatPlatformVersion(version: string): string {
  return version.startsWith("v") || version.startsWith("V") ? version : `v${version}`;
}

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
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const pageStickyHeaderRef = useRef<HTMLDivElement>(null);

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
        .map((p) => platformTimingValue(p, qid))
        .filter((v): v is number => v !== null);
      mins[qid] = vals.length > 0 ? Math.min(...vals) : null;
    }
    return mins;
  }, [platforms, sortedQueryIds]);

  // Determine primary display metric from the artifact's ranking config.
  const primaryMetric = ranking?.primary_metric === "power_score" ? "power_score" : "display_geomean_ms";
  const higherIsBetter = ranking?.primary_order === "desc";
  const defaultPrimaryDirection: SortDirection = higherIsBetter ? "desc" : "asc";
  type MatrixSortKey = "platform" | "primary" | "geomean" | `query:${string}`;
  const [sort, setSort] = useState<SortState<MatrixSortKey> | null>(null);
  const activeSort = sort ?? { key: "primary", direction: defaultPrimaryDirection };
  // Show secondary geomean column when the artifact carries a secondary metric,
  // rather than hardcoding the power_score assumption.
  const showGeomeanCol = ranking?.secondary_metric === "display_geomean_ms";

  function getPrimaryValue(row: PlatformRow): number | null {
    return validPrimaryMetricValue(row, primaryMetric);
  }

  function fmtPrimary(val: number | null): string {
    if (val === null) return "-";
    return primaryMetric === "power_score" ? formatPowerScore(val).valueText : fmtGeomean(val);
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
      if (isRankable(a) !== isRankable(b)) {
        return isRankable(a) ? -1 : 1;
      }
      return compareNullableNumber(getPrimaryValue(a), getPrimaryValue(b), current.direction);
    }
    if (current.key === "geomean") {
      return compareNullableNumber(
        validPrimaryMetricValue(a, "display_geomean_ms"),
        validPrimaryMetricValue(b, "display_geomean_ms"),
        current.direction,
      );
    }
    if (current.key.startsWith("query:")) {
      const queryId = current.key.slice("query:".length);
      return compareNullableNumber(platformTimingValue(a, queryId), platformTimingValue(b, queryId), current.direction);
    }
    return 0;
  }

  const sorted = useMemo(
    () => [...platforms].sort((a, b) => compareMatrixRows(a, b, activeSort)),
    [activeSort, platforms],
  );

  function syncPageStickyHeaderScroll() {
    if (!scrollContainerRef.current || !pageStickyHeaderRef.current) return;
    pageStickyHeaderRef.current.scrollLeft = scrollContainerRef.current.scrollLeft;
  }

  useEffect(() => {
    syncPageStickyHeaderScroll();
  }, [hasSelection, showGeomeanCol, sortedQueryIds.length]);

  /** Returns the short_id for a row if available, otherwise falls back to result_id.
   *  The short_id is used for Compare URLs so bookmarks stay compact. */
  function rowKey(row: PlatformRow): string {
    return row.short_id || row.result_id;
  }

  function toggleRow(row: PlatformRow) {
    if (!onSelectionChange || !selectedIds) return;
    if (!isComparable(row)) return;
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
      <div class="rounded-lg border border-dashed border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] p-10 text-center text-[var(--bb-data-fg-subtle)]">
        No results available for this configuration.
      </div>
    );
  }

  // Single-platform: suppress heat coloring (no relative comparison to show).
  const suppressHeat = sorted.length < 2;

  const primaryLabel = primaryMetric === "power_score" ? "Power score" : "Geomean latency";
  const primaryDirectionLabel = primaryMetric === "power_score" ? "higher is better" : "lower is better";
  // The legend heading describes what the *cells* show, not the cohort's
  // primary score metric. Heatmap cells are always per-query latency values,
  // regardless of whether the primary score column is power_score or
  // display_geomean_ms. Earlier copy ("Power Score:
  // higher is better") contradicted the rendered data on tpch-style
  // cohorts. The primary score column keeps its own column header
  // explanation (`primaryLabel`/`primaryDirectionLabel`) below.
  const heatmapMeaning = suppressHeat
    ? "Heat color is suppressed because this ranking has fewer than two comparable platforms."
    : "Heat color compares each query column with the fastest published timing; darker cells are slower.";

  function renderHeaderSortControl(
    label: string,
    key: MatrixSortKey,
    options: {
      className?: string;
      initialDirection?: SortDirection;
      pageSticky?: boolean;
      queryLabel?: string;
    } = {},
  ) {
    const className =
      options.className ?? "table-th block w-full cursor-pointer select-none border-0 bg-transparent text-left";
    const content = (
      <>
        {label}{sortArrow(key)}
        {options.pageSticky ? null : sortAnnouncement(key)}
      </>
    );

    if (options.pageSticky) return <span class={className}>{content}</span>;

    return (
      <button
        type="button"
        class={className}
        data-query-label={options.queryLabel}
        onClick={() => toggleSort(key, options.initialDirection)}
      >
        {content}
      </button>
    );
  }

  function renderHeaderRow(pageSticky = false) {
    return (
      <tr role="row" class="bg-[var(--bb-surface-data-muted)]">
        {hasSelection && (
          <th
            role="columnheader"
            scope="col"
            aria-label="Select for comparison"
            class="table-th sticky z-30 w-12 min-w-12 bg-[var(--bb-surface-data-muted)] px-2"
            style={stickyLeftStyle(cumulativeStickyLeft({ hasSelection, showGeomeanCol }, "checkbox"))}
          />
        )}
        <th
          role="columnheader"
          scope="col"
          class="sticky z-30 w-44 min-w-44 bg-[var(--bb-surface-data-muted)] p-0"
          style={stickyLeftStyle(cumulativeStickyLeft({ hasSelection, showGeomeanCol }, "platform"))}
          aria-sort={ariaSort("platform")}
        >
          {renderHeaderSortControl("Platform", "platform", { pageSticky })}
        </th>
        <th
          role="columnheader"
          scope="col"
          aria-sort={ariaSort("primary")}
          class="sticky z-30 w-32 min-w-32 whitespace-nowrap bg-[var(--bb-surface-data-muted)] p-0"
          style={stickyLeftStyle(cumulativeStickyLeft({ hasSelection, showGeomeanCol }, "primary"))}
          title={primaryLabel}
        >
          {renderHeaderSortControl(primaryLabel, "primary", {
            initialDirection: defaultPrimaryDirection,
            pageSticky,
          })}
        </th>
        {showGeomeanCol && (
          <th
            role="columnheader"
            scope="col"
            class="sticky z-30 w-32 min-w-32 whitespace-nowrap bg-[var(--bb-surface-data-muted)] p-0"
            style={stickyLeftStyle(cumulativeStickyLeft({ hasSelection, showGeomeanCol }, "geomean"))}
            aria-sort={ariaSort("geomean")}
            title="Geometric mean of per-query display times"
          >
            {renderHeaderSortControl("Geomean latency", "geomean", {
              className:
                "table-th block w-full cursor-pointer select-none border-0 bg-transparent text-left text-[var(--bb-data-fg-subtle)]",
              pageSticky,
            })}
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
            {renderHeaderSortControl(queryDisplayLabel(qid), `query:${qid}`, {
              className:
                "table-th block w-full cursor-pointer select-none border-0 bg-transparent text-left font-mono",
              pageSticky,
              queryLabel: pageSticky ? undefined : qid,
            })}
          </th>
        ))}
      </tr>
    );
  }

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
        class="mb-3 rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-3 py-2 text-xs text-[var(--bb-data-fg-muted)]"
        data-testid="query-heatmap-legend"
      >
        <div class="font-semibold text-[var(--bb-data-fg-primary)]">
          Per-query latency: lower is better
        </div>
        <div class="mt-1">
          {heatmapMeaning} <strong>&lt;1 ms</strong> means a positive sub-millisecond timing; exact zero timings are{" "}
          excluded from heat, ranks, and comparisons. <strong>No run</strong> means missing data. The primary score column (
          {primaryLabel}) on the left of each row uses its own metric and direction ({primaryDirectionLabel}).
        </div>
      </div>

      <div
        class="space-y-3 md:hidden"
        data-testid="query-heatmap-mobile-cards"
        role="list"
        aria-label={`${summary.benchmark} compact query result cards`}
      >
        {sorted.map((row) => {
          const isSelected = selectedIds?.has(rowKey(row)) ?? false;
          const comparable = isComparable(row);
          const comparisonExclusion = comparable ? null : formatTimingExclusion(row.comparison_exclusion_reason);
          const comparisonCopy = describeCompareExclusionReason(row.comparison_exclusion_reason);
          const comparisonReasonId = comparisonCopy ? `query-heatmap-mobile-compare-reason-${row.result_id}` : undefined;
          const rankingExclusion = isRankable(row) ? null : formatTimingExclusion(row.ranking_exclusion_reason);
          const outliers = queryOutliers(row, sortedQueryIds, colMins);
          return (
            <article
              key={row.result_id}
              data-testid={`query-heatmap-mobile-card-${row.result_id}`}
              role="listitem"
              class={`rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] p-3 shadow-sm ${
                isSelected ? "border-[var(--bb-accent-hover)] bg-[var(--bb-tone-info-bg)]" : ""
              }`}
            >
              <div class="flex items-start gap-3">
                {hasSelection && (
                  <input
                    type="checkbox"
                    checked={isSelected}
                    disabled={!comparable}
                    onChange={() => toggleRow(row)}
                    aria-label={compareSelectionLabel({
                      platform: row.platform,
                      benchmark: summary.benchmark,
                      scaleFactor: summary.scale_factor,
                      phase: summary.phase,
                      runDate: row.run_date,
                      resultId: row.result_id,
                    })}
                    aria-describedby={comparisonReasonId}
                    title={comparisonExclusion ?? undefined}
                    class="mt-1 h-4 w-4 shrink-0 rounded border-[var(--bb-data-border-strong)]"
                  />
                )}
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-1">
                    <h2 class="text-sm font-semibold text-[var(--bb-data-fg-primary)]">{row.platform}</h2>
                    {rankingExclusion && (
                      <span
                        role="img"
                        class="text-xs text-[var(--bb-data-fg-subtle)] cursor-help"
                        title={rankingExclusion}
                        aria-label={rankingExclusion}
                        data-testid={`heatmap-mobile-compliance-marker-${row.result_id}`}
                      >
                        *
                      </span>
                    )}
                  </div>
                  {row.platform_version && (
                    <div class="mt-0.5 text-xs text-[var(--bb-data-fg-subtle)]">{row.platform_version}</div>
                  )}
                  {hasSelection && comparisonCopy && (
                    <CompareDisabledReason id={comparisonReasonId} copy={comparisonCopy} />
                  )}
                  <a
                    href={`/results/r/${row.result_id}#run-receipt`}
                    class="mt-1 inline-block text-xs font-medium no-underline"
                  >
                    Receipt →
                  </a>
                </div>
                <dl class="shrink-0 text-right">
                  <dt class="text-[0.65rem] font-semibold uppercase text-[var(--bb-data-fg-subtle)]">{primaryLabel}</dt>
                  <dd class="font-mono text-sm font-semibold text-[var(--bb-data-fg-primary)]">
                    {fmtPrimary(getPrimaryValue(row))}
                  </dd>
                </dl>
              </div>

              <div class="mt-3 flex flex-wrap gap-1.5">
                <TrustBadge trustLabel={row.trust_label} compact />
                <ValidationBadge validationStatus={row.validation_status} showMissing />
                {showGeomeanCol && (
                  <span class="rounded-full bg-[var(--bb-surface-app)] px-2 py-0.5 font-mono text-xs text-[var(--bb-data-fg-muted)]">
                    Geomean latency {fmtGeomean(validPrimaryMetricValue(row, "display_geomean_ms"))}
                  </span>
                )}
              </div>

              <div class="mt-3 border-t border-[var(--bb-data-border)] pt-3">
                <div class="text-[0.65rem] font-semibold uppercase text-[var(--bb-data-fg-subtle)]">Query outliers</div>
                {outliers.length > 0 ? (
                  <div class="mt-2 grid gap-2" role="list" aria-label={`${row.platform} query outliers`}>
                    {outliers.map((outlier) => (
                      <div
                        key={outlier.queryId}
                        role="listitem"
                        class="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-md bg-[var(--bb-surface-data-muted)] px-2 py-1.5"
                      >
                        <div class="min-w-0">
                          <div class="truncate font-mono text-xs font-semibold text-[var(--bb-data-fg-primary)]">
                            {queryDisplayLabel(outlier.queryId)}
                          </div>
                          <div class="text-xs text-[var(--bb-data-fg-muted)]">{outlier.ratioLabel}</div>
                        </div>
                        <div class="font-mono text-xs font-semibold text-[var(--bb-data-fg-primary)]">
                          {fmtQueryMs(outlier.ms)}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p class="mt-2 rounded-md bg-[var(--bb-surface-data-muted)] px-2 py-1.5 text-xs text-[var(--bb-data-fg-muted)]">
                    No query timings published.
                  </p>
                )}
              </div>
            </article>
          );
        })}
      </div>

      <div class="hidden md:block">
        <div class="mb-2 flex items-center justify-between gap-3 text-xs text-[var(--bb-data-fg-muted)]">
          <span
            data-testid="query-heatmap-scroll-hint"
            class="inline-flex items-center rounded-full border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-2.5 py-1 font-medium shadow-sm"
          >
            Query columns →
          </span>
          <span>{sortedQueryIds.length.toLocaleString()} queries</span>
        </div>
        <div
          aria-hidden="true"
          class="pointer-events-none sticky top-0 z-40 h-0 overflow-visible"
          data-testid="query-heatmap-page-sticky-header-shell"
        >
          <div
            ref={pageStickyHeaderRef}
            class="overflow-x-hidden rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] shadow-sm"
            data-testid="query-heatmap-page-sticky-header"
          >
            <table role="presentation" class="min-w-max text-sm">
              <thead class="bg-[var(--bb-surface-data-muted)]">{renderHeaderRow(true)}</thead>
            </table>
          </div>
        </div>
        <div
          ref={scrollContainerRef}
          class="overflow-x-auto rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] shadow-sm"
          data-testid="query-heatmap-scroll-container"
          onScroll={syncPageStickyHeaderScroll}
        >
          <table
            ref={gridRef}
            role="grid"
            aria-label={`${summary.benchmark} SF${summary.scale_factor} ${summary.phase} results`}
            class="min-w-max text-sm"
          >
            <thead class="bg-[var(--bb-surface-data-muted)]">{renderHeaderRow()}</thead>
            <tbody class="divide-y divide-[var(--bb-data-border)]">
              {sorted.map((row, rowIdx) => {
                const isSelected = selectedIds?.has(rowKey(row)) ?? false;
                const comparable = isComparable(row);
                const comparisonExclusion = comparable ? null : formatTimingExclusion(row.comparison_exclusion_reason);
                const comparisonCopy = describeCompareExclusionReason(row.comparison_exclusion_reason);
                const comparisonReasonId = comparisonCopy ? `query-heatmap-compare-reason-${row.result_id}` : undefined;
                const rankingExclusion = isRankable(row) ? null : formatTimingExclusion(row.ranking_exclusion_reason);
                return (
                  <tr
                    key={row.result_id}
                    role="row"
                    data-testid={row.result_id}
                    data-density-contract="benchmark-matrix-row"
                    class={`hover:bg-[var(--bb-surface-data-muted)] ${isSelected ? "bg-[var(--bb-tone-info-bg)]" : ""}`}
                  >
                  {hasSelection && (
                    <td
                      role="gridcell"
                      class={`table-td sticky z-10 w-12 min-w-12 px-2 ${
                        isSelected ? "bg-[var(--bb-tone-info-bg)]" : "bg-[var(--bb-surface-data)]"
                      }`}
                      style={stickyLeftStyle(cumulativeStickyLeft({ hasSelection, showGeomeanCol }, "checkbox"))}
                    >
                      <input
                        type="checkbox"
                        checked={isSelected}
                        disabled={!comparable}
                        onChange={() => toggleRow(row)}
                        aria-label={compareSelectionLabel({
                          platform: row.platform,
                          benchmark: summary.benchmark,
                          scaleFactor: summary.scale_factor,
                          phase: summary.phase,
                          runDate: row.run_date,
                          resultId: row.result_id,
                        })}
                        aria-describedby={comparisonReasonId}
                        title={comparisonExclusion ?? undefined}
                        class="h-4 w-4 rounded border-[var(--bb-data-border-strong)]"
                      />
                    </td>
                  )}
                  <td
                    role="gridcell"
                    class={`table-td sticky z-10 w-44 min-w-44 ${
                      isSelected ? "bg-[var(--bb-tone-info-bg)]" : "bg-[var(--bb-surface-data)]"
                    }`}
                    style={stickyLeftStyle(cumulativeStickyLeft({ hasSelection, showGeomeanCol }, "platform"))}
                  >
                    <div class="flex items-center gap-1">
                      <span class="font-medium text-[var(--bb-data-fg-primary)]">{row.platform}</span>
                      {row.platform_version && (
                        <span class="text-xs text-[var(--bb-data-fg-subtle)]">
                          {formatPlatformVersion(row.platform_version)}
                        </span>
                      )}
                      {rankingExclusion && (
                        <span
                          role="img"
                          class="text-xs text-[var(--bb-data-fg-subtle)] cursor-help"
                          title={rankingExclusion}
                          aria-label={rankingExclusion}
                          data-testid={`heatmap-compliance-marker-${row.result_id}`}
                        >
                          *
                        </span>
                      )}
                    </div>
                    <details class="mt-1 text-xs text-[var(--bb-data-fg-muted)]">
                      <summary class="cursor-pointer font-medium text-[var(--bb-accent-hover)]">
                        {BENCHMARK_MATRIX_DENSITY_CONTRACT.secondaryMetadataAffordance}
                      </summary>
                      <div class="mt-1 flex flex-wrap items-center gap-1">
                        <TrustBadge trustLabel={row.trust_label} compact />
                        <ValidationBadge validationStatus={row.validation_status} showMissing />
                        <a
                          href={`/results/r/${row.result_id}#run-receipt`}
                          class="font-medium no-underline"
                        >
                          Receipt →
                        </a>
                      </div>
                    </details>
                    {hasSelection && comparisonCopy && (
                      <CompareDisabledReason id={comparisonReasonId} copy={comparisonCopy} />
                    )}
                  </td>
                  <td
                    role="gridcell"
                    class={`table-td sticky z-10 w-32 min-w-32 whitespace-nowrap font-mono ${
                      isSelected ? "bg-[var(--bb-tone-info-bg)]" : "bg-[var(--bb-surface-data)]"
                    }`}
                    style={stickyLeftStyle(cumulativeStickyLeft({ hasSelection, showGeomeanCol }, "primary"))}
                  >
                    {fmtPrimary(getPrimaryValue(row))}
                  </td>
                  {showGeomeanCol && (
                    <td
                      role="gridcell"
                      class={`table-td sticky z-10 w-32 min-w-32 whitespace-nowrap font-mono text-[var(--bb-data-fg-muted)] ${
                        isSelected ? "bg-[var(--bb-tone-info-bg)]" : "bg-[var(--bb-surface-data)]"
                      }`}
                      style={stickyLeftStyle(cumulativeStickyLeft({ hasSelection, showGeomeanCol }, "geomean"))}
                    >
                      {fmtGeomean(validPrimaryMetricValue(row, "display_geomean_ms"))}
                    </td>
                  )}
                  {sortedQueryIds.map((qid, colIdx) => {
                    const rawMs = row.timings[qid] ?? null;
                    const timingExclusionReason = row.timing_eligibility[qid]?.timing_exclusion_reason ?? null;
                    const ms = platformTimingValue(row, qid);
                    const minInCol = colMins[qid] ?? null;
                    const hue = suppressHeat ? null : colorForCell(ms, minInCol);
                    const lightness = suppressHeat ? null : lightnessForCell(ms, minInCol);
                    const ratio =
                      ms !== null && minInCol !== null && minInCol > 0 ? ms / minInCol : null;
                    const isExcludedTiming = rawMs !== null && ms === null;
                    const excludedReason =
                      timingExclusionReason !== null
                        ? formatTimingExclusion(timingExclusionReason)
                        : rawMs === 0
                          ? formatTimingExclusion("zero_timing")
                          : "Timing is excluded from display evidence.";
                    const ariaLabel =
                      ms !== null
                        ? ratio !== null
                          ? ratio <= 1.005
                            ? `${fmtQueryMs(ms)}, fastest in column`
                            : `${fmtQueryMs(ms)}, ${formatSpeedup(ratio, { unit: "×" }).valueText} fastest in column`
                          : fmtQueryMs(ms)
                        : isExcludedTiming
                          ? `${formatDurationMs(rawMs)}, excluded: ${excludedReason}`
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
                        class={`table-td min-w-[7rem] whitespace-nowrap text-right font-mono ${
                          hue !== null ? "heatmap-cell" : ms === null ? "bg-[var(--bb-surface-data-muted)] text-[var(--bb-data-fg-subtle)]" : ""
                        }`}
                        style={cellStyle}
                        aria-label={ariaLabel}
                        title={
                          isExcludedTiming
                            ? excludedReason
                            : ms === null
                              ? "No published run for this query/platform cell."
                              : undefined
                        }
                        onKeyDown={(e) => handleCellKey(e as KeyboardEvent, rowIdx, colIdx)}
                        onFocus={() => setAnnouncement(`${queryDisplayLabel(qid)}: ${ariaLabel}`)}
                      >
                        {ms !== null ? fmtQueryMs(ms) : isExcludedTiming ? "Excluded" : "No run"}
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
      const ms = platformTimingValue(row, queryId);
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
  if (ratio === null) return "No ranking baseline";
  if (ratio <= 1.005) return "Fastest in ranking";
  return `${formatSpeedup(ratio, { unit: "×" }).valueText} fastest`;
}
