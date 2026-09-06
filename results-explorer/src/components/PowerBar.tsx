// ---------------------------------------------------------------------------
// PowerBar - horizontal bar chart of TPC Power@Size scores
//
// Higher score = better.  Only renders when platforms have power_score data.
// Sorts bars locally by power_score descending so the visual order is reliable
// regardless of BenchmarkSummary ordering (upstream order depends on the
// benchmark family and can change; a local sort keeps this chart stable).
//
// Python reference: textcharts.bar_chart (performance_bar / power_bar variant)
// ---------------------------------------------------------------------------

import type { BenchmarkSummary } from "@/types";
import { useElementSize } from "@/lib/useElementSize";
import { paletteColor } from "@/lib/chartTheme";
import { isRankable } from "@/lib/displayEligibility";
import { formatPowerScore } from "@/lib/metricFormatters";
import { formatRunIdentityLabelsForCohort, preserveUniqueAfterTruncation } from "@/lib/runIdentity";
import { isNarrowChart, NARROW_CHART_MIN_WIDTH } from "@/lib/chartResponsive";

const LABEL_W = 160;
const ROW_H = 36;
const AXIS_H = 32;
const PADDING_TOP = 8;
const VALUE_TRAIL = 72; // space after bar for value label

interface Props {
  summary: BenchmarkSummary;
}

export function PowerBar({ summary }: Props) {
  const [containerRef, { width: containerWidth }] = useElementSize();
  const narrow = isNarrowChart(containerWidth);
  const w = Math.max(containerWidth, narrow ? NARROW_CHART_MIN_WIDTH : 400);
  const labelWidth = narrow ? 112 : LABEL_W;
  const rowHeight = narrow ? 48 : ROW_H;
  const axisHeight = narrow ? 36 : AXIS_H;
  const paddingTop = narrow ? 12 : PADDING_TOP;
  const valueTrail = narrow ? 64 : VALUE_TRAIL;

  const cohortLabels = formatRunIdentityLabelsForCohort(
    summary.platforms.map((platform) => ({ ...platform, scale_factor: summary.scale_factor })),
  );
  const displayLabels = preserveUniqueAfterTruncation(
    cohortLabels.map((label) => label.disambiguated),
    narrow ? 14 : 22,
  );
  const rows = summary.platforms
    .map((p, i) => ({
      ...p,
      colorIdx: i,
      displayLabel: displayLabels[i] ?? p.platform,
      fullLabel: cohortLabels[i]?.full ?? p.platform,
    }))
    .filter((p) => isRankable(p) && p.power_score !== null && p.power_score > 0)
    .sort((a, b) => (b.power_score ?? 0) - (a.power_score ?? 0));

  if (rows.length === 0) {
    return <p class="text-sm italic text-[var(--bb-data-fg-subtle)]">Power@Size scores not available for these results.</p>;
  }

  const maxScore = Math.max(...rows.map((r) => r.power_score!));
  const plotW = w - labelWidth - valueTrail;
  const totalH = paddingTop + rows.length * rowHeight + axisHeight;

  return (
    <div ref={containerRef} class="w-full overflow-x-auto">
      <svg class="bb-chart-svg" width={w} height={totalH} role="img" aria-label="TPC Power@Size comparison - higher is better">
        {rows.map((row, ri) => {
          const barW = (row.power_score! / maxScore) * plotW;
          const y = paddingTop + ri * rowHeight;
          const midY = y + rowHeight * 0.5;
          const barH = rowHeight * 0.55;
          const color = paletteColor(row.colorIdx);
          return (
            <g key={row.result_id}>
              <text
                x={labelWidth - 6}
                y={midY + 4}
                textAnchor="end"
                aria-label={row.fullLabel}
                title={row.fullLabel}
                style={{ fontSize: "11px", fill: "var(--bb-chart-label)" }}
              >
                {row.displayLabel}
              </text>
              <rect x={labelWidth} y={midY - barH / 2} width={Math.max(2, barW)} height={barH} fill={color} rx={2}>
                <title>{`${row.fullLabel}: ${formatPowerScore(row.power_score).valueText} QphH`}</title>
              </rect>
              <text x={labelWidth + barW + 6} y={midY + 4} style={{ fontSize: "11px", fill: "var(--bb-chart-label)" }}>
                {formatPowerScore(row.power_score).valueText}
              </text>
              {ri < rows.length - 1 && (
                <line x1={0} y1={y + rowHeight} x2={w} y2={y + rowHeight} stroke="var(--bb-chart-grid)" strokeWidth={1} />
              )}
            </g>
          );
        })}

        {/* X-axis */}
        <g transform={`translate(0, ${paddingTop + rows.length * rowHeight})`}>
          <line x1={labelWidth} y1={0} x2={labelWidth + plotW} y2={0} stroke="var(--bb-chart-grid)" strokeWidth={1} />
          {[0, 0.25, 0.5, 0.75, 1].map((f) => {
            const x = labelWidth + f * plotW;
            const val = f * maxScore;
            return (
              <g key={f}>
                <line x1={x} y1={0} x2={x} y2={4} stroke="var(--bb-chart-label-muted)" strokeWidth={1} />
                <text x={x} y={16} textAnchor="middle" style={{ fontSize: "10px", fill: "var(--bb-chart-axis)" }}>
                  {val > 0 ? formatPowerScore(val).valueText : "0"}
                </text>
              </g>
            );
          })}
          <text
            x={labelWidth + plotW / 2}
            y={axisHeight - 2}
            textAnchor="middle"
            style={{ fontSize: "10px", fill: "var(--bb-chart-label-muted)" }}
          >
            Power@Size (QphH) - higher is better
          </text>
        </g>
      </svg>
    </div>
  );
}
