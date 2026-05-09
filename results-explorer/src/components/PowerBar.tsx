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
import { formatRunIdentitiesForCohort } from "@/lib/runIdentity";

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
  const w = Math.max(containerWidth, 400);

  const cohortLabels = formatRunIdentitiesForCohort(
    summary.platforms.map((platform) => ({ ...platform, scale_factor: summary.scale_factor })),
    "chart",
  );
  const rows = summary.platforms
    .map((p, i) => ({ ...p, colorIdx: i, displayLabel: cohortLabels[i] ?? p.platform }))
    .filter((p) => p.power_score !== null && p.power_score > 0)
    .sort((a, b) => (b.power_score ?? 0) - (a.power_score ?? 0));

  if (rows.length === 0) {
    return <p class="text-sm italic text-[var(--bb-data-fg-subtle)]">Power@Size scores not available for these results.</p>;
  }

  const maxScore = Math.max(...rows.map((r) => r.power_score!));
  const plotW = w - LABEL_W - VALUE_TRAIL;
  const totalH = PADDING_TOP + rows.length * ROW_H + AXIS_H;

  return (
    <div ref={containerRef} class="w-full overflow-x-auto">
      <svg class="bb-chart-svg" width={w} height={totalH} role="img" aria-label="TPC Power@Size comparison - higher is better">
        {rows.map((row, ri) => {
          const barW = (row.power_score! / maxScore) * plotW;
          const y = PADDING_TOP + ri * ROW_H;
          const midY = y + ROW_H * 0.5;
          const barH = ROW_H * 0.55;
          const color = paletteColor(row.colorIdx);
          return (
            <g key={row.result_id}>
              <text x={LABEL_W - 6} y={midY + 4} textAnchor="end" style={{ fontSize: "11px", fill: "#374151" }}>
                {row.displayLabel.length > 22 ? `${row.displayLabel.slice(0, 21)}…` : row.displayLabel}
              </text>
              <rect x={LABEL_W} y={midY - barH / 2} width={Math.max(2, barW)} height={barH} fill={color} rx={2}>
                <title>{`${row.displayLabel}: ${row.power_score!.toLocaleString(undefined, { maximumFractionDigits: 0 })} QphH`}</title>
              </rect>
              <text x={LABEL_W + barW + 6} y={midY + 4} style={{ fontSize: "11px", fill: "#374151" }}>
                {row.power_score!.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </text>
              {ri < rows.length - 1 && (
                <line x1={0} y1={y + ROW_H} x2={w} y2={y + ROW_H} stroke="#e5e7eb" strokeWidth={1} />
              )}
            </g>
          );
        })}

        {/* X-axis */}
        <g transform={`translate(0, ${PADDING_TOP + rows.length * ROW_H})`}>
          <line x1={LABEL_W} y1={0} x2={LABEL_W + plotW} y2={0} stroke="#d1d5db" strokeWidth={1} />
          {[0, 0.25, 0.5, 0.75, 1].map((f) => {
            const x = LABEL_W + f * plotW;
            const val = f * maxScore;
            return (
              <g key={f}>
                <line x1={x} y1={0} x2={x} y2={4} stroke="#9ca3af" strokeWidth={1} />
                <text x={x} y={16} textAnchor="middle" style={{ fontSize: "10px", fill: "#6b7280" }}>
                  {val > 0 ? val.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "0"}
                </text>
              </g>
            );
          })}
          <text
            x={LABEL_W + plotW / 2}
            y={AXIS_H - 2}
            textAnchor="middle"
            style={{ fontSize: "10px", fill: "#9ca3af" }}
          >
            Power@Size (QphH) - higher is better
          </text>
        </g>
      </svg>
    </div>
  );
}
