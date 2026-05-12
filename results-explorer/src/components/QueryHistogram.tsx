// ---------------------------------------------------------------------------
// QueryHistogram - vertical bar chart of per-query latency
//
// Each bar = one query's display_ms value for a platform.
// Multiple platforms → grouped bars per query.
// Auto-splits into panels of MAX_PER_PANEL queries when count > MAX_PER_PANEL.
//
// Python reference: textcharts.histogram.Histogram (bar chart, not frequency histogram)
// ---------------------------------------------------------------------------

import type { BenchmarkSummary } from "@/types";
import { useElementSize } from "@/lib/useElementSize";
import { paletteColor } from "@/lib/chartTheme";
import { queryDisplayLabel, sortQueryIds } from "@/lib/queryLabels";
import { formatTimingExclusion, platformTimingValue } from "@/lib/displayEligibility";
import { formatLatencyMs } from "@/lib/metricFormatters";

const MAX_PER_PANEL = 33;
const BAR_GAP = 3;
const AXIS_W = 44;
const LABEL_H = 28;
const CHART_H = 160;
const PADDING_TOP = 8;

interface Props {
  summary: BenchmarkSummary;
}

function fmtMs(ms: number): string {
  return formatLatencyMs(ms, { subMillisecond: "compact" }).valueText;
}

export function QueryHistogram({ summary }: Props) {
  const [containerRef, { width: containerWidth }] = useElementSize(300);
  const w = Math.max(containerWidth, 300);

  const { platforms, query_ids } = summary;
  if (platforms.length === 0 || query_ids.length === 0) return null;
  const sortedQueryIds = sortQueryIds(query_ids);

  // Split into panels
  const panels: string[][] = [];
  for (let i = 0; i < sortedQueryIds.length; i += MAX_PER_PANEL) {
    panels.push(sortedQueryIds.slice(i, i + MAX_PER_PANEL));
  }

  function renderPanel(qids: string[], panelIdx: number) {
    // Only positive timings contribute to the y-scale; null/0 represent
    // "did not run" and render as a tiny hatched tick so they're visibly
    // distinct from a genuine fast-but-present result.
    const allMs = platforms.flatMap((p) =>
      qids.map((qid) => {
        return platformTimingValue(p, qid) ?? 0;
      }),
    );
    const maxMs = Math.max(...allMs, 1);

    const n = qids.length;
    const groupW = (w - AXIS_W) / n;
    const innerW = groupW - BAR_GAP;
    const barW = Math.max(2, Math.floor(innerW / platforms.length));

    return (
      <div key={panelIdx} class="mb-2">
        {panels.length > 1 && (
          <p class="mb-0.5 ml-[44px] text-[10px] text-[var(--bb-data-fg-subtle)]">
            Queries {panelIdx * MAX_PER_PANEL + 1}-{Math.min((panelIdx + 1) * MAX_PER_PANEL, sortedQueryIds.length)}
          </p>
        )}
        <svg
          class="bb-chart-svg"
          width="100%"
          height={PADDING_TOP + CHART_H + LABEL_H}
          viewBox={`0 0 ${w} ${PADDING_TOP + CHART_H + LABEL_H}`}
          role="img"
          aria-label={`Query latency histogram${panels.length > 1 ? ` (panel ${panelIdx + 1})` : ""}`}
        >
          {/* Y-axis guides */}
          {[0, 0.25, 0.5, 0.75, 1].map((f) => {
            const y = PADDING_TOP + (1 - f) * CHART_H;
            return (
              <g key={f}>
                <line x1={AXIS_W} y1={y} x2={w} y2={y} stroke="#f3f4f6" strokeWidth={1} />
                {f > 0 && (
                  <text x={AXIS_W - 3} y={y + 3} textAnchor="end" style={{ fontSize: "9px", fill: "#9ca3af" }}>
                    {fmtMs(f * maxMs)}
                  </text>
                )}
              </g>
            );
          })}

          {/* Bars */}
          {qids.map((qid, qi) => {
            const groupX = AXIS_W + qi * groupW + BAR_GAP / 2;
            return (
              <g key={qid}>
                {platforms.map((p, pi) => {
                  const raw = p.timings[qid];
                  const ms = platformTimingValue(p, qid);
                  const missing = ms === null;
                  const barH = missing ? 0 : Math.max(1, (ms / maxMs) * CHART_H);
                  if (missing) {
                    const reason = formatTimingExclusion(
                      p.timing_eligibility[qid]?.timing_exclusion_reason ?? (raw === 0 ? "zero_timing" : "missing_timing"),
                    );
                    // Render a 2px dash at the x-axis so "missing" reads
                    // as distinct from "fast but present".
                    return (
                      <line
                        key={p.result_id}
                        x1={groupX + pi * barW}
                        y1={PADDING_TOP + CHART_H - 1}
                        x2={groupX + pi * barW + (barW - 1)}
                        y2={PADDING_TOP + CHART_H - 1}
                        stroke={paletteColor(pi)}
                        strokeWidth={2}
                        strokeDasharray="2,1"
                        opacity={0.5}
                      >
                        <title>{`${p.platform} · ${queryDisplayLabel(qid)}: ${reason}`}</title>
                      </line>
                    );
                  }
                  return (
                    <rect
                      key={p.result_id}
                      x={groupX + pi * barW}
                      y={PADDING_TOP + CHART_H - barH}
                      width={barW - 1}
                      height={barH}
                      fill={paletteColor(pi)}
                      fillOpacity={0.85}
                    >
                      <title>{`${p.platform} · ${queryDisplayLabel(qid)}: ${fmtMs(ms)}`}</title>
                    </rect>
                  );
                })}
                <text
                  x={groupX + innerW / 2}
                  y={PADDING_TOP + CHART_H + 14}
                  textAnchor="middle"
                  data-query-label={qid}
                  style={{ fontSize: "9px", fill: "#9ca3af" }}
                >
                  {queryDisplayLabel(qid)}
                </text>
              </g>
            );
          })}

          {/* Axes */}
          <line x1={AXIS_W} y1={PADDING_TOP} x2={AXIS_W} y2={PADDING_TOP + CHART_H} stroke="#d1d5db" strokeWidth={1} />
          <line
            x1={AXIS_W}
            y1={PADDING_TOP + CHART_H}
            x2={w}
            y2={PADDING_TOP + CHART_H}
            stroke="#d1d5db"
            strokeWidth={1}
          />
        </svg>
      </div>
    );
  }

  return (
    <div ref={containerRef} class="w-full">
      {panels.map((slice, pi) => renderPanel(slice, pi))}
      {platforms.length > 1 && (
        <div class="mt-1 flex flex-wrap gap-3 text-xs text-[var(--bb-data-fg-muted)]">
          {platforms.map((p, i) => (
            <span key={p.result_id} class="flex items-center gap-1">
              <span class="inline-block w-3 h-3 rounded-sm" style={{ backgroundColor: paletteColor(i) }} />
              {p.platform}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
