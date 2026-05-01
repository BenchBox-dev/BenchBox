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
import { humanizeBenchmark, fmtScore, fmtGeomean, errMsg } from "@/utils";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { ErrorMessage } from "@/components/ErrorMessage";
import { MetaLeaderboard } from "@/components/MetaLeaderboard";
import type { MetaLeaderboardMode } from "@/components/MetaLeaderboard";
import { arraySerde, stringSerde, useUrlState } from "@/lib/useUrlState";
import { useDocumentTitle } from "@/lib/useDocumentTitle";

const EMPTY_STRING_ARRAY: string[] = [];

export function Home(_: RoutableProps) {
  useDocumentTitle("Results · BenchBox");
  const [results, setResults] = useState<ResultRow[] | null>(null);
  const [metaLeaderboard, setMetaLeaderboard] = useState<MetaLeaderboardData | null>(null);
  const [metaLeaderboardLoaded, setMetaLeaderboardLoaded] = useState(false);
  const retriedEmptyResults = useRef(false);
  const [emptyResultsRetryFinished, setEmptyResultsRetryFinished] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [benchmarkFilters, setBenchmarkFilters] = useUrlState<string[]>("bm", EMPTY_STRING_ARRAY, arraySerde);
  const [scaleFilters, setScaleFilters] = useUrlState<string[]>("sf", EMPTY_STRING_ARRAY, arraySerde);
  const [phaseFilter, setPhaseFilter] = useUrlState<string>("phase", "all", stringSerde);
  const [tuningFilter, setTuningFilter] = useUrlState<string>("tuning", "all", stringSerde);
  const [trustFilter, setTrustFilter] = useUrlState<string>("trust", "all", stringSerde);
  const [dateWindow, setDateWindow] = useUrlState<string>("window", "all", stringSerde);
  const [modeRaw, setModeRaw] = useUrlState<string>("mode", "times", stringSerde);

  useEffect(() => {
    let cancelled = false;
    listResults()
      .then((rows) => {
        if (!cancelled) setResults(rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errMsg(err));
      });
    getMetaLeaderboardData()
      .then((data) => {
        if (!cancelled) {
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

  // Cold-load mitigation (N5 in pass-2 review): listResults() can briefly
  // resolve to [] on a cold DuckDB-WASM attach while the meta-leaderboard
  // succeeds, which would otherwise paint "0 Results / 0 Benchmarks /
  // 0 Platforms" before the real corpus arrives. Retrying once is a
  // symptom-mitigation, not a root-cause fix; we have not pinned which of
  // (a) WASM cold-cache partial read, (b) Preact effect-cleanup race, or
  // (c) shared initPromise in db.ts is the trigger. The diagnostic log
  // makes future investigation possible by surfacing the exact mismatch
  // in browser DevTools without needing to re-run the audit setup.
  const hasInconsistentEmptySnapshot = results !== null && results.length === 0 && metaLeaderboard !== null;
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
    listResults()
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
  }, [hasInconsistentEmptySnapshot]);

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
      if (!matchesMultiFilter(cohort.benchmark, benchmarkFilters)) return false;
      if (!matchesMultiFilter(String(cohort.scale_factor), scaleFilters)) return false;
      if (phaseFilter !== "all" && cohort.phase !== phaseFilter) return false;

      return (cohort.platforms ?? []).some((row) => {
        const result = resultById.get(row.result_id);
        return result !== undefined && matchesEntryFilters(result, tuningFilter, trustFilter, dateWindow);
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
            return result !== undefined && matchesEntryFilters(result, tuningFilter, trustFilter, dateWindow);
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
    dateWindow,
    metaLeaderboard,
    phaseFilter,
    resultById,
    scaleFilters,
    trustFilter,
    tuningFilter,
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
    return <LoadingSpinner message="Loading results..." />;
  }

  const mode: MetaLeaderboardMode =
    modeRaw === "ranks" || modeRaw === "speedup" ? modeRaw : "times";
  const benchmarks = [...new Set(results.map((result) => result.benchmark))].sort();
  const platformIdToName = new Map(results.map((result) => [result.platform_id, result.platform]));
  const platformIds = [...new Set(results.map((result) => result.platform_id))].sort();
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
    if (tuningFilter !== "all") params.set("tuning", tuningFilter);
    if (trustFilter !== "all") params.set("trust", trustFilter);
    if (dateWindow !== "all") params.set("window", dateWindow);
    const query = params.toString();
    return `/results/${cohort.benchmark}/${query ? `?${query}` : ""}`;
  }

  function buildPlatformHref(platformId: string): string {
    const params = new URLSearchParams();
    if (tuningFilter !== "all") params.set("tuning", tuningFilter);
    if (trustFilter !== "all") params.set("trust", trustFilter);
    if (dateWindow !== "all") params.set("window", dateWindow);
    const query = params.toString();
    return `/results/p/${platformId}/${query ? `?${query}` : ""}`;
  }

  return (
    <div class="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
      <div class="mb-12 text-center">
        <h1 class="mb-4 text-4xl font-bold tracking-tight text-gray-900 sm:text-5xl">
          BenchBox Results
        </h1>
        <p class="mx-auto max-w-2xl text-lg text-gray-600">
          Browse, compare, and analyze public benchmark results across SQL engines and
          DataFrame libraries. The current public corpus is maintainer-curated, and new
          submissions go through PR validation plus maintainer review before they appear here.
          Every result remains reproducible with{" "}
          <code class="rounded bg-gray-100 px-1.5 py-0.5 text-sm font-mono">
            benchbox run
          </code>
          .
        </p>
      </div>

      <div class="mb-12 grid grid-cols-3 gap-6 text-center">
        <StatCard value={results.length} label="Results" />
        <StatCard value={benchmarks.length} label="Benchmarks" />
        <StatCard value={platformIds.length} label="Platforms" />
      </div>

      <section class="mb-12 rounded-xl border border-brand-200 bg-brand-50 p-6 shadow-sm">
        <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 class="text-xl font-semibold text-gray-900">
              Run BenchBox on your platform and submit your results
            </h2>
            <p class="mt-2 max-w-2xl text-sm text-gray-600">
              The Phase 2 workflow is simple: run a benchmark, package it with{" "}
              <code class="rounded bg-white px-1 py-0.5 text-xs">benchbox submit</code>, then
              open a PR against the public corpus.
            </p>
          </div>
          <a href="/docs/contributing-results.html" class="btn-primary text-sm text-center">
            Submit a Result
          </a>
        </div>
      </section>

      {filteredMetaLeaderboard && (
        <>
          <section class="sticky top-0 z-20 mb-6 rounded-xl border border-gray-200 bg-white/95 p-4 shadow-sm backdrop-blur">
            <div class="grid gap-4 lg:grid-cols-2">
              <FilterGroup
                label="Benchmark"
                options={benchmarkOptions}
                current={benchmarkFilters}
                onToggle={(value) => toggleMultiValue(value, benchmarkFilters, setBenchmarkFilters, benchmarkOptions)}
                format={(value) => humanizeBenchmark(value)}
              />
              <FilterGroup
                label="Scale"
                options={scaleOptions}
                current={scaleFilters}
                onToggle={(value) => toggleMultiValue(value, scaleFilters, setScaleFilters, scaleOptions)}
                format={(value) => `SF ${value}`}
              />
              <SingleFilterGroup
                label="Phase"
                options={["all", ...phaseOptions]}
                current={phaseFilter}
                onSelect={setPhaseFilter}
                format={(value) => (value === "all" ? "All phases" : value)}
              />
              <SingleFilterGroup
                label="Tuning"
                options={tuningOptions}
                current={tuningFilter}
                onSelect={setTuningFilter}
                format={(value) => (value === "all" ? "All tuning" : value)}
              />
              <SingleFilterGroup
                label="Trust"
                options={trustOptions}
                current={trustFilter}
                onSelect={setTrustFilter}
                format={(value) => (value === "all" ? "All trust tiers" : value)}
              />
              <SingleFilterGroup
                label="Date window"
                options={["all", "30d", "90d", "365d"]}
                current={dateWindow}
                onSelect={setDateWindow}
                format={(value) => (value === "all" ? "All time" : `Last ${value}`)}
              />
            </div>
          </section>

          <MetaLeaderboard
            data={filteredMetaLeaderboard}
            mode={mode}
            onModeChange={(value) => setModeRaw(value)}
            cohortHref={buildCohortHref}
            platformHref={buildPlatformHref}
            resultMetadataById={resultById}
          />
        </>
      )}

      {filteredMetaLeaderboard && filteredMetaLeaderboard.cohorts.length === 0 && (
        <section class="mb-12 rounded-lg border border-dashed border-gray-300 bg-white p-10 text-center text-gray-400">
          No leaderboard cells match the current filters.
        </section>
      )}

      <section class="mb-12">
        <h2 class="mb-4 text-xl font-semibold text-gray-900">Recent Results</h2>
        <div class="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
          <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
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
            <tbody class="divide-y divide-gray-100 bg-white">
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
  );
}

function matchesEntryFilters(
  entry: ResultRow,
  tuningFilter: string,
  trustFilter: string,
  dateWindow: string,
): boolean {
  if (tuningFilter !== "all" && (entry.tuning_mode ?? "untuned") !== tuningFilter) return false;
  if (trustFilter !== "all" && entry.trust_label !== trustFilter) return false;
  return matchesDateWindow(entry.run_date, dateWindow);
}

function matchesDateWindow(runDate: string, windowValue: string): boolean {
  if (windowValue === "all") return true;
  const days = Number(windowValue.replace("d", ""));
  if (Number.isNaN(days)) return true;
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  return new Date(runDate).getTime() >= cutoff;
}

function matchesMultiFilter(value: string, selected: string[]): boolean {
  return selected.length === 0 || selected.includes(value);
}

function normalizedCostValue(entry: ResultRow): number | null {
  if (entry.cost_status !== "normalized") return null;
  if (entry.normalized_cost_usd === null || entry.normalized_cost_usd === undefined) return null;
  return Number.isFinite(entry.normalized_cost_usd) ? entry.normalized_cost_usd : null;
}

function normalizedCostLabel(entry: ResultRow): string {
  const value = normalizedCostValue(entry);
  if (value !== null) return `$${value.toFixed(2)}`;
  if (entry.cost_status === "not_applicable_local") return "local";
  if (entry.cost_status === "unavailable") return "unavailable";
  return "-";
}

function toggleMultiValue(
  value: string,
  current: string[],
  setCurrent: (values: string[]) => void,
  allValues: string[],
) {
  if (current.length === 0) {
    setCurrent([value]);
    return;
  }

  const base = new Set(current);
  if (base.has(value)) {
    base.delete(value);
  } else {
    base.add(value);
  }

  if (base.size === 0 || base.size === allValues.length) {
    setCurrent([]);
    return;
  }

  setCurrent(allValues.filter((candidate) => base.has(candidate)));
}

function StatCard({ value, label }: { value: number; label: string }) {
  return (
    <div class="card">
      <div class="text-3xl font-bold text-brand-600">{value}</div>
      <div class="mt-1 text-sm font-medium text-gray-500">{label}</div>
    </div>
  );
}

function FilterGroup({
  label,
  options,
  current,
  onToggle,
  format,
}: {
  label: string;
  options: string[];
  current: string[];
  onToggle: (value: string) => void;
  format: (value: string) => string;
}) {
  if (options.length === 0) return null;
  return (
    <div>
      <div class="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</div>
      <div class="flex flex-wrap gap-2">
        {options.map((value) => {
          const active = current.length === 0 || current.includes(value);
          return (
            <button
              key={value}
              class={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                active
                  ? "bg-brand-600 text-white"
                  : "bg-gray-100 text-gray-500 hover:bg-gray-200"
              }`}
              onClick={() => onToggle(value)}
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
      <div class="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</div>
      <div class="flex flex-wrap gap-2">
        {options.map((value) => {
          const active = current === value;
          return (
            <button
              key={value}
              class={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                active
                  ? "bg-gray-900 text-white"
                  : "bg-gray-100 text-gray-500 hover:bg-gray-200"
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
    <tr class="hover:bg-gray-50">
      <td class="table-td font-medium">{humanizeBenchmark(entry.benchmark)}</td>
      <td class="table-td">
        <span class="badge badge-blue">{entry.platform}</span>
      </td>
      <td class="table-td">SF {entry.scale_factor}</td>
      <td class="table-td text-gray-500">{entry.run_date}</td>
      <td class="table-td font-mono">{fmtScore(entry.power_score)}</td>
      <td class="table-td font-mono">{fmtGeomean(entry.geomean_ms)}</td>
      {showCost && <td class="table-td font-mono text-gray-500">{normalizedCostLabel(entry)}</td>}
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
      <h2 class="mb-3 text-xl font-semibold text-gray-900">{title}</h2>
      <div class="flex flex-wrap gap-2">
        {items.map((item) => (
          <a
            key={item}
            href={hrefFn(item)}
            class="rounded-full border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm no-underline hover:border-brand-300 hover:bg-brand-50 hover:text-brand-700 transition-colors"
          >
            {labelFn(item)}
          </a>
        ))}
      </div>
    </section>
  );
}
