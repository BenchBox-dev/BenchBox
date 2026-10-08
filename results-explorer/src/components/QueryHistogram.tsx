import { formatRunIdentitiesForCohort } from "@/lib/runIdentity";

import type { BenchmarkSummary } from "@/types";
import { useElementSize } from "@/lib/useElementSize";
import { chartFrame, CHART_COMPACT_BELOW } from "@/lib/chartFrame";
import { paletteColor } from "@/lib/chartTheme";
import { queryDisplayLabel, sortQueryIds } from "@/lib/queryLabels";
import { formatTimingExclusion, platformTimingValue } from "@/lib/displayEligibility";
import { formatLatencyMs } from "@/lib/metricFormatters";

const MAX_PER_PANEL = 33;
const MIN_BAR_W = 3;
const BAR_GAP = 3;
const AXIS_W = 44;
const LABEL_H = 28;
const CHART_H = 160;
const PADDING_TOP = 8;

interface Props {
  summary: BenchmarkSummary;
  preserveOrder?: boolean;
}

function fmtMs(ms: number): string {
  return formatLatencyMs(ms, { subMillisecond: "compact" }).valueText;
}

export function QueryHistogram({ summary, preserveOrder = false }: Props) {
  const [containerRef, { width: containerWidth }] = useElementSize(300);
  const frame = chartFrame(containerWidth, { minWidth: 300 });
  const w = frame.width;

  const { platforms, query_ids } = summary;
  if (platforms.length === 0 || query_ids.length === 0) return null;
  const runLabels = formatRunIdentitiesForCohort(platforms, "chart");
  const sortedQueryIds = preserveOrder ? query_ids : sortQueryIds(query_ids);
  const maxMs = Math.max(1, ...platforms.flatMap((p) => sortedQueryIds.map((qid) => platformTimingValue(p, qid) ?? 0)));

  const minGroupW = platforms.length * MIN_BAR_W + BAR_GAP;
  const perPanel = Math.max(1, Math.min(MAX_PER_PANEL, Math.floor((w - AXIS_W) / minGroupW)));

  const panels: string[][] = [];
  for (let i = 0; i < sortedQueryIds.length; i += perPanel) {
    panels.push(sortedQueryIds.slice(i, i + perPanel));
  }

  function renderHorizontalPanel(qids: string[], panelIdx: number) {
    const rowHeight = 18;
    const groupHeight = platforms.length * rowHeight + 10;
    const labelWidth = Math.min(100, w / 3);
    const plotWidth = w - labelWidth - 8;
    const height = qids.length * groupHeight + 32;
    return <svg key={panelIdx} class="bb-chart-svg" width="100%" height={height}
      viewBox={`0 0 ${w} ${height}`} role="img" aria-label={`Query latency bar chart (panel ${panelIdx + 1})`} data-orientation="horizontal">
      {[0, 0.5, 1].map((fraction) => <g key={fraction}>
        <line x1={labelWidth + fraction * plotWidth} x2={labelWidth + fraction * plotWidth} y1={24} y2={height} stroke="var(--bb-chart-grid-muted)" />
        <text x={labelWidth + fraction * plotWidth} y={14} text-anchor={fraction === 1 ? "end" : "middle"} style={{ fontSize: "10px", fill: "var(--bb-chart-label-muted)" }}>{fmtMs(fraction * maxMs)}</text>
      </g>)}
      {qids.map((qid, qi) => <g key={qid}>
        <text x={labelWidth - 6} y={32 + qi * groupHeight} text-anchor="end" data-query-label={qid} style={{ fontSize: "11px", fill: "var(--bb-chart-label-muted)" }}>{queryDisplayLabel(qid)}</text>
        {platforms.map((p, pi) => {
          const ms = platformTimingValue(p, qid);
          const y = 24 + qi * groupHeight + pi * rowHeight;
          const title = `${runLabels[pi] ?? p.platform} · ${queryDisplayLabel(qid)}: ${ms === null ? formatTimingExclusion(p.timing_eligibility[qid]?.timing_exclusion_reason ?? "missing_timing") : fmtMs(ms)}`;
          return ms === null
            ? <line key={p.result_id} x1={labelWidth} x2={labelWidth + 4} y1={y + 6} y2={y + 6} stroke={paletteColor(pi)} stroke-dasharray="2,1"><title>{title}</title></line>
            : <rect key={p.result_id} x={labelWidth} y={y} width={Math.max(1, ms / maxMs * plotWidth)} height={12} fill={paletteColor(pi)} fill-opacity={0.85}><title>{title}</title></rect>;
        })}
      </g>)}
    </svg>;
  }

  function renderPanel(qids: string[], panelIdx: number) {

    const n = qids.length;
    const groupW = (w - AXIS_W) / n;
    const innerW = groupW - BAR_GAP;
    const idealBarW = innerW / platforms.length;
    const barW = idealBarW >= MIN_BAR_W ? Math.floor(idealBarW) : Math.max(0.5, idealBarW);
    const labelStride = groupW >= 22 ? 1 : Math.ceil(22 / Math.max(groupW, 1));

    return (
      <div key={panelIdx} class="mb-2">
        {panels.length > 1 && (
          <p class="mb-0.5 ml-[44px] text-[10px] text-[var(--bb-data-fg-subtle)]">
            Queries {panelIdx * perPanel + 1}-{Math.min((panelIdx + 1) * perPanel, sortedQueryIds.length)}
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
          {[0, 0.25, 0.5, 0.75, 1].map((f) => {
            const y = PADDING_TOP + (1 - f) * CHART_H;
            return (
              <g key={f}>
                <line x1={AXIS_W} y1={y} x2={w} y2={y} stroke="var(--bb-chart-grid-muted)" stroke-width={1} />
                {f > 0 && (
                  <text x={AXIS_W - 3} y={y + 3} text-anchor="end" style={{ fontSize: "9px", fill: "var(--bb-chart-label-muted)" }}>
                    {fmtMs(f * maxMs)}
                  </text>
                )}
              </g>
            );
          })}

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
                    return (
                      <line
                        key={p.result_id}
                        x1={groupX + pi * barW}
                        y1={PADDING_TOP + CHART_H - 1}
                        x2={groupX + pi * barW + (barW - 1)}
                        y2={PADDING_TOP + CHART_H - 1}
                        stroke={paletteColor(pi)}
                        stroke-width={2}
                        stroke-dasharray="2,1"
                        opacity={0.5}
                      >
                        <title>{`${runLabels[pi] ?? p.platform} · ${queryDisplayLabel(qid)}: ${reason}`}</title>
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
                      fill-opacity={0.85}
                    >
                      <title>{`${runLabels[pi] ?? p.platform} · ${queryDisplayLabel(qid)}: ${fmtMs(ms)}`}</title>
                    </rect>
                  );
                })}
                {qi % labelStride === 0 && (
                  <text
                    x={groupX + innerW / 2}
                    y={PADDING_TOP + CHART_H + 14}
                    text-anchor="middle"
                    data-query-label={qid}
                    style={{ fontSize: "9px", fill: "var(--bb-chart-label-muted)" }}
                  >
                    {queryDisplayLabel(qid)}
                  </text>
                )}
              </g>
            );
          })}

          <line x1={AXIS_W} y1={PADDING_TOP} x2={AXIS_W} y2={PADDING_TOP + CHART_H} stroke="var(--bb-chart-grid)" stroke-width={1} />
          <line
            x1={AXIS_W}
            y1={PADDING_TOP + CHART_H}
            x2={w}
            y2={PADDING_TOP + CHART_H}
            stroke="var(--bb-chart-grid)"
            stroke-width={1}
          />
        </svg>
      </div>
    );
  }

  return (
    <div ref={containerRef} class="w-full">
      {panels.map((slice, pi) => w < CHART_COMPACT_BELOW ? renderHorizontalPanel(slice, pi) : renderPanel(slice, pi))}
      {platforms.length > 1 && (
        <div class="mt-1 flex flex-wrap gap-3 text-xs text-[var(--bb-data-fg-muted)]">
          {platforms.map((p, i) => (
            <span key={p.result_id} class="flex items-center gap-1">
              <span class="inline-block w-3 h-3 rounded-sm" style={{ backgroundColor: paletteColor(i) }} />
              {runLabels[i] ?? p.platform}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
