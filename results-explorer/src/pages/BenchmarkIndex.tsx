import type { ComponentChildren } from "preact";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { RoutableProps } from "preact-router";
import { route } from "preact-router";
import type { BenchmarkSummary, PlatformRow, SortDirection, SortState } from "@/types";
import type { ResultRow } from "@/lib/duckdbQueries";
import { getBenchmarkSummaryFromDuckDB, listBenchmarksWithPublicResults, listResults } from "@/lib/duckdbQueries";
import { BENCHMARK_LABELS, humanizeBenchmark, isKnownBenchmark, fmtScore, fmtGeomean, errMsg, complianceLabel } from "@/utils";
import { facetsToWhereClause, useFacetState, type DateWindowFacet, type ExplorerFacetKey, type FacetState } from "@/lib/facetModel";
import { hasActiveFacets, matchesFacetRow, singleFacetValue } from "@/lib/facetMatching";
import {
  buildCompareUrl,
  compareIdForRow,
  resultIdentityAriaLabel,
  resultReceiptHref,
  visibleResultIdForRow,
  MAX_COMPARE_SELECTIONS,
} from "@/lib/resultLinks";
import {
  formatCohortExclusion,
  formatTimingExclusion,
  isComparable,
  isTimingDisplayable,
} from "@/lib/displayEligibility";
import { describeCompareExclusionReason, summarizeCompareExclusionReasons } from "@/lib/compareExclusionReasons";
import { BenchmarkMatrixSkeleton } from "@/components/LoadingSpinner";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Breadcrumb } from "@/components/Breadcrumb";
import { TrustBadge, ValidationBadge } from "@/components/TrustBadge";
import { FundingChip } from "@/components/FundingChip";
import { TuningBadge, tuningLabel } from "@/components/TuningBadge";
import { QueryHeatmap } from "@/components/QueryHeatmap";
import { RankTable } from "@/components/RankTable";
import { ChartPanel } from "@/components/ChartPanel";
import { ProvenanceLegend } from "@/components/ProvenanceLegend";
import { RunIdentityLabel } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { CompareTray } from "@/components/CompareTray";
import { TrayAnnouncer } from "@/components/TrayAnnouncer";
import { RunDateChip } from "@/components/RunAge";
import { NotFound } from "@/pages/NotFound";
import { useDocumentTitle } from "@/lib/useDocumentTitle";
import {
  canonicalBenchmarkSlug,
  canonicalPhase,
  formatArchitecture,
  formatCpuFamily,
  formatMemoryGb,
  formatValidationStatus,
} from "@/lib/displayLabels";
import { formatRunIdentitiesForCohort } from "@/lib/runIdentity";
import { formatSelectedCount } from "@/lib/copyFormatters";
import {
  COHORT_GROUP_BY_LABELS,
  groupCohortRows,
  limitCohortGroups,
  type CohortGroupBy,
} from "@/lib/queryFilters";

const BENCHMARK_SELECTION_LIMIT_REASON_ID = "benchmark-selection-limit";

