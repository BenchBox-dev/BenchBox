/**
 * Grouped SVG bar chart for the compare view.
 * No external chart library - pure SVG.
 */

import { formatLatencyMs, formatPlainNumber } from "@/lib/metricFormatters";
import { useElementSize } from "@/lib/useElementSize";

/**
 * Grouped bar chart for compare view - one group per query, one bar per result.
 */
interface GroupedBar {
  queryId: string;
  values: { label: string; value: number | null; color: string }[];
}

interface GroupedChartProps {
  groups: GroupedBar[];
  unit?: string;
  height?: number;
}

export function GroupedQueryChart({ groups, unit = "ms", height = 260 }: GroupedChartProps) {
  const [containerRef, { width: containerWidth }] = useElementSize(900);

  if (groups.length === 0) return null;

  const paddingLeft = 52;
  const paddingRight = 16;
  const paddingTop = 16;
  const paddingBottom = 60;
  const groupGap = 8;
  const barGap = 2;
  // This chart opts out of reflow: it stays wide and scrolls inside its own
  // container. The viewBox must therefore be sized to the SAME minimum the CSS
  // enforces below. Drawing 300 units into a box CSS has stretched to
  // `groupCount * 60` px magnifies every coordinate by the ratio between them,
  // so the bars are computed against a width the chart is not given, collide at
  // their minimum width, and are then blown up along with the gaps.
  const scrollMinWidth = Math.max(500, groups.length * 60);
  const viewWidth = Math.max(containerWidth, scrollMinWidth);
  const chartWidth = viewWidth - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;

  const seriesCount = groups[0]?.values.length ?? 1;
  const groupCount = groups.length;
  const groupWidth = (chartWidth - groupGap * (groupCount - 1)) / groupCount;
  const barWidth = Math.max(4, (groupWidth - barGap * (seriesCount - 1)) / seriesCount);

  const allValues = groups.flatMap((g) => g.values.map((v) => v.value)).filter((v): v is number => v !== null);
  const maxValue = Math.max(...allValues, 1);
  const yTicks = 4;
  const yStep = maxValue / yTicks;

  function formatValue(v: number): string {
    if (unit === "ms") return formatLatencyMs(v, { subMillisecond: "compact" }).valueText;
    return `${formatPlainNumber(v).valueText}${unit}`;
  }

  return (
    <div ref={containerRef} class="overflow-x-auto">
      <svg
        class="bb-chart-svg"
        width="100%"
        height={height}
        viewBox={`0 0 ${viewWidth} ${height}`}
        style={{ minWidth: `${scrollMinWidth}px` }}
        role="img"
        aria-label="Grouped query timing bar chart"
      >
        {/* Y-axis grid + labels */}
        {Array.from({ length: yTicks + 1 }, (_, i) => {
          const v = yStep * i;
          const y = paddingTop + chartHeight - (chartHeight * i) / yTicks;
          return (
            <g key={i}>
              <line x1={paddingLeft} y1={y} x2={viewWidth - paddingRight} y2={y} stroke="var(--bb-chart-grid)" stroke-width="1" />
              <text x={paddingLeft - 6} y={y + 4} text-anchor="end" font-size="10" fill="var(--bb-chart-label-muted)">
                {formatValue(v)}
              </text>
            </g>
          );
        })}

        {/* Groups */}
        {groups.map((group, gi) => {
          const groupX = paddingLeft + gi * (groupWidth + groupGap);
          return (
            <g key={group.queryId}>
              {group.values.map((v, si) => {
                const x = groupX + si * (barWidth + barGap);
                {
                  /* Null means all runs failed for this query; render a dashed
                    outline so failed queries don't misrepresent as "fastest". */
                }
                if (v.value === null) {
                  const y = paddingTop + chartHeight - 6;
                  return (
                    <g key={v.label}>
                      <rect
                        x={x}
                        y={y}
                        width={barWidth}
                        height={6}
                        fill="none"
                        stroke={v.color}
                        stroke-dasharray="2 2"
                        rx="2"
                        opacity="0.5"
                      >
                        <title>
                          {group.queryId} - {v.label}: no data
                        </title>
                      </rect>
                    </g>
                  );
                }
                const barH = Math.max(2, (v.value / maxValue) * chartHeight);
                const y = paddingTop + chartHeight - barH;
                return (
                  <rect key={v.label} x={x} y={y} width={barWidth} height={barH} fill={v.color} rx="2" opacity="0.85">
                    <title>
                      {group.queryId} - {v.label}: {formatValue(v.value)}
                    </title>
                  </rect>
                );
              })}
              {/* Group label */}
              <text
                x={groupX + groupWidth / 2}
                y={paddingTop + chartHeight + 14}
                text-anchor="middle"
                font-size="9"
                fill="var(--bb-chart-axis)"
                transform={`rotate(-45, ${groupX + groupWidth / 2}, ${paddingTop + chartHeight + 14})`}
              >
                {group.queryId}
              </text>
            </g>
          );
        })}

        {/* Baseline */}
        <line
          x1={paddingLeft}
          y1={paddingTop + chartHeight}
          x2={viewWidth - paddingRight}
          y2={paddingTop + chartHeight}
          stroke="var(--bb-chart-grid)"
          stroke-width="1"
        />
      </svg>
    </div>
  );
}
