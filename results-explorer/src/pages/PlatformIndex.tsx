import { useEffect, useState } from "preact/hooks";
import type { RoutableProps } from "preact-router";
import { route } from "preact-router";
import type { PlatformIndexRowRow } from "@/lib/duckdbQueries";
import { getPlatformIndexRows } from "@/lib/duckdbQueries";
import { useFacetState, type DateWindowFacet, type FacetKey, type FacetState } from "@/lib/facetModel";
import { hasActiveFacets, matchesFacetRow, singleFacetValue, toDateWindowFacet } from "@/lib/facetMatching";
import { formatTrustLabel, formatValidationStatus } from "@/lib/displayLabels";
import { buildCompareUrl, compareIdForRow, displayCompareId } from "@/lib/resultLinks";
import { humanizeBenchmark, fmtScore, fmtGeomean, errMsg } from "@/utils";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Breadcrumb } from "@/components/Breadcrumb";
import { TrustBadge, ValidationBadge } from "@/components/TrustBadge";
import { TuningBadge, tuningLabel } from "@/components/TuningBadge";
import { TimeSeries } from "@/components/TimeSeries";
import type { SortState } from "@/types";
import { useDocumentTitle } from "@/lib/useDocumentTitle";

interface PlatformIndexProps extends RoutableProps {
  platform?: string;
}

