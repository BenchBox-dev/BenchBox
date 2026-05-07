// ---------------------------------------------------------------------------
// DivergingBarChart - per-query improvement/regression vs baseline
//
// delta_pct = (this_ms - baseline_ms) / baseline_ms * 100
//   negative (green): faster than baseline
//   positive (red): slower than baseline
//
// Sorted by abs(delta_pct) descending so biggest changes appear first.
// ---------------------------------------------------------------------------

import { deltaPct, sortByMagnitudeDesc } from "@/lib/chartMath";
import { DIVERGING_MAX_PCT, FASTER_FILL, SLOWER_FILL, paletteColor } from "@/lib/chartTheme";
import { useElementSize } from "@/lib/useElementSize";

interface DivergingEntry {
  queryId: string;
  platform: string;
  deltaPct: number;
  color: string;
}

interface Props {
  queries: { queryId: string; timings: ({ ms: number; status: string } | null)[] }[];
  results: { platform: string }[];
  baselineIdx: number;
}

export function DivergingBarChart({ queries, results, baselineIdx }: Props) {
  const [containerRef, { width: containerWidth }] = useElementSize();
  const drawWidth = Math.max(containerWidth, 300);

  if (queries.length === 0 || results.length < 2) return null;

  const BAR_H = 16;
  const BAR_GAP = 3;
  const LABEL_W = 72;
  const AXIS_H = 20;
  const PADDING = 8;

  // Build flat sorted entries (one bar per query per non-baseline result)
  const rawEntries: DivergingEntry[] = [];
  for (const { queryId, timings } of queries) {
    const baselineT = timings[baselineIdx];
    const baselineMs = baselineT && baselineT.ms > 0 ? baselineT.ms : null;
    if (!baselineMs) continue;
    timings.forEach((t, i) => {
      if (i === baselineIdx || !t || t.ms <= 0) return;
      const colorIdx = i < baselineIdx ? i : i + 1;
      const color = paletteColor(colorIdx);
      const dp = deltaPct(t.ms, baselineMs);
      if (dp === null) return;
      rawEntries.push({
        queryId,
        platform: results[i]?.platform ?? "",
        deltaPct: dp,
        color,
      });
    });
  }

  // Group by queryId, sort by max abs delta descending
  const grouped = new Map<string, DivergingEntry[]>();
  for (const e of rawEntries) {
    const g = grouped.get(e.queryId) ?? [];
    g.push(e);
    grouped.set(e.queryId, g);
  }

  const sortedGroups = sortByMagnitudeDesc([...grouped.entries()]);

  const nonBaselineCount = results.length - 1;
  const rowHeight = BAR_H * nonBaselineCount + BAR_GAP * (nonBaselineCount + 1);
  const totalHeight = AXIS_H + sortedGroups.length * rowHeight + PADDING;

  // Summary
  const faster = rawEntries.filter((e) => e.deltaPct < 0).length;
  const slower = rawEntries.filter((e) => e.deltaPct > 0).length;
  const sorted = [...rawEntries].sort((a, b) => a.deltaPct - b.deltaPct);
  const medianDelta = sorted.length > 0
    ? sorted[Math.floor(sorted.length / 2)]?.deltaPct ?? 0
    : 0;

  return (
    <div ref={containerRef} class="w-full overflow-x-auto">
      <p class="mb-2 text-xs text-[var(--bb-data-fg-muted)]">
        {faster} quer{faster === 1 ? "y" : "ies"} faster, {slower} quer{slower === 1 ? "y" : "ies"} slower
        {rawEntries.length > 0 && ` · median delta: ${medianDelta >= 0 ? "+" : ""}${medianDelta.toFixed(1)}%`}
        {" · sorted by magnitude"}
      </p>
      <svg
        class="bb-chart-svg"
        width="100%"
        height={totalHeight}
        viewBox={`0 0 ${drawWidth} ${totalHeight}`}
        aria-label="Diverging bar chart"
      >
        {/* Center axis */}
        <line
          x1={LABEL_W + (drawWidth - LABEL_W - PADDING) / 2}
          y1={0}
          x2={LABEL_W + (drawWidth - LABEL_W - PADDING) / 2}
          y2={totalHeight - AXIS_H}
          stroke="#6b7280"
          stroke-width={1}
        />
        {/* Axis label */}
        <text
          x={LABEL_W + (drawWidth - LABEL_W - PADDING) / 2}
          y={totalHeight - 4}
          text-anchor="middle"
          font-size="9"
          fill="#9ca3af"
        >
          baseline
        </text>

        {sortedGroups.map(([queryId, entries], rowIdx) => {
          const y0 = rowIdx * rowHeight;
          const barAreaW = drawWidth - LABEL_W - PADDING;
          const centerX = LABEL_W + barAreaW / 2;
          const halfW = barAreaW / 2;

          return (
            <g key={queryId} transform={`translate(0, ${y0})`}>
              <text
                x={LABEL_W - 4}
                y={rowHeight / 2 + 4}
                text-anchor="end"
                font-size="9"
                fill="#6b7280"
                font-family="monospace"
              >
                {queryId}
              </text>
              {entries.map((entry, si) => {
                const barY = BAR_GAP + si * (BAR_H + BAR_GAP);
                const clampedPct = Math.max(-DIVERGING_MAX_PCT, Math.min(entry.deltaPct, DIVERGING_MAX_PCT));
                const barW = (Math.abs(clampedPct) / DIVERGING_MAX_PCT) * halfW;
                const isRegression = entry.deltaPct > 0;
                const barX = isRegression ? centerX : centerX - barW;
                return (
                  // Composite key: a single platform name can appear twice
                  // in `entries` if the caller passes variant rows (same
                  // platform, different tuning_mode). The loop index `si`
                  // disambiguates within the queryId group; the outer <g>
                  // key={queryId} disambiguates across groups.
                  <g key={`${entry.platform}-${si}`}>
                    <rect
                      x={barX}
                      y={barY}
                      width={Math.max(barW, 1)}
                      height={BAR_H}
                      fill={isRegression ? SLOWER_FILL : FASTER_FILL}
                      opacity={0.75}
                    />
                    <text
                      x={isRegression ? barX + barW + 2 : barX - 2}
                      y={barY + BAR_H / 2 + 3}
                      font-size="8"
                      fill={entry.color}
                      text-anchor={isRegression ? "start" : "end"}
                    >
                      {entry.deltaPct >= 0 ? "+" : ""}{entry.deltaPct.toFixed(1)}%
                    </text>
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>

      {/* Legend */}
      <div class="mt-2 flex flex-wrap gap-3 text-xs text-[var(--bb-data-fg-muted)]">
        <span>Baseline: <strong>{results[baselineIdx]?.platform}</strong></span>
        <span class="ml-2">
            <span class="inline-block h-2 w-3 rounded-sm mr-1" style={{ backgroundColor: FASTER_FILL }} />faster (negative %)
        </span>
        <span>
          <span class="inline-block h-2 w-3 rounded-sm mr-1" style={{ backgroundColor: SLOWER_FILL }} />slower (positive %)
        </span>
      </div>
    </div>
  );
}
