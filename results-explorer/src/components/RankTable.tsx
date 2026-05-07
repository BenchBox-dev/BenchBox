// ---------------------------------------------------------------------------
// RankTable - per-query platform ranking table
//
// Rows = query IDs, columns = platforms.
// Each cell shows the ordinal rank (1st = fastest) of that platform for
// that query.  Ties receive equal rank.
//
// Summary footer: win-count (# times ranked 1st) per platform.
//
// Python reference: textcharts.rank_table.RankTable
// ---------------------------------------------------------------------------

import type { BenchmarkSummary } from "@/types";
import { paletteColor } from "@/lib/chartTheme";
import { computeRankTable } from "@/lib/chartMath";
import { queryDisplayLabel, sortQueryIds } from "@/lib/queryLabels";

interface Props {
  summary: BenchmarkSummary;
}

function ordinal(n: number): string {
  const suffixes = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return `${n}${suffixes[(v - 20) % 10] ?? suffixes[v] ?? suffixes[0]}`;
}

export function RankTable({ summary }: Props) {
  const { platforms, query_ids } = summary;
  if (platforms.length === 0 || query_ids.length === 0) return null;
  const sortedQueryIds = sortQueryIds(query_ids);

  const ranks = computeRankTable(
    sortedQueryIds,
    platforms.map((p) => p.timings),
  );

  const winCounts = platforms.map((_, i) =>
    sortedQueryIds.filter((qid) => ranks[qid]?.[i] === 1).length,
  );
  const maxWins = Math.max(...winCounts);

  return (
    <div class="w-full overflow-x-auto">
      <table
        class="text-xs border-collapse min-w-full"
        aria-label="Per-query platform rankings (1st = fastest)"
      >
        <thead>
          <tr>
            <th class="text-left px-2 py-1.5 border-b border-[var(--bb-data-border)] text-[var(--bb-data-fg-muted)] font-normal sticky left-0 bg-[var(--bb-surface-data)] min-w-[4rem]">
              Query
            </th>
            {platforms.map((p, i) => (
              <th
                key={p.result_id}
                class="px-2 py-1.5 border-b border-[var(--bb-data-border)] text-[var(--bb-data-fg-primary)] font-semibold whitespace-nowrap text-center"
              >
                <span
                  class="inline-block w-2 h-2 rounded-full mr-1 align-middle"
                  style={{ backgroundColor: paletteColor(i) }}
                />
                {p.platform.length > 16 ? `${p.platform.slice(0, 15)}…` : p.platform}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedQueryIds.map((qid) => (
            <tr key={qid} class="hover:bg-[var(--bb-surface-data-muted)]">
              <td class="px-2 py-1 border-b border-[var(--bb-data-border)] text-[var(--bb-data-fg-muted)] font-mono sticky left-0 bg-[var(--bb-surface-data)]">
                {queryDisplayLabel(qid)}
              </td>
              {platforms.map((_, i) => {
                const r = ranks[qid]?.[i] ?? null;
                return (
                  <td
                    key={i}
                    class={`px-2 py-1 border-b border-[var(--bb-data-border)] text-center font-mono ${
                      r === 1
                        ? "font-bold text-[var(--bb-tone-success-fg)] bg-[var(--bb-tone-success-bg)]"
                        : r === null
                          ? "text-[var(--bb-data-fg-subtle)]"
                          : "text-[var(--bb-data-fg-muted)]"
                    }`}
                  >
                    {r === null ? "-" : ordinal(r)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr class="bg-[var(--bb-surface-data-muted)] border-t border-[var(--bb-data-border)]">
            <td class="px-2 py-1.5 text-[var(--bb-data-fg-muted)] sticky left-0 bg-[var(--bb-surface-data-muted)]">1st wins</td>
            {winCounts.map((w, i) => (
              <td
                key={i}
                class={`px-2 py-1.5 text-center font-semibold ${
                  w === maxWins && maxWins > 0 ? "text-[var(--bb-tone-success-fg)]" : "text-[var(--bb-data-fg-primary)]"
                }`}
              >
                {w}
              </td>
            ))}
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
