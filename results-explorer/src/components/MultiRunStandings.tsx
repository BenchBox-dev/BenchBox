import type { DetailResult } from "@/types";
import { StatusBadge } from "@/components/StatusBadge";
import { geomeanMs } from "@/lib/chartMath";
import { timingValueForQuery } from "@/lib/displayEligibility";
import { COMPARE_TIE_THRESHOLD } from "@/lib/compareSummary";
import { fmtGeomean } from "@/utils";

/**
 * Standings for a three-to-four run comparison.
 *
 * A multi-run selection is a ranking problem, not a diff: the reader wants an
 * order and a margin, which 309 undifferentiated diff rows cannot give them.
 *
 * Every geomean here is computed over the SAME intersected query set, and the
 * caption states its size and how it was chosen. A standings table whose rows
 * were each averaged over a different query set would be an ordering of
 * incomparable numbers presented as a ranking.
 */
export interface MultiRunStandingsProps {
  results: DetailResult[];
  baselineIndex: number;
  runLabels: readonly string[];
}

export interface StandingRow {
  resultId: string;
  label: string;
  engine: string;
  hardware: string;
  geomeanMs: number | null;
  /** Ratio against the baseline: <1 faster, >1 slower. */
  ratioToBaseline: number | null;
  queriesWon: number;
  isBaseline: boolean;
  /** Inside the tie band against the baseline, so neither faster nor slower may be claimed. */
  tied: boolean;
  /** Inside a tie band with other runs for its rank position. */
  rankTied: boolean;
  /** Competition rank ("1", "T-1", or "—" when unranked). */
  rank: string;
}

/** Queries every selected run can answer. */
export function sharedQueryIdsFor(results: readonly DetailResult[]): string[] {
  const all = new Set<string>();
  for (const r of results) for (const t of r.display_timings) all.add(t.query_id);
  return [...all]
    .filter((q) => results.every((r) => timingValueForQuery(r, q) !== null))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}

function countWinsPerPlatform(results: readonly DetailResult[], shared: string[]): number[] {
  const wins = new Array(results.length).fill(0) as number[];
  shared.forEach((q) => {
    let best: number | null = null;
    let bestRuns: number[] = [];
    results.forEach((r, ri) => {
      const v = timingValueForQuery(r, q);
      if (v === null) return;
      if (best === null || v < best) {
        best = v;
        bestRuns = [ri];
      } else if (v === best) {
        bestRuns.push(ri);
      }
    });
    if (bestRuns.length === 1) {
      const winner = bestRuns[0]!;
      wins[winner] = (wins[winner] ?? 0) + 1;
    }
  });
  return wins;
}

export function buildStandings(
  results: readonly DetailResult[],
  baselineIndex: number,
  runLabels: readonly string[],
): { rows: StandingRow[]; sharedQueryIds: string[]; totalQueryIds: number } {
  const shared = sharedQueryIdsFor(results);
  const geomeans = results.map((r) => geomeanMs(shared.map((q) => timingValueForQuery(r, q)!)));
  const baselineGeomean = geomeans[baselineIndex] ?? null;
  const wins = countWinsPerPlatform(results, shared);

  const all = new Set<string>();
  for (const r of results) for (const t of r.display_timings) all.add(t.query_id);

  const rows: StandingRow[] = results.map((r, i) => {
    const g = geomeans[i] ?? null;
    const ratio = g !== null && baselineGeomean !== null && baselineGeomean > 0 ? g / baselineGeomean : null;
    const hw = r.environment?.cpu_model
      ? r.environment.cpu_model
      : r.environment?.cpu_family
      ? r.environment.cpu_family
      : r.environment?.arch
      ? r.environment.arch
      : "Not recorded";
    const mem = r.environment?.memory_gb !== undefined ? ` · ${r.environment.memory_gb} GB` : "";
    const hardware = hw === "Not recorded" ? "Not recorded" : `${hw}${mem}`;
    const engine = r.platform_version ? `${r.platform} v${r.platform_version}` : r.platform;
    return {
      resultId: r.result_id,
      label: runLabels[i] ?? r.platform,
      engine,
      hardware,
      geomeanMs: g,
      ratioToBaseline: ratio,
      queriesWon: wins[i] ?? 0,
      isBaseline: i === baselineIndex,
      tied: ratio !== null && Math.abs(ratio - 1) < COMPARE_TIE_THRESHOLD,
      rankTied: false,
      rank: "—",
    };
  });

  // Rank by geomean, faster first. Rows without a geomean sort last rather
  // than being dropped -- a run that could not be reduced is still selected.
  rows.sort((a, b) => {
    if (a.geomeanMs === null && b.geomeanMs === null) return 0;
    if (a.geomeanMs === null) return 1;
    if (b.geomeanMs === null) return -1;
    return a.geomeanMs - b.geomeanMs;
  });

  // Assign competition rank: tied rows receive "T-1", unranked rows receive "—".
  // Tie groups are formed against the fixed group leader to prevent transitive chaining.
  let i = 0;
  while (i < rows.length) {
    const leader = rows[i]!;
    if (leader.geomeanMs === null) {
      leader.rank = "—";
      i++;
      continue;
    }

    const leaderMs = leader.geomeanMs;
    const rankNum = i + 1;
    let j = i + 1;
    while (
      j < rows.length &&
      rows[j]!.geomeanMs !== null &&
      Math.abs(rows[j]!.geomeanMs! - leaderMs) / Math.min(rows[j]!.geomeanMs!, leaderMs) < COMPARE_TIE_THRESHOLD
    ) {
      j++;
    }

    const isTie = j > i + 1;
    const rankLabel = isTie ? `T-${rankNum}` : String(rankNum);
    for (let k = i; k < j; k++) {
      rows[k]!.rank = rankLabel;
      rows[k]!.rankTied = isTie;
    }

    i = j;
  }

  return { rows, sharedQueryIds: shared, totalQueryIds: all.size };
}

