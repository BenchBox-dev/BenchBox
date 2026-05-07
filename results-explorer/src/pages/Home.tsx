import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { RoutableProps } from "preact-router";
import type {
  MetaCohort,
  MetaLeaderboard as MetaLeaderboardData,
  MetaPlatform,
  MetaRank,
} from "@/types";
import type { ResultRow } from "@/lib/duckdbQueries";
import { getMetaLeaderboardData, listResults } from "@/lib/duckdbQueries";
import { BENCHMARK_LABELS, humanizeBenchmark, fmtScore, fmtGeomean, errMsg } from "@/utils";
import { MetaLeaderboardSkeleton, SkeletonBlock } from "@/components/LoadingSpinner";
import { ErrorMessage } from "@/components/ErrorMessage";
import { MetaLeaderboard } from "@/components/MetaLeaderboard";
import type { MetaLeaderboardMode } from "@/components/MetaLeaderboard";
import {
  FACET_KEYS,
  useFacetState,
  type FacetKey,
  type FacetState,
} from "@/lib/facetModel";
import {
  appendFacetParams,
  matchesFacetRow,
  singleFacetValue,
  toggleFacetValue,
  toDateWindowFacet,
} from "@/lib/facetMatching";
import { normalizedCostLabel, normalizedCostValue } from "@/lib/costDisplay";
import { formatFacetDisplayValue } from "@/lib/facetDisplay";
import { stringSerde, useUrlState } from "@/lib/useUrlState";
import { useDocumentTitle } from "@/lib/useDocumentTitle";
import {
  EXPLORER_PERFORMANCE_MARKS,
  EXPLORER_PERFORMANCE_MEASURES,
  markExplorerPerformance,
  measureExplorerPerformance,
} from "@/lib/performanceMarks";

const SUPPORTED_BENCHMARK_COUNT = new Set(Object.values(BENCHMARK_LABELS)).size;

