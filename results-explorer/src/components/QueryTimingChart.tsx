/**
 * SVG bar chart for per-query timings.
 * No external chart library - pure SVG.
 */

import { paletteColor } from "@/lib/chartTheme";
import { formatLatencyMs, formatPlainNumber } from "@/lib/metricFormatters";
import { useElementSize } from "@/lib/useElementSize";

interface Bar {
  label: string;
  value: number;
  color?: string;
}

interface QueryTimingChartProps {
  bars: Bar[];
  unit?: string;
  height?: number;
}

export function QueryTimingChart({ bars, unit = "ms", height = 220 }: QueryTimingChartProps) {
  const [containerRef, { width: containerWidth }] = useElementSize(800);

  if (bars.length === 0) return null;

  const paddingLeft = 48;
  const paddingRight = 16;
  const paddingTop = 16;
  const paddingBottom = 56;
  const barGap = 4;
  const viewWidth = Math.max(containerWidth, 300);
  const chartWidth = viewWidth - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;

  const maxValue = Math.max(...bars.map((b) => b.value), 1);
  const barWidth = Math.max(4, Math.floor((chartWidth - barGap * (bars.length - 1)) / bars.length));

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
        style={{ minWidth: `${Math.max(400, bars.length * 28)}px` }}
        role="img"
        aria-label="Query timing bar chart"
      >
        {/* Y-axis grid lines + labels */}
        {Array.from({ length: yTicks + 1 }, (_, i) => {
          const v = yStep * i;
          const y = paddingTop + chartHeight - (chartHeight * i) / yTicks;
          return (
            <g key={i}>
              <line x1={paddingLeft} y1={y} x2={viewWidth - paddingRight} y2={y} stroke="#e5e7eb" stroke-width="1" />
              <text x={paddingLeft - 6} y={y + 4} text-anchor="end" font-size="10" fill="#9ca3af">
                {formatValue(v)}
              </text>
            </g>
          );
        })}

        {/* Bars */}
        {bars.map((bar, i) => {
          const barH = Math.max(2, (bar.value / maxValue) * chartHeight);
          const x = paddingLeft + i * (barWidth + barGap);
          const y = paddingTop + chartHeight - barH;
          const color = bar.color ?? paletteColor(i);

          return (
            <g key={bar.label}>
              <rect x={x} y={y} width={barWidth} height={barH} fill={color} rx="2" opacity="0.85">
                <title>
                  {bar.label}: {formatValue(bar.value)}
                </title>
              </rect>
              {/* X-axis label */}
              <text
                x={x + barWidth / 2}
                y={paddingTop + chartHeight + 14}
                text-anchor="middle"
                font-size="9"
                fill="#6b7280"
                transform={`rotate(-45, ${x + barWidth / 2}, ${paddingTop + chartHeight + 14})`}
              >
                {bar.label}
              </text>
            </g>
          );
        })}

        {/* X-axis baseline */}
        <line
          x1={paddingLeft}
          y1={paddingTop + chartHeight}
          x2={viewWidth - paddingRight}
          y2={paddingTop + chartHeight}
          stroke="#d1d5db"
          stroke-width="1"
        />
      </svg>
    </div>
  );
}

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
  const viewWidth = Math.max(containerWidth, 300);
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
        style={{ minWidth: `${Math.max(500, groupCount * 60)}px` }}
        role="img"
        aria-label="Grouped query timing bar chart"
      >
        {/* Y-axis grid + labels */}
        {Array.from({ length: yTicks + 1 }, (_, i) => {
          const v = yStep * i;
          const y = paddingTop + chartHeight - (chartHeight * i) / yTicks;
          return (
            <g key={i}>
              <line x1={paddingLeft} y1={y} x2={viewWidth - paddingRight} y2={y} stroke="#e5e7eb" stroke-width="1" />
              <text x={paddingLeft - 6} y={y + 4} text-anchor="end" font-size="10" fill="#9ca3af">
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
                        strokeDasharray="2 2"
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
                fill="#6b7280"
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
          stroke="#d1d5db"
          stroke-width="1"
        />
      </svg>
    </div>
  );
}