function ratioText(row: StandingRow): string {
  if (row.isBaseline) return "baseline";
  if (row.ratioToBaseline === null) return "—";
  if (row.tied) return "tied";
  return `${row.ratioToBaseline.toFixed(2)}x`;
}

export function MultiRunStandings({ results, baselineIndex, runLabels }: MultiRunStandingsProps) {
  if (results.length < 3) return null;
  const { rows, sharedQueryIds, totalQueryIds } = buildStandings(results, baselineIndex, runLabels);
  const excluded = totalQueryIds - sharedQueryIds.length;

  return (
    <section class="card mb-8" aria-labelledby="standings-title">
      <div class="mb-3">
        <h2 id="standings-title" class="text-base font-semibold text-[var(--bb-data-fg-primary)]">
          Standings
        </h2>
        <p class="mt-1 text-xs text-[var(--bb-data-fg-muted)]" data-testid="standings-caption">
          {`Ranked by geometric mean over the ${sharedQueryIds.length} of ${totalQueryIds} queries every run can answer.`}
          {excluded > 0
            ? ` ${excluded} ${excluded === 1 ? "query is" : "queries are"} excluded from every run so the geomeans compare like with like.`
            : ""}
        </p>
      </div>
      <div class="overflow-x-auto">
        <table class="min-w-full w-max divide-y divide-[var(--bb-data-border)] text-sm">
          <thead class="bg-[var(--bb-surface-data-muted)]">
            <tr>
              <th scope="col" class="table-th">Rank</th>
              <th scope="col" class="table-th">Run</th>
              <th scope="col" class="table-th">Hardware</th>
              <th scope="col" class="table-th">Geomean</th>
              <th scope="col" class="table-th">vs baseline</th>
              <th scope="col" class="table-th">Queries won</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-[var(--bb-data-border)] bg-[var(--bb-surface-data)]">
            {rows.map((row) => (
              <tr key={row.resultId} class="hover:bg-[var(--bb-surface-data-muted)]">
                <td class="table-td font-mono">{row.rank}</td>
                <td class="table-td">
                  {row.label}
                  {row.isBaseline ? (
                    <StatusBadge role="comparison" tone="neutral" class="ml-2">
                      Baseline
                    </StatusBadge>
                  ) : null}
                </td>
                <td class="table-td text-xs text-[var(--bb-data-fg-muted)]">
                  {row.hardware}
                </td>
                <td class="table-td font-mono">
                  {row.geomeanMs !== null ? fmtGeomean(row.geomeanMs) : "—"}
                </td>
                <td class="table-td font-mono" data-testid={`ratio-${row.resultId}`}>
                  {ratioText(row)}
                </td>
                <td class="table-td font-mono">{row.queriesWon}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
