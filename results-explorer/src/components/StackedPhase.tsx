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
import { PHASE_COLORS } from "@/lib/chartTheme";
import { formatRunIdentitiesForCohort } from "@/lib/runIdentity";

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
  const w = Math.max(containerWidth, 400);

  const cohortLabels = formatRunIdentitiesForCohort(
    summary.platforms.map((platform) => ({ ...platform, scale_factor: summary.scale_factor })),
    "chart",
  );
  const rowLabelByResultId = new Map(
    summary.platforms.map((platform, index) => [platform.result_id, cohortLabels[index] ?? platform.platform]),
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
  const plotW = w - LABEL_W - VALUE_TRAIL;
  const totalH = PADDING_TOP + rows.length * ROW_H + AXIS_H;

  return (
    <div ref={containerRef} class="w-full overflow-x-auto">
      <svg
        class="bb-chart-svg"
        width={w}
        height={totalH}
        role="img"
        aria-label="Benchmark phase duration breakdown"
      >
        {rows.map((row, ri) => {
          const y = PADDING_TOP + ri * ROW_H;
          const midY = y + ROW_H * 0.5;
          const barH = ROW_H * 0.55;
          const pd = row.phase_durations!;
          const total = Object.values(pd).reduce((a, b) => a + b, 0);

          let xOffset = LABEL_W;
          return (
            <g key={row.result_id}>
              <text
                x={LABEL_W - 6}
                y={midY + 4}
                textAnchor="end"
                style={{ fontSize: "11px", fill: "#374151" }}
              >
                {(() => {
                  const label = rowLabelByResultId.get(row.result_id) ?? row.platform;
                  return label.length > 22 ? `${label.slice(0, 21)}…` : label;
                })()}
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
                    fill={PHASE_COLORS[phase] ?? "#94a3b8"}
                    rx={1}
                  >
                    <title>{`${PHASE_LABELS[phase] ?? phase}: ${dur.toFixed(1)}s`}</title>
                  </rect>
                );
              })}

              <text
                x={xOffset + 5}
                y={midY + 4}
                style={{ fontSize: "10px", fill: "#6b7280" }}
              >
                {total >= 60 ? `${(total / 60).toFixed(1)}m` : `${total.toFixed(1)}s`}
              </text>

              {ri < rows.length - 1 && (
                <line
                  x1={0}
                  y1={y + ROW_H}
                  x2={w - VALUE_TRAIL}
                  y2={y + ROW_H}
                  stroke="#e5e7eb"
                  strokeWidth={1}
                />
              )}
            </g>
          );
        })}

        <line
          x1={LABEL_W}
          y1={PADDING_TOP + rows.length * ROW_H}
          x2={LABEL_W + plotW}
          y2={PADDING_TOP + rows.length * ROW_H}
          stroke="#d1d5db"
          strokeWidth={1}
        />
      </svg>

      {/* Legend */}
      <div class="mt-1.5 flex flex-wrap gap-3 text-xs text-[var(--bb-data-fg-muted)]">
        {allPhases.map((phase) => (
          <span key={phase} class="flex items-center gap-1">
            <span
              class="inline-block w-3 h-3 rounded-sm"
              style={{ backgroundColor: PHASE_COLORS[phase] ?? "#94a3b8" }}
            />
            {PHASE_LABELS[phase] ?? phase}
          </span>
        ))}
      </div>
    </div>
  );
}
