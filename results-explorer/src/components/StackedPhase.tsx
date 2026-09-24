// ---------------------------------------------------------------------------
// StackedPhase - stacked horizontal bar chart of benchmark phase durations
//
// One stacked bar per platform, segments = benchmark phases.
// Phase data comes from PlatformRow.phase_durations (pipeline-emitted,
// extracted from the bundle's phases block).
//
// Python reference: textcharts.stacked_bar.StackedBar
// ---------------------------------------------------------------------------

import type { BenchmarkSummary } from "@/types";
import { useElementSize } from "@/lib/useElementSize";
import { barRowLayout, chartFrame } from "@/lib/chartFrame";
import { PHASE_COLORS } from "@/lib/chartTheme";
import { formatDurationSeconds } from "@/lib/metricFormatters";
import { formatRunIdentityLabelsForCohort, preserveUniqueAfterTruncation } from "@/lib/runIdentity";

// Phase display names (bundle phase name → human-readable)
const PHASE_LABELS: Record<string, string> = {
  data_generation: "DataGen",
  schema_creation: "Schema",
  data_loading: "Load",
  validation: "Validate",
  power_test: "Power",
  throughput_test: "Throughput",
};

// Canonical phase display order
const PHASE_ORDER = [
  "data_generation",
  "schema_creation",
  "data_loading",
  "validation",
  "power_test",
  "throughput_test",
];

const LABEL_W = 160;
const ROW_H = 36;
const AXIS_H = 16;
const PADDING_TOP = 8;
const VALUE_TRAIL = 56;

interface Props {
  summary: BenchmarkSummary;
}

export function StackedPhase({ summary }: Props) {
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
  const rowLabelByResultId = new Map(
    summary.platforms.map((platform, index) => [platform.result_id, displayLabels[index] ?? platform.platform]),
  );
  const fullLabelByResultId = new Map(
    summary.platforms.map((platform, index) => [platform.result_id, cohortLabels[index]?.full ?? platform.platform]),
  );
  const rows = summary.platforms.filter(
    (p) => p.phase_durations && Object.keys(p.phase_durations).length > 0,
  );

  if (rows.length === 0) {
    return (
      <p class="text-sm italic text-[var(--bb-data-fg-subtle)]">
        Phase duration data is not available for these results. Re-run the pipeline with a bundle
        that includes a phases block.
      </p>
    );
  }

  // Which phases appear across any row, in canonical order.  Unknown phases
  // (not in PHASE_ORDER) are appended so they render with the fallback color
  // instead of contributing to `total` while being silently omitted.
  const knownInUse = PHASE_ORDER.filter((ph) =>
    rows.some((r) => r.phase_durations![ph] !== undefined),
  );
  const unknownInUse = Array.from(
    new Set(
      rows.flatMap((r) =>
        Object.keys(r.phase_durations!).filter((ph) => !PHASE_ORDER.includes(ph)),
      ),
    ),
  ).sort();
  const allPhases = [...knownInUse, ...unknownInUse];

  const allTotals = rows.map((r) =>
    Object.values(r.phase_durations!).reduce((a, b) => a + b, 0),
  );
  const maxTotal = Math.max(...allTotals, 1);
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
        aria-label="Benchmark phase duration breakdown"
      >
        {rows.map((row, ri) => {
          const y = PADDING_TOP + ri * layout.rowHeight;
          const midY = y + layout.barCenter;
          const barH = ROW_H * 0.55;
          const pd = row.phase_durations!;
          const total = Object.values(pd).reduce((a, b) => a + b, 0);

          let xOffset = layout.plotX;
          return (
            <g key={row.result_id}>
              <text
                x={layout.labelAbove ? 0 : LABEL_W - 6}
                y={y + layout.labelBaseline}
                text-anchor={layout.labelAbove ? "start" : "end"}
                style={{ fontSize: "11px", fill: "var(--bb-chart-label)" }}
              >
                <title>{fullLabelByResultId.get(row.result_id) ?? row.platform}</title>
                {rowLabelByResultId.get(row.result_id) ?? row.platform}
              </text>

              {allPhases.map((phase) => {
                const dur = pd[phase] ?? 0;
                if (dur <= 0) return null;
                const segW = (dur / maxTotal) * plotW;
                const x = xOffset;
                xOffset += segW;
                return (
                  <rect
                    key={phase}
                    x={x}
                    y={midY - barH / 2}
                    width={Math.max(1, segW)}
                    height={barH}
                    fill={PHASE_COLORS[phase] ?? "var(--bb-chart-axis)"}
                    rx={1}
                  >
                    <title>{`${PHASE_LABELS[phase] ?? phase}: ${formatDurationSeconds(dur).valueText}`}</title>
                  </rect>
                );
              })}

              <text
                x={layout.labelAbove ? w : xOffset + 5}
                y={layout.labelAbove ? y + layout.labelBaseline : midY + 4}
                text-anchor={layout.labelAbove ? "end" : "start"}
                style={{ fontSize: "10px", fill: "var(--bb-chart-axis)" }}
              >
                {formatDurationSeconds(total).valueText}
              </text>

              {ri < rows.length - 1 && (
                <line
                  x1={0}
                  y1={y + layout.rowHeight}
                  x2={layout.plotX + plotW}
                  y2={y + layout.rowHeight}
                  stroke="var(--bb-chart-grid)"
                  stroke-width={1}
                />
              )}
            </g>
          );
        })}

        <line
          x1={layout.plotX}
          y1={PADDING_TOP + rows.length * layout.rowHeight}
          x2={layout.plotX + plotW}
          y2={PADDING_TOP + rows.length * layout.rowHeight}
          stroke="var(--bb-chart-grid)"
          stroke-width={1}
        />
      </svg>

      {/* Legend */}
      <div class="mt-1.5 flex flex-wrap gap-3 text-xs text-[var(--bb-data-fg-muted)]">
        {allPhases.map((phase) => (
          <span key={phase} class="flex items-center gap-1">
            <span
              class="inline-block w-3 h-3 rounded-sm"
              style={{ backgroundColor: PHASE_COLORS[phase] ?? "var(--bb-chart-axis)" }}
            />
            {PHASE_LABELS[phase] ?? phase}
          </span>
        ))}
      </div>
    </div>
  );
}
