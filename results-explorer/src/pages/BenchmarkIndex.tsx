import type { ComponentChildren } from "preact";
import { useEffect, useMemo, useState } from "preact/hooks";
import type { RoutableProps } from "preact-router";
import type { BenchmarkSummary, PlatformRow, SortDirection, SortState } from "@/types";
import type { ResultRow } from "@/lib/duckdbQueries";
import { getBenchmarkSummaryFromDuckDB, listResults } from "@/lib/duckdbQueries";
import { humanizeBenchmark, isKnownBenchmark, fmtScore, fmtGeomean, errMsg, complianceLabel } from "@/utils";
import { facetsToWhereClause, useFacetState, type DateWindowFacet, type FacetState } from "@/lib/facetModel";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Breadcrumb } from "@/components/Breadcrumb";
import { TrustBadge, ValidationBadge } from "@/components/TrustBadge";
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
const TABLE_RENDER_LIMIT = 200;
const TABLE_RENDER_INCREMENT = 200;

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
  const { facets, setFacet } = useFacetState();
  const requestedSf = singleFacetValue(facets.scale_factor);
  const phaseFilter = singleFacetValue(facets.phase) ?? "power";
  const tuningFilter = singleFacetValue(facets.tuning_mode) ?? "all";
  const trustFilter = facets.trust_tier.length === 0 ? null : new Set(facets.trust_tier);
  const benchmarkResultWhere = useMemo(
    () =>
      facetsToWhereClause({
        ...facets,
        benchmark: benchmark ? [benchmark] : [],
        scale_factor: [],
        phase: [],
        tuning_mode: [],
        trust_tier: [],
      }),
    [
      benchmark,
      facets.cloud_provider,
      facets.cloud_region,
      facets.cost_status,
      facets.date_window,
      facets.deployment_class,
      facets.execution_mode,
      facets.instance_or_warehouse,
      facets.platform,
      facets.storage_format,
      facets.validation_status,
    ],
  );

  const setScaleFilter = (value: string | null) => setFacet("scale_factor", value ? [value] : []);
  const setPhaseFilter = (value: string) => setFacet("phase", value === "power" ? [] : [value]);
  const setTuningFilter = (value: string) => setFacet("tuning_mode", value === "all" ? [] : [value]);
  const setTrustFilter = (value: Set<string> | null) => setFacet("trust_tier", value ? [...value].sort() : []);

  // View: matrix (default), ranks, or list
  const [viewMode, setViewMode] = useState<ViewMode>("matrix");

  // High contrast / reduced-color mode for the heatmap (explicit user toggle).
  // Also activates automatically via CSS prefers-contrast: more media query.
  const [highContrast, setHighContrast] = useState(false);

  // Row selection for Compare
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    listResults(benchmarkResultWhere)
      .then((r) => {
        if (!cancelled) setResults(r);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errMsg(err));
      });
    return () => {
      cancelled = true;
    };
  }, [benchmarkResultWhere]);

  // Derive available scale factors and phases from the loaded rows.
  const benchmarkResults = results?.filter((r) => r.benchmark === benchmark) ?? [];
  const benchmarkNotFound = results !== null && benchmarkResults.length === 0 && !isKnownBenchmark(benchmark);
  useDocumentTitle(benchmarkNotFound ? "Not found · BenchBox Results" : `${title} · BenchBox Results`);

  const scaleFactors = [
    ...new Set(benchmarkResults.map((r) => String(r.scale_factor))),
  ].sort((a, b) => Number(a) - Number(b));

  const scaleFilter: string | null =
    requestedSf !== null && scaleFactors.includes(requestedSf) ? requestedSf : null;

  // Set defaults once manifest loads.
  const effectiveSf = scaleFilter ?? scaleFactors[0] ?? "0.01";

  useEffect(() => {
    if (!results || scaleFactors.length === 0 || requestedSf === null || requestedSf === effectiveSf) return;
    setScaleFilter(effectiveSf);
  }, [effectiveSf, requestedSf, results, scaleFactors.length]);

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
    setSelectedIds(new Set());
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
    if (hasActiveBenchmarkResultFacets(facets)) {
      return (
        <div class="mx-auto max-w-7xl px-4 py-24 text-center sm:px-6 lg:px-8">
          <Breadcrumb crumbs={[{ label: "Results", href: "/results/" }, { label: humanizeBenchmark(benchmark) }]} />
          <h1 class="mt-6 text-3xl font-bold text-gray-900">{humanizeBenchmark(benchmark)}</h1>
          <p class="mt-4 text-lg text-gray-600">
            No published results match the selected filters for {humanizeBenchmark(benchmark)}.
          </p>
          <a href={`/results/${benchmark}/`} class="mt-6 inline-block btn btn-primary no-underline">
            Clear filters
          </a>
        </div>
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

  const resultMetadataById = new Map(benchmarkResults.map((result) => [result.result_id, result]));
  const summaryWithResultMetadata: BenchmarkSummary | null = summary
    ? {
        ...summary,
        platforms: summary.platforms.map((platform) => {
          const metadata = resultMetadataById.get(platform.result_id);
          return {
            ...platform,
            platform_version: platform.platform_version ?? metadata?.platform_version ?? null,
            validation_status: platform.validation_status ?? metadata?.validation_status ?? null,
          };
        }),
      }
    : null;

  // Collect unique trust labels and tuning modes from the loaded summary.
  const tuningModes = summaryWithResultMetadata
    ? [...new Set(summaryWithResultMetadata.platforms.map((p) => p.tuning_mode).filter((m): m is string => m !== null))].sort()
    : [];
  const trustLabels = summaryWithResultMetadata
    ? [...new Set(summaryWithResultMetadata.platforms.map((p) => p.trust_label))].sort()
    : [];

  // Apply client-side filters (tuning + trust) to the summary platforms.
  const filteredSummary: BenchmarkSummary | null = summaryWithResultMetadata
    ? {
        ...summaryWithResultMetadata,
        platforms: summaryWithResultMetadata.platforms.filter((p) => {
          return matchesFacetFields(p, facets);
        }),
      }
    : null;
  const historicalEntries = benchmarkResults.filter((result) => {
    if (String(result.scale_factor) !== effectiveSf) return false;
    if ((result.test_type ?? "power") !== effectivePhase) return false;
    return matchesFacetFields(result, facets);
  });

  const selectedCompareRowsById = new Map(
    (summaryWithResultMetadata?.platforms ?? []).map((row) => [compareIdForBenchmarkRow(row), row]),
  );
  const selectedCompareRows = [...selectedIds]
    .map((id) => selectedCompareRowsById.get(id))
    .filter((row): row is PlatformRow => row !== undefined);

  // Build the Compare URL from selected compact IDs when available.
  const compareUrl =
    selectedIds.size >= 2
      ? buildCompareUrl([...selectedIds])
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
        <ListTable benchmark={benchmark} results={results} scaleFactor={effectiveSf} facets={facets} />
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
          <div class="mx-auto flex max-w-7xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div class="min-w-0 flex-1">
              <div class="text-sm text-gray-700">
                <strong>{selectedIds.size}</strong> platforms selected for compare
              </div>
              <div
                class="mt-2 flex max-h-32 flex-wrap gap-2 overflow-y-auto pr-1"
                role="list"
                aria-label="Selected compare results"
              >
                {selectedCompareRows.map((row) => {
                  const id = compareIdForBenchmarkRow(row);
                  const cohortBenchmark = summaryWithResultMetadata?.benchmark ?? benchmark;
                  const cohortScale = summaryWithResultMetadata?.scale_factor ?? effectiveSf;
                  const cohortPhase = summaryWithResultMetadata?.phase ?? effectivePhase;
                  return (
                    <div
                      key={id}
                      data-testid={`compare-tray-row-${id}`}
                      role="listitem"
                      class="flex max-w-full flex-wrap items-center gap-1.5 rounded-md border border-gray-200 bg-gray-50 px-2 py-1 text-xs text-gray-600"
                    >
                      <span class="font-medium text-gray-900">{row.platform}</span>
                      <span>{humanizeBenchmark(cohortBenchmark)}</span>
                      <span>SF {cohortScale}</span>
                      <span>{cohortPhase}</span>
                      <span>{row.run_date}</span>
                      <TrustBadge trustLabel={row.trust_label} compact />
                      <span class="font-mono text-gray-500">ID {displayCompareId(id)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
            <div class="flex shrink-0 items-center gap-3">
              <button
                type="button"
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
// Shared facet helpers for benchmark-scoped row and platform filtering.
// ---------------------------------------------------------------------------

function singleFacetValue(values: string[]): string | null {
  return values.length === 1 ? (values[0] ?? null) : null;
}

function hasActiveBenchmarkResultFacets(facets: FacetState): boolean {
  return (
    facets.platform.length > 0 ||
    facets.execution_mode.length > 0 ||
    facets.validation_status.length > 0 ||
    facets.deployment_class.length > 0 ||
    facets.cloud_provider.length > 0 ||
    facets.cloud_region.length > 0 ||
    facets.instance_or_warehouse.length > 0 ||
    facets.storage_format.length > 0 ||
    facets.cost_status.length > 0 ||
    facets.date_window !== "all"
  );
}

function matchesFacetFields(row: ResultRow | PlatformRow, facets: FacetState): boolean {
  if (!matchesPlatformFacet(row, facets.platform)) return false;
  if (!matchesOptionalFilter(row.execution_mode, facets.execution_mode)) return false;
  if (!matchesTuningFacet(row, facets.tuning_mode)) return false;
  if (!matchesMultiFilter(row.trust_label, facets.trust_tier)) return false;
  if (!matchesOptionalFilter(row.validation_status, facets.validation_status)) return false;
  if (!matchesDeploymentFacet(row, facets.deployment_class)) return false;
  if (!matchesOptionalFilter(row.cloud_provider, facets.cloud_provider)) return false;
  if (!matchesOptionalFilter(row.cloud_region, facets.cloud_region)) return false;
  if (!matchesOptionalFilter(rowShape(row), facets.instance_or_warehouse)) return false;
  if (!matchesOptionalFilter(row.storage_format, facets.storage_format)) return false;
  if (!matchesOptionalFilter(row.cost_status, facets.cost_status)) return false;
  return matchesDateWindow(row.run_date, facets.date_window);
}

function matchesMultiFilter(value: string, selected: string[]): boolean {
  return selected.length === 0 || selected.includes(value);
}

function matchesOptionalFilter(value: string | null | undefined, selected: string[]): boolean {
  return selected.length === 0 || (value !== null && value !== undefined && selected.includes(value));
}

function matchesPlatformFacet(row: ResultRow | PlatformRow, selected: string[]): boolean {
  return selected.length === 0 || selected.includes(row.platform) || selected.includes(row.platform_id);
}

function matchesTuningFacet(row: ResultRow | PlatformRow, selected: string[]): boolean {
  return selected.length === 0 || selected.includes(row.tuning_mode ?? "untuned");
}

function matchesDeploymentFacet(row: ResultRow | PlatformRow, selected: string[]): boolean {
  if (selected.length === 0) return true;
  const deployment = rowDeploymentClass(row);
  return deployment !== null && selected.includes(deployment);
}

function rowDeploymentClass(row: ResultRow | PlatformRow): string | null {
  return row.deployment_class ?? null;
}

function rowShape(row: ResultRow | PlatformRow): string | null {
  return row.instance_or_warehouse ?? null;
}

function compareIdForBenchmarkRow(row: PlatformRow): string {
  return row.short_id || row.result_id;
}

function buildCompareUrl(ids: string[]): string {
  return `/results/compare?ids=${ids.map(encodeURIComponent).join(",")}`;
}

function displayCompareId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}...` : id;
}

function matchesDateWindow(runDate: string, windowValue: DateWindowFacet): boolean {
  if (windowValue === "all") return true;
  const days = Number(windowValue.replace("d", ""));
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  return new Date(runDate).getTime() >= cutoff;
}

// ---------------------------------------------------------------------------
// List view - sorted table of all result rows for the benchmark
// ---------------------------------------------------------------------------

function ListTable({
  benchmark,
  results,
  scaleFactor,
  facets,
}: {
  benchmark: string;
  results: ResultRow[];
  scaleFactor: string;
  facets: FacetState;
}) {
  const [sort, setSort] = useState<SortState<BenchmarkListSortKey>>({
    key: "display_geomean_ms",
    direction: "asc",
  });
  const [visibleLimit, setVisibleLimit] = useState(TABLE_RENDER_LIMIT);
  const benchmarkResults = results.filter((r) => r.benchmark === benchmark);

  const byScale = benchmarkResults.filter((r) => String(r.scale_factor) === scaleFactor);

  const filtered = byScale
    .filter((row) => matchesFacetFields(row, facets))
    .sort((a, b) => compareListRows(a, b, sort));
  const visibleRows = filtered.slice(0, visibleLimit);

  useEffect(() => {
    setVisibleLimit(TABLE_RENDER_LIMIT);
  }, [
    benchmark,
    scaleFactor,
    facets.platform,
    facets.execution_mode,
    facets.tuning_mode,
    facets.trust_tier,
    facets.validation_status,
    facets.deployment_class,
    facets.cloud_provider,
    facets.cloud_region,
    facets.instance_or_warehouse,
    facets.storage_format,
    facets.cost_status,
    facets.date_window,
    sort.key,
    sort.direction,
  ]);

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
      <div class="border-b border-gray-200 bg-white px-4 py-3 text-sm text-gray-500">
        Showing {visibleRows.length.toLocaleString()} of {filtered.length.toLocaleString()} results for SF {scaleFactor}
      </div>
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
          {visibleRows.map((r) => (
            <BenchmarkRow key={r.result_id} entry={r} />
          ))}
        </tbody>
      </table>
      {visibleRows.length < filtered.length && (
        <div class="border-t border-gray-200 bg-gray-50 px-4 py-3 text-center">
          <button
            type="button"
            class="btn btn-secondary"
            onClick={() => setVisibleLimit((limit) => limit + TABLE_RENDER_INCREMENT)}
          >
            Show more results
          </button>
        </div>
      )}
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
          <ValidationBadge validationStatus={entry.validation_status} showMissing />
          {entry.tuning_mode && <TuningBadge tuningMode={entry.tuning_mode} />}
        </div>
      </td>
      <td class="table-td text-right">
        <a href={`/results/r/${entry.result_id}#run-receipt`} class="text-xs font-medium no-underline">
          Receipt →
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
