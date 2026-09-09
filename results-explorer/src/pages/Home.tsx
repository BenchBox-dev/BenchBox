import { useEffect, useRef, useState } from "preact/hooks";
import type { RoutableProps } from "preact-router";
import type { MetaLeaderboard as MetaLeaderboardData } from "@/types";
import type { ResultRow } from "@/lib/duckdbQueries";
import { getMetaLeaderboardData, listResults } from "@/lib/duckdbQueries";
import {
  BENCHMARK_LABELS,
  humanizeBenchmark,
  fmtScoreCompact,
  fmtScoreExact,
  fmtGeomean,
  errMsg,
} from "@/utils";
import { canonicalBenchmarkSlug, formatBenchmarkLabel } from "@/lib/displayLabels";
import { SkeletonBlock } from "@/components/LoadingSpinner";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { TableScrollHint } from "@/components/TableScrollHint";
import { ProvenanceLegend } from "@/components/ProvenanceLegend";
import { RunDateChip } from "@/components/RunAge";
import { formatCount } from "@/lib/copyFormatters";
import { normalizedCostLabel, normalizedCostValue } from "@/lib/costDisplay";
import { useDocumentTitle } from "@/lib/useDocumentTitle";

const SUPPORTED_BENCHMARK_COUNT = new Set(Object.values(BENCHMARK_LABELS)).size;
const RECENT_RESULT_COUNT = 5;

/**
 * The corpus overview: what BenchBox holds and what arrived most recently.
 *
 * The ranking table and its filters live on the compare route, which is where
 * a reader who wants to rank runs against each other is already headed. This
 * page answers the prior question - what is in the corpus at all - without
 * putting a filter between the reader and the answer.
 */
