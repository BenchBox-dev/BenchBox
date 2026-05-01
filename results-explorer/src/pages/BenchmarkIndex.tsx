import type { ComponentChildren } from "preact";
import { useEffect, useState } from "preact/hooks";
import type { RoutableProps } from "preact-router";
import type { BenchmarkSummary, SortDirection, SortState } from "@/types";
import type { ResultRow } from "@/lib/duckdbQueries";
import { getBenchmarkSummaryFromDuckDB, listResults } from "@/lib/duckdbQueries";
import { humanizeBenchmark, isKnownBenchmark, fmtScore, fmtGeomean, errMsg, complianceLabel } from "@/utils";
import { useUrlState, stringSerde } from "@/lib/useUrlState";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Breadcrumb } from "@/components/Breadcrumb";
import { TrustBadge } from "@/components/TrustBadge";
import { TuningBadge, tuningLabel } from "@/components/TuningBadge";
import { QueryHeatmap } from "@/components/QueryHeatmap";
import { RankTable } from "@/components/RankTable";
import { ChartPanel } from "@/components/ChartPanel";
import { NotFound } from "@/pages/NotFound";
import { useDocumentTitle } from "@/lib/useDocumentTitle";

interface BenchmarkIndexProps extends RoutableProps {
  benchmark?: string;
}

type ViewMode = "matrix" | "ranks" | "list";
type BenchmarkListSortKey = "platform" | "scale_factor" | "run_date" | "power_score" | "display_geomean_ms" | "query_count";

const TRUST_LABEL_ABBREV: Record<string, string> = {
  "maintainer-run": "Maintainer",
  "community-submission": "Community",
  "ci-verified": "CI",
  "local": "Local",
};

function trustAbbrev(label: string): string {
  return TRUST_LABEL_ABBREV[label] ?? label.split("-")[0] ?? label;
}