export function Home(_: RoutableProps) {
  useDocumentTitle("Results · BenchBox");
  const [results, setResults] = useState<ResultRow[] | null>(null);
  const [metaLeaderboard, setMetaLeaderboard] = useState<MetaLeaderboardData | null>(null);
  const [metaLeaderboardLoaded, setMetaLeaderboardLoaded] = useState(false);
  const retriedEmptyResults = useRef(false);
  const [emptyResultsRetryFinished, setEmptyResultsRetryFinished] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { facets, where: facetWhere, setFacet, resetFacets } = useFacetState();
  const [modeRaw, setModeRaw] = useUrlState<string>("mode", "times", stringSerde);
  const benchmarkFilters = facets.benchmark;
  const scaleFilters = facets.scale_factor;
  const phaseFilter = singleFacetValue(facets.phase, "all");
  const tuningFilter = singleFacetValue(facets.tuning_mode, "all");
  const trustFilter = singleFacetValue(facets.trust_tier, "all");
  const dateWindow = facets.date_window;

  useEffect(() => {
    let cancelled = false;
    listResults(facetWhere)
      .then((rows) => {
        if (!cancelled) setResults(rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errMsg(err));
      });
    return () => {
      cancelled = true;
    };
  }, [facetWhere]);

  useEffect(() => {
    let cancelled = false;
    markExplorerPerformance(EXPLORER_PERFORMANCE_MARKS.HOME_LEADERBOARD_DATA_START, { once: true });
    getMetaLeaderboardData()
      .then((data) => {
        if (!cancelled) {
          markExplorerPerformance(EXPLORER_PERFORMANCE_MARKS.HOME_LEADERBOARD_DATA_READY, {
            once: true,
            detail: { cohortCount: data?.cohorts.length ?? 0 },
          });
          measureExplorerPerformance(
            EXPLORER_PERFORMANCE_MEASURES.HOME_LEADERBOARD_DATA,
            EXPLORER_PERFORMANCE_MARKS.HOME_LEADERBOARD_DATA_START,
            EXPLORER_PERFORMANCE_MARKS.HOME_LEADERBOARD_DATA_READY,
            { once: true },
          );
          setMetaLeaderboard(data);
          setMetaLeaderboardLoaded(true);
        }
      })
      .catch(() => {
        if (!cancelled) setMetaLeaderboardLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Cold-load mitigation (N5 in pass-2 review): unfiltered listResults() can briefly
  // resolve to [] on a cold DuckDB-WASM attach while the meta-leaderboard
  // succeeds, which would otherwise paint "0 Results / 0 Benchmarks /
  // 0 Platforms" before the real corpus arrives. Retrying once is a
  // symptom-mitigation, not a root-cause fix; we have not pinned which of
  // (a) WASM cold-cache partial read, (b) Preact effect-cleanup race, or
  // (c) shared initPromise in db.ts is the trigger. The diagnostic log
  // makes future investigation possible by surfacing the exact mismatch
  // in browser DevTools without needing to re-run the audit setup.
  const hasInconsistentEmptySnapshot =
    facetWhere.sql === "" && results !== null && results.length === 0 && metaLeaderboard !== null;
  const hasPersistentInconsistentEmptySnapshot = hasInconsistentEmptySnapshot && emptyResultsRetryFinished;

  useEffect(() => {
    if (!hasInconsistentEmptySnapshot || retriedEmptyResults.current) return;
    let cancelled = false;
    retriedEmptyResults.current = true;
    if (typeof console !== "undefined") {
      console.warn(
        "[Home] Inconsistent cold-load snapshot detected: listResults()=[] but meta-leaderboard has %d cohort(s). Retrying once.",
        metaLeaderboard?.cohorts?.length ?? 0,
      );
    }
    listResults(facetWhere)
      .then((rows) => {
        if (!cancelled) {
          setResults(rows);
          setEmptyResultsRetryFinished(true);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setEmptyResultsRetryFinished(true);
          setError(errMsg(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [facetWhere, hasInconsistentEmptySnapshot]);

  const resultById = useMemo(
    () => new Map((results ?? []).map((result) => [result.result_id, result])),
    [results],
  );

  const cohortPlatformIndex = useMemo(() => {
    const index = new Map<string, Map<string, string>>();
    if (!metaLeaderboard) return index;
    for (const cohort of metaLeaderboard.cohorts) {
      const inner = new Map<string, string>();
      for (const row of cohort.platforms ?? []) {
        inner.set(row.platform_id, row.result_id);
      }
      index.set(cohort.key, inner);
    }
    return index;
  }, [metaLeaderboard]);

  const filteredMetaLeaderboard = useMemo(() => {
    if (!metaLeaderboard) return null;

    const visibleCohorts = metaLeaderboard.cohorts.filter((cohort) => {
      if (benchmarkFilters.length > 0 && !benchmarkFilters.includes(cohort.benchmark)) return false;
      if (scaleFilters.length > 0 && !scaleFilters.includes(String(cohort.scale_factor))) return false;
      if (phaseFilter !== "all" && cohort.phase !== phaseFilter) return false;

      return (cohort.platforms ?? []).some((row) => {
        const result = resultById.get(row.result_id);
        return result !== undefined && matchesFacetRow(result, facets);
      });
    });

    const visibleCohortKeys = new Set(visibleCohorts.map((cohort) => cohort.key));
    const platforms = metaLeaderboard.platforms
      .map((platform) => {
        const ranks = Object.fromEntries(
          Object.entries(platform.ranks).filter(([cohortKey]) => {
            if (!visibleCohortKeys.has(cohortKey)) return false;
            const resultId = cohortPlatformIndex.get(cohortKey)?.get(platform.platform_id);
            const result = resultId ? resultById.get(resultId) : undefined;
            return result !== undefined && matchesFacetRow(result, facets);
          }),
        ) as Record<string, MetaRank>;

        const rankValues = Object.values(ranks).map((rank) => rank.rank);
        const avgRank = rankValues.length > 0
          ? Math.round((rankValues.reduce((sum, rank) => sum + rank, 0) / rankValues.length) * 10) / 10
          : null;

        return {
          ...platform,
          ranks,
          avg_rank: avgRank,
          n_cohorts: rankValues.length,
        } satisfies MetaPlatform;
      })
      .filter((platform) => platform.n_cohorts > 0)
      .sort((a, b) => {
        if (a.avg_rank === null && b.avg_rank === null) return 0;
        if (a.avg_rank === null) return 1;
        if (b.avg_rank === null) return -1;
        return a.avg_rank - b.avg_rank;
      });

    return {
      ...metaLeaderboard,
      cohorts: visibleCohorts,
      platforms,
    };
  }, [
    benchmarkFilters,
    cohortPlatformIndex,
    facets,
    metaLeaderboard,
    phaseFilter,
    resultById,
    scaleFilters,
  ]);

  if (error) return <ErrorMessage message={error} />;
  if (hasPersistentInconsistentEmptySnapshot) {
    return (
      <ErrorMessage
        title="Results snapshot incomplete"
        message="The results table loaded empty while leaderboard metadata is present. Reload the page to retry the DuckDB snapshot load."
      />
    );
  }
  if (!results || !metaLeaderboardLoaded || hasInconsistentEmptySnapshot) {
    return <HomeLoadingSkeleton />;
  }

  const mode: MetaLeaderboardMode =
    modeRaw === "ranks" || modeRaw === "speedup" ? modeRaw : "times";
  const benchmarks = [...new Set(results.map((result) => result.benchmark))].sort();
  const platformIdToName = new Map(
    (metaLeaderboard?.platforms ?? []).map((platform) => [platform.platform_id, platform.platform]),
  );
  for (const result of results) {
    platformIdToName.set(result.platform_id, result.platform);
  }
  const platformIds = [...new Set(results.map((result) => result.platform_id))].sort();
  const activeFacetSummaries = summarizeActiveFacets(facets, platformIdToName);
  const benchmarkOptions = metaLeaderboard
    ? [...new Set(metaLeaderboard.cohorts.map((cohort) => cohort.benchmark))].sort()
    : [];
  const scaleOptions = metaLeaderboard
    ? [...new Set(metaLeaderboard.cohorts.map((cohort) => String(cohort.scale_factor)))].sort(
        (a, b) => Number(a) - Number(b),
      )
    : [];
  const phaseOptions = metaLeaderboard
    ? [...new Set(metaLeaderboard.cohorts.map((cohort) => cohort.phase))].sort()
    : [];
  const tuningOptions = [
    "all",
    ...[...new Set(results.map((result) => result.tuning_mode).filter((value): value is string => value !== null))].sort(),
  ];
  const trustOptions = ["all", ...[...new Set(results.map((result) => result.trust_label))].sort()];
  const recent = [...results]
    .sort((a, b) => b.run_date.localeCompare(a.run_date))
    .slice(0, 5);
  const showRecentCost = recent.some((result) => normalizedCostValue(result) !== null);

  function buildCohortHref(cohort: MetaCohort): string {
    const params = new URLSearchParams();
    params.set("sf", String(cohort.scale_factor));
    params.set("phase", cohort.phase);
    appendFacetParams(params, facets, new Set(["benchmark", "scale_factor", "phase"]));
    const query = params.toString();
    return `/results/${cohort.benchmark}/${query ? `?${query}` : ""}`;
  }

  function buildPlatformHref(platformId: string): string {
    const params = new URLSearchParams();
    appendFacetParams(params, facets, new Set(["platform"]));
    const query = params.toString();
    return `/results/p/${platformId}/${query ? `?${query}` : ""}`;
  }

  return (
    <div>
      <section class="border-b border-[var(--bb-border-default)] bg-[var(--bb-bg-primary)] text-[var(--bb-fg-primary)]">
        <div class="mx-auto max-w-7xl px-4 py-7 sm:px-6 lg:px-8">
          <div class="max-w-4xl">
            <h1 class="text-3xl font-bold sm:text-4xl">BenchBox Database Leaderboards</h1>
            <p class="mt-3 max-w-3xl text-base text-[var(--bb-fg-muted)] sm:text-lg">
              Reproducible OLAP benchmark rankings by workload, scale, deployment, and normalized cost.
            </p>
          </div>

          {filteredMetaLeaderboard && (
            <ActiveLeaderboardSummary
              benchmark={summarizeSelection(benchmarkFilters, "All benchmarks", humanizeBenchmark)}
              scaleFactor={summarizeSelection(scaleFilters, "All scales", (value) => `SF ${value}`)}
              phase={phaseFilter === "all" ? "All phases" : phaseFilter}
              activeFacets={activeFacetSummaries}
            />
          )}
        </div>
      </section>

      <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {filteredMetaLeaderboard && (
          <MetaLeaderboard
            data={filteredMetaLeaderboard}
            mode={mode}
            onModeChange={(value) => setModeRaw(value)}
            cohortHref={buildCohortHref}
            platformHref={buildPlatformHref}
            resultMetadataById={resultById}
          />
        )}

        {filteredMetaLeaderboard && filteredMetaLeaderboard.cohorts.length === 0 && (
          <CoverageEmptyState
            activeFacets={activeFacetSummaries}
            canClearScale={scaleFilters.length > 0}
            canClearPlatform={facets.platform.length > 0}
            onClearScale={() => setFacet("scale_factor", [])}
            onClearPlatform={() => setFacet("platform", [])}
            onReset={resetFacets}
          />
        )}

        {filteredMetaLeaderboard && (
          <section
            aria-label="Leaderboard cohort selector"
            class="mb-8 rounded-lg border border-[var(--bb-border-default)] bg-[var(--bb-bg-panel)] p-3"
          >
            <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <MultiSelectFilter
                label="Benchmark"
                allLabel="All benchmarks"
                options={benchmarkOptions}
                current={benchmarkFilters}
                onSelect={(value) =>
                  setFacet(
                    "benchmark",
                    value === "all" ? [] : toggleFacetValue(benchmarkFilters, value),
                  )
                }
                format={(value) => humanizeBenchmark(value)}
              />
              <MultiSelectFilter
                label="Scale factor"
                allLabel="All scales"
                options={scaleOptions}
                current={scaleFilters}
                onSelect={(value) =>
                  setFacet(
                    "scale_factor",
                    value === "all" ? [] : toggleFacetValue(scaleFilters, value),
                  )
                }
                format={(value) => `SF ${value}`}
              />
              <SelectFilter
                label="Phase"
                options={["all", ...phaseOptions]}
                current={phaseFilter}
                onSelect={(value) => setFacet("phase", value === "all" ? [] : [value])}
                format={(value) => (value === "all" ? "All phases" : value)}
              />
              <CoverageSummary />
            </div>

            <details class="mt-3 border-t border-[var(--bb-border-default)] pt-3">
              <summary class="cursor-pointer text-sm font-medium text-[var(--bb-fg-muted)] hover:text-[var(--bb-fg-primary)]">
                Advanced filters
              </summary>
              <div class="mt-3 grid gap-3 md:grid-cols-3">
                <SingleFilterGroup
                  label="Tuning"
                  options={tuningOptions}
                  current={tuningFilter}
                  onSelect={(value) => setFacet("tuning_mode", value === "all" ? [] : [value])}
                  format={(value) => (value === "all" ? "All tuning" : value)}
                />
                <SingleFilterGroup
                  label="Trust"
                  options={trustOptions}
                  current={trustFilter}
                  onSelect={(value) => setFacet("trust_tier", value === "all" ? [] : [value])}
                  format={(value) => (value === "all" ? "All trust tiers" : value)}
                />
                <SingleFilterGroup
                  label="Date window"
                  options={["all", "30d", "90d", "365d"]}
                  current={dateWindow}
                  onSelect={(value) => setFacet("date_window", toDateWindowFacet(value))}
                  format={(value) => (value === "all" ? "All time" : `Last ${value}`)}
                />
              </div>
            </details>
          </section>
        )}

        {filteredMetaLeaderboard && <FlywheelStrip />}

        <section aria-label="Corpus summary" class="mb-12 grid grid-cols-2 gap-4 text-center lg:grid-cols-4">
          <StatCard
            value={SUPPORTED_BENCHMARK_COUNT}
            label="supported benchmarks"
            detail={`${benchmarks.length} with public results`}
          />
          <StatCard
            value={results.length}
            label="public result bundles"
            detail="maintainer-curated corpus"
          />
          <StatCard
            value={platformIds.length}
            label="platforms with public results"
            detail="published platform IDs"
          />
          <StatCard
            value="PR"
            label="PR-validated corpus"
            detail="bundles reviewed before publication"
          />
        </section>

        <section class="mb-12">
          <h2 class="mb-4 text-xl font-semibold text-[var(--bb-data-fg-primary)]">Recent Results</h2>
          <div class="overflow-hidden rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] shadow-sm">
            <table class="min-w-full divide-y divide-[var(--bb-data-border)]">
              <thead class="bg-[var(--bb-surface-data-muted)]">
                <tr>
                  <th class="table-th">Benchmark</th>
                  <th class="table-th">Platform</th>
                  <th class="table-th">Scale</th>
                  <th class="table-th">Date</th>
                  <th class="table-th">Power Score</th>
                  <th
                    class="table-th"
                    title="Geometric mean of per-query execution times (measurement runs only). Lower is faster."
                  >
                    Geomean (ms)
                  </th>
                  {showRecentCost && (
                    <th
                      class="table-th"
                      title="BenchBox normalized USD from emitted normalized_cost metadata. Local and unavailable rows are not comparable cloud cost."
                    >
                      Normalized cost
                    </th>
                  )}
                  <th class="table-th" />
                </tr>
              </thead>
              <tbody class="divide-y divide-[var(--bb-data-border)] bg-[var(--bb-surface-data)]">
                {recent.map((result) => (
                  <RecentRow key={result.result_id} entry={result} showCost={showRecentCost} />
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <div class="grid grid-cols-1 gap-8 sm:grid-cols-2">
          <BrowseSection
            title="Browse by Benchmark"
            items={benchmarks}
            hrefFn={(benchmark) => `/results/${benchmark}/`}
            labelFn={humanizeBenchmark}
          />
          <BrowseSection
            title="Browse by Platform"
            items={platformIds}
            hrefFn={(platformId) => `/results/p/${platformId}/`}
            labelFn={(platformId) => platformIdToName.get(platformId) ?? platformId}
          />
        </div>
      </div>
    </div>
  );
}

function HomeLoadingSkeleton() {
  return (
    <div>
      <section class="border-b border-[var(--bb-border-default)] bg-[var(--bb-bg-primary)] text-[var(--bb-fg-primary)]">
        <div class="mx-auto max-w-7xl px-4 py-7 sm:px-6 lg:px-8">
          <div class="max-w-4xl">
            <h1 class="text-3xl font-bold sm:text-4xl">BenchBox Database Leaderboards</h1>
            <p class="mt-3 max-w-3xl text-base text-[var(--bb-fg-muted)] sm:text-lg">
              Reproducible OLAP benchmark rankings by workload, scale, deployment, and normalized cost.
            </p>
          </div>

          <section
            aria-label="Leaderboard cohort selector"
            class="mt-5 rounded-lg border border-[var(--bb-border-default)] bg-[var(--bb-bg-panel)] p-3"
          >
            <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <SkeletonSelect label="Benchmark" />
              <SkeletonSelect label="Scale factor" />
              <SkeletonSelect label="Phase" />
              <CoverageSummary />
            </div>
          </section>
        </div>
      </section>

      <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <MetaLeaderboardSkeleton />
      </div>
    </div>
  );
}

function SkeletonSelect({ label }: { label: string }) {
  return (
    <div>
      <div class="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--bb-data-fg-muted)]">{label}</div>
      <SkeletonBlock className="h-9 w-full bb-skeleton-dark" />
    </div>
  );
}

interface ActiveFacetSummary {
  key: FacetKey;
  label: string;
  value: string;
}

const FACET_LABELS: Record<FacetKey, string> = {
  benchmark: "Benchmark",
  scale_factor: "Scale factor",
  phase: "Phase",
  platform: "Platform",
  execution_mode: "Execution",
  tuning_mode: "Tuning",
  trust_tier: "Trust",
  validation_status: "Validation",
  deployment_class: "Deployment",
  cloud_provider: "Cloud provider",
  cloud_region: "Cloud region",
  instance_or_warehouse: "Instance / warehouse",
  storage_format: "Storage format",
  cost_status: "Cost status",
  date_window: "Date window",
};

function ActiveLeaderboardSummary({
  benchmark,
  scaleFactor,
  phase,
  activeFacets,
}: {
  benchmark: string;
  scaleFactor: string;
  phase: string;
  activeFacets: ActiveFacetSummary[];
}) {
  const items = [
    { label: "Benchmark", value: benchmark },
    { label: "Scale", value: scaleFactor },
    { label: "Phase", value: phase },
  ];

  return (
    <section
      aria-label="Active leaderboard filters"
      class="mt-5 rounded-lg border border-[var(--bb-border-default)] bg-[var(--bb-bg-panel)] p-3"
    >
      <div class="grid gap-2 sm:grid-cols-3">
        {items.map((item) => (
          <div
            key={item.label}
            class="rounded-md border border-[var(--bb-border-subtle)] bg-[var(--bb-bg-primary)] px-3 py-2"
          >
            <div class="text-[11px] font-semibold uppercase tracking-wide text-[var(--bb-fg-muted)]">
              {item.label}
            </div>
            <div class="mt-1 text-sm font-medium text-[var(--bb-fg-primary)]">{item.value}</div>
          </div>
        ))}
      </div>
      {activeFacets.length > 0 && (
        <div aria-label="Active filter chips" class="mt-3 flex flex-wrap gap-2">
          {activeFacets.map((facet) => (
            <span
              key={facet.key}
              class="rounded-full bg-[var(--bb-bg-elevated)] px-3 py-1.5 text-xs font-medium text-[var(--bb-fg-muted)]"
            >
              {facet.label}: {facet.value}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

function CoverageEmptyState({
  activeFacets,
  canClearScale,
  canClearPlatform,
  onClearScale,
  onClearPlatform,
  onReset,
}: {
  activeFacets: ActiveFacetSummary[];
  canClearScale: boolean;
  canClearPlatform: boolean;
  onClearScale: () => void;
  onClearPlatform: () => void;
  onReset: () => void;
}) {
  return (
    <section
      aria-labelledby="coverage-empty-title"
      class="mb-12 rounded-lg border border-dashed border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] p-8 text-[var(--bb-data-fg-muted)]"
    >
      <div class="mx-auto max-w-3xl text-center">
        <h2 id="coverage-empty-title" class="text-lg font-semibold text-[var(--bb-data-fg-primary)]">
          No leaderboard cells match the current filters
        </h2>
        <p class="mt-2 text-sm text-[var(--bb-data-fg-muted)]">
          The current facet combination removed every published cohort cell.
        </p>
      </div>

      {activeFacets.length > 0 ? (
        <dl
          aria-label="Active filters removing leaderboard cells"
          class="mx-auto mt-5 grid max-w-3xl gap-2 sm:grid-cols-2 lg:grid-cols-3"
        >
          {activeFacets.map((facet) => (
            <div key={facet.key} class="rounded-md border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-3 py-2 text-left">
              <dt class="text-[11px] font-semibold uppercase tracking-wide text-[var(--bb-data-fg-subtle)]">{facet.label}</dt>
              <dd class="mt-1 text-sm font-medium text-[var(--bb-data-fg-primary)]">{facet.value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p class="mt-5 text-center text-sm text-[var(--bb-data-fg-muted)]">
          No active facets are applied; the public corpus has no leaderboard cohorts for this view.
        </p>
      )}

      <div class="mt-5 flex flex-wrap justify-center gap-2">
        <button
          type="button"
          class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-2 text-sm font-medium text-[var(--bb-data-fg-primary)] hover:bg-[var(--bb-surface-data-muted)] disabled:cursor-not-allowed disabled:opacity-50"
          onClick={onClearScale}
          disabled={!canClearScale}
        >
          Clear scale factor
        </button>
        <button
          type="button"
          class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-2 text-sm font-medium text-[var(--bb-data-fg-primary)] hover:bg-[var(--bb-surface-data-muted)] disabled:cursor-not-allowed disabled:opacity-50"
          onClick={onClearPlatform}
          disabled={!canClearPlatform}
        >
          Clear platform
        </button>
        <button
          type="button"
          class="rounded-md border border-brand-600 bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700"
          onClick={onReset}
        >
          Reset all
        </button>
      </div>
    </section>
  );
}

function summarizeSelection(
  values: string[],
  allLabel: string,
  format: (value: string) => string,
): string {
  if (values.length === 0) return allLabel;
  if (values.length === 1) return format(values[0] ?? "");
  return `${values.length} selected`;
}

function summarizeActiveFacets(
  facets: FacetState,
  platformIdToName: ReadonlyMap<string, string>,
): ActiveFacetSummary[] {
  const summaries: ActiveFacetSummary[] = [];
  for (const key of FACET_KEYS) {
    const value = facets[key];
    if (Array.isArray(value)) {
      if (value.length === 0) continue;
      summaries.push({
        key,
        label: FACET_LABELS[key],
        value: value.map((item) => formatFacetValue(key, item, platformIdToName)).join(", "),
      });
    } else if (value !== "all") {
      summaries.push({
        key,
        label: FACET_LABELS[key],
        value: formatFacetValue(key, value, platformIdToName),
      });
    }
  }
  return summaries;
}

function formatFacetValue(
  key: FacetKey,
  value: string,
  platformIdToName: ReadonlyMap<string, string>,
): string {
  if (key === "benchmark") return humanizeBenchmark(value);
  if (key === "platform") return platformIdToName.get(value) ?? value;
  return formatFacetDisplayValue(key, value);
}

function StatCard({
  value,
  label,
  detail,
}: {
  value: number | string;
  label: string;
  detail?: string;
}) {
  return (
    <div class="card">
      <div class="text-3xl font-bold text-brand-600">{value}</div>
      <div class="mt-1 text-sm font-medium text-[var(--bb-data-fg-muted)]">{label}</div>
      {detail && <div class="mt-2 text-xs text-[var(--bb-data-fg-subtle)]">{detail}</div>}
    </div>
  );
}

function MultiSelectFilter({
  label,
  allLabel,
  options,
  current,
  onSelect,
  format,
}: {
  label: string;
  allLabel: string;
  options: string[];
  current: string[];
  onSelect: (value: string) => void;
  format: (value: string) => string;
}) {
  if (options.length === 0) return null;
  const value = current.length === 0 ? "all" : current.length === 1 ? current[0] : "__multiple";

  return (
    <label class="block">
      <span class="mb-2 block text-xs font-semibold uppercase tracking-wide text-[var(--bb-data-fg-muted)]">{label}</span>
      <select
        class="h-9 w-full rounded-md border border-[var(--bb-border-default)] bg-[var(--bb-surface-data)] px-3 text-sm font-medium text-[var(--bb-data-fg-primary)]"
        value={value}
        onChange={(event) => onSelect((event.currentTarget as HTMLSelectElement).value)}
      >
        <option value="all">{allLabel}</option>
        {current.length > 1 && (
          <option value="__multiple" disabled>
            Multiple selected
          </option>
        )}
        {options.map((option) => (
          <option key={option} value={option}>
            {format(option)}
          </option>
        ))}
      </select>
    </label>
  );
}

function SelectFilter({
  label,
  options,
  current,
  onSelect,
  format,
}: {
  label: string;
  options: string[];
  current: string;
  onSelect: (value: string) => void;
  format: (value: string) => string;
}) {
  if (options.length === 0) return null;
  return (
    <label class="block">
      <span class="mb-2 block text-xs font-semibold uppercase tracking-wide text-[var(--bb-data-fg-muted)]">{label}</span>
      <select
        class="h-9 w-full rounded-md border border-[var(--bb-border-default)] bg-[var(--bb-surface-data)] px-3 text-sm font-medium text-[var(--bb-data-fg-primary)]"
        value={current}
        onChange={(event) => onSelect((event.currentTarget as HTMLSelectElement).value)}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {format(option)}
          </option>
        ))}
      </select>
    </label>
  );
}

function CoverageSummary() {
  return (
    <div>
      <div class="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--bb-data-fg-muted)]">Deployment / cost</div>
      <div class="flex flex-wrap gap-2">
        <span class="rounded-full bg-[var(--bb-surface-app)] px-3 py-1.5 text-xs font-medium text-[var(--bb-data-fg-muted)]">
          All public coverage
        </span>
      </div>
    </div>
  );
}

const FLYWHEEL_STEPS = [
  { label: "Run a benchmark", href: "/docs/usage/installation.html" },
  { label: "Compare your result", href: "/results/compare" },
  { label: "Submit a bundle", href: "/docs/contributing-results.html" },
];

function FlywheelStrip() {
  return (
    <section class="mb-12 border-y border-[var(--bb-data-border)] py-3">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p class="text-sm font-semibold text-[var(--bb-data-fg-primary)]">Run -&gt; Compare -&gt; Submit</p>
        <nav aria-label="Result contribution workflow" class="flex flex-wrap gap-2">
          {FLYWHEEL_STEPS.map((step, index) => (
            <a
              key={step.href}
              href={step.href}
              aria-label={step.label}
              class="inline-flex h-9 items-center gap-2 rounded-md border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-3 text-sm font-medium text-[var(--bb-data-fg-primary)] no-underline hover:border-brand-300 hover:bg-brand-50 hover:text-[var(--bb-accent-hover)]"
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

function SingleFilterGroup({
  label,
  options,
  current,
  onSelect,
  format,
}: {
  label: string;
  options: string[];
  current: string;
  onSelect: (value: string) => void;
  format: (value: string) => string;
}) {
  if (options.length === 0) return null;
  return (
    <div>
      <div class="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--bb-data-fg-muted)]">{label}</div>
      <div class="flex flex-wrap gap-2">
        {options.map((value) => {
          const active = current === value;
          return (
            <button
              key={value}
              class={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                active
                  ? "bg-[var(--bb-bg-primary)] text-white"
                  : "bg-[var(--bb-surface-app)] text-[var(--bb-data-fg-muted)] hover:bg-[var(--bb-data-border)]"
              }`}
              onClick={() => onSelect(value)}
              aria-pressed={active}
            >
              {format(value)}
            </button>
          );
        })}
      </div>
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
      <td class="table-td text-[var(--bb-data-fg-muted)]">{entry.run_date}</td>
      <td class="table-td font-mono">{fmtScore(entry.power_score)}</td>
      <td class="table-td font-mono">{fmtGeomean(entry.geomean_ms)}</td>
      {showCost && <td class="table-td font-mono text-[var(--bb-data-fg-muted)]">{normalizedCostLabel(entry)}</td>}
      <td class="table-td text-right">
        <a href={`/results/r/${entry.result_id}`} class="text-xs font-medium no-underline">
          View →
        </a>
      </td>
    </tr>
  );
}

interface BrowseSectionProps {
  title: string;
  items: string[];
  hrefFn: (item: string) => string;
  labelFn: (item: string) => string;
}

function BrowseSection({ title, items, hrefFn, labelFn }: BrowseSectionProps) {
  return (
    <section>
      <h2 class="mb-3 text-xl font-semibold text-[var(--bb-data-fg-primary)]">{title}</h2>
      <div class="flex flex-wrap gap-2">
        {items.map((item) => (
          <a
            key={item}
            href={hrefFn(item)}
            class="rounded-full border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-4 py-2 text-sm font-medium text-[var(--bb-data-fg-primary)] shadow-sm no-underline hover:border-brand-300 hover:bg-brand-50 hover:text-[var(--bb-accent-hover)] transition-colors"
          >
            {labelFn(item)}
          </a>
        ))}
      </div>
    </section>
  );
}