export function Home(_: RoutableProps) {
  const recentResultsScrollerRef = useRef<HTMLDivElement>(null);
  useDocumentTitle("Overview · BenchBox");
  const [results, setResults] = useState<ResultRow[] | null>(null);
  const [metaLeaderboard, setMetaLeaderboard] = useState<MetaLeaderboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // The overview reports the whole corpus, so it reads it unfiltered rather
    // than through the facet state the ranking table maintains.
    listResults()
      .then((rows) => {
        if (!cancelled) setResults(rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errMsg(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    getMetaLeaderboardData()
      .then((data) => {
        if (!cancelled) setMetaLeaderboard(data);
      })
      .catch(() => {
        // The rankings only supply a count here. Losing them leaves the rest of
        // the overview usable, so this failure is not surfaced as a page error.
        if (!cancelled) setMetaLeaderboard(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <ErrorMessage title="Could not load results" message={error} />;
  if (!results) return <OverviewSkeleton />;

  const benchmarks = [...new Set(results.map((result) => canonicalBenchmarkSlug(result.benchmark)))].sort();
  const platformIdToName = new Map(
    (metaLeaderboard?.platforms ?? []).map((platform) => [platform.platform_id, platform.platform]),
  );
  for (const result of results) {
    platformIdToName.set(result.platform_id, result.platform);
  }
  const platformIds = [...new Set(results.map((result) => result.platform_id))].sort();
  const recent = [...results]
    .sort((a, b) => b.run_date.localeCompare(a.run_date))
    .slice(0, RECENT_RESULT_COUNT);
  const showRecentCost = recent.some((result) => normalizedCostValue(result) !== null);
  const leaderboardCohortCount = metaLeaderboard?.cohorts.length ?? 0;
  const rankedPlatformCount =
    metaLeaderboard?.platforms.filter((platform) => platform.n_cohorts > 0).length ?? 0;

  return (
    <div class="mx-auto max-w-7xl px-4 py-4 sm:px-6 sm:py-8 lg:px-8" data-testid="overview-surface">
      <PageHeader
        eyebrow="Results"
        title="Overview"
        subtitle="What the public corpus holds today, and what arrived most recently. Rank runs against each other on the compare page."
        actions={
          <a href="/results/compare" class="btn btn-primary no-underline" data-testid="overview-compare-cta">
            Compare benchmark results
          </a>
        }
      />

      <FlywheelStrip />

      <section aria-label="Corpus summary" class="mb-8 grid grid-cols-2 gap-4 text-center sm:mb-12 lg:grid-cols-4">
        <StatCard
          value={SUPPORTED_BENCHMARK_COUNT}
          label={{ singular: "supported benchmark", plural: "supported benchmarks" }}
          detail={`${benchmarks.length} with public results`}
        />
        <StatCard
          value={results.length}
          label={{ singular: "published run", plural: "published runs" }}
          detail="reviewed by BenchBox maintainers"
        />
        <StatCard
          value={platformIds.length}
          label={{
            singular: "platform with public results",
            plural: "platforms with public results",
          }}
          detail="published platform IDs"
        />
        <StatCard
          value={leaderboardCohortCount}
          label={{ singular: "ranking", plural: "rankings" }}
          detail={`${formatCount(rankedPlatformCount, "ranked platform")}`}
        />
      </section>

      <section class="mb-8 sm:mb-12">
        <h2 class="mb-4 text-xl font-semibold text-[var(--bb-data-fg-primary)]">Recent results</h2>
        <div class="overflow-hidden rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] shadow-sm">
          <TableScrollHint
            scrollerRef={recentResultsScrollerRef}
            testId="recent-results-scroll-hint"
            label="Scroll table for row actions →"
            wrapperClassName="flex justify-end"
            className="m-2"
          />
          <div ref={recentResultsScrollerRef} class="overflow-x-auto" data-testid="recent-results-scroll-container">
            <table class="min-w-full w-max divide-y divide-[var(--bb-data-border)]">
              <thead class="bg-[var(--bb-surface-data-muted)]">
                <tr>
                  <th class="table-th">Benchmark</th>
                  <th class="table-th">Platform</th>
                  <th class="table-th">Scale</th>
                  <th class="table-th">Date</th>
                  <th class="table-th">Power score</th>
                  <th
                    class="table-th"
                    title="Geometric mean of per-query execution times (measurement runs only). Lower is faster."
                  >
                    Geomean latency
                  </th>
                  {showRecentCost && (
                    <th
                      class="table-th"
                      title="BenchBox estimated this cloud cost from the recorded deployment details. Local runs and runs without cost details are not included."
                    >
                      Normalized cost
                    </th>
                  )}
                  <th class="table-th sticky right-0 z-10 bg-[var(--bb-surface-data-muted)]" />
                </tr>
              </thead>
              <tbody class="divide-y divide-[var(--bb-data-border)] bg-[var(--bb-surface-data)]">
                {recent.map((result) => (
                  <RecentRow key={result.result_id} entry={result} showCost={showRecentCost} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <div class="grid grid-cols-1 gap-8 sm:grid-cols-2">
        <BrowseSection
          title="Browse public benchmark results"
          description={`${formatCount(benchmarks.length, "public benchmark set")}, covered by ${formatCount(leaderboardCohortCount, "ranking")}.`}
          items={benchmarks}
          hrefFn={(benchmark) => `/results/${benchmark}/`}
          labelFn={formatBenchmarkLabel}
        />
        <BrowseSection
          title="Browse public platform results"
          description={`${formatCount(platformIds.length, "published platform ID")} in the public corpus, independent of ranking coverage.`}
          items={platformIds}
          hrefFn={(platformId) => `/results/p/${platformId}/`}
          labelFn={(platformId) => platformIdToName.get(platformId) ?? platformId}
        />
      </div>

      <ProvenanceLegend />
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div class="mx-auto max-w-7xl px-4 py-4 sm:px-6 sm:py-8 lg:px-8" data-testid="overview-skeleton">
      <SkeletonBlock className="h-9 w-48" />
      <SkeletonBlock className="mt-3 h-5 w-full max-w-2xl" />
      <div class="mt-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[0, 1, 2, 3].map((slot) => (
          <SkeletonBlock key={slot} className="h-28" />
        ))}
      </div>
      <SkeletonBlock className="mt-8 h-64" />
    </div>
  );
}

const FLYWHEEL_STEPS = [
  { label: "Run a benchmark", href: "/docs/usage/installation.html" },
  { label: "Compare your result", href: "/results/query" },
  { label: "Submit a bundle", href: "/docs/contributing-results.html" },
];

function FlywheelStrip() {
  return (
    <section class="mb-12 border-y border-[var(--bb-data-border)] py-3">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p class="text-sm font-semibold text-[var(--bb-data-fg-primary)]">Run, compare, and submit</p>
        <nav aria-label="Result contribution workflow" class="flex flex-wrap gap-2">
          {FLYWHEEL_STEPS.map((step, index) => (
            <a
              key={step.href}
              href={step.href}
              data-native={step.href.startsWith("/docs/") ? "true" : undefined}
              aria-label={step.label}
              class="inline-flex h-9 items-center gap-2 rounded-md border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-3 text-sm font-medium text-[var(--bb-data-fg-primary)] no-underline hover:border-[var(--bb-accent)] hover:bg-[var(--bb-tone-info-bg)] hover:text-[var(--bb-accent-hover)]"
            >
              <span class="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--bb-surface-app)] text-xs text-[var(--bb-data-fg-muted)]">
                {index + 1}
              </span>
              {step.label}
            </a>
          ))}
        </nav>
      </div>
    </section>
  );
}

type StatCardLabel = string | { singular: string; plural: string };

function resolveStatCardLabel(value: number | string, label: StatCardLabel): string {
  if (typeof label === "string") return label;
  return typeof value === "number" && value === 1 ? label.singular : label.plural;
}

function StatCard({
  value,
  label,
  detail,
}: {
  value: number | string;
  label: StatCardLabel;
  detail?: string;
}) {
  const resolvedLabel = resolveStatCardLabel(value, label);
  return (
    <div class="card">
      <div class="text-3xl font-bold text-[var(--bb-accent-hover)]">{value}</div>
      <div class="mt-1 text-sm font-medium text-[var(--bb-data-fg-muted)]">{resolvedLabel}</div>
      {detail && <div class="mt-2 text-xs text-[var(--bb-data-fg-subtle)]">{detail}</div>}
    </div>
  );
}

function RecentRow({ entry, showCost }: { entry: ResultRow; showCost: boolean }) {
  return (
    <tr class="hover:bg-[var(--bb-surface-data-muted)]">
      <td class="table-td font-medium">{humanizeBenchmark(entry.benchmark)}</td>
      <td class="table-td">
        <span class="badge badge-blue">{entry.platform}</span>
      </td>
      <td class="table-td">SF {entry.scale_factor}</td>
      <td class="table-td text-[var(--bb-data-fg-muted)]"><RunDateChip runDate={entry.run_date} /></td>
      <td
        class="table-td font-mono"
        title={entry.power_score != null ? `Exact power score: ${fmtScoreExact(entry.power_score)}` : undefined}
      >
        {fmtScoreCompact(entry.power_score)}
      </td>
      <td class="table-td font-mono">{fmtGeomean(entry.geomean_ms)}</td>
      {showCost && <td class="table-td font-mono text-[var(--bb-data-fg-muted)]">{normalizedCostLabel(entry)}</td>}
      <td class="table-td sticky right-0 z-10 bg-[var(--bb-surface-data)] text-right">
        <a href={`/results/r/${entry.result_id}`} class="text-xs font-medium no-underline">
          View →
        </a>
      </td>
    </tr>
  );
}

interface BrowseSectionProps {
  title: string;
  description: string;
  items: string[];
  hrefFn: (item: string) => string;
  labelFn: (item: string) => string;
}

function BrowseSection({ title, description, items, hrefFn, labelFn }: BrowseSectionProps) {
  return (
    <section>
      <h2 class="text-xl font-semibold text-[var(--bb-data-fg-primary)]">{title}</h2>
      <p class="mt-1 mb-3 text-sm text-[var(--bb-data-fg-muted)]">{description}</p>
      <div class="flex flex-wrap gap-2">
        {items.map((item) => (
          <a
            key={item}
            href={hrefFn(item)}
            class="rounded-full border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-4 py-2 text-sm font-medium text-[var(--bb-data-fg-primary)] shadow-sm no-underline hover:border-[var(--bb-accent)] hover:bg-[var(--bb-tone-info-bg)] hover:text-[var(--bb-accent-hover)] transition-colors"
          >
            {labelFn(item)}
          </a>
        ))}
      </div>
    </section>
  );
}
