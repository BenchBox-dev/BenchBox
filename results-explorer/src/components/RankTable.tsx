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

import type { BenchmarkSummary, PlatformRow } from "@/types";
import { paletteColor } from "@/lib/chartTheme";
import { computeRankTable } from "@/lib/chartMath";
import { formatTimingExclusion, isRankable, platformTimingValue } from "@/lib/displayEligibility";
import { queryDisplayLabel, sortQueryIds } from "@/lib/queryLabels";
import {
  formatRunIdentitiesForCohort,
  preserveUniqueAfterTruncation,
  type RunIdentitySource,
} from "@/lib/runIdentity";

export { preserveUniqueAfterTruncation } from "@/lib/runIdentity";

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
  const rankableCellCount = countRankableTimingCells(platforms, sortedQueryIds);

  if (rankableCellCount === 0) {
    return <RankTableEmptyState summary={summary} queryIds={sortedQueryIds} />;
  }

  const ranks = computeRankTable(
    sortedQueryIds,
    platforms.map((platform) =>
      Object.fromEntries(
        sortedQueryIds.map((queryId) => [
          queryId,
          isRankable(platform) ? platformTimingValue(platform, queryId) : null,
        ]),
      ),
    ),
  );

  const winCounts = platforms.map((_, i) =>
    sortedQueryIds.filter((qid) => ranks[qid]?.[i] === 1).length,
  );
  const maxWins = Math.max(...winCounts);

  // Cohort-aware column-header identities. When the same platform name
  // appears more than once in the rank cohort (e.g., two DataFusion
  // versions), append the shortest qualifier set that distinguishes
  // them. Single occurrences keep the bare platform name. We pass the
  // deployment fingerprint fields too so two same-platform/same-version
  // runs that differ only by deployment can be disambiguated naturally
  // instead of falling straight to a result_id tiebreaker.
  const headerIdentitySources: RunIdentitySource[] = platforms.map((p) => ({
    result_id: p.result_id,
    platform: p.platform,
    platform_version: p.platform_version,
    run_date: p.run_date,
    trust_label: p.trust_label,
    deployment_class: p.deployment_class,
    instance_or_warehouse: p.instance_or_warehouse,
  }));
  const headerIdentities = formatRunIdentitiesForCohort(headerIdentitySources, "compact");
  const headerTooltips = formatRunIdentitiesForCohort(headerIdentitySources, "tooltip");
  // Visual truncation that preserves cohort uniqueness. The 16-char cap
  // keeps headers narrow on small viewports, but a naive slice can
  // re-introduce duplicates by cutting off the qualifier suffix that
  // distinguished two same-platform runs (e.g., `DataFusion v1.40.0`
  // vs `DataFusion v1.40.1` both → `DataFusion v1.4…`). Detect those
  // collisions and keep the full identity for the affected rows so the
  // disambiguation contract is preserved at the cost of slightly wider
  // header cells. The tooltip variant remains attached for hover
  // recovery in either case.
  const displayedHeaders = preserveUniqueAfterTruncation(headerIdentities, 16);
  const excludedPlatformCount = platforms.filter((platform) => !isRankable(platform)).length;

  return (
    <div>
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
            {platforms.map((p, i) => {
              const tooltip = headerTooltips[i] ?? p.platform;
              const truncated = displayedHeaders[i] ?? p.platform;
              const exclusion = isRankable(p) ? null : formatTimingExclusion(p.ranking_exclusion_reason);
              return (
                <th
                  key={p.result_id}
                  class="px-2 py-1.5 border-b border-[var(--bb-data-border)] text-[var(--bb-data-fg-primary)] font-semibold whitespace-nowrap text-center"
                  title={exclusion ? `${tooltip} - ${exclusion}` : tooltip}
                >
                  <span
                    class="inline-block w-2 h-2 rounded-full mr-1 align-middle"
                    style={{ backgroundColor: paletteColor(i) }}
                  />
                  {truncated}
                  {exclusion && (
                    <span class="ml-1 text-[var(--bb-data-fg-subtle)]" aria-label={exclusion}>
                      *
                    </span>
                  )}
                </th>
              );
            })}
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
      {excludedPlatformCount > 0 && (
        <p class="mt-2 text-[11px] text-[var(--bb-data-fg-subtle)]">
          Excluded columns are marked with * and are shown for provenance, not as rankable competitors.
        </p>
      )}
    </div>
  );
}

function countRankableTimingCells(platforms: readonly PlatformRow[], queryIds: readonly string[]): number {
  return platforms.reduce((total, platform) => {
    if (!isRankable(platform)) return total;
    return total + queryIds.filter((queryId) => platformTimingValue(platform, queryId) !== null).length;
  }, 0);
}

function RankTableEmptyState({ summary, queryIds }: { summary: BenchmarkSummary; queryIds: readonly string[] }) {
  const reasons = summarizeRankChartReasons(summary.platforms, queryIds);
  return (
    <div
      role="status"
      aria-label="Rank chart unavailable"
      class="rounded-md border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-4 py-3 text-sm"
    >
      <p class="font-semibold text-[var(--bb-data-fg-primary)]">Rank chart unavailable</p>
      <p class="mt-1 text-[var(--bb-data-fg-muted)]">
        No rankable timing cells are available for this cohort. Submitted evidence is Excluded or lacks valid timing,
        so a normal rank matrix would be all dashes.
      </p>
      {reasons.length > 0 && (
        <ul class="mt-2 space-y-1 text-xs text-[var(--bb-data-fg-muted)]">
          {reasons.slice(0, 3).map(({ reason, count }) => (
            <li key={reason}>
              {count} {count === 1 ? "result" : "results"}: {reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function summarizeRankChartReasons(
  platforms: readonly PlatformRow[],
  queryIds: readonly string[],
): { reason: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const platform of platforms) {
    const reason = rankChartReason(platform, queryIds);
    counts.set(reason, (counts.get(reason) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([reason, count]) => ({ reason, count }))
    .sort((a, b) => b.count - a.count || a.reason.localeCompare(b.reason));
}

function rankChartReason(platform: PlatformRow, queryIds: readonly string[]): string {
  if (!isRankable(platform)) return formatTimingExclusion(platform.ranking_exclusion_reason);
  const hasValidTiming = queryIds.some((queryId) => platformTimingValue(platform, queryId) !== null);
  return hasValidTiming
    ? "Result has rankable timing evidence."
    : formatTimingExclusion("no_valid_display_timing", "No valid display timing is available.");
}
