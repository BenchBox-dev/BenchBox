// ---------------------------------------------------------------------------
// TimeSeries - line chart of performance metric over time
//
// Shows geomean_ms or power_score (depending on benchmark) over run_date.
// One line per platform_id group.  Requires ≥2 data points per series.
//
// Input: ChartHistoricalEntry[] (all entries for one or more platforms,
//        sorted by platform_id + run_date internally). Both ChartHistoricalEntry
//        and DuckDB row shapes satisfy the narrow interface.
//
// Python reference: textcharts.line_chart.LineChart
// ---------------------------------------------------------------------------

import type { ChartHistoricalEntry } from "@/lib/chartRegistry";
import { useElementSize } from "@/lib/useElementSize";
import { timeSeriesColor } from "@/lib/chartTheme";
import { formatLatencyMs, formatPowerScore } from "@/lib/metricFormatters";
import {
  resultDetailHref,
  resultIdentityAriaLabel,
  resultReceiptHref,
  visibleResultIdForRow,
} from "@/lib/resultLinks";
import { formatRunIdentityLabelsForCohort, type RunIdentitySource } from "@/lib/runIdentity";

const LABEL_W = 58;
const AXIS_H = 32;
const PADDING_TOP = 16;
const PADDING_RIGHT = 12;
const CHART_H = 160;

interface Props {
  entries: ChartHistoricalEntry[];
  /**
   * Primary metric to chart - `"power_score"` (higher-is-better) or
   * `"display_geomean_ms"` (lower-is-better). The caller resolves this from
   * the canonical `benchmark_rankings.primary_metric` column; omitted means
   * geomean.
   */
  primaryMetric?: "power_score" | "display_geomean_ms";
}

interface SeriesPoint {
  /** Stable per-run identifier; used as the React key so two runs on the
   *  same `date` (common for batch runs) don't collide on `key={date}`. */
  resultId: string;
  date: string;
  value: number;
  title: string;
  ariaLabel: string;
}

interface Series {
  platformId: string;
  label: string;
  fullLabel: string;
  color: string;
  points: SeriesPoint[];
}

