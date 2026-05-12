import type { ComponentChildren } from "preact";
import { useEffect, useMemo, useState } from "preact/hooks";
import type { RoutableProps } from "preact-router";
import { route } from "preact-router";
import type { BenchmarkSummary, PlatformRow, SortDirection, SortState } from "@/types";
import type { ResultRow } from "@/lib/duckdbQueries";
import { getBenchmarkSummaryFromDuckDB, listResults } from "@/lib/duckdbQueries";
import { BENCHMARK_LABELS, humanizeBenchmark, isKnownBenchmark, fmtScore, fmtGeomean, errMsg, complianceLabel } from "@/utils";
import { facetsToWhereClause, useFacetState, type FacetKey, type FacetState } from "@/lib/facetModel";
import { hasActiveFacets, matchesFacetRow, singleFacetValue } from "@/lib/facetMatching";
import { buildCompareUrl, compareIdForRow, displayCompareId } from "@/lib/resultLinks";
import { stringSerde, useUrlState } from "@/lib/useUrlState";
import {
  formatCohortExclusion,
  formatTimingExclusion,
  isComparable,
  isTimingDisplayable,
} from "@/lib/displayEligibility";
import { summarizeCompareExclusionReasons } from "@/lib/compareExclusionReasons";
import { BenchmarkMatrixSkeleton } from "@/components/LoadingSpinner";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Breadcrumb } from "@/components/Breadcrumb";
import { TrustBadge, ValidationBadge } from "@/components/TrustBadge";
import { TuningBadge, tuningLabel } from "@/components/TuningBadge";
import { QueryHeatmap } from "@/components/QueryHeatmap";
import { RankTable } from "@/components/RankTable";
import { ChartPanel } from "@/components/ChartPanel";
import { SegmentedControl } from "@/components/SegmentedControl";
import { NotFound } from "@/pages/NotFound";
import { useDocumentTitle } from "@/lib/useDocumentTitle";

interface BenchmarkIndexProps extends RoutableProps {
  benchmark?: string;
}

type ViewMode = "matrix" | "ranks" | "list";
type BenchmarkListSortKey = "platform" | "scale_factor" | "run_date" | "power_score" | "display_geomean_ms" | "query_count";
const VIEW_MODES = new Set<ViewMode>(["matrix", "ranks", "list"]);
function coerceViewMode(value: string): ViewMode {
  return VIEW_MODES.has(value as ViewMode) ? (value as ViewMode) : "matrix";
}
const TABLE_RENDER_LIMIT = 200;
const TABLE_RENDER_INCREMENT = 200;
const BENCHMARK_RESULT_FACET_KEYS: FacetKey[] = [
  "platform",
  "execution_mode",
  "validation_status",
  "deployment_class",
  "cloud_provider",
  "cloud_region",
  "instance_or_warehouse",
  "storage_format",
  "cost_status",
  "date_window",
];
const BENCHMARK_ROW_FACET_KEYS: FacetKey[] = [
  "platform",
  "execution_mode",
  "tuning_mode",
  "trust_tier",
  "validation_status",
  "deployment_class",
  "cloud_provider",
  "cloud_region",
  "instance_or_warehouse",
  "storage_format",
  "cost_status",
  "date_window",
];

const TRUST_LABEL_ABBREV: Record<string, string> = {
  "maintainer-run": "Maintainer",
  "community-submission": "Community",
  "ci-verified": "CI",
  "local": "Local",
};

function trustAbbrev(label: string): string {
  return TRUST_LABEL_ABBREV[label] ?? label.split("-")[0] ?? label;
}

function benchmarkContextNote(benchmark: string): string | null {
  if (benchmark === "star_schema" || benchmark === "ssb") {
    return "Star Schema Benchmark (SSB): the route keeps the canonical star_schema slug while the published benchmark label uses SSB.";
  }
  return null;
}

/**
 * Distinct benchmark slugs paired with display labels for the in-page
 * sibling switcher. Two slugs sometimes share a display label
 * (`star_schema` and `ssb` both render "SSB"; `tsbs-devops` and
 * `tsbs_devops` both render "TSBS DevOps") because legacy and
 * canonical routes coexist. We keep the first slug encountered so the
 * switcher lists each benchmark family exactly once and the canonical
 * route wins (BENCHMARK_LABELS is declared with the canonical slug
 * first).
 */
