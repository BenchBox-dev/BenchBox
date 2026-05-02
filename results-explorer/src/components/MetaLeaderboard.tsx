import { useMemo, useRef, useState } from "preact/hooks";
import { route } from "preact-router";
import type { MetaCohort, MetaLeaderboard as MetaLeaderboardData, MetaPlatform, MetaRank } from "@/types";
import { colorForCell } from "@/lib/chartMath";
import { fmtGeomean, fmtScore, humanizeBenchmark } from "@/utils";
import { TrustBadge, ValidationBadge } from "@/components/TrustBadge";

export type MetaLeaderboardMode = "times" | "ranks" | "speedup";

interface MetaLeaderboardProps {
  data: MetaLeaderboardData;
  mode: MetaLeaderboardMode;
  onModeChange: (mode: MetaLeaderboardMode) => void;
  cohortHref?: (cohort: MetaCohort) => string;
  platformHref?: (platformId: string) => string;
  resultMetadataById?: ReadonlyMap<string, { trust_label: string; validation_status?: string | null }>;
}

const MODE_LABELS: Record<MetaLeaderboardMode, string> = {
  times: "Times",
  ranks: "Ranks",
  speedup: "Speedup",
};

export function MetaLeaderboard({
  data,
  mode,
  onModeChange,
  cohortHref = (cohort) => cohort.href,
  platformHref = (platformId) => `/results/p/${platformId}/`,
  resultMetadataById,
}: MetaLeaderboardProps) {
  const { cohorts = [], platforms = [] } = data ?? {};
  const gridRef = useRef<HTMLTableElement>(null);
  const [focusPos, setFocusPos] = useState({ row: 0, col: 0 });
  const [announcement, setAnnouncement] = useState("");

  const columnMins = useMemo(() => {
    const mins = new Map<string, number | null>();
    for (const cohort of cohorts) {
      const values = platforms
        .map((platform) => cellShadeMetric(platform.ranks[cohort.key], mode, cohort))
        .filter((value): value is number => value !== null);
      mins.set(cohort.key, values.length > 0 ? Math.min(...values) : null);
    }
    return mins;
  }, [cohorts, mode, platforms]);

  if (platforms.length === 0 || cohorts.length === 0) return null;

  function handleCellKey(event: KeyboardEvent, rowIdx: number, colIdx: number) {
    let nextRow = rowIdx;
    let nextCol = colIdx;
    switch (event.key) {
      case "ArrowRight":
        nextCol = Math.min(colIdx + 1, cohorts.length - 1);
        break;
      case "ArrowLeft":
        nextCol = Math.max(colIdx - 1, 0);
        break;
      case "ArrowDown":
        nextRow = Math.min(rowIdx + 1, platforms.length - 1);
        break;
      case "ArrowUp":
        nextRow = Math.max(rowIdx - 1, 0);
        break;
      case "Home":
        nextCol = 0;
        break;
      case "End":
        nextCol = cohorts.length - 1;
        break;
      case "PageUp":
        nextRow = 0;
        break;
      case "PageDown":
        nextRow = platforms.length - 1;
        break;
      case "Enter":
      case " ": {
        event.preventDefault();
        // Activation matches the row's mouse-click target (platform page), so
        // keyboard and pointer paths navigate to the same destination. The
        // column's cohort link is reachable via Tab on the header row.
        const platform = platforms[rowIdx];
        if (platform) route(platformHref(platform.platform_id));
        return;
      }
      default:
        return;
    }

    event.preventDefault();
    if (nextRow === rowIdx && nextCol === colIdx) return;
    setFocusPos({ row: nextRow, col: nextCol });
    const target = gridRef.current?.querySelector(
      `[data-cell="${nextRow}-${nextCol}"]`,
    ) as HTMLElement | null;
    target?.focus();
  }

  return (
    <section class="mb-12" aria-labelledby="meta-leaderboard-title">
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        class="sr-only"
      >
        {announcement}
      </div>

      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="meta-leaderboard-title" class="text-xl font-semibold text-gray-900">
            Cross-Benchmark Leaderboard
          </h2>
          <p class="mt-1 text-xs text-gray-500">
            Absolute values, ranks, or speedup-vs-cohort-best across the visible cohorts.
          </p>
        </div>
        <div class="flex overflow-hidden rounded-md border border-gray-300 text-sm">
          {(["times", "ranks", "speedup"] as const).map((value) => (
            <button
              key={value}
              class={`px-3 py-1.5 ${
                mode === value
                  ? "bg-brand-600 text-white"
                  : "bg-white text-gray-600 hover:bg-gray-50"
              }`}
              onClick={() => onModeChange(value)}
              aria-pressed={mode === value}
            >
              {MODE_LABELS[value]}
            </button>
          ))}
        </div>
      </div>

      <div class="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
        <table
          ref={gridRef}
          role="grid"
          aria-label="Cross-benchmark leaderboard"
          class="min-w-full text-sm"
        >
          <thead class="bg-gray-50">
            <tr role="row">
              <th scope="col" class="table-th sticky left-0 z-10 min-w-40 bg-gray-50">
                Platform
              </th>
              {cohorts.map((cohort) => (
                <th
                  key={cohort.key}
                  scope="col"
                  class="table-th whitespace-nowrap"
                  title={`${humanizeBenchmark(cohort.benchmark)} SF${cohort.scale_factor} ${cohort.phase} - ${cohort.platform_count} platforms`}
                >
                  <a
                    href={cohortHref(cohort)}
                    class="no-underline text-gray-500 hover:text-brand-600"
                  >
                    {cohort.label}
                  </a>
                </th>
              ))}
              <th
                scope="col"
                class="table-th whitespace-nowrap text-gray-700"
                title="Average rank across visible cohorts"
              >
                Avg rank
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-100">
            {platforms.map((platform, rowIdx) => (
              <tr
                key={platform.platform_id}
                class="cursor-pointer hover:bg-gray-50"
                onClick={() => route(platformHref(platform.platform_id))}
              >
                <td class="table-td sticky left-0 z-10 bg-white font-medium text-gray-900">
                  <a
                    href={platformHref(platform.platform_id)}
                    class="no-underline hover:text-brand-600"
                    onClick={(event) => event.stopPropagation()}
                  >
                    {platform.platform}
                  </a>
                </td>
                {cohorts.map((cohort, colIdx) => {
                  const rank = platform.ranks[cohort.key];
                  const shadeMetric = cellShadeMetric(rank, mode, cohort);
                  const minInCol = columnMins.get(cohort.key) ?? null;
                  const hue = shadeMetric !== null ? colorForCell(shadeMetric, minInCol) : null;
                  const active = focusPos.row === rowIdx && focusPos.col === colIdx;
                  const text = describeCell(platform, cohort, rank, mode);
                  const result = cohort.platforms?.find((row) => row.platform_id === platform.platform_id);
                  const metadata = result ? resultMetadataById?.get(result.result_id) : undefined;
                  const receiptHref = result ? `/results/r/${result.result_id}#run-receipt` : null;
                  return (
                    <td
                      key={cohort.key}
                      role="gridcell"
                      aria-colindex={colIdx + 1}
                      aria-rowindex={rowIdx + 1}
                      aria-label={text}
                      class={`table-td text-center font-mono ${active ? "ring-2 ring-brand-500 ring-inset" : ""}`}
                      style={{
                        backgroundColor: hue !== null ? `hsl(${hue} 72% 93%)` : undefined,
                      }}
                      tabIndex={active ? 0 : -1}
                      data-cell={`${rowIdx}-${colIdx}`}
                      onFocus={() => {
                        setFocusPos({ row: rowIdx, col: colIdx });
                        setAnnouncement(text);
                      }}
                      onKeyDown={(event) => handleCellKey(event, rowIdx, colIdx)}
                    >
                      {receiptHref ? (
                        <a
                          href={receiptHref}
                          class="font-mono no-underline hover:text-brand-700"
                          onClick={(event) => event.stopPropagation()}
                          title="Open result receipt"
                        >
                          {renderCellValue(rank, cohort, mode)}
                        </a>
                      ) : (
                        renderCellValue(rank, cohort, mode)
                      )}
                      {metadata && (
                        <div class="mt-1 flex flex-wrap justify-center gap-1">
                          <TrustBadge trustLabel={metadata.trust_label} compact />
                          <ValidationBadge validationStatus={metadata.validation_status} showMissing />
                        </div>
                      )}
                    </td>
                  );
                })}
                <td class="table-td text-center font-mono font-semibold text-gray-700">
                  {platform.avg_rank !== null ? platform.avg_rank.toFixed(1) : <span class="text-gray-300">-</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <details class="mt-3">
        <summary class="cursor-pointer text-xs text-gray-400 hover:text-gray-600">
          How this matrix is calculated
        </summary>
        <div class="mt-2 rounded-md border border-gray-100 bg-gray-50 px-4 py-3 text-xs text-gray-500 space-y-1">
          <p>
            <strong>Times</strong> shows the cohort&apos;s primary metric in its native units:
            geomean latency for most benchmarks, Power@Size for TPC-H/TPC-DS.
          </p>
          <p>
            <strong>Ranks</strong> keeps the original meta-leaderboard contract: 1 = best in the
            cohort, and missing cohorts are excluded from average-rank math.
          </p>
          <p>
            <strong>Speedup</strong> normalizes every cell to the cohort best, where 1.00x is
            best-in-cohort and smaller values are worse.
          </p>
        </div>
      </details>
    </section>
  );
}

function cellText(rank: MetaRank, cohort: MetaCohort, mode: MetaLeaderboardMode): string {
  if (mode === "ranks") return `${rank.rank}/${rank.total}`;
  if (mode === "speedup") {
    return rank.speedup_vs_best !== null && rank.speedup_vs_best !== undefined
      ? `${rank.speedup_vs_best.toFixed(2)}x`
      : "-";
  }
  if (rank.metric_value === null || rank.metric_value === undefined) return "-";
  return cohort.primary_order === "desc" ? fmtScore(rank.metric_value) : fmtGeomean(rank.metric_value);
}

function renderCellValue(
  rank: MetaRank | undefined,
  cohort: MetaCohort,
  mode: MetaLeaderboardMode,
) {
  if (!rank) return <span class="text-gray-300">-</span>;
  const text = cellText(rank, cohort, mode);
  if (mode === "ranks") {
    return (
      <span class={rank.rank === 1 ? "font-semibold text-green-700" : "text-gray-700"}>{text}</span>
    );
  }
  return text;
}

function cellShadeMetric(
  rank: MetaRank | undefined,
  mode: MetaLeaderboardMode,
  cohort: MetaCohort,
): number | null {
  if (!rank) return null;

  if (mode === "ranks") return rank.rank;

  if (cohort.primary_order === "desc") {
    if (rank.speedup_vs_best === null || rank.speedup_vs_best === undefined || rank.speedup_vs_best <= 0) {
      return null;
    }
    return 1 / rank.speedup_vs_best;
  }

  return rank.metric_value ?? null;
}

function describeCell(
  platform: MetaPlatform,
  cohort: MetaCohort,
  rank: MetaRank | undefined,
  mode: MetaLeaderboardMode,
): string {
  if (!rank) return `${platform.platform} did not run ${cohort.label}`;
  const text = cellText(rank, cohort, mode);
  return `${platform.platform} ${MODE_LABELS[mode].toLowerCase()} for ${cohort.label}: ${text}`;
}