type PlatformSortKey = "benchmark" | "scale_factor" | "run_date" | "power_score" | "geomean_ms";
type TrendMetric = "power_score" | "display_geomean_ms";
const TABLE_RENDER_LIMIT = 200;
const TABLE_RENDER_INCREMENT = 200;
const MIN_TREND_OBSERVATIONS = 3;
const PLATFORM_RESULT_FACET_KEYS: FacetKey[] = [
  "benchmark",
  "scale_factor",
  "phase",
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

interface TrendCohort {
  key: string;
  label: string;
  primaryMetric: TrendMetric;
  metricDescription: string;
  observationCount: number;
  entries: PlatformIndexRowRow[];
}

function trendMetricDescription(metric: TrendMetric): string {
  return metric === "power_score" ? "power score (higher is better)" : "geomean latency, ms (lower is faster)";
}

function primaryMetricContract(metric: string): string {
  return trendMetricDescription(normalizeTrendMetric(metric));
}

function selectedCohortDifferences(rows: PlatformIndexRowRow[]): string[] {
  if (rows.length < 2) return [];
  const first = rows[0]!;
  const differs = (field: keyof PlatformIndexRowRow) => rows.some((row) => row[field] !== first[field]);
  const differences: string[] = [];
  if (differs("benchmark")) differences.push("benchmark");
  if (differs("scale_factor")) differences.push("scale factor");
  if (differs("phase")) differences.push("phase");
  if (differs("primary_metric")) differences.push("primary metric");
  return differences;
}

function platformCompareGuidanceMessage(
  selectedRows: PlatformIndexRowRow[],
  selectedCount: number,
  platformName: string,
): string {
  if (selectedCount === 0) {
    return `Select two or more ${platformName} results from the same benchmark, scale, phase, and primary metric for a decision-grade comparison.`;
  }
  if (selectedCount === 1) {
    const row = selectedRows[0];
    const cohort = row ? `${humanizeBenchmark(row.benchmark)} SF ${row.scale_factor} ${row.phase}` : "this cohort";
    return `1 result selected in ${cohort}. Select one more result from the same comparable cohort.`;
  }
  const differences = selectedCohortDifferences(selectedRows);
  if (differences.length > 0) {
    return `${selectedCount} results selected, but they differ by ${differences.join(", ")}. Compare will keep the receipts visible and may suppress winner claims for mixed cohorts.`;
  }
  const first = selectedRows[0];
  const cohort = first ? `${humanizeBenchmark(first.benchmark)} SF ${first.scale_factor} ${first.phase}` : "one cohort";
  return `${selectedCount} results selected in ${cohort}. The sticky tray opens Compare with matching cohort context.`;
}

export function PlatformIndex({ platform = "" }: PlatformIndexProps) {
  const [rows, setRows] = useState<PlatformIndexRowRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [visibleLimit, setVisibleLimit] = useState(TABLE_RENDER_LIMIT);
  const { facets, setFacet } = useFacetState();
  const tuningFilter = singleFacetValue(facets.tuning_mode, "all") ?? "all";
  const setTuningFilter = (value: string) => setFacet("tuning_mode", value === "all" ? [] : [value]);
  // w5 (table-sticky-density-and-semantics): single-select filters for the
  // Platform detail table. Each maps to a FacetKey already plumbed through
  // useFacetState/matchesFacetRow so the filtered count strip updates as
  // soon as the user picks a value.
  const benchmarkFilter = singleFacetValue(facets.benchmark, "all") ?? "all";
  const scaleFilter = singleFacetValue(facets.scale_factor, "all") ?? "all";
  const phaseFilter = singleFacetValue(facets.phase, "all") ?? "all";
  const trustFilter = singleFacetValue(facets.trust_tier, "all") ?? "all";
  const validationFilter = singleFacetValue(facets.validation_status, "all") ?? "all";
  const dateWindowFilter: DateWindowFacet = facets.date_window;
  // Helper for the five string-array facets that share the "all means
  // empty array" pattern. date_window has its own DateWindowFacet shape
  // and uses toDateWindowFacet directly.
  const setSingleArrayFacet = (
    key: "benchmark" | "scale_factor" | "phase" | "trust_tier" | "validation_status",
    value: string,
  ) => setFacet(key, value === "all" ? [] : [value]);
  const w5FilterKeys: FacetKey[] = [
    "benchmark",
    "scale_factor",
    "phase",
    "trust_tier",
    "validation_status",
    "date_window",
  ];
  const hasW5Filters = hasActiveFacets(facets, w5FilterKeys);
  const resetW5Filters = () => {
    setFacet("benchmark", []);
    setFacet("scale_factor", []);
    setFacet("phase", []);
    setFacet("trust_tier", []);
    setFacet("validation_status", []);
    setFacet("date_window", "all");
  };
  // Default: geomean_ms ascending (fastest first), nulls last. The empty-state
  // ordering is observable behaviour — must_preserve in the parent TODO.
  const [sort, setSort] = useState<SortState<PlatformSortKey>>({
    key: "geomean_ms",
    direction: "asc",
  });
  const platformDisplayName =
    rows?.find((r) => r.platform_id === platform || r.platform === platform)?.platform ?? platform;
  useDocumentTitle(`${platformDisplayName} · BenchBox Results`);

  useEffect(() => {
    let cancelled = false;
    // Fetch all platform index rows so we can also accept legacy display-name URLs.
    // Cost stays small in the committed corpus; the query projects only the table
    // columns plus cohort metadata needed to avoid mixed-cohort trend charts.
    getPlatformIndexRows()
      .then((r) => {
        if (!cancelled) setRows(r);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errMsg(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setVisibleLimit(TABLE_RENDER_LIMIT);
  }, [
    platform,
    facets.benchmark,
    facets.scale_factor,
    facets.phase,
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

  if (error) return <ErrorMessage message={error} />;
  if (!rows) return <LoadingSpinner message="Loading results..." />;

  // Match by platform_id (URL slug) - platform_id is stable and URL-safe.
  // Fall back to matching by display name for backward compatibility with any
  // old links constructed from the display name.
  const allPlatformResults = rows.filter((r) => r.platform_id === platform || r.platform === platform);

  // Distinct platform options for the in-page sibling pivot, sorted by
  // display name. Each row carries (platform_id, platform); we keep the
  // first display name encountered for each id.
  const platformOptions = (() => {
    const byId = new Map<string, string>();
    for (const row of rows) {
      if (!byId.has(row.platform_id)) byId.set(row.platform_id, row.platform);
    }
    return [...byId.entries()]
      .map(([platform_id, platform]) => ({ platform_id, platform }))
      .sort((a, b) => a.platform.localeCompare(b.platform));
  })();

  // Unique non-null tuning modes - only show filter when multiple modes present.
  const tuningModes = [
    ...new Set(allPlatformResults.map((r) => r.tuning_mode).filter((m): m is string => m !== null)),
  ].sort();

  // w5: derived option lists for the new filter strip. Each list is built
  // from the unfiltered cohort (allPlatformResults) so the user can always
  // see every available value, even after narrowing.
  const benchmarkOptions = [...new Set(allPlatformResults.map((r) => r.benchmark))].sort();
  const scaleOptions = [
    ...new Set(allPlatformResults.map((r) => r.scale_factor)),
  ].sort((a, b) => a - b);
  const phaseOptions = [...new Set(allPlatformResults.map((r) => r.phase))].sort();
  const trustOptions = [
    ...new Set(
      allPlatformResults
        .map((r) => r.trust_label)
        .filter((label): label is string => label !== null && label !== undefined),
    ),
  ].sort();
  const validationOptions = [
    ...new Set(
      allPlatformResults
        .map((r) => r.validation_status)
        .filter((status): status is string => status !== null && status !== undefined),
    ),
  ].sort();
  const showW5Filters = allPlatformResults.length >= 25;

  const platformResultsRaw = allPlatformResults.filter((row) =>
    matchesFacetRow(row, facets, { keys: PLATFORM_RESULT_FACET_KEYS }),
  );
  const allTrendCohorts = buildTrendCohorts(platformResultsRaw);
  const trendCohorts = allTrendCohorts.filter((cohort) => cohort.observationCount >= MIN_TREND_OBSERVATIONS);
  const sparseTrendCohorts = allTrendCohorts.filter(
    (cohort) => cohort.observationCount > 0 && cohort.observationCount < MIN_TREND_OBSERVATIONS,
  );
  const rowsByResultId = new Map(allPlatformResults.map((row) => [row.result_id, row]));
  const selectedRows = [...selected]
    .map((resultId) => rowsByResultId.get(resultId))
    .filter((row): row is PlatformIndexRowRow => row !== undefined);
  const selectedCompareIds = [...selected].map((resultId) => {
    const row = rowsByResultId.get(resultId);
    return row ? compareIdForRow(row) : resultId;
  });
  const compareUrl = selected.size >= 2 ? buildCompareUrl(selectedCompareIds) : null;
  const compareGuidance = platformCompareGuidanceMessage(selectedRows, selected.size, platformDisplayName);

  const platformResults = [...platformResultsRaw].sort((a, b) => {
    const dir = sort.direction === "asc" ? 1 : -1;
    if (sort.key === "benchmark") return dir * a.benchmark.localeCompare(b.benchmark);
    // run_date is "YYYY-MM-DD" (ISO 8601); strict lexicographic compare matches
    // chronological order without dragging in locale-sensitive collation.
    if (sort.key === "run_date") {
      if (a.run_date === b.run_date) return 0;
      return dir * (a.run_date < b.run_date ? -1 : 1);
    }
    const av = a[sort.key];
    const bv = b[sort.key];
    // Nulls sort last in BOTH directions. Convention varies (Excel flips
    // null position with direction; React Table / AG Grid default to
    // always-last). We pick always-last so a click never buries the
    // populated rows below the gaps.
    if (av === null && bv === null) return 0;
    if (av === null) return 1;
    if (bv === null) return -1;
    return dir * (av - bv);
  });
  const visiblePlatformResults = platformResults.slice(0, visibleLimit);

  function toggleSort(key: PlatformSortKey) {
    setSort((prev) =>
      prev.key === key
        ? { key, direction: prev.direction === "asc" ? "desc" : "asc" }
        : { key, direction: "asc" },
    );
  }

  function sortArrow(key: PlatformSortKey) {
    if (sort.key !== key) return " ↕";
    return sort.direction === "asc" ? " ↑" : " ↓";
  }

  function ariaSort(key: PlatformSortKey): "ascending" | "descending" | "none" {
    if (sort.key !== key) return "none";
    return sort.direction === "asc" ? "ascending" : "descending";
  }

  function ariaSortAnnouncement(key: PlatformSortKey) {
    if (sort.key !== key) return null;
    return (
      <span class="sr-only">
        {sort.direction === "asc" ? "sorted ascending" : "sorted descending"}
      </span>
    );
  }

  function toggleSelect(resultId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(resultId)) {
        next.delete(resultId);
      } else {
        next.add(resultId);
      }
      return next;
    });
  }

  // w6 (compare-flow-entrypoints): the cohort signature of the first
  // selected row locks the rest of the table until the user deselects
  // back to zero. Compatible siblings stay selectable; incompatible
  // rows render their checkbox disabled with a reason tooltip.
  const cohortLockSignature = (() => {
    const firstSelectedId = [...selected][0];
    if (firstSelectedId === undefined) return null;
    const firstRow = allPlatformResults.find((row) => row.result_id === firstSelectedId);
    if (!firstRow) return null;
    return {
      benchmark: firstRow.benchmark,
      scale_factor: firstRow.scale_factor,
      phase: firstRow.phase,
      primary_metric: firstRow.primary_metric,
    } as const;
  })();
  function cohortLockReason(row: PlatformIndexRowRow): string | undefined {
    if (cohortLockSignature === null) return undefined;
    if (selected.has(row.result_id)) return undefined;
    const sig = cohortLockSignature;
    const mismatches: string[] = [];
    if (row.benchmark !== sig.benchmark) mismatches.push("benchmark");
    if (row.scale_factor !== sig.scale_factor) mismatches.push("scale");
    if (row.phase !== sig.phase) mismatches.push("phase");
    if (row.primary_metric !== sig.primary_metric) mismatches.push("primary metric");
    if (mismatches.length === 0) return undefined;
    return `Locked: first selection is ${humanizeBenchmark(sig.benchmark)} SF ${sig.scale_factor} ${sig.phase}. This row differs by ${mismatches.join(", ")}.`;
  }

  return (
    <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <Breadcrumb crumbs={[{ label: "Results", href: "/results/" }, { label: platformDisplayName }]} />

      <div class="mt-6 mb-6 flex flex-wrap items-center justify-between gap-4">
        <h1 class="text-3xl font-bold text-[var(--bb-data-fg-primary)]">{platformDisplayName} Results</h1>

        <div class="flex flex-wrap items-center gap-4">
          {/* Platform switcher (sibling pivot). Tuning is platform-specific
              so we do not preserve it across the switch. */}
          {platformOptions.length > 1 && (
            <div class="flex items-center gap-2">
              <label class="text-sm font-medium text-[var(--bb-data-fg-primary)]" for="platform-switcher">
                Platform:
              </label>
              <select
                id="platform-switcher"
                data-testid="platform-switcher"
                class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-1.5 text-sm shadow-sm"
                value={platform}
                onChange={(event) => {
                  const next = (event.target as HTMLSelectElement).value;
                  if (next === platform) return;
                  route(`/results/p/${next}/`);
                }}
              >
                {platformOptions.map((option) => (
                  <option key={option.platform_id} value={option.platform_id}>
                    {option.platform}
                  </option>
                ))}
                {!platformOptions.some((option) => option.platform_id === platform) && (
                  <option value={platform}>{platformDisplayName}</option>
                )}
              </select>
            </div>
          )}
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
        </div>
      </div>

      {showW5Filters && (
        <section
          class="mb-4 rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-4 py-3 shadow-sm"
          data-testid="platform-detail-filters"
          aria-label="Platform result filters"
        >
          <div class="flex flex-wrap items-end gap-3">
            <div class="flex flex-col gap-1">
              <label class="text-xs font-medium text-[var(--bb-data-fg-muted)]" for="platform-filter-benchmark">
                Benchmark
              </label>
              <select
                id="platform-filter-benchmark"
                data-testid="platform-filter-benchmark"
                class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-2 py-1 text-sm shadow-sm"
                value={benchmarkFilter}
                onChange={(event) =>
                  setSingleArrayFacet("benchmark", (event.target as HTMLSelectElement).value)
                }
              >
                <option value="all">All benchmarks</option>
                {benchmarkOptions.map((value) => (
                  <option key={value} value={value}>
                    {humanizeBenchmark(value)}
                  </option>
                ))}
              </select>
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-xs font-medium text-[var(--bb-data-fg-muted)]" for="platform-filter-scale">
                Scale
              </label>
              <select
                id="platform-filter-scale"
                data-testid="platform-filter-scale"
                class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-2 py-1 text-sm shadow-sm"
                value={scaleFilter}
                onChange={(event) =>
                  setSingleArrayFacet("scale_factor", (event.target as HTMLSelectElement).value)
                }
              >
                <option value="all">All scales</option>
                {scaleOptions.map((value) => (
                  <option key={String(value)} value={String(value)}>
                    SF {value}
                  </option>
                ))}
              </select>
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-xs font-medium text-[var(--bb-data-fg-muted)]" for="platform-filter-phase">
                Phase
              </label>
              <select
                id="platform-filter-phase"
                data-testid="platform-filter-phase"
                class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-2 py-1 text-sm shadow-sm"
                value={phaseFilter}
                onChange={(event) =>
                  setSingleArrayFacet("phase", (event.target as HTMLSelectElement).value)
                }
              >
                <option value="all">All phases</option>
                {phaseOptions.map((value) => (
                  <option key={value} value={value}>
                    {value.charAt(0).toUpperCase() + value.slice(1)}
                  </option>
                ))}
              </select>
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-xs font-medium text-[var(--bb-data-fg-muted)]" for="platform-filter-trust">
                Trust tier
              </label>
              <select
                id="platform-filter-trust"
                data-testid="platform-filter-trust"
                class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-2 py-1 text-sm shadow-sm"
                value={trustFilter}
                onChange={(event) =>
                  setSingleArrayFacet("trust_tier", (event.target as HTMLSelectElement).value)
                }
              >
                <option value="all">All trust tiers</option>
                {trustOptions.map((value) => (
                  <option key={value} value={value}>
                    {formatTrustLabel(value)}
                  </option>
                ))}
              </select>
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-xs font-medium text-[var(--bb-data-fg-muted)]" for="platform-filter-validation">
                Validation
              </label>
              <select
                id="platform-filter-validation"
                data-testid="platform-filter-validation"
                class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-2 py-1 text-sm shadow-sm"
                value={validationFilter}
                onChange={(event) =>
                  setSingleArrayFacet("validation_status", (event.target as HTMLSelectElement).value)
                }
              >
                <option value="all">All validation</option>
                {validationOptions.map((value) => (
                  <option key={value} value={value}>
                    {formatValidationStatus(value)}
                  </option>
                ))}
              </select>
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-xs font-medium text-[var(--bb-data-fg-muted)]" for="platform-filter-date-window">
                Date window
              </label>
              <select
                id="platform-filter-date-window"
                data-testid="platform-filter-date-window"
                class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-2 py-1 text-sm shadow-sm"
                value={dateWindowFilter}
                onChange={(event) =>
                  setFacet("date_window", toDateWindowFacet((event.target as HTMLSelectElement).value))
                }
              >
                <option value="all">All time</option>
                <option value="30d">Last 30 days</option>
                <option value="90d">Last 90 days</option>
                <option value="365d">Last 365 days</option>
              </select>
            </div>
            {hasW5Filters && (
              <button
                type="button"
                data-testid="platform-filter-reset"
                class="ml-auto rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-1.5 text-sm font-medium text-[var(--bb-data-fg-primary)] shadow-sm hover:bg-[var(--bb-surface-data-muted)]"
                onClick={resetW5Filters}
              >
                Reset filters
              </button>
            )}
          </div>
        </section>
      )}

      <section
        class="mb-4 rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-4 py-3 shadow-sm"
        data-testid="platform-compare-guidance"
        aria-label="Platform compare guidance"
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
              {selected.size === 1 ? "Select 1 more result" : "Select 2 comparable results"}
            </button>
          )}
        </div>
      </section>

      {platformResults.length === 0 ? (
        <p class="text-[var(--bb-data-fg-muted)]">
          {allPlatformResults.length > 0 && hasActivePlatformResultFacets(facets)
            ? `No results match the selected filters for platform: ${platformDisplayName}.`
            : `No results found for platform: ${platformDisplayName}.`}
        </p>
      ) : (
        <div class="overflow-hidden rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] shadow-sm">
          <div class="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-4 py-3 text-sm text-[var(--bb-data-fg-muted)]">
            <span>
              Showing {visiblePlatformResults.length.toLocaleString()} of {platformResults.length.toLocaleString()} results
            </span>
            {selected.size > 0 && <span>{selected.size.toLocaleString()} selected for compare</span>}
          </div>
          <div class="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-4 py-2 text-xs text-[var(--bb-data-fg-muted)]">
            <span>Rows are labelled by comparable cohort: benchmark, scale, phase, and primary metric.</span>
            <span data-testid="platform-table-scroll-hint">Scroll table for source and receipt columns →</span>
          </div>
          <div class="overflow-x-auto" data-testid="platform-results-scroll-container">
          <table class="min-w-max divide-y divide-[var(--bb-data-border)]">
            <thead class="bg-[var(--bb-surface-data-muted)]">
              <tr>
                <th class="table-th w-8">
                  <span class="sr-only">Compare</span>
                </th>
                <th class="p-0" scope="col" aria-sort={ariaSort("benchmark")}>
                  <button
                    type="button"
                    class="table-th block w-full text-left cursor-pointer select-none bg-transparent border-0"
                    onClick={() => toggleSort("benchmark")}
                  >
                    Benchmark{sortArrow("benchmark")}
                    {ariaSortAnnouncement("benchmark")}
                  </button>
                </th>
                <th class="p-0" scope="col" aria-sort={ariaSort("scale_factor")}>
                  <button
                    type="button"
                    class="table-th block w-full text-left cursor-pointer select-none bg-transparent border-0"
                    onClick={() => toggleSort("scale_factor")}
                  >
                    Scale{sortArrow("scale_factor")}
                    {ariaSortAnnouncement("scale_factor")}
                  </button>
                </th>
                <th class="table-th">Phase</th>
                <th class="table-th">Metric contract</th>
                <th class="p-0" scope="col" aria-sort={ariaSort("run_date")}>
                  <button
                    type="button"
                    class="table-th block w-full text-left cursor-pointer select-none bg-transparent border-0"
                    onClick={() => toggleSort("run_date")}
                  >
                    Date{sortArrow("run_date")}
                    {ariaSortAnnouncement("run_date")}
                  </button>
                </th>
                <th class="p-0" scope="col" aria-sort={ariaSort("power_score")}>
                  <button
                    type="button"
                    class="table-th block w-full text-left cursor-pointer select-none bg-transparent border-0"
                    onClick={() => toggleSort("power_score")}
                  >
                    Power Score{sortArrow("power_score")}
                    {ariaSortAnnouncement("power_score")}
                  </button>
                </th>
                <th
                  class="p-0"
                  scope="col"
                  aria-sort={ariaSort("geomean_ms")}
                  title="Geometric mean of per-query execution times (measurement runs only). Lower is faster."
                >
                  <button
                    type="button"
                    class="table-th block w-full text-left cursor-pointer select-none bg-transparent border-0"
                    onClick={() => toggleSort("geomean_ms")}
                  >
                    Geomean (ms){sortArrow("geomean_ms")}
                    {ariaSortAnnouncement("geomean_ms")}
                  </button>
                </th>
                <th class="table-th">Source</th>
                <th class="table-th" />
              </tr>
            </thead>
            <tbody class="divide-y divide-[var(--bb-data-border)] bg-[var(--bb-surface-data)]">
              {visiblePlatformResults.map((r) => (
                <PlatformRow
                  key={r.result_id}
                  entry={r}
                  checked={selected.has(r.result_id)}
                  onToggle={() => toggleSelect(r.result_id)}
                  disabledReason={cohortLockReason(r)}
                />
              ))}
            </tbody>
          </table>
          </div>
          {visiblePlatformResults.length < platformResults.length && (
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
      )}

      {selected.size === 1 && <p class="mt-3 text-sm text-[var(--bb-data-fg-muted)]">Select at least one more result to compare.</p>}

      {compareUrl && (
        <div class="fixed bottom-0 left-0 right-0 z-50 border-t border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-4 py-3 shadow-lg">
          <div class="mx-auto flex max-w-7xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div class="min-w-0 flex-1">
              <div class="text-sm text-[var(--bb-data-fg-primary)]">
                <strong>{selected.size}</strong> results selected for compare
              </div>
              <div
                class="mt-2 flex max-h-32 flex-wrap gap-2 overflow-y-auto pr-1"
                role="list"
                aria-label="Selected compare results"
              >
                {selectedRows.map((row) => {
                  const id = compareIdForRow(row);
                  return (
                    <div
                      key={row.result_id}
                      data-testid={`compare-tray-row-${row.result_id}`}
                      role="listitem"
                      class="flex max-w-full flex-wrap items-center gap-1.5 rounded-md border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-2 py-1 text-xs text-[var(--bb-data-fg-muted)]"
                    >
                      <span class="font-medium text-[var(--bb-data-fg-primary)]">{row.platform}</span>
                      <span>{humanizeBenchmark(row.benchmark)}</span>
                      <span>SF {row.scale_factor}</span>
                      <span>{row.phase}</span>
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
                onClick={() => setSelected(new Set())}
              >
                Clear
              </button>
              <a href={compareUrl} class="btn btn-primary text-sm no-underline">
                Compare {selected.size} selected →
              </a>
            </div>
          </div>
        </div>
      )}

      {platformResultsRaw.length > 0 && (
        <section class="card mt-8" aria-label="Performance trends by comparable cohort">
          <h2 class="mb-2 text-base font-semibold text-[var(--bb-data-fg-primary)]">Performance Trends by Cohort</h2>
          <p class="mb-4 text-sm text-[var(--bb-data-fg-muted)]">
            Trend cohorts never mix benchmark, scale, phase, or metric. Charts require at least {MIN_TREND_OBSERVATIONS} observations;
            smaller cohorts stay visible as sparse-data states.
          </p>
          {trendCohorts.length === 0 && sparseTrendCohorts.length === 0 ? (
            <p class="text-sm text-[var(--bb-data-fg-subtle)] italic">
              No trendable metric values are available for the selected filters.
            </p>
          ) : (
            <div class="space-y-6">
              {trendCohorts.map((cohort) => (
                <section key={cohort.key} data-testid={`trend-cohort-${cohort.key}`} class="space-y-2">
                  <h3 class="text-sm font-medium text-[var(--bb-data-fg-primary)]">{cohort.label}</h3>
                  <p class="text-xs text-[var(--bb-data-fg-muted)]">
                    {cohort.observationCount} observations · {cohort.metricDescription}
                  </p>
                  <TimeSeries entries={cohort.entries} primaryMetric={cohort.primaryMetric} />
                </section>
              ))}
              {sparseTrendCohorts.map((cohort) => (
                <section
                  key={cohort.key}
                  data-testid={`trend-sparse-${cohort.key}`}
                  class="rounded-lg border border-dashed border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-3 py-3"
                >
                  <h3 class="text-sm font-medium text-[var(--bb-data-fg-primary)]">{cohort.label}</h3>
                  <p class="mt-1 text-sm text-[var(--bb-data-fg-muted)]">
                    Limited observations: {cohort.observationCount} published {cohort.observationCount === 1 ? "run" : "runs"}
                    in this comparable cohort. Trend chart hidden until at least {MIN_TREND_OBSERVATIONS} observations exist.
                  </p>
                  <p class="mt-1 text-xs text-[var(--bb-data-fg-subtle)]">Metric: {cohort.metricDescription}.</p>
                </section>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function hasActivePlatformResultFacets(facets: FacetState): boolean {
  return hasActiveFacets(facets, PLATFORM_RESULT_FACET_KEYS);
}

function buildTrendCohorts(rows: PlatformIndexRowRow[]): TrendCohort[] {
  const groups = new Map<string, TrendCohort>();
  for (const row of rows) {
    const primaryMetric = normalizeTrendMetric(row.primary_metric);
    const key = `${row.benchmark}-sf${row.scale_factor}-${row.phase}-${primaryMetric}`;
    let cohort = groups.get(key);
    if (!cohort) {
      const metricDescription = trendMetricDescription(primaryMetric);
      cohort = {
        key,
        label: `${humanizeBenchmark(row.benchmark)} · SF ${row.scale_factor} · ${row.phase} · ${metricDescription}`,
        primaryMetric,
        metricDescription,
        observationCount: 0,
        entries: [],
      };
      groups.set(key, cohort);
    }
    cohort.entries.push(row);
  }

  return [...groups.values()]
    .map((cohort) => {
      const entries = [...cohort.entries].sort((a, b) => a.run_date.localeCompare(b.run_date));
      return {
        ...cohort,
        entries,
        observationCount: entries.filter((entry) => trendValue(entry, cohort.primaryMetric) !== null).length,
      };
    })
    .filter((cohort) => cohort.observationCount > 0)
    .sort((a, b) => a.label.localeCompare(b.label));
}

function normalizeTrendMetric(metric: string): TrendMetric {
  return metric === "power_score" ? "power_score" : "display_geomean_ms";
}

function trendValue(row: PlatformIndexRowRow, metric: TrendMetric): number | null {
  return metric === "power_score" ? row.power_score : row.display_geomean_ms;
}

interface PlatformRowProps {
  entry: PlatformIndexRowRow;
  checked: boolean;
  onToggle: () => void;
  /**
   * w6 (compare-flow-entrypoints): when a row outside the locked
   * cohort signature is rendered, the checkbox is disabled with a
   * tooltip rather than letting the user accumulate a mixed cohort
   * that Compare would later have to suppress winner claims for.
   */
  disabledReason?: string;
}

function PlatformRow({ entry, checked, onToggle, disabledReason }: PlatformRowProps) {
  return (
    <tr class="hover:bg-[var(--bb-surface-data-muted)]" data-testid={entry.result_id}>
      <td class="table-td">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          disabled={Boolean(disabledReason)}
          title={disabledReason}
          class="h-4 w-4 rounded border-[var(--bb-data-border-strong)] disabled:cursor-not-allowed disabled:opacity-50"
          aria-label={`Select ${entry.result_id} for comparison`}
          data-testid={`platform-compare-checkbox-${entry.result_id}`}
        />
      </td>
      <td class="table-td font-medium">{humanizeBenchmark(entry.benchmark)}</td>
      <td class="table-td">SF {entry.scale_factor}</td>
      <td class="table-td text-[var(--bb-data-fg-muted)]">{entry.phase}</td>
      <td class="table-td max-w-[12rem] text-xs text-[var(--bb-data-fg-muted)]">
        {primaryMetricContract(entry.primary_metric)}
      </td>
      <td class="table-td text-[var(--bb-data-fg-muted)]">{entry.run_date}</td>
      <td class="table-td font-mono">{fmtScore(entry.power_score)}</td>
      <td class="table-td font-mono">{fmtGeomean(entry.geomean_ms)}</td>
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
