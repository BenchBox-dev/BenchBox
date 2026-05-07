// ---------------------------------------------------------------------------
// SparklineTable - compact metrics table with inline spark bars
//
// One row per platform, columns: platform name, geomean_ms (bar+value),
// power_score (bar+value, when applicable), P99 latency, normalized cost.
// Inline bars make relative sizes visible at a glance.
//
// Python reference: textcharts.sparkline_table.SparklineTable
// ---------------------------------------------------------------------------

import type { BenchmarkSummary } from "@/types";
import { paletteColor } from "@/lib/chartTheme";
import { costModelDisclosure, costStatusLabel, normalizedCostValue } from "@/lib/costDisplay";

interface Props {
  summary: BenchmarkSummary;
}

function fmtMs(ms: number | null): string {
  if (ms === null) return "-";
  if (ms >= 10000) return `${(ms / 1000).toFixed(0)}s`;
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
  return `${ms.toFixed(0)}ms`;
}

function fmtScore(s: number | null): string {
  if (s === null) return "-";
  return s.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

// Inline bar: MAX_BAR_PX pixels = full-width bar.
// MIN_FRAC reserves a small stub for the worst value so the row never
// collapses to zero width and the slowest platform is still visually located.
const MAX_BAR_PX = 48;
const MIN_FRAC = 0.08;

interface SparkProps {
  value: number | null;
  max: number;
  color: string;
  higherIsBetter?: boolean;
}

function SparkBar({ value, max, color, higherIsBetter = false }: SparkProps) {
  if (value === null || max <= 0) return <span class="text-[var(--bb-data-fg-subtle)]">-</span>;
  // For higher-is-better (power_score): best = full bar, worst → MIN_FRAC.
  // For lower-is-better (latency):     best = full bar, worst → MIN_FRAC.
  // Either way, best=1.0 and worst=MIN_FRAC so relative spread is visible.
  const ratio = value / max;
  const scaled = higherIsBetter ? ratio : 1 - ratio;
  const barFraction = MIN_FRAC + Math.max(0, Math.min(1, scaled)) * (1 - MIN_FRAC);
  const barW = Math.max(2, Math.round(barFraction * MAX_BAR_PX));
  return (
    <span class="inline-flex items-center gap-1.5">
      <span
        class="inline-block h-2 rounded-sm align-middle flex-shrink-0"
        style={{ width: `${barW}px`, backgroundColor: color, opacity: 0.75 }}
      />
    </span>
  );
}

export function SparklineTable({ summary }: Props) {
  const { platforms } = summary;
  if (platforms.length === 0) return null;

  // Primary metric comes from the canonical DuckDB-persisted ranking row
  // (pipeline writes `benchmark_rankings.primary_metric`). Fall back to
  // geomean when the summary has no ranking config (synthetic summaries
  // built from a single DetailResult where geomean is always defined).
  const metric = summary.ranking?.primary_metric ?? "display_geomean_ms";
  const showPower = metric === "power_score" && platforms.some((p) => p.power_score !== null);
  const showP99 = platforms.some((p) => p.percentile_stats !== null);
  const showCost = platforms.some((p) => normalizedCostValue(p) !== null);

  const maxGeomean = Math.max(...platforms.map((p) => p.display_geomean_ms ?? 0), 1);
  const maxPower = Math.max(...platforms.map((p) => p.power_score ?? 0), 1);

  return (
    <div class="w-full overflow-x-auto">
      <table
        class="text-xs border-collapse min-w-full"
        role="grid"
        aria-label="Compact performance metrics overview"
      >
        <thead>
          <tr class="border-b border-[var(--bb-data-border)]">
            <th class="text-left px-2 py-1.5 text-[var(--bb-data-fg-muted)] font-normal min-w-[10rem]">Platform</th>
            <th class="text-right px-2 py-1.5 text-[var(--bb-data-fg-muted)] font-normal whitespace-nowrap" colSpan={2}>
              Geomean
            </th>
            {showPower && (
              <th class="text-right px-2 py-1.5 text-[var(--bb-data-fg-muted)] font-normal whitespace-nowrap" colSpan={2}>
                Power@Size
              </th>
            )}
            {showP99 && (
              <th class="text-right px-2 py-1.5 text-[var(--bb-data-fg-muted)] font-normal">P99</th>
            )}
            {showCost && (
              <th class="text-right px-2 py-1.5 text-[var(--bb-data-fg-muted)] font-normal" title={costModelDisclosure(platforms)}>
                Normalized cost
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {platforms.map((p, i) => {
            const color = paletteColor(i);
            return (
              <tr key={p.result_id} class="border-b border-[var(--bb-data-border)] hover:bg-[var(--bb-surface-data-muted)]">
                <td class="px-2 py-1.5 font-medium text-[var(--bb-data-fg-primary)]">
                  <span
                    class="inline-block w-2 h-2 rounded-full mr-1.5 align-middle"
                    style={{ backgroundColor: color }}
                  />
                  {p.platform}
                </td>
                {/* Geomean spark + value */}
                <td class="px-1 py-1.5">
                  <SparkBar value={p.display_geomean_ms} max={maxGeomean} color={color} />
                </td>
                <td class="px-2 py-1.5 text-right font-mono text-[var(--bb-data-fg-primary)]">
                  {fmtMs(p.display_geomean_ms)}
                </td>
                {/* Power score spark + value */}
                {showPower && (
                  <>
                    <td class="px-1 py-1.5">
                      <SparkBar
                        value={p.power_score}
                        max={maxPower}
                        color={color}
                        higherIsBetter
                      />
                    </td>
                    <td class="px-2 py-1.5 text-right font-mono text-[var(--bb-data-fg-primary)]">
                      {fmtScore(p.power_score)}
                    </td>
                  </>
                )}
                {/* P99 */}
                {showP99 && (
                  <td class="px-2 py-1.5 text-right font-mono text-[var(--bb-data-fg-muted)]">
                    {fmtMs(p.percentile_stats?.p99 ?? null)}
                  </td>
                )}
                {/* Cost */}
                {showCost && (
                  <td class="px-2 py-1.5 text-right font-mono text-[var(--bb-data-fg-muted)]">
                    {normalizedCostValue(p) !== null ? `$${normalizedCostValue(p)!.toFixed(2)}` : costStatusLabel(p)}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