export function BenchmarkIndex({ benchmark = "" }: BenchmarkIndexProps) {
  const title = humanizeBenchmark(benchmark);
  const [results, setResults] = useState<ResultRow[] | null>(null);
  const [summary, setSummary] = useState<BenchmarkSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filter state - URL-synced so views are shareable.
  const [_sfRaw, setSfRaw] = useUrlState<string>("sf", "", stringSerde);
  const setScaleFilter = (v: string | null) => setSfRaw(v ?? "");
  const [phaseFilter, setPhaseFilter] = useUrlState<string>("phase", "power", stringSerde);
  const [tuningFilter, setTuningFilter] = useUrlState<string>("tuning", "all", stringSerde);
  // Trust filter: null = "all tiers shown". When set, contains the set of
  // trust_labels to include. Defaults to showing everything.
  const [trustFilter, setTrustFilter] = useState<Set<string> | null>(null);

  // View: matrix (default), ranks, or list
  const [viewMode, setViewMode] = useState<ViewMode>("matrix");

  // High contrast / reduced-color mode for the heatmap (explicit user toggle).
  // Also activates automatically via CSS prefers-contrast: more media query.
  const [highContrast, setHighContrast] = useState(false);

  // Row selection for Compare
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    listResults()
      .then((r) => {
        if (!cancelled) setResults(r);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errMsg(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Derive available scale factors and phases from the loaded rows.
  const benchmarkResults = results?.filter((r) => r.benchmark === benchmark) ?? [];
  const benchmarkNotFound = results !== null && benchmarkResults.length === 0 && !isKnownBenchmark(benchmark);
  useDocumentTitle(benchmarkNotFound ? "Not found · BenchBox Results" : `${title} · BenchBox Results`);

  const scaleFactors = [
    ...new Set(benchmarkResults.map((r) => String(r.scale_factor))),
  ].sort((a, b) => Number(a) - Number(b));

  const scaleFilter: string | null =
    _sfRaw !== "" && scaleFactors.includes(_sfRaw) ? _sfRaw : null;

  // Set defaults once manifest loads.
  const effectiveSf = scaleFilter ?? scaleFactors[0] ?? "0.01";

  useEffect(() => {
    if (!results || scaleFactors.length === 0 || _sfRaw === "" || _sfRaw === effectiveSf) return;
    setSfRaw(effectiveSf);
  }, [_sfRaw, effectiveSf, results, scaleFactors.length, setSfRaw]);

  // Phases available for the *current* scale factor only - prevents requesting
  // a phase+SF combination that has no artifact (e.g. "power" for SF 0.01
  // when only SF 0.1 has power runs).
  const phases = [
    ...new Set(
      benchmarkResults
        .filter((r) => String(r.scale_factor) === effectiveSf)
        .map((r) => r.test_type ?? "power")
        .filter(Boolean),
    ),
  ].sort();

  // If the stored phaseFilter isn't available for the current SF, fall back to
  // the first available phase so we never request a non-existent artifact.
  const effectivePhase = phases.includes(phaseFilter) ? phaseFilter : (phases[0] ?? phaseFilter);

  useEffect(() => {
    if (!results || phases.length === 0 || phaseFilter === effectivePhase) return;
    setPhaseFilter(effectivePhase);
  }, [effectivePhase, phaseFilter, phases.length, results, setPhaseFilter]);

  // Load the BenchmarkSummary from DuckDB whenever (sf, phase) changes.
  useEffect(() => {
    // Guard: don't request until phases have resolved for the current SF.
    // Without this guard, effectivePhase falls back to the stale phaseFilter
    // default ("power") even when only "standard" rows exist, triggering a
    // needless empty-cohort fetch.
    if (!results || phases.length === 0) return;
    let cancelled = false;
    setSummary(null);
    setSummaryError(null);
    setSummaryLoading(true);
    getBenchmarkSummaryFromDuckDB(benchmark, Number(effectiveSf), effectivePhase)
      .then((s) => {
        if (!cancelled) {
          setSummary(s);
          setSummaryLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setSummaryError(errMsg(err));
          setSummaryLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
    // `phaseFilter` is intentionally omitted: `effectivePhase` is derived from
    // it, so any phaseFilter change that produces a new effectivePhase
    // already triggers this effect. Including phaseFilter would cause a redundant
    // double-fetch when the user picks a phase that is available.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results, benchmark, effectiveSf, effectivePhase]);

  // Clear selection when the summary changes.
  useEffect(() => {
    setSelectedIds(new Set());
  }, [summary]);

  if (error) return <ErrorMessage message={error} />;
  if (!results) return <LoadingSpinner message="Loading results..." />;

  // preact-router's `:benchmark/` slug matches any single segment, so an
  // unknown slug like /results/does-not-exist/ would otherwise render an
  // empty BenchmarkIndex shell. Once results are loaded, distinguish:
  //   - Unknown slug (not in BENCHMARK_LABELS) → NotFound with a
  //     specific message so the user knows it's the slug that's wrong.
  //   - Known benchmark with no published rows yet → an "empty corpus"
  //     state that explains TPC-DS / ClickBench / etc. are supported
  //     but haven't been ingested yet.
  // Note: the summary-fetch useEffect above is incidentally safe for
  // both cases because its `phases.length === 0` early-return catches
  // them — `phases` is derived from `benchmarkResults` so it's always
  // [] when this guard fires. A future refactor that decouples them
  // would need to add an explicit early-return there.
  if (benchmarkResults.length === 0) {
    if (benchmarkNotFound) {
      return (
        <NotFound
          message={`Benchmark "${benchmark}" is not part of the published corpus.`}
        />
      );
    }
    return (
      <div class="mx-auto max-w-7xl px-4 py-24 text-center sm:px-6 lg:px-8">
        <Breadcrumb crumbs={[{ label: "Results", href: "/results/" }, { label: humanizeBenchmark(benchmark) }]} />
        <h1 class="mt-6 text-3xl font-bold text-gray-900">{humanizeBenchmark(benchmark)}</h1>
        <p class="mt-4 text-lg text-gray-600">
          No published results yet for {humanizeBenchmark(benchmark)}.
        </p>
        <p class="mt-2 text-sm text-gray-500">
          The benchmark is supported by BenchBox but no runs have been ingested into the public corpus.
        </p>
        <a href="/results/" class="mt-6 inline-block btn btn-primary no-underline">
          Back to Results
        </a>
      </div>
    );
  }

  // Collect unique trust labels and tuning modes from the loaded summary.
  const tuningModes = summary
    ? [...new Set(summary.platforms.map((p) => p.tuning_mode).filter((m): m is string => m !== null))].sort()
    : [];
  const trustLabels = summary
    ? [...new Set(summary.platforms.map((p) => p.trust_label))].sort()
    : [];

  // Apply client-side filters (tuning + trust) to the summary platforms.
  const filteredSummary: BenchmarkSummary | null = summary
    ? {
        ...summary,
        platforms: summary.platforms.filter((p) => {
          if (tuningFilter !== "all" && p.tuning_mode !== tuningFilter) return false;
          if (trustFilter !== null && !trustFilter.has(p.trust_label)) return false;
          return true;
        }),
      }
    : null;
  const historicalEntries = benchmarkResults.filter((result) => {
    if (String(result.scale_factor) !== effectiveSf) return false;
    if ((result.test_type ?? "power") !== effectivePhase) return false;
    if (tuningFilter !== "all" && result.tuning_mode !== tuningFilter) return false;
    if (trustFilter !== null && !trustFilter.has(result.trust_label)) return false;
    return true;
  });

  // Build the Compare URL from selected result_ids.
  const compareUrl =
    selectedIds.size >= 2
      ? `/results/compare?ids=${[...selectedIds].join(",")}`
      : null;

  return (
    <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <Breadcrumb
        crumbs={[
          { label: "Results", href: "/results/" },
          { label: title },
        ]}
      />

      <div class="mt-6 mb-6 flex flex-wrap items-center justify-between gap-4">
        <h1 class="text-3xl font-bold text-gray-900">{title} Results</h1>

        <div class="flex flex-wrap items-center gap-3">
          {/* Scale factor filter */}
          {scaleFactors.length > 1 && (
            <div class="flex items-center gap-2">
              <label class="text-sm font-medium text-gray-700" for="scale-filter">
                Scale:
              </label>
              <select
                id="scale-filter"
                class="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                value={effectiveSf}
                onChange={(e) => setScaleFilter((e.target as HTMLSelectElement).value)}
              >
                {scaleFactors.map((sf) => (
                  <option key={sf} value={sf}>
                    SF {sf}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Phase filter */}
          {phases.length > 1 && (
            <div class="flex items-center gap-2">
              <label class="text-sm font-medium text-gray-700" for="phase-filter">
                Phase:
              </label>
              <select
                id="phase-filter"
                class="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                value={effectivePhase}
                onChange={(e) => setPhaseFilter((e.target as HTMLSelectElement).value)}
              >
                {phases.map((ph) => (
                  <option key={ph} value={ph}>
                    {ph.charAt(0).toUpperCase() + ph.slice(1)}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Tuning filter */}
          {tuningModes.length > 1 && (
            <div class="flex items-center gap-2">
              <label class="text-sm font-medium text-gray-700" for="tuning-filter">
                Tuning:
              </label>
              <select
                id="tuning-filter"
                class="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                value={tuningFilter}
                onChange={(e) => setTuningFilter((e.target as HTMLSelectElement).value)}
              >
                <option value="all">All</option>
                {tuningModes.map((m) => (
                  <option key={m} value={m}>
                    {tuningLabel(m)}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Trust filter chips - default "all tiers shown"; shown only when >1 tier present */}
          {trustLabels.length > 1 && (
            <div class="flex items-center gap-2">
              <span class="text-sm font-medium text-gray-700">Trust:</span>
              <div class="flex flex-wrap gap-1">
                {trustLabels.map((tier) => {
                  const active = trustFilter === null || trustFilter.has(tier);
                  return (
                    <button
                      key={tier}
                      class={`rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors ${
                        active
                          ? "bg-gray-700 text-white"
                          : "bg-gray-100 text-gray-400 hover:bg-gray-200"
                      }`}
                      aria-pressed={active}
                      onClick={() => {
                        // Toggle this tier in/out of the active set.
                        const current = trustFilter ?? new Set(trustLabels);
                        const next = new Set(current);
                        if (next.has(tier)) {
                          next.delete(tier);
                          // Never allow empty selection - reset to "all"
                          setTrustFilter(next.size === 0 ? null : next);
                        } else {
                          next.add(tier);
                          // Full selection is equivalent to "all"
                          setTrustFilter(next.size === trustLabels.length ? null : next);
                        }
                      }}
                    >
                      {trustAbbrev(tier)}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* View toggle */}
          <div class="flex overflow-hidden rounded-md border border-gray-300 text-sm">
            <button
              class={`px-3 py-1.5 ${viewMode === "matrix" ? "bg-brand-600 text-white" : "bg-white text-gray-600 hover:bg-gray-50"}`}
              onClick={() => setViewMode("matrix")}
              aria-pressed={viewMode === "matrix"}
            >
              Matrix
            </button>
            <button
              class={`px-3 py-1.5 ${viewMode === "ranks" ? "bg-brand-600 text-white" : "bg-white text-gray-600 hover:bg-gray-50"}`}
              onClick={() => setViewMode("ranks")}
              aria-pressed={viewMode === "ranks"}
            >
              Ranks
            </button>
            <button
              class={`px-3 py-1.5 ${viewMode === "list" ? "bg-brand-600 text-white" : "bg-white text-gray-600 hover:bg-gray-50"}`}
              onClick={() => setViewMode("list")}
              aria-pressed={viewMode === "list"}
            >
              List
            </button>
          </div>

          {/* High contrast toggle - only meaningful in matrix (heatmap) view */}
          {viewMode === "matrix" && (
            <button
              class={`rounded-md border px-3 py-1.5 text-sm transition-colors ${
                highContrast
                  ? "border-gray-700 bg-gray-700 text-white"
                  : "border-gray-300 bg-white text-gray-600 hover:bg-gray-50"
              }`}
              onClick={() => setHighContrast((v) => !v)}
              aria-pressed={highContrast}
              title="Switch heatmap to grayscale for color-vision accessibility"
            >
              High contrast
            </button>
          )}
        </div>
      </div>

      {/* Matrix view */}
      {viewMode === "matrix" && (
        <>
          {summaryError ? (
            <div class="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              Could not load benchmark matrix: {summaryError}
            </div>
          ) : summaryLoading ? (
            <LoadingSpinner message="Loading matrix..." />
          ) : !filteredSummary ? (
            <div class="rounded-lg border border-dashed border-gray-300 bg-white p-10 text-center text-gray-400">
              <p class="font-medium">
                No benchmark data available for {humanizeBenchmark(benchmark)} SF{effectiveSf} phase {effectivePhase}.
              </p>
            </div>
          ) : (
            <QueryHeatmap
              summary={filteredSummary}
              selectedIds={selectedIds}
              onSelectionChange={setSelectedIds}
              highContrast={highContrast}
            />
          )}
        </>
      )}

      {/* Rank table view */}
      {viewMode === "ranks" && (
        <>
          {summaryError ? (
            <div class="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              Could not load rank data: {summaryError}
            </div>
          ) : summaryLoading ? (
            <LoadingSpinner message="Loading ranks..." />
          ) : !filteredSummary ? (
            <div class="rounded-lg border border-dashed border-gray-300 bg-white p-10 text-center text-gray-400">
              <p class="font-medium">
                No benchmark data available for {humanizeBenchmark(benchmark)} SF{effectiveSf} phase {effectivePhase}.
              </p>
            </div>
          ) : (
            <div class="card">
              <RankTable summary={filteredSummary} />
            </div>
          )}
        </>
      )}

      {/* List view (mobile-friendly fallback) */}
      {viewMode === "list" && (
        <ListTable benchmark={benchmark} results={results} scaleFactor={effectiveSf} tuningFilter={tuningFilter} trustFilter={trustFilter} />
      )}

      {filteredSummary && viewMode !== "list" && (
        <div class="mt-8">
          <ChartPanel
            context={{
              kind: "summary",
              summary: filteredSummary,
              historical: historicalEntries,
            }}
          />
        </div>
      )}

      {/* Sticky Compare bar */}
      {compareUrl && (
        <div class="fixed bottom-0 left-0 right-0 z-50 border-t border-gray-200 bg-white px-4 py-3 shadow-lg">
          <div class="mx-auto flex max-w-7xl items-center justify-between">
            <span class="text-sm text-gray-700">
              <strong>{selectedIds.size}</strong> platforms selected
            </span>
            <div class="flex items-center gap-3">
              <button
                class="text-sm text-gray-500 hover:text-gray-700"
                onClick={() => setSelectedIds(new Set())}
              >
                Clear
              </button>
              <a href={compareUrl} class="btn btn-primary text-sm no-underline">
                Compare {selectedIds.size} selected →
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// List view - sorted table of all result rows for the benchmark
// ---------------------------------------------------------------------------

function ListTable({
  benchmark,
  results,
  scaleFactor,
  tuningFilter,
  trustFilter,
}: {
  benchmark: string;
  results: ResultRow[];
  scaleFactor: string;
  tuningFilter: string;
  trustFilter: Set<string> | null;
}) {
  const [sort, setSort] = useState<SortState<BenchmarkListSortKey>>({
    key: "display_geomean_ms",
    direction: "asc",
  });
  const benchmarkResults = results.filter((r) => r.benchmark === benchmark);

  const byScale = benchmarkResults.filter((r) => String(r.scale_factor) === scaleFactor);

  const tuningFiltered =
    tuningFilter === "all" ? byScale : byScale.filter((r) => r.tuning_mode === tuningFilter);

  const trustFiltered =
    trustFilter === null ? tuningFiltered : tuningFiltered.filter((r) => trustFilter.has(r.trust_label));

  const filtered = [...trustFiltered].sort((a, b) => compareListRows(a, b, sort));

  function toggleSort(key: BenchmarkListSortKey) {
    setSort((prev) =>
      prev.key === key
        ? { key, direction: prev.direction === "asc" ? "desc" : "asc" }
        : { key, direction: "asc" },
    );
  }

  function ariaSort(key: BenchmarkListSortKey): "ascending" | "descending" | "none" {
    if (sort.key !== key) return "none";
    return sort.direction === "asc" ? "ascending" : "descending";
  }

  function sortArrow(key: BenchmarkListSortKey) {
    if (sort.key !== key) return " ↕";
    return sort.direction === "asc" ? " ↑" : " ↓";
  }

  function sortAnnouncement(key: BenchmarkListSortKey) {
    if (sort.key !== key) return null;
    return (
      <span class="sr-only">
        {sort.direction === "asc" ? "sorted ascending" : "sorted descending"}
      </span>
    );
  }

  if (filtered.length === 0) {
    return (
      <p class="text-gray-500">
        No results found for SF {scaleFactor}.
      </p>
    );
  }

  return (
    <div class="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
      <table class="min-w-full divide-y divide-gray-200">
        <thead class="bg-gray-50">
          <tr>
            <ListSortHeader
              label="Platform"
              sortKey="platform"
              ariaSort={ariaSort}
              sortArrow={sortArrow}
              sortAnnouncement={sortAnnouncement}
              onSort={toggleSort}
            />
            <ListSortHeader
              label="Scale"
              sortKey="scale_factor"
              ariaSort={ariaSort}
              sortArrow={sortArrow}
              sortAnnouncement={sortAnnouncement}
              onSort={toggleSort}
            />
            <ListSortHeader
              label="Date"
              sortKey="run_date"
              ariaSort={ariaSort}
              sortArrow={sortArrow}
              sortAnnouncement={sortAnnouncement}
              onSort={toggleSort}
            />
            <ListSortHeader
              label="Power Score"
              sortKey="power_score"
              ariaSort={ariaSort}
              sortArrow={sortArrow}
              sortAnnouncement={sortAnnouncement}
              onSort={toggleSort}
            />
            <th
              class="p-0"
              scope="col"
              aria-sort={ariaSort("display_geomean_ms")}
              title="Geometric mean of per-query median execution times (measurement runs only). Lower is faster."
            >
              <button
                type="button"
                class="table-th block w-full cursor-pointer select-none border-0 bg-transparent text-left"
                onClick={() => toggleSort("display_geomean_ms")}
              >
                Geomean (ms){sortArrow("display_geomean_ms")}
                {sortAnnouncement("display_geomean_ms")}
              </button>
            </th>
            <ListSortHeader
              label="Queries"
              sortKey="query_count"
              ariaSort={ariaSort}
              sortArrow={sortArrow}
              sortAnnouncement={sortAnnouncement}
              onSort={toggleSort}
            />
            <th class="table-th">Source</th>
            <th class="table-th" />
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100 bg-white">
          {filtered.map((r) => (
            <BenchmarkRow key={r.result_id} entry={r} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BenchmarkRow({ entry }: { entry: ResultRow }) {
  return (
    <tr class="hover:bg-gray-50" data-testid={entry.result_id}>
      <td class="table-td">
        <a href={`/results/p/${entry.platform_id}/`} class="font-medium no-underline">
          {entry.platform}
        </a>
        {entry.compliance_class && entry.compliance_class !== "official" && (
          <span class="ml-2 text-xs text-gray-400">{complianceLabel(entry.compliance_class)}</span>
        )}
        {entry.driver_version && (
          <span class="ml-2 text-xs text-gray-400">v{entry.driver_version}</span>
        )}
      </td>
      <td class="table-td">SF {entry.scale_factor}</td>
      <td class="table-td text-gray-500">{entry.run_date}</td>
      <td class="table-td font-mono">{fmtScore(entry.power_score)}</td>
      <td class="table-td font-mono">{fmtGeomean(entry.display_geomean_ms ?? entry.geomean_ms)}</td>
      <td class="table-td text-gray-500">{entry.query_count}</td>
      <td class="table-td">
        <div class="flex flex-wrap gap-1">
          <TrustBadge trustLabel={entry.trust_label} compact />
          {entry.tuning_mode && <TuningBadge tuningMode={entry.tuning_mode} />}
        </div>
      </td>
      <td class="table-td text-right">
        <a href={`/results/r/${entry.result_id}`} class="text-xs font-medium no-underline">
          View →
        </a>
      </td>
    </tr>
  );
}

function ListSortHeader({
  label,
  sortKey,
  ariaSort,
  sortArrow,
  sortAnnouncement,
  onSort,
}: {
  label: string;
  sortKey: BenchmarkListSortKey;
  ariaSort: (key: BenchmarkListSortKey) => "ascending" | "descending" | "none";
  sortArrow: (key: BenchmarkListSortKey) => string;
  sortAnnouncement: (key: BenchmarkListSortKey) => ComponentChildren;
  onSort: (key: BenchmarkListSortKey) => void;
}) {
  return (
    <th class="p-0" scope="col" aria-sort={ariaSort(sortKey)}>
      <button
        type="button"
        class="table-th block w-full cursor-pointer select-none border-0 bg-transparent text-left"
        onClick={() => onSort(sortKey)}
      >
        {label}{sortArrow(sortKey)}
        {sortAnnouncement(sortKey)}
      </button>
    </th>
  );
}

function compareListRows(a: ResultRow, b: ResultRow, sort: SortState<BenchmarkListSortKey>): number {
  if (sort.key === "platform") {
    return sort.direction === "asc"
      ? a.platform.localeCompare(b.platform)
      : b.platform.localeCompare(a.platform);
  }
  if (sort.key === "run_date") {
    if (a.run_date === b.run_date) return 0;
    const order = a.run_date < b.run_date ? -1 : 1;
    return sort.direction === "asc" ? order : -order;
  }
  if (sort.key === "display_geomean_ms") {
    return compareNullableNumber(
      a.display_geomean_ms ?? a.geomean_ms,
      b.display_geomean_ms ?? b.geomean_ms,
      sort.direction,
    );
  }
  return compareNullableNumber(a[sort.key], b[sort.key], sort.direction);
}

function compareNullableNumber(a: number | null, b: number | null, direction: SortDirection): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return direction === "asc" ? a - b : b - a;
}