function uniqueBenchmarkOptions(): { value: string; label: string }[] {
  const seen = new Set<string>();
  const options: { value: string; label: string }[] = [];
  for (const [value, label] of Object.entries(BENCHMARK_LABELS)) {
    if (seen.has(label)) continue;
    seen.add(label);
    options.push({ value, label });
  }
  return options.sort((a, b) => a.label.localeCompare(b.label));
}

function benchmarkCompareGuidanceMessage(
  selectedCount: number,
  title: string,
  scaleFactor: string,
  phase: string,
): string {
  const cohort = `${title} SF ${scaleFactor} ${phase}`;
  if (selectedCount === 0) {
    return `Select two or more platforms from the same ${cohort} cohort to compare. Benchmark, scale, phase, metric, and unit stay fixed on this page.`;
  }
  if (selectedCount === 1) {
    return `1 result selected in ${cohort}. Select one more result from this cohort to enable Compare.`;
  }
  return `${selectedCount} results selected in ${cohort}. The sticky tray opens Compare with the same benchmark, scale, and phase contract.`;
}

function isResultTimingDisplayable(row: ResultRow): boolean {
  return row.display_exclusion_reason === null;
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
  const phaseFilter = singleFacetValue(facets.phase, "power") ?? "power";
  const tuningFilter = singleFacetValue(facets.tuning_mode, "all") ?? "all";
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

  // View: matrix (default), ranks, or list. URL-synced so matrix/list/ranks
  // screenshots and shared links preserve the same browse state.
  const [viewModeRaw, setViewModeRaw] = useUrlState<string>("view", "matrix", stringSerde);
  const viewMode = coerceViewMode(viewModeRaw);
  const setViewMode = (value: ViewMode) => setViewModeRaw(value);

  useEffect(() => {
    if (viewModeRaw !== viewMode) setViewModeRaw(viewMode);
  }, [setViewModeRaw, viewMode, viewModeRaw]);

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
  if (!results) {
    return (
      <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <BenchmarkMatrixSkeleton message="Loading results..." />
      </div>
    );
  }

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
    if (hasActiveFacets(facets, BENCHMARK_RESULT_FACET_KEYS)) {
      return (
        <div class="mx-auto max-w-7xl px-4 py-24 text-center sm:px-6 lg:px-8">
          <Breadcrumb crumbs={[{ label: "Results", href: "/results/" }, { label: humanizeBenchmark(benchmark) }]} />
          <h1 class="mt-6 text-3xl font-bold text-[var(--bb-data-fg-primary)]">{humanizeBenchmark(benchmark)}</h1>
          <p class="mt-4 text-lg text-[var(--bb-data-fg-muted)]">
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
        <h1 class="mt-6 text-3xl font-bold text-[var(--bb-data-fg-primary)]">{humanizeBenchmark(benchmark)}</h1>
        <p class="mt-4 text-lg text-[var(--bb-data-fg-muted)]">
          No published results yet for {humanizeBenchmark(benchmark)}.
        </p>
        <p class="mt-2 text-sm text-[var(--bb-data-fg-muted)]">
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
          return matchesFacetRow(p, facets, { keys: BENCHMARK_ROW_FACET_KEYS });
        }),
      }
    : null;
  const analysisSummary: BenchmarkSummary | null = filteredSummary
    ? {
        ...filteredSummary,
        platforms: filteredSummary.platforms.filter(isTimingDisplayable),
      }
    : null;
  const excludedRows = filteredSummary?.platforms.filter((row) => !isTimingDisplayable(row)) ?? [];
  const rankGateReason = filteredSummary ? formatCohortExclusion(filteredSummary) : null;
  const historicalEntries = benchmarkResults.filter((result) => {
    if (String(result.scale_factor) !== effectiveSf) return false;
    if ((result.test_type ?? "power") !== effectivePhase) return false;
    if (!isResultTimingDisplayable(result)) return false;
    return matchesFacetRow(result, facets, { keys: BENCHMARK_ROW_FACET_KEYS });
  });

  const selectedCompareRowsById = new Map(
    (analysisSummary?.platforms ?? [])
      .filter(isComparable)
      .map((row) => [compareIdForRow(row), row]),
  );
  const selectedCompareRows = [...selectedIds]
    .map((id) => selectedCompareRowsById.get(id))
    .filter((row): row is PlatformRow => row !== undefined);

  // Build the Compare URL from selected compact IDs when available.
  const compareUrl =
    selectedCompareRows.length >= 2
      ? buildCompareUrl(selectedCompareRows.map((row) => compareIdForRow(row)))
      : null;
  const benchmarkOptions = uniqueBenchmarkOptions();
  const hasCurrentBenchmarkOption = benchmarkOptions.some((option) => option.value === benchmark);
  const contextNote = benchmarkContextNote(benchmark);
  const selectedComparableCount = selectedCompareRows.length;
  const compareGuidance = benchmarkCompareGuidanceMessage(selectedComparableCount, title, effectiveSf, effectivePhase);
  const matrixCompareRows = analysisSummary?.platforms ?? [];
  const zeroSelectableCompareRows =
    matrixCompareRows.length > 0 && matrixCompareRows.every((row) => !isComparable(row));
  const zeroSelectableReasons = summarizeCompareExclusionReasons(
    matrixCompareRows.map((row) => row.comparison_exclusion_reason),
  );

  return (
    <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <Breadcrumb
        crumbs={[
          { label: "Results", href: "/results/" },
          { label: title },
        ]}
      />

      <div class="mt-6 mb-6 flex flex-wrap items-center justify-between gap-4">
        <h1 class="text-3xl font-bold text-[var(--bb-data-fg-primary)]">{title} Results</h1>

        <div class="flex flex-wrap items-center gap-3">
          {/* Benchmark switcher (sibling pivot). View mode is the only piece
              of UI state that survives the switch; scale, phase, and tuning
              are benchmark-specific so we drop them rather than risk an
              empty page on the destination. */}
          <div class="flex items-center gap-2">
            <label class="text-sm font-medium text-[var(--bb-data-fg-primary)]" for="benchmark-switcher">
              Benchmark:
            </label>
            <select
              id="benchmark-switcher"
              data-testid="benchmark-switcher"
              class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-1.5 text-sm shadow-sm"
              value={benchmark}
              onChange={(event) => {
                const next = (event.target as HTMLSelectElement).value;
                if (next === benchmark) return;
                const params = new URLSearchParams();
                if (viewMode !== "matrix") params.set("view", viewMode);
                const query = params.toString();
                route(`/results/${next}/${query ? `?${query}` : ""}`);
              }}
            >
              {benchmarkOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
              {!hasCurrentBenchmarkOption && (
                <option value={benchmark}>{title}</option>
              )}
            </select>
          </div>

          {/* Scale factor filter */}
          {scaleFactors.length > 1 && (
            <div class="flex items-center gap-2">
              <label class="text-sm font-medium text-[var(--bb-data-fg-primary)]" for="scale-filter">
                Scale:
              </label>
              <select
                id="scale-filter"
                class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-1.5 text-sm shadow-sm"
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
              <label class="text-sm font-medium text-[var(--bb-data-fg-primary)]" for="phase-filter">
                Phase:
              </label>
              <select
                id="phase-filter"
                class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-1.5 text-sm shadow-sm"
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
              <label class="text-sm font-medium text-[var(--bb-data-fg-primary)]" for="tuning-filter">
                Tuning:
              </label>
              <select
                id="tuning-filter"
                class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-1.5 text-sm shadow-sm"
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
              <span class="text-sm font-medium text-[var(--bb-data-fg-primary)]">Trust:</span>
              <div class="flex flex-wrap gap-1">
                {trustLabels.map((tier) => {
                  const active = trustFilter === null || trustFilter.has(tier);
                  return (
                    <button
                      key={tier}
                      class={`rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors ${
                        active
                          ? "bg-[var(--bb-tone-info-bg)] text-[var(--bb-tone-info-fg)]"
                          : "bg-[var(--bb-surface-app)] text-[var(--bb-data-fg-subtle)] hover:bg-[var(--bb-data-border)]"
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
          <SegmentedControl
            ariaLabel="Benchmark view"
            value={viewMode}
            onChange={(value) => setViewMode(value)}
            options={[
              { value: "matrix", label: "Matrix" },
              { value: "ranks", label: rankGateReason ? "Rank Evidence" : "Ranks" },
              { value: "list", label: "List" },
            ]}
          />

          {/* Reduced-color (grayscale) toggle - only meaningful in matrix (heatmap) view.
              Renamed from "High contrast" because the implementation is a
              greyscale lightness palette, not a true high-contrast palette;
              calling greyscale "high contrast" mismatched the rendered cells
              for users who toggled it expecting WCAG-style luminance bumps. */}
          {viewMode === "matrix" && (
            <button
              class={`rounded-md border px-3 py-1.5 text-sm transition-colors ${
                highContrast
                  ? "border-[var(--bb-accent-hover)] bg-[var(--bb-tone-info-bg)] text-[var(--bb-tone-info-fg)]"
                  : "border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] text-[var(--bb-data-fg-muted)] hover:bg-[var(--bb-surface-data-muted)]"
              }`}
              onClick={() => setHighContrast((v) => !v)}
              aria-pressed={highContrast}
              title="Switch the heatmap palette to greyscale for color-vision accessibility"
            >
              Reduced color
            </button>
          )}
        </div>
      </div>

      {contextNote && (
        <div
          class="mb-4 rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-4 py-3 text-sm text-[var(--bb-data-fg-muted)]"
          data-testid="benchmark-context-note"
        >
          {contextNote}
        </div>
      )}

      <section
        class="mb-4 rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-4 py-3 shadow-sm"
        data-testid="benchmark-compare-guidance"
        aria-label="Benchmark compare guidance"
      >
        <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 class="text-sm font-semibold text-[var(--bb-data-fg-primary)]">Compare selected results</h2>
            <p class="mt-1 text-sm text-[var(--bb-data-fg-muted)]">{compareGuidance}</p>
          </div>
          {compareUrl ? (
            <span
              class="shrink-0 rounded-md border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-3 py-1.5 text-sm font-medium text-[var(--bb-data-fg-muted)]"
              aria-live="polite"
            >
              Use sticky tray to compare
            </span>
          ) : (
            <button type="button" class="btn btn-secondary shrink-0 text-sm" disabled>
              {selectedIds.size === 1 ? "Select 1 more result" : "Select 2 comparable results"}
            </button>
          )}
        </div>
      </section>

      {zeroSelectableCompareRows && (
        <section
          class="mb-4 rounded-lg border border-[var(--bb-tone-warning-border)] bg-[var(--bb-tone-warning-bg)] px-4 py-3 text-sm text-[var(--bb-tone-warning-fg)]"
          data-testid="benchmark-zero-selectable"
          aria-label="No selectable benchmark compare rows"
        >
          <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 class="font-semibold">No selectable compare rows</h2>
              <p class="mt-1">
                {zeroSelectableReasons.length > 0
                  ? `${zeroSelectableReasons[0]!.count} ${zeroSelectableReasons[0]!.copy.shortText.toLowerCase()} row${
                      zeroSelectableReasons[0]!.count === 1 ? "" : "s"
                    }. ${zeroSelectableReasons[0]!.copy.recoveryHint}`
                  : "This benchmark cohort does not expose a comparable run. Choose another cohort in the Compare builder."}
              </p>
            </div>
            <a href="/results/compare" class="btn btn-secondary shrink-0 text-sm no-underline">
              Choose another cohort
            </a>
          </div>
        </section>
      )}

      {/* Matrix view */}
      {viewMode === "matrix" && (
        <>
          {summaryError ? (
            <div class="rounded-lg tone-warning border border-[var(--bb-data-border)] px-4 py-3 text-sm">
              Could not load benchmark matrix: {summaryError}
            </div>
          ) : summaryLoading ? (
            <BenchmarkMatrixSkeleton message="Loading matrix..." />
          ) : !filteredSummary ? (
            <div class="rounded-lg border border-dashed border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] p-10 text-center text-[var(--bb-data-fg-subtle)]">
              <p class="font-medium">
                No benchmark data available for {humanizeBenchmark(benchmark)} SF{effectiveSf} phase {effectivePhase}.
              </p>
            </div>
          ) : (
            <QueryHeatmap
              summary={analysisSummary ?? filteredSummary}
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
            <div class="rounded-lg tone-warning border border-[var(--bb-data-border)] px-4 py-3 text-sm">
              Could not load rank data: {summaryError}
            </div>
          ) : summaryLoading ? (
            <BenchmarkMatrixSkeleton message="Loading ranks..." />
          ) : !filteredSummary ? (
            <div class="rounded-lg border border-dashed border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] p-10 text-center text-[var(--bb-data-fg-subtle)]">
              <p class="font-medium">
                No benchmark data available for {humanizeBenchmark(benchmark)} SF{effectiveSf} phase {effectivePhase}.
              </p>
            </div>
          ) : rankGateReason ? (
            <RankGateNotice
              reason={rankGateReason}
              benchmark={title}
              scaleFactor={effectiveSf}
              phase={effectivePhase}
            />
          ) : (
            <div class="card">
              <RankTable summary={analysisSummary ?? filteredSummary} />
            </div>
          )}
        </>
      )}

      {/* List view (mobile-friendly fallback) */}
      {viewMode === "list" && (
        <ListTable benchmark={benchmark} results={results} scaleFactor={effectiveSf} facets={facets} />
      )}

      {viewMode !== "list" && <ExcludedRunsDisclosure rows={excludedRows} />}

      {analysisSummary && analysisSummary.platforms.length > 0 && viewMode !== "list" && (
        <div class="mt-8">
          <ChartPanel
            context={{
              kind: "summary",
              summary: analysisSummary,
              historical: historicalEntries,
            }}
            excludeChartIds={viewMode === "matrix" ? ["query_heatmap"] : undefined}
          />
        </div>
      )}

      {/* Sticky Compare bar */}
      {compareUrl && (
        <div class="fixed bottom-0 left-0 right-0 z-50 border-t border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-4 py-3 shadow-lg">
          <div class="mx-auto flex max-w-7xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div class="min-w-0 flex-1">
              <div class="text-sm text-[var(--bb-data-fg-primary)]">
                <strong>{selectedComparableCount}</strong> platforms selected for compare
              </div>
              <div
                class="mt-2 flex max-h-32 flex-wrap gap-2 overflow-y-auto pr-1"
                role="list"
                aria-label="Selected compare results"
              >
                {selectedCompareRows.map((row) => {
                  const id = compareIdForRow(row);
                  const cohortBenchmark = summaryWithResultMetadata?.benchmark ?? benchmark;
                  const cohortScale = summaryWithResultMetadata?.scale_factor ?? effectiveSf;
                  const cohortPhase = summaryWithResultMetadata?.phase ?? effectivePhase;
                  return (
                    <div
                      key={id}
                      data-testid={`compare-tray-row-${id}`}
                      role="listitem"
                      class="flex max-w-full flex-wrap items-center gap-1.5 rounded-md border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-2 py-1 text-xs text-[var(--bb-data-fg-muted)]"
                    >
                      <span class="font-medium text-[var(--bb-data-fg-primary)]">{row.platform}</span>
                      <span>{humanizeBenchmark(cohortBenchmark)}</span>
                      <span>SF {cohortScale}</span>
                      <span>{cohortPhase}</span>
                      <span>{row.run_date}</span>
                      <TrustBadge trustLabel={row.trust_label} compact />
                      <span class="font-mono text-[var(--bb-data-fg-muted)]">ID {displayCompareId(id)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
            <div class="flex shrink-0 items-center gap-3">
              <button
                type="button"
                class="text-sm text-[var(--bb-data-fg-muted)] hover:text-[var(--bb-data-fg-primary)]"
                onClick={() => setSelectedIds(new Set())}
              >
                Clear
              </button>
              <a href={compareUrl} class="btn btn-primary text-sm no-underline">
                Compare {selectedComparableCount} selected →
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function RankGateNotice({
  reason,
  benchmark,
  scaleFactor,
  phase,
}: {
  reason: string;
  benchmark: string;
  scaleFactor: string;
  phase: string;
}) {
  return (
    <section
      class="rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] p-5 text-sm shadow-sm"
      data-testid="rank-gate-notice"
      aria-label="Rank gate"
    >
      <h2 class="text-base font-semibold text-[var(--bb-data-fg-primary)]">Ranks are unavailable</h2>
      <p class="mt-2 text-[var(--bb-data-fg-muted)]">
        {benchmark} SF {scaleFactor} {phase} is not published as a leaderboard because {reason}
      </p>
      <p class="mt-2 text-xs text-[var(--bb-data-fg-subtle)]">
        Timing evidence and receipts remain available, but BenchBox will not rank this cohort.
      </p>
    </section>
  );
}

function ExcludedRunsDisclosure({ rows }: { rows: PlatformRow[] }) {
  if (rows.length === 0) return null;
  return (
    <details
      class="mt-4 rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-4 py-3 text-sm shadow-sm"
      data-testid="excluded-runs"
    >
      <summary class="cursor-pointer font-medium text-[var(--bb-data-fg-primary)]">
        Excluded runs ({rows.length})
      </summary>
      <div class="mt-3 overflow-x-auto">
        <table class="min-w-full divide-y divide-[var(--bb-data-border)]">
          <thead class="bg-[var(--bb-surface-data-muted)]">
            <tr>
              <th class="table-th text-left">Platform</th>
              <th class="table-th text-left">Reason</th>
              <th class="table-th text-left">Receipt</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-[var(--bb-data-border)]">
            {rows.map((row) => (
              <tr key={row.result_id} data-testid={`excluded-run-${row.result_id}`}>
                <td class="table-td font-medium text-[var(--bb-data-fg-primary)]">{row.platform}</td>
                <td class="table-td text-[var(--bb-data-fg-muted)]">
                  {formatTimingExclusion(row.display_exclusion_reason, "Display timing is unavailable.")}
                </td>
                <td class="table-td">
                  <a href={`/results/r/${row.result_id}#run-receipt`} class="text-xs font-medium no-underline">
                    Receipt →
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
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
    .filter((row) => matchesFacetRow(row, facets, { keys: BENCHMARK_ROW_FACET_KEYS }))
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
      <p class="text-[var(--bb-data-fg-muted)]">
        No results found for SF {scaleFactor}.
      </p>
    );
  }

  return (
    <div class="overflow-hidden rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] shadow-sm">
      <div class="border-b border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-4 py-3 text-sm text-[var(--bb-data-fg-muted)]">
        Showing {visibleRows.length.toLocaleString()} of {filtered.length.toLocaleString()} results for SF {scaleFactor}
      </div>
      <table class="min-w-full divide-y divide-[var(--bb-data-border)]">
        <thead class="bg-[var(--bb-surface-data-muted)]">
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
              label="Power score"
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
                Geomean latency{sortArrow("display_geomean_ms")}
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
        <tbody class="divide-y divide-[var(--bb-data-border)] bg-[var(--bb-surface-data)]">
          {visibleRows.map((r) => (
            <BenchmarkRow key={r.result_id} entry={r} />
          ))}
        </tbody>
      </table>
      {visibleRows.length < filtered.length && (
        <div class="border-t border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-4 py-3 text-center">
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
    <tr class="hover:bg-[var(--bb-surface-data-muted)]" data-testid={entry.result_id}>
      <td class="table-td">
        <a href={`/results/p/${entry.platform_id}/`} class="font-medium no-underline">
          {entry.platform}
        </a>
        {entry.compliance_class && entry.compliance_class !== "official" && (
          <span class="ml-2 text-xs text-[var(--bb-data-fg-subtle)]">{complianceLabel(entry.compliance_class)}</span>
        )}
        {entry.driver_version && (
          <span class="ml-2 text-xs text-[var(--bb-data-fg-subtle)]">v{entry.driver_version}</span>
        )}
      </td>
      <td class="table-td">SF {entry.scale_factor}</td>
      <td class="table-td text-[var(--bb-data-fg-muted)]">{entry.run_date}</td>
      <td class="table-td font-mono">{fmtScore(entry.power_score)}</td>
      <td class="table-td font-mono">{fmtGeomean(entry.display_geomean_ms ?? entry.geomean_ms)}</td>
      <td class="table-td text-[var(--bb-data-fg-muted)]">{entry.query_count}</td>
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
