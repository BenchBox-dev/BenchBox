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
import { axisLabelAnchor, barRowLayout, chartFrame } from "@/lib/chartFrame";
import { paletteColor } from "@/lib/chartTheme";
import { isRankable } from "@/lib/displayEligibility";
import { formatPowerScore } from "@/lib/metricFormatters";
import { formatRunIdentityLabelsForCohort, preserveUniqueAfterTruncation } from "@/lib/runIdentity";

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
  const frame = chartFrame(containerWidth);
  const w = frame.width;
  const layout = barRowLayout(frame, { labelWidth: LABEL_W, rowHeight: ROW_H, valueTrail: VALUE_TRAIL });

  const cohortLabels = formatRunIdentityLabelsForCohort(
    summary.platforms.map((platform) => ({ ...platform, scale_factor: summary.scale_factor })),
  );
  const displayLabels = preserveUniqueAfterTruncation(
    cohortLabels.map((label) => label.disambiguated),
    22,
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
  const plotW = layout.plotWidth;
  const totalH = PADDING_TOP + rows.length * layout.rowHeight + AXIS_H;

  return (
    <div ref={containerRef} class="w-full">
      <svg
        class="bb-chart-svg"
        width="100%"
        height={totalH}
        viewBox={`0 0 ${w} ${totalH}`}
        role="img"
        aria-label="TPC Power@Size comparison - higher is better"
      >
        {rows.map((row, ri) => {
          const barW = (row.power_score! / maxScore) * plotW;
          const y = PADDING_TOP + ri * layout.rowHeight;
          const midY = y + layout.barCenter;
          const barH = ROW_H * 0.55;
          const color = paletteColor(row.colorIdx);
          const valueText = formatPowerScore(row.power_score).valueText;
          return (
            <g key={row.result_id}>
              <text
                x={layout.labelAbove ? 0 : LABEL_W - 6}
                y={y + layout.labelBaseline}
                text-anchor={layout.labelAbove ? "start" : "end"}
                aria-label={row.fullLabel}
                title={row.fullLabel}
                style={{ fontSize: "11px", fill: "var(--bb-chart-label)" }}
              >
                {row.displayLabel}
              </text>
              <rect
                x={layout.plotX}
                y={midY - barH / 2}
                width={Math.max(2, barW)}
                height={barH}
                fill={color}
                rx={2}
              >
                <title>{`${row.fullLabel}: ${valueText} QphH`}</title>
              </rect>
              {/* Wide rows trail the value after the bar; compact rows park it at
                  the end of the label line, where a long bar cannot push it off
                  the right edge. */}
              <text
                x={layout.labelAbove ? w : layout.plotX + barW + 6}
                y={layout.labelAbove ? y + layout.labelBaseline : midY + 4}
                text-anchor={layout.labelAbove ? "end" : "start"}
                style={{ fontSize: "11px", fill: "var(--bb-chart-label)" }}
              >
                {valueText}
              </text>
              {ri < rows.length - 1 && (
                <line
                  x1={0}
                  y1={y + layout.rowHeight}
                  x2={w}
                  y2={y + layout.rowHeight}
                  stroke="var(--bb-chart-grid)"
                  stroke-width={1}
                />
              )}
            </g>
          );
        })}

        {/* X-axis */}
        <g transform={`translate(0, ${PADDING_TOP + rows.length * layout.rowHeight})`}>
          <line x1={layout.plotX} y1={0} x2={layout.plotX + plotW} y2={0} stroke="var(--bb-chart-grid)" stroke-width={1} />
          {(layout.compactTicks ? [0, 0.5, 1] : [0, 0.25, 0.5, 0.75, 1]).map((f) => {
            const x = layout.plotX + f * plotW;
            const val = f * maxScore;
            return (
              <g key={f}>
                <line x1={x} y1={0} x2={x} y2={4} stroke="var(--bb-chart-label-muted)" stroke-width={1} />
                <text
                  x={x}
                  y={16}
                  text-anchor={axisLabelAnchor(x, w)}
                  style={{ fontSize: "10px", fill: "var(--bb-chart-axis)" }}
                >
                  {val > 0 ? formatPowerScore(val).valueText : "0"}
                </text>
              </g>
            );
          })}
          <text
            x={layout.plotX + plotW / 2}
            y={AXIS_H - 2}
            text-anchor="middle"
            style={{ fontSize: "10px", fill: "var(--bb-chart-label-muted)" }}
          >
            Power@Size (QphH) - higher is better
          </text>
        </g>
      </svg>
    </div>
  );
}