const DATE_WINDOW_OPTIONS: { value: DateWindowFacet; label: string }[] = [
  { value: "all", label: "Any time" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
  { value: "365d", label: "Last year" },
];

interface BenchmarkIndexProps extends RoutableProps {
  benchmark?: string;
}

type ViewMode = "matrix" | "ranks" | "list";
type BenchmarkListSortKey = "platform" | "scale_factor" | "arch" | "cpu_family" | "memory_gb" | "run_date" | "power_score" | "display_geomean_ms" | "query_count";
const TABLE_RENDER_LIMIT = 200;
const TABLE_RENDER_INCREMENT = 200;
const BENCHMARK_RESULT_FACET_KEYS: ExplorerFacetKey[] = [
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
  "platform_version",
  "arch",
  "cpu_family",
];
const BENCHMARK_ROW_FACET_KEYS: ExplorerFacetKey[] = [
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
  "platform_version",
  "arch",
  "cpu_family",
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

function requestedBenchmarkSection(): ViewMode | null {
  const hash = window.location.hash.replace("#benchmark-section-", "");
  if (window.location.hash.startsWith("#benchmark-section-") && ["matrix", "ranks", "list"].includes(hash)) {
    return hash as ViewMode;
  }
  const legacyView = new URLSearchParams(window.location.search).get("view");
  return legacyView === "ranks" || legacyView === "list" ? legacyView : null;
}

function benchmarkContextNote(benchmark: string): string | null {
  if (benchmark === "star_schema" || benchmark === "ssb") {
    return "Star Schema Benchmark (SSB): raw star_schema evidence is retained, while cohort and ranking identity uses canonical ssb.";
  }
  return null;
}

/**
 * Distinct canonical benchmark families paired with display labels for the
 * in-page sibling switcher. Raw aliases remain reachable as legacy routes,
 * but the switcher exposes one value per canonical family.
 */
function uniqueBenchmarkOptions(availableBenchmarks: ReadonlySet<string> | null): { value: string; label: string }[] {
  if (availableBenchmarks === null) return [];
  const seen = new Set<string>();
  const options: { value: string; label: string }[] = [];
  for (const [value, label] of Object.entries(BENCHMARK_LABELS)) {
    if (!availableBenchmarks.has(value)) continue;
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
  const ranking = `${title} SF ${scaleFactor} ${phase}`;
  const selectedStatus = formatSelectedCount(selectedCount, "result", MAX_COMPARE_SELECTIONS);
  if (selectedCount === 0) {
    return `${selectedStatus}. Select two or more platforms from the same ${ranking} ranking to compare. Benchmark, scale, phase, metric, and unit stay fixed on this page.`;
  }
  if (selectedCount === 1) {
    return `${selectedStatus} in ${ranking}. Select one more result from this ranking to enable Compare.`;
  }
  return `${selectedStatus} in ${ranking}. The sticky tray opens Compare with the same benchmark, scale, and phase contract.`;
}

function isResultTimingDisplayable(row: ResultRow): boolean {
  return row.display_exclusion_reason === null;
}

export function BenchmarkIndex({ benchmark = "" }: BenchmarkIndexProps) {
  const canonicalBenchmark = canonicalBenchmarkSlug(benchmark);
  const title = humanizeBenchmark(canonicalBenchmark);
  const [results, setResults] = useState<ResultRow[] | null>(null);
  const [platformVersionDomainResults, setPlatformVersionDomainResults] = useState<ResultRow[] | null>(null);
  const [summary, setSummary] = useState<BenchmarkSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Distinct benchmark slugs that have at least one public result bundle.
  // Drives the corpus-aware sibling switcher so users cannot pivot into a
  // no-result benchmark detail page. `null` means the list is still loading;
  // on hard failure we instead collapse to a single-element set containing
  // only the current benchmark so the switcher never silently regresses to
  // the catalog-wide list (which would re-introduce the no-result dead-end
  // anti-pattern Contract A is meant to prevent).
  const [availableBenchmarks, setAvailableBenchmarks] = useState<ReadonlySet<string> | null>(null);

  useEffect(() => {
    let cancelled = false;
    listBenchmarksWithPublicResults()
      .then((slugs) => {
        if (!cancelled) setAvailableBenchmarks(new Set(slugs));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // Hard failure (snapshot missing, transport error, etc.). Collapse
        // the switcher to just the current benchmark via the fallback
        // <option>; never silently revert to catalog-wide, which would let
        // users pivot into no-result dead ends. Log once so observability
        // can pick up persistent snapshot failures.
        console.warn("listBenchmarksWithPublicResults failed; switcher will show only the current benchmark", err);
        setAvailableBenchmarks(new Set(canonicalBenchmark ? [canonicalBenchmark] : []));
      });
    return () => {
      cancelled = true;
    };
  }, [benchmark]);

  // Filter state - URL-synced so views are shareable.
  const { facets, setFacet, resetFacets } = useFacetState();
  const requestedSf = singleFacetValue(facets.scale_factor);
  const phaseFilter = singleFacetValue(facets.phase, "power") ?? "power";
  const tuningFilter = singleFacetValue(facets.tuning_mode, "all") ?? "all";
  const platformVersionFilter = facets.platform_version.length === 0
    ? "all"
    : facets.platform_version.length === 1
      ? facets.platform_version[0]!
      : "__multiple__";
  const trustFilter = facets.trust_tier.length === 0 ? null : new Set(facets.trust_tier);
  const benchmarkResultWhere = useMemo(
    () =>
      facetsToWhereClause({
        ...facets,
        benchmark: canonicalBenchmark ? [canonicalBenchmark] : [],
        scale_factor: [],
        phase: [],
        tuning_mode: [],
        trust_tier: [],
      }),
    [
      benchmark,
      canonicalBenchmark,
      facets.cloud_provider,
      facets.cloud_region,
      facets.cost_status,
      facets.date_window,
      facets.deployment_class,
      facets.execution_mode,
      facets.instance_or_warehouse,
      facets.platform,
      facets.platform_version,
      facets.arch,
      facets.cpu_family,
      facets.storage_format,
      facets.validation_status,
    ],
  );
  const benchmarkVersionDomainWhere = useMemo(
    () => facetsToWhereClause({
      ...facets,
      benchmark: canonicalBenchmark ? [canonicalBenchmark] : [],
      scale_factor: [],
      phase: [],
      tuning_mode: [],
      trust_tier: [],
      platform_version: [],
    }),
    [
      benchmark,
      canonicalBenchmark,
      facets.cloud_provider,
      facets.cloud_region,
      facets.cost_status,
      facets.date_window,
      facets.deployment_class,
      facets.execution_mode,
      facets.instance_or_warehouse,
      facets.platform,
      facets.arch,
      facets.cpu_family,
      facets.storage_format,
      facets.validation_status,
    ],
  );

  const setScaleFilter = (value: string | null) => setFacet("scale_factor", value ? [value] : []);
  const setPhaseFilter = (value: string) => setFacet("phase", value === "power" ? [] : [value]);
  const setTuningFilter = (value: string) => setFacet("tuning_mode", value === "all" ? [] : [value]);
  const setTrustFilter = (value: Set<string> | null) => setFacet("trust_tier", value ? [...value].sort() : []);

  const [sectionNavigation, setSectionNavigation] = useState(0);
  const completedSectionScroll = useRef<string | null>(null);
  const [settledSummaryKey, setSettledSummaryKey] = useState<string | null>(null);
  const requestedSection = requestedBenchmarkSection();
  useEffect(() => {
    const onNavigation = () => setSectionNavigation((value) => value + 1);
    window.addEventListener("hashchange", onNavigation);
    window.addEventListener("popstate", onNavigation);
    return () => {
      window.removeEventListener("hashchange", onNavigation);
      window.removeEventListener("popstate", onNavigation);
    };
  }, []);

  // High contrast / reduced-color mode for the heatmap (explicit user toggle).
  // Also activates automatically via CSS prefers-contrast: more media query.
  const [highContrast, setHighContrast] = useState(false);

  // Row selection for Compare
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Bumped by the ErrorMessage retry button so a reader can re-issue this
  // read after a DuckDB worker fault without reloading the page.
  const [resultsRetryToken, setResultsRetryToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    // The List section always renders Arch/CPU columns, independent of
    // whether the active facets filter on hardware, so it must always ask
    // for those columns rather than relying on listResults' filter-sniffing.
    listResults(benchmarkResultWhere, { includeHardware: true })
      .then((r) => {
        if (!cancelled) setResults(r);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errMsg(err));
      });
    return () => {
      cancelled = true;
    };
  }, [benchmarkResultWhere, resultsRetryToken]);

  useEffect(() => {
    if (facets.platform_version.length === 0) {
      setPlatformVersionDomainResults(null);
      return;
    }
    let cancelled = false;
    listResults(benchmarkVersionDomainWhere)
      .then((rows) => {
        if (!cancelled) setPlatformVersionDomainResults(rows);
      })
      .catch(() => {
        if (!cancelled) setPlatformVersionDomainResults(null);
      });
    return () => {
      cancelled = true;
    };
  }, [benchmarkVersionDomainWhere, facets.platform_version]);

  // Derive available scale factors and phases from the loaded rows.
  const benchmarkResults = results?.filter((r) => canonicalBenchmarkSlug(r.benchmark) === canonicalBenchmark) ?? [];
  const benchmarkNotFound = results !== null && benchmarkResults.length === 0 && !isKnownBenchmark(canonicalBenchmark);
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
        .map((r) => canonicalPhase(r.test_type))
        .filter(Boolean),
    ),
  ].sort();

  // If the stored phaseFilter isn't available for the current SF, fall back to
  // the first available phase so we never request a non-existent artifact.
  const effectivePhase = phases.includes(phaseFilter) ? phaseFilter : (phases[0] ?? phaseFilter);
  const summaryKey = JSON.stringify([benchmark, effectiveSf, effectivePhase]);

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
    setSettledSummaryKey(null);
    getBenchmarkSummaryFromDuckDB(benchmark, Number(effectiveSf), effectivePhase)
      .then((s) => {
        if (!cancelled) {
          setSummary(s);
          setSummaryLoading(false);
          setSettledSummaryKey(summaryKey);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setSummaryError(errMsg(err));
          setSummaryLoading(false);
          setSettledSummaryKey(summaryKey);
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

  // Native fragment navigation happens before async sections exist. Wait for
  // the current cohort so replacing its skeleton cannot move the target away.
  useEffect(() => {
    if (!requestedSection || summaryLoading || settledSummaryKey !== summaryKey) return;
    const navigationKey = `${benchmark}:${requestedSection}:${sectionNavigation}`;
    if (completedSectionScroll.current === navigationKey) return;
    const target = document.getElementById(`benchmark-section-${requestedSection}`);
    if (!target) return;
    target.scrollIntoView?.({ block: "start" });
    completedSectionScroll.current = navigationKey;
  }, [benchmark, requestedSection, sectionNavigation, settledSummaryKey, summaryKey, summaryLoading]);

  if (error) return <ErrorMessage message={error} onRetry={() => setResultsRetryToken((t) => t + 1)} />;
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
            arch: metadata?.arch ?? null,
            cpu_family: metadata?.cpu_family ?? null,
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
  const platformOptions = summaryWithResultMetadata
    ? [...new Set(summaryWithResultMetadata.platforms.map((p) => p.platform))].sort((a, b) => a.localeCompare(b))
    : [];
  const validationOptions = summaryWithResultMetadata
    ? [
        ...new Set(
          summaryWithResultMetadata.platforms
            .map((p) => p.validation_status)
            .filter((status): status is string => status !== null && status !== ""),
        ),
      ].sort()
    : [];
  const platformVersions = [
    ...new Set(
      (platformVersionDomainResults ?? benchmarkResults)
        .map((result) => result.platform_version)
        .filter((version): version is string => version !== null),
    ),
  ].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

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
    if (canonicalPhase(result.test_type) !== effectivePhase) return false;
    if (!isResultTimingDisplayable(result)) return false;
    return matchesFacetRow(result, facets, { keys: BENCHMARK_ROW_FACET_KEYS });
  });

  const selectedCompareRowsById = new Map(
    (summaryWithResultMetadata?.platforms ?? [])
      .filter(isTimingDisplayable)
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
  // Corpus-aware switcher: list only benchmarks with public results once the
  // distinct-benchmarks query resolves. The currently-viewed benchmark is
  // always reachable through the fallback option below, so direct links to
  // no-result benchmark routes still recover gracefully.
  const benchmarkOptions = uniqueBenchmarkOptions(availableBenchmarks);
  const hasCurrentBenchmarkOption = benchmarkOptions.some(
    (option) => canonicalBenchmarkSlug(option.value) === canonicalBenchmark,
  );
  const contextNote = benchmarkContextNote(benchmark);
  const selectedComparableCount = selectedCompareRows.length;
  const compareGuidance = benchmarkCompareGuidanceMessage(selectedComparableCount, title, effectiveSf, effectivePhase);
  const selectionLimitCopy =
    selectedIds.size >= MAX_COMPARE_SELECTIONS
      ? describeCompareExclusionReason(`Up to ${MAX_COMPARE_SELECTIONS} runs can be compared.`)
      : null;
  const matrixCompareRows = analysisSummary?.platforms ?? [];
  const zeroSelectableCompareRows =
    matrixCompareRows.length > 0 && matrixCompareRows.every((row) => !isComparable(row));
  const zeroSelectableReasons = summarizeCompareExclusionReasons(
    matrixCompareRows.map((row) => row.comparison_exclusion_reason),
  );

  const updateSelectedIds = (next: Set<string>) => {
    if (next.size <= MAX_COMPARE_SELECTIONS) setSelectedIds(next);
  };

  return (
    <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <PageHeader
        crumbs={[
          { label: "Results", href: "/results/" },
          { label: title },
        ]}
        eyebrow="Benchmark"
        title={`${title} Results`}
        meta={
          filteredSummary && filteredSummary.platforms.length > 0 ? (
            <>
              <span class="bb-meta-chip" data-testid="cohort-counts">
                {filteredSummary.platforms.length} published runs
              </span>
              <span class="bb-meta-chip">{filteredSummary.query_ids.length} queries</span>
              <span class="bb-meta-chip">SF {filteredSummary.scale_factor}</span>
              <span class="bb-meta-chip">{effectivePhase}</span>
            </>
          ) : undefined
        }
        actions={
          <>
          {/* Keep the section link while clearing benchmark-specific filters. */}
          <div class="flex items-center gap-2">
            <label class="text-sm font-medium text-[var(--bb-data-fg-primary)]" for="benchmark-switcher">
              Benchmark:
            </label>
            <select
              id="benchmark-switcher"
              data-testid="benchmark-switcher"
              class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-1.5 text-sm shadow-sm"
              value={canonicalBenchmark}
              onChange={(event) => {
                const next = (event.target as HTMLSelectElement).value;
                if (next === benchmark) return;
                const section = requestedBenchmarkSection();
                resetFacets();
                route(`/results/${next}/${section ? `#benchmark-section-${section}` : ""}`);
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

          {/* Jump nav. Matrix, Ranks, and List are all rendered below - these
              are anchor links to the section on this same page, not a control
              that swaps one section in for the other two. */}
          <nav aria-label="Jump to section" class="flex items-center gap-3 text-sm font-medium text-[var(--bb-data-fg-muted)]">
            <a href="#benchmark-section-matrix" class="no-underline hover:text-[var(--bb-data-fg-primary)] hover:underline">Matrix</a>
            <a href="#benchmark-section-ranks" class="no-underline hover:text-[var(--bb-data-fg-primary)] hover:underline">
              {rankGateReason ? "Rank Evidence" : "Ranks"}
            </a>
            <a href="#benchmark-section-list" class="no-underline hover:text-[var(--bb-data-fg-primary)] hover:underline">List</a>
          </nav>

          </>
        }
      />

      {/* Every filter that narrows the cohort, in one place. These were
          previously split between the title row and nowhere at all: platform,
          validation status, and the date window were plumbed through the facet
          model but had no control. */}
      <section
        class="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-4 py-3"
        data-testid="benchmark-filters"
        aria-label="Cohort filters"
      >
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

          {(platformVersionFilter !== "all" || platformVersions.length > 1) && (
            <div class="flex items-center gap-2">
              <label class="text-sm font-medium text-[var(--bb-data-fg-primary)]" for="benchmark-version-filter">
                Platform version:
              </label>
              <select
                id="benchmark-version-filter"
                data-testid="benchmark-version-filter"
                class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-1.5 text-sm shadow-sm"
                value={platformVersionFilter}
                onChange={(event) => {
                  const value = (event.target as HTMLSelectElement).value;
                  setFacet("platform_version", value === "all" ? [] : [value]);
                }}
              >
                <option value="all">All versions</option>
                {platformVersionFilter === "__multiple__" && (
                  <option value="__multiple__" disabled>{facets.platform_version.length} versions selected</option>
                )}
                {platformVersions.map((version) => (
                  <option key={version} value={version}>{version}</option>
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
                          : "bg-[var(--bb-surface-app)] text-[var(--bb-data-fg-muted)] hover:bg-[var(--bb-data-border)]"
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


          {platformOptions.length > 1 && (
            <div class="flex items-center gap-2">
              <label class="text-sm font-medium text-[var(--bb-data-fg-primary)]" for="benchmark-platform-filter">
                Platform:
              </label>
              <select
                id="benchmark-platform-filter"
                data-testid="benchmark-platform-filter"
                class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-1.5 text-sm shadow-sm"
                value={facets.platform.length === 1 ? facets.platform[0]! : "all"}
                onChange={(event) => {
                  const value = (event.target as HTMLSelectElement).value;
                  setFacet("platform", value === "all" ? [] : [value]);
                }}
              >
                <option value="all">All platforms</option>
                {platformOptions.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            </div>
          )}

          {validationOptions.length > 1 && (
            <div class="flex items-center gap-2">
              <label class="text-sm font-medium text-[var(--bb-data-fg-primary)]" for="benchmark-validation-filter">
                Validation:
              </label>
              <select
                id="benchmark-validation-filter"
                data-testid="benchmark-validation-filter"
                class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-1.5 text-sm shadow-sm"
                value={facets.validation_status.length === 1 ? facets.validation_status[0]! : "all"}
                onChange={(event) => {
                  const value = (event.target as HTMLSelectElement).value;
                  setFacet("validation_status", value === "all" ? [] : [value]);
                }}
              >
                <option value="all">Any status</option>
                {validationOptions.map((status) => (
                  <option key={status} value={status}>{formatValidationStatus(status)}</option>
                ))}
              </select>
            </div>
          )}

          <div class="flex items-center gap-2">
            <label class="text-sm font-medium text-[var(--bb-data-fg-primary)]" for="benchmark-date-window-filter">
              Run date:
            </label>
            <select
              id="benchmark-date-window-filter"
              data-testid="benchmark-date-window-filter"
              class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-1.5 text-sm shadow-sm"
              value={facets.date_window}
              onChange={(event) => {
                setFacet("date_window", (event.target as HTMLSelectElement).value as DateWindowFacet);
              }}
            >
              {DATE_WINDOW_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>

          {hasActiveFacets(facets, BENCHMARK_ROW_FACET_KEYS) && (
            <button
              type="button"
              class="btn btn-subtle text-sm"
              data-testid="benchmark-clear-filters"
              onClick={() => {
                for (const key of BENCHMARK_ROW_FACET_KEYS) {
                  if (key === "date_window") continue;
                  setFacet(key, [] as never);
                }
                setFacet("date_window", "all");
              }}
            >
              Clear filters
            </button>
          )}
      </section>

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
            <p
              class="mt-1 text-sm text-[var(--bb-data-fg-muted)]"
              {...(selectedComparableCount < 2 ? { "aria-live": "polite" as const, "aria-atomic": "true" as const } : {})}
            >
              {compareGuidance}
            </p>
            {selectionLimitCopy && (
              <p
                id={BENCHMARK_SELECTION_LIMIT_REASON_ID}
                class="mt-1 text-sm text-[var(--bb-tone-warning-fg)]"
                data-testid="benchmark-selection-limit"
              >
                <span class="font-medium">{selectionLimitCopy.shortText}.</span> {selectionLimitCopy.recoveryHint}
              </p>
            )}
          </div>
          {/* One slot, whatever the state. A disabled button that looks
              clickable and then relocates the moment it becomes clickable
              costs the reader two mistakes; the affordance appears here only
              when it can actually be used, and the pending state reads as
              status text. */}
          {compareUrl ? (
            <a href={compareUrl} class="btn btn-primary shrink-0 text-sm no-underline" data-testid="benchmark-compare-cta">
              Compare {selectedComparableCount} selected
            </a>
          ) : (
            <p class="shrink-0 text-sm text-[var(--bb-data-fg-subtle)]" data-testid="benchmark-compare-cta-pending">
              {selectedIds.size === 1 ? "Select 1 more result" : "Select 2 results to compare"}
            </p>
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
                  : "This ranking does not expose a comparable run. Choose another ranking in the Compare builder."}
              </p>
            </div>
            <a href="/results/compare" class="btn btn-secondary shrink-0 text-sm no-underline">
              Choose another ranking
            </a>
          </div>
        </section>
      )}

      <section id="benchmark-section-matrix" class="scroll-mt-24" aria-labelledby="benchmark-heading-matrix">
        <h2 id="benchmark-heading-matrix" class="mb-3 text-lg font-semibold text-[var(--bb-data-fg-primary)]">
          Matrix
        </h2>
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
          <div id="evidence-matrix" data-testid="evidence-matrix">
            {/* Palette control sits with the thing it repaints. In the page
                filter row it read as another cohort filter. */}
            <div class="mb-2 flex justify-end">
              <button
                type="button"
                class={`rounded-md border px-3 py-1 text-xs transition-colors ${
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
            </div>
            <QueryHeatmap
              summary={analysisSummary ?? filteredSummary}
              selectedIds={selectedIds}
              onSelectionChange={updateSelectedIds}
              selectionLimitReasonId={selectionLimitCopy ? BENCHMARK_SELECTION_LIMIT_REASON_ID : undefined}
              highContrast={highContrast}
            />
          </div>
        )}
      </section>

      <section id="benchmark-section-ranks" class="mt-8 scroll-mt-24 overflow-x-hidden" aria-labelledby="benchmark-heading-ranks">
        <h2 id="benchmark-heading-ranks" class="mb-3 text-lg font-semibold text-[var(--bb-data-fg-primary)]">
          {rankGateReason ? "Rank Evidence" : "Ranks"}
        </h2>
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
      </section>

      <section id="benchmark-section-list" class="mt-8 scroll-mt-24 overflow-x-hidden" aria-labelledby="benchmark-heading-list">
        <h2 id="benchmark-heading-list" class="mb-3 text-lg font-semibold text-[var(--bb-data-fg-primary)]">
          List
        </h2>
        <ListTable
          benchmark={benchmark}
          results={results}
          scaleFactor={effectiveSf}
          phase={effectivePhase}
          facets={facets}
        />
      </section>

      <ExcludedRunsDisclosure rows={excludedRows} />

      {analysisSummary && analysisSummary.platforms.length > 0 && (
        <div class="mt-8">
          <ChartPanel
            context={{
              kind: "summary",
              summary: analysisSummary,
              historical: historicalEntries,
            }}
            summaryLayout="long"
            excludeChartIds={["query_heatmap"]}
          />
        </div>
      )}

      <TrayAnnouncer count={selectedComparableCount} />
      {/* Sticky Compare bar */}
      {compareUrl && (
        <CompareTray
          summary={
            <>
              <strong>{selectedComparableCount}</strong> platforms selected for compare
            </>
          }
          items={selectedCompareRows.map((row) => ({
            id: compareIdForRow(row),
            platform: row.platform,
            benchmarkLabel: humanizeBenchmark(summaryWithResultMetadata?.benchmark ?? benchmark),
            scaleFactor: summaryWithResultMetadata?.scale_factor ?? effectiveSf,
            phase: summaryWithResultMetadata?.phase ?? effectivePhase,
            runDate: row.run_date,
            trustLabel: row.trust_label,
            funding: row.funding,
            visibleResultId: visibleResultIdForRow(row),
          }))}
          compareHref={compareUrl}
          compareLabel={`Compare ${selectedComparableCount} selected`}
          onClear={() => setSelectedIds(new Set())}
        />
      )}
      <div id="provenance-legend" class="scroll-mt-24">
        <ProvenanceLegend />
      </div>
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
        Timing evidence and receipts remain available, but BenchBox will not publish a ranking here.
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
                  <a
                    href={resultReceiptHref(row)}
                    aria-label={resultIdentityAriaLabel(row, "receipt")}
                    class="text-xs font-medium no-underline"
                  >
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
  phase,
  facets,
}: {
  benchmark: string;
  results: ResultRow[];
  scaleFactor: string;
  phase?: string;
  facets: FacetState;
}) {
  const [sort, setSort] = useState<SortState<BenchmarkListSortKey>>({
    key: "display_geomean_ms",
    direction: "asc",
  });
  const [visibleLimit, setVisibleLimit] = useState(TABLE_RENDER_LIMIT);
  const benchmarkResults = results.filter((r) => canonicalBenchmarkSlug(r.benchmark) === canonicalBenchmarkSlug(benchmark));

  const byCohort = benchmarkResults.filter((r) => {
    if (String(r.scale_factor) !== scaleFactor) return false;
    if (phase && canonicalPhase(r.test_type) !== phase) return false;
    return true;
  });

  const filtered = byCohort
    .filter((row) => matchesFacetRow(row, facets, { keys: BENCHMARK_ROW_FACET_KEYS }))
    .sort((a, b) => compareListRows(a, b, sort));
  const [groupBy, setGroupBy] = useState<CohortGroupBy>("none");
  const visibleRows = filtered.slice(0, visibleLimit);
  const groupedRows = useMemo(() => {
    return limitCohortGroups(
      groupCohortRows(
        filtered,
        groupBy,
        (row) => row.platform_version ?? null,
      ),
      filtered,
      visibleLimit,
    );
  }, [filtered, groupBy, visibleLimit]);
  const runIdentityLabels = formatRunIdentitiesForCohort(filtered, "table");

  // Skip the mount run: visibleLimit already starts at TABLE_RENDER_LIMIT,
  // and a mount-time reset would silently eat a Show more click that lands
  // before this effect flushes.
  const skipVisibleLimitResetOnMount = useRef(true);
  useEffect(() => {
    if (skipVisibleLimitResetOnMount.current) {
      skipVisibleLimitResetOnMount.current = false;
      return;
    }
    setVisibleLimit(TABLE_RENDER_LIMIT);
  }, [
    benchmark,
    scaleFactor,
    phase,
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
    facets.platform_version,
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
      <div class="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-4 py-3 text-sm text-[var(--bb-data-fg-muted)]">
        <span>
          Showing {visibleRows.length.toLocaleString()} of {filtered.length.toLocaleString()} results for SF {scaleFactor}
        </span>
        <div class="flex items-center gap-2">
          <label class="text-xs font-medium text-[var(--bb-data-fg-muted)]" for="benchmark-list-group-by">
            Group by:
          </label>
          <select
            id="benchmark-list-group-by"
            data-testid="benchmark-list-group-by"
            class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-2 py-1 text-sm shadow-sm"
            value={groupBy}
            onChange={(e) => setGroupBy((e.target as HTMLSelectElement).value as CohortGroupBy)}
          >
            <option value="none">{COHORT_GROUP_BY_LABELS.none}</option>
            <option value="engine_version">{COHORT_GROUP_BY_LABELS.engine_version}</option>
          </select>
        </div>
      </div>
      {/*
        The basis statement, per w3. A leaderboard that does not say what its
        numbers mean is the same defect the compare work is fixing.

        The median-or-min CONTROL is deferred, not forgotten -- see w0.log and
        deferral #724 for the measurement and the reason.
      */}
      <p class="mb-3 text-xs text-[var(--bb-data-fg-muted)]" data-testid="basis-statement">
        Geomean query time uses the median of each query's published measurement passes, then the
        geometric mean across queries. Warmup passes are excluded. Dates, counts, and power scores use
        the definitions shown in their columns and receipts.
      </p>
      <div class="overflow-x-auto">
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
              label="Arch"
              sortKey="arch"
              ariaSort={ariaSort}
              sortArrow={sortArrow}
              sortAnnouncement={sortAnnouncement}
              onSort={toggleSort}
            />
            <ListSortHeader
              label="CPU family"
              sortKey="cpu_family"
              ariaSort={ariaSort}
              sortArrow={sortArrow}
              sortAnnouncement={sortAnnouncement}
              onSort={toggleSort}
            />
            <ListSortHeader
              label="Memory"
              sortKey="memory_gb"
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
            <ListSortHeader
              label="Geomean"
              sortKey="display_geomean_ms"
              ariaSort={ariaSort}
              sortArrow={sortArrow}
              sortAnnouncement={sortAnnouncement}
              onSort={toggleSort}
            />
            <ListSortHeader
              label="Queries"
              sortKey="query_count"
              ariaSort={ariaSort}
              sortArrow={sortArrow}
              sortAnnouncement={sortAnnouncement}
              onSort={toggleSort}
            />
            <th class="table-th text-left">Badges</th>
            <th class="table-th text-right">Receipt</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-[var(--bb-data-border)] bg-[var(--bb-surface-data)]">
          {groupBy === "none"
            ? visibleRows.map((r, index) => (
                <BenchmarkRow key={r.result_id} entry={r} runIdentityLabel={runIdentityLabels[index] ?? r.platform} />
              ))
            : groupedRows.map((group) => (
                <>
                  <tr
                    key={`group-${group.key}`}
                    class="bg-[var(--bb-surface-data-muted)] font-semibold text-xs text-[var(--bb-data-fg-primary)]"
                  >
                    <td colspan={11} class="px-4 py-2">
                      {group.label} ({group.totalRows} {group.totalRows === 1 ? "result" : "results"})
                    </td>
                  </tr>
                  {group.rows.map((r) => {
                    const index = filtered.findIndex((row) => row.result_id === r.result_id);
                    return (
                      <BenchmarkRow key={r.result_id} entry={r} runIdentityLabel={runIdentityLabels[index] ?? r.platform} />
                    );
                  })}
                </>
              ))}
        </tbody>
      </table>
      </div>
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

function BenchmarkRow({ entry, runIdentityLabel }: { entry: ResultRow; runIdentityLabel: string }) {
  return (
    <tr class="hover:bg-[var(--bb-surface-data-muted)]" data-testid={`list-${entry.result_id}`}>
      <td class="table-td">
        <RunIdentityLabel label={runIdentityLabel} href={`/results/p/${entry.platform_id}/`} />
        {entry.compliance_class && entry.compliance_class !== "official" && (
          <span class="ml-2 text-xs text-[var(--bb-data-fg-subtle)]">{complianceLabel(entry.compliance_class)}</span>
        )}
      </td>
      <td class="table-td">SF {entry.scale_factor}</td>
      <td class="table-td text-[var(--bb-data-fg-muted)]">{entry.arch ? formatArchitecture(entry.arch) : "—"}</td>
      <td class="table-td text-[var(--bb-data-fg-muted)]">{entry.cpu_family ? formatCpuFamily(entry.cpu_family) : "—"}</td>
      <td class="table-td text-[var(--bb-data-fg-muted)]">{entry.memory_gb != null ? formatMemoryGb(entry.memory_gb) : "—"}</td>
      <td class="table-td text-[var(--bb-data-fg-muted)]"><RunDateChip runDate={entry.run_date} /></td>
      <td class="table-td font-mono">{fmtScore(entry.power_score)}</td>
      <td class="table-td font-mono">{fmtGeomean(entry.display_geomean_ms ?? entry.geomean_ms)}</td>
      <td class="table-td text-[var(--bb-data-fg-muted)]">{entry.query_count}</td>
      <td class="table-td">
        <div class="flex flex-wrap gap-1">
          <TrustBadge trustLabel={entry.trust_label} compact />
          <FundingChip funding={entry.funding} compact />
          <ValidationBadge validationStatus={entry.validation_status} showMissing />
          {entry.tuning_mode && (
            <TuningBadge
              tuningMode={entry.tuning_mode}
              tuningValidationStatus={entry.tuning_validation_status}
            />
          )}
        </div>
      </td>
      <td class="table-td text-right">
        <a
          href={resultReceiptHref(entry)}
          aria-label={resultIdentityAriaLabel(entry, "receipt")}
          class="text-xs font-medium no-underline"
        >
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
        class="table-th relative block w-full cursor-pointer select-none border-0 bg-transparent text-left"
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
  if (sort.key === "arch" || sort.key === "cpu_family") {
    const aVal = a[sort.key] ?? "";
    const bVal = b[sort.key] ?? "";
    if (!aVal && !bVal) return 0;
    if (!aVal) return 1;
    if (!bVal) return -1;
    return sort.direction === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
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
  if (sort.key === "memory_gb") {
    return compareNullableNumber(a.memory_gb ?? null, b.memory_gb ?? null, sort.direction);
  }
  return compareNullableNumber(a[sort.key], b[sort.key], sort.direction);
}

function compareNullableNumber(a: number | null, b: number | null, direction: SortDirection): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return direction === "asc" ? a - b : b - a;
}