export function TimeSeries({ entries, primaryMetric }: Props) {
  const [containerRef, { width: containerWidth }] = useElementSize(320);
  const w = Math.max(containerWidth, 320);

  const metric = primaryMetric ?? "display_geomean_ms";
  const higherIsBetter = metric === "power_score";

  // Defensive dedup on result_id: TimeSeries trusts the caller, but if any
  // upstream JOIN regression ever produces duplicate entries the chart
  // would silently render stacked points. Drop the second copy.
  const seenIds = new Set<string>();
  const dedupedEntries: ChartHistoricalEntry[] = [];
  for (const e of entries) {
    if (seenIds.has(e.result_id)) continue;
    seenIds.add(e.result_id);
    dedupedEntries.push(e);
  }

  const duplicateDayGroups = duplicateSameDayGroups(dedupedEntries, metric);
  const duplicateDayPlatformIds = new Set(
    duplicateDayGroups.flatMap((group) => group.runs.map(({ entry }) => entry.platform_id)),
  );

  // Group by platform_id, sort by run_date within each group
  const byPlatform = new Map<string, ChartHistoricalEntry[]>();
  for (const e of dedupedEntries) {
    const arr = byPlatform.get(e.platform_id) ?? [];
    arr.push(e);
    byPlatform.set(e.platform_id, arr);
  }

  // Build the per-platform series first, then disambiguate series labels
  // when two platform_ids share a display name (e.g. two DataFusion
  // tracks differing only by platform_id). RunIdentity natural qualifiers
  // (driver_version, deployment, etc.) aren't carried on
  // ChartHistoricalEntry, so the cohort-aware formatter falls through to
  // its short result_id tiebreaker — better than two indistinguishable
  // "DataFusion" entries in the legend.
  let colorIdx = 0;
  const seriesDescriptors: { pid: string; firstEntry: ChartHistoricalEntry; points: SeriesPoint[] }[] = [];
  for (const [pid, platformEntries] of byPlatform) {
    if (duplicateDayPlatformIds.has(pid)) continue;
    const sorted = [...platformEntries].sort((a, b) => a.run_date.localeCompare(b.run_date));
    const trendable = sorted
      .map((entry) => {
        const value = trendValue(entry, metric);
        return value !== null ? { entry, value } : null;
      })
      .filter((point): point is { entry: ChartHistoricalEntry; value: number } => point !== null);
    const pointLabels = formatRunIdentityLabelsForCohort(
      trendable.map((point) => runIdentitySourceForEntry(point.entry)),
    );
    const points: SeriesPoint[] = trendable.map((point, index) => {
      const identity = pointLabels[index]?.full ?? point.entry.platform;
      const metricValue = formatMetricValue(point.value, metric);
      const title = `${identity}: ${point.entry.run_date} = ${metricValue}`;
      return {
        resultId: point.entry.result_id,
        date: point.entry.run_date,
        value: point.value,
        title,
        ariaLabel: title,
      };
    });
    if (points.length >= 2 && sorted[0]) {
      seriesDescriptors.push({ pid, firstEntry: sorted[0], points });
    }
  }
  const cohortLabels = formatRunIdentityLabelsForCohort(
    seriesDescriptors.map((descriptor): RunIdentitySource => ({
      result_id: descriptor.firstEntry.result_id,
      platform: descriptor.firstEntry.platform,
      run_date: descriptor.firstEntry.run_date,
      scale_factor: descriptor.firstEntry.scale_factor,
    })),
  );
  const allSeries: Series[] = seriesDescriptors.map((descriptor, idx) => ({
    platformId: descriptor.pid,
    label: cohortLabels[idx]?.disambiguated ?? descriptor.firstEntry.platform,
    fullLabel: cohortLabels[idx]?.full ?? descriptor.firstEntry.platform,
    color: timeSeriesColor(colorIdx++),
    points: descriptor.points,
  }));

  if (allSeries.length === 0) {
    if (duplicateDayGroups.length > 0) {
      return (
        <DuplicateDayTrendState
          groups={duplicateDayGroups}
          metric={metric}
          observationCount={countTrendableEntries(dedupedEntries, metric)}
        />
      );
    }
    return (
      <p class="text-sm text-[var(--bb-data-fg-subtle)] italic">
        Not enough historical data for a trend chart (need ≥2 runs per platform).
      </p>
    );
  }

  const allDates = [...new Set(allSeries.flatMap((s) => s.points.map((p) => p.date)))].sort();
  const dateIndex = new Map<string, number>(allDates.map((d, i) => [d, i]));
  const allValues = allSeries.flatMap((s) => s.points.map((p) => p.value));
  const minVal = Math.min(...allValues);
  const maxVal = Math.max(...allValues);
  const valPad = (maxVal - minVal) * 0.08 || maxVal * 0.08 || 1;
  const yMin = Math.max(0, minVal - valPad);
  const yMax = maxVal + valPad;
  const yRange = yMax - yMin || 1;

  const plotW = w - LABEL_W - PADDING_RIGHT;
  const totalH = PADDING_TOP + CHART_H + AXIS_H;

  function xFor(date: string): number {
    const idx = dateIndex.get(date) ?? 0;
    return LABEL_W + (idx / Math.max(1, allDates.length - 1)) * plotW;
  }

  function yFor(val: number): number {
    const normalized = (val - yMin) / yRange;
    // Higher value → top of chart for power_score; bottom for latency
    const pos = higherIsBetter ? normalized : 1 - normalized;
    return PADDING_TOP + CHART_H * (1 - pos);
  }

  const metricLabel = metric === "power_score" ? "Power score" : "Geomean latency";
  const yTicks = [yMin, (yMin + yMax) / 2, yMax];
  const duplicateDayState =
    duplicateDayGroups.length > 0 ? (
      <DuplicateDayTrendState
        groups={duplicateDayGroups}
        metric={metric}
        observationCount={countTrendableEntries(dedupedEntries, metric)}
      />
    ) : null;

  // Show at most 7 x-axis labels when there are many dates
  const step = Math.ceil(allDates.length / 7);
  const shownDates = allDates.filter((_, i) => i % step === 0 || i === allDates.length - 1);

  return (
    <div class={duplicateDayState ? "space-y-3" : undefined}>
      {duplicateDayState}
      <div ref={containerRef} class="w-full overflow-x-auto">
        <svg
          class="bb-chart-svg"
          width={w}
          height={totalH}
          role="img"
          aria-label={`${metricLabel} trend over time`}
        >
          {/* Y-axis grid + labels */}
          {yTicks.map((val) => {
            const y = yFor(val);
            const label =
              metric === "power_score"
                ? formatPowerScore(val).valueText
                : formatLatencyMs(val, { subMillisecond: "compact" }).valueText;
            return (
              <g key={val}>
                <line
                  x1={LABEL_W}
                  y1={y}
                  x2={w - PADDING_RIGHT}
                  y2={y}
                  stroke="var(--bb-chart-grid)"
                  strokeWidth={1}
                />
                <text
                  x={LABEL_W - 4}
                  y={y + 4}
                  textAnchor="end"
                  style={{ fontSize: "9px", fill: "var(--bb-chart-label-muted)" }}
                >
                  {label}
                </text>
              </g>
            );
          })}

        {/* Series lines + dots */}
        {allSeries.map((s) => {
          const d = s.points
            .map(
              (p, i) =>
                `${i === 0 ? "M" : "L"}${xFor(p.date).toFixed(1)},${yFor(p.value).toFixed(1)}`,
            )
            .join(" ");
          return (
            <g key={s.platformId}>
              <path d={d} stroke={s.color} strokeWidth={2} fill="none" strokeLinejoin="round" />
              {s.points.map((p) => (
                <circle
                  key={p.resultId}
                  data-result-id={p.resultId}
                  aria-label={p.ariaLabel}
                  tabIndex={0}
                  cx={xFor(p.date)}
                  cy={yFor(p.value)}
                  r={3}
                  fill={s.color}
                >
                  <title>{p.title}</title>
                </circle>
              ))}
            </g>
          );
        })}

        {/* X-axis */}
        <g transform={`translate(0, ${PADDING_TOP + CHART_H})`}>
          <line x1={LABEL_W} y1={0} x2={w - PADDING_RIGHT} y2={0} stroke="var(--bb-chart-grid)" strokeWidth={1} />
          {shownDates.map((date) => {
            const x = xFor(date);
            return (
              <g key={date}>
                <line x1={x} y1={0} x2={x} y2={4} stroke="var(--bb-chart-label-muted)" strokeWidth={1} />
                <text
                  x={x}
                  y={20}
                  textAnchor="middle"
                  style={{ fontSize: "9px", fill: "var(--bb-chart-axis)" }}
                >
                  {date.slice(5)}
                </text>
              </g>
            );
          })}
        </g>
        </svg>

        {/* Legend */}
        {allSeries.length > 1 && (
          <div class="flex flex-wrap gap-4 text-xs text-[var(--bb-data-fg-muted)] mt-1">
            {allSeries.map((s) => (
              <span key={s.platformId} class="flex items-center gap-1.5">
                <span class="inline-block w-5 border-t-2" style={{ borderColor: s.color }} />
                <span title={s.fullLabel}>
                  {s.label}
                </span>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

interface DuplicateDayGroup {
  platform: string;
  date: string;
  runs: { entry: ChartHistoricalEntry; value: number; title: string }[];
}

function runIdentitySourceForEntry(entry: ChartHistoricalEntry): RunIdentitySource {
  return {
    result_id: entry.result_id,
    platform: entry.platform,
    run_date: entry.run_date,
    scale_factor: entry.scale_factor,
  };
}

function trendValue(entry: ChartHistoricalEntry, metric: Props["primaryMetric"]): number | null {
  return metric === "power_score" ? entry.power_score : entry.display_geomean_ms;
}

function formatMetricValue(value: number, metric: Props["primaryMetric"]): string {
  return metric === "power_score" ? formatPowerScore(value).valueText : formatLatencyMs(value).valueText;
}

function countTrendableEntries(entries: ChartHistoricalEntry[], metric: Props["primaryMetric"]): number {
  return entries.filter((entry) => trendValue(entry, metric) !== null).length;
}

function duplicateSameDayGroups(entries: ChartHistoricalEntry[], metric: Props["primaryMetric"]): DuplicateDayGroup[] {
  const byPlatformDate = new Map<string, ChartHistoricalEntry[]>();
  for (const entry of entries) {
    if (trendValue(entry, metric) === null) continue;
    const key = `${entry.platform_id}\u0000${entry.run_date}`;
    const group = byPlatformDate.get(key) ?? [];
    group.push(entry);
    byPlatformDate.set(key, group);
  }

  return [...byPlatformDate.values()]
    .filter((group) => group.length > 1)
    .map((group) => {
      const entriesForDay = [...group].sort((a, b) => a.result_id.localeCompare(b.result_id));
      const labels = formatRunIdentityLabelsForCohort(entriesForDay.map(runIdentitySourceForEntry));
      return {
        platform: entriesForDay[0]!.platform,
        date: entriesForDay[0]!.run_date,
        runs: entriesForDay.map((entry, index) => {
          const value = trendValue(entry, metric)!;
          return {
            entry,
            value,
            title: `${labels[index]?.full ?? entry.platform}: ${entry.run_date} = ${formatMetricValue(value, metric)}`,
          };
        }),
      };
    })
    .sort((a, b) => a.date.localeCompare(b.date) || a.platform.localeCompare(b.platform));
}

function DuplicateDayTrendState({
  groups,
  metric,
  observationCount,
}: {
  groups: DuplicateDayGroup[];
  metric: Props["primaryMetric"];
  observationCount: number;
}) {
  const duplicateRunCount = groups.reduce((count, group) => count + group.runs.length, 0);
  const duplicateRunLabel = duplicateRunCount === 1 ? "same-day run" : "same-day runs";
  const observationLabel = observationCount === 1 ? "observation remains" : "observations remain";
  const message =
    `Trend line hidden: ${duplicateRunCount} ${duplicateRunLabel} in this ranking do not carry time-of-day ordering. ` +
    `${observationCount} ${observationLabel} in the ranking; duplicate same-day runs are listed below.`;
  return (
    <div
      data-testid="time-series-duplicate-day"
      class="rounded-lg border border-dashed border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-3 py-3"
    >
      <p class="text-sm text-[var(--bb-data-fg-muted)]">
        {message}
      </p>
      <div class="mt-3 overflow-x-auto">
        <table class="min-w-max text-left text-xs">
          <thead class="text-[var(--bb-data-fg-muted)]">
            <tr>
              <th class="pr-4 pb-1 font-medium">Date</th>
              <th class="pr-4 pb-1 font-medium">Platform</th>
              <th class="pr-4 pb-1 font-medium">Public ID</th>
              <th class="pr-4 pb-1 font-medium">{metric === "power_score" ? "Power score" : "Geomean latency"}</th>
              <th class="pr-4 pb-1 font-medium">Details</th>
              <th class="pb-1 font-medium">Receipt</th>
            </tr>
          </thead>
          <tbody class="text-[var(--bb-data-fg-primary)]">
            {groups.flatMap((group) =>
              group.runs.map(({ entry, value, title }) => (
                <tr key={entry.result_id} data-result-id={entry.result_id} title={title}>
                  <td class="pr-4 py-1 font-mono text-[var(--bb-data-fg-muted)]">{group.date}</td>
                  <td class="pr-4 py-1">{group.platform}</td>
                  <td class="pr-4 py-1 font-mono">Public ID {visibleResultIdForRow(entry)}</td>
                  <td class="pr-4 py-1 font-mono">{formatMetricValue(value, metric)}</td>
                  <td class="pr-4 py-1">
                    <a href={resultDetailHref(entry)} aria-label={resultIdentityAriaLabel(entry, "details")}>
                      Details
                    </a>
                  </td>
                  <td class="py-1">
                    <a href={resultReceiptHref(entry)} aria-label={resultIdentityAriaLabel(entry, "receipt")}>
                      Receipt
                    </a>
                  </td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
