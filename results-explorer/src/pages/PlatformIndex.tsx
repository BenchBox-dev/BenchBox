import { useEffect, useState } from "preact/hooks";
import type { RoutableProps } from "preact-router";
import type { PlatformIndexRowRow } from "@/lib/duckdbQueries";
import { getPlatformIndexRows } from "@/lib/duckdbQueries";
import { useFacetState, type DateWindowFacet, type FacetState } from "@/lib/facetModel";
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

interface TrendCohort {
  key: string;
  label: string;
  primaryMetric: TrendMetric;
  entries: PlatformIndexRowRow[];
}

export function PlatformIndex({ platform = "" }: PlatformIndexProps) {
  const [rows, setRows] = useState<PlatformIndexRowRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [visibleLimit, setVisibleLimit] = useState(TABLE_RENDER_LIMIT);
  const { facets, setFacet } = useFacetState();
  const tuningFilter = singleFacetValue(facets.tuning_mode) ?? "all";
  const setTuningFilter = (value: string) => setFacet("tuning_mode", value === "all" ? [] : [value]);
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

  // Unique non-null tuning modes - only show filter when multiple modes present.
  const tuningModes = [
    ...new Set(allPlatformResults.map((r) => r.tuning_mode).filter((m): m is string => m !== null)),
  ].sort();

  const platformResultsRaw = allPlatformResults.filter((row) => matchesPlatformIndexFacets(row, facets));
  const trendCohorts = buildTrendCohorts(platformResultsRaw);
  const rowsByResultId = new Map(allPlatformResults.map((row) => [row.result_id, row]));
  const selectedRows = [...selected]
    .map((resultId) => rowsByResultId.get(resultId))
    .filter((row): row is PlatformIndexRowRow => row !== undefined);
  const selectedCompareIds = [...selected].map((resultId) => {
    const row = rowsByResultId.get(resultId);
    return row ? compareIdForPlatformRow(row) : resultId;
  });
  const compareUrl = selected.size >= 2 ? buildCompareUrl(selectedCompareIds) : null;

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

  return (
    <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <Breadcrumb crumbs={[{ label: "Results", href: "/results/" }, { label: platformDisplayName }]} />

      <div class="mt-6 mb-8 flex items-center justify-between">
        <h1 class="text-3xl font-bold text-gray-900">{platformDisplayName} Results</h1>

        <div class="flex items-center gap-4">
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
          {compareUrl && (
            <a class="btn btn-primary text-sm no-underline" href={compareUrl}>
              Compare {selected.size} results
            </a>
          )}
        </div>
      </div>

      {platformResults.length === 0 ? (
        <p class="text-gray-500">
          {allPlatformResults.length > 0 && hasActivePlatformResultFacets(facets)
            ? `No results match the selected filters for platform: ${platformDisplayName}.`
            : `No results found for platform: ${platformDisplayName}.`}
        </p>
      ) : (
        <div class="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
          <div class="flex flex-wrap items-center justify-between gap-2 border-b border-gray-200 bg-white px-4 py-3 text-sm text-gray-500">
            <span>
              Showing {visiblePlatformResults.length.toLocaleString()} of {platformResults.length.toLocaleString()} results
            </span>
            {selected.size > 0 && <span>{selected.size.toLocaleString()} selected for compare</span>}
          </div>
          <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
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
            <tbody class="divide-y divide-gray-100 bg-white">
              {visiblePlatformResults.map((r) => (
                <PlatformRow
                  key={r.result_id}
                  entry={r}
                  checked={selected.has(r.result_id)}
                  onToggle={() => toggleSelect(r.result_id)}
                />
              ))}
            </tbody>
          </table>
          {visiblePlatformResults.length < platformResults.length && (
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
      )}

      {selected.size === 1 && <p class="mt-3 text-sm text-gray-500">Select at least one more result to compare.</p>}

      {compareUrl && (
        <div class="fixed bottom-0 left-0 right-0 z-50 border-t border-gray-200 bg-white px-4 py-3 shadow-lg">
          <div class="mx-auto flex max-w-7xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div class="min-w-0 flex-1">
              <div class="text-sm text-gray-700">
                <strong>{selected.size}</strong> results selected for compare
              </div>
              <div
                class="mt-2 flex max-h-32 flex-wrap gap-2 overflow-y-auto pr-1"
                role="list"
                aria-label="Selected compare results"
              >
                {selectedRows.map((row) => {
                  const id = compareIdForPlatformRow(row);
                  return (
                    <div
                      key={row.result_id}
                      data-testid={`compare-tray-row-${row.result_id}`}
                      role="listitem"
                      class="flex max-w-full flex-wrap items-center gap-1.5 rounded-md border border-gray-200 bg-gray-50 px-2 py-1 text-xs text-gray-600"
                    >
                      <span class="font-medium text-gray-900">{row.platform}</span>
                      <span>{humanizeBenchmark(row.benchmark)}</span>
                      <span>SF {row.scale_factor}</span>
                      <span>{row.phase}</span>
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

      {platformResultsRaw.length >= 2 && (
        <section class="card mt-8" aria-label="Performance trends by comparable cohort">
          <h2 class="mb-2 text-base font-semibold text-gray-900">Performance Trends by Cohort</h2>
          {trendCohorts.length === 0 ? (
            <p class="text-sm text-gray-400 italic">
              Trends require at least two runs within the same benchmark, scale, phase, and primary metric.
            </p>
          ) : (
            <div class="space-y-6">
              {trendCohorts.map((cohort) => (
                <section key={cohort.key} data-testid={`trend-cohort-${cohort.key}`} class="space-y-2">
                  <h3 class="text-sm font-medium text-gray-700">{cohort.label}</h3>
                  <TimeSeries entries={cohort.entries} primaryMetric={cohort.primaryMetric} />
                </section>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function singleFacetValue(values: string[]): string | null {
  return values.length === 1 ? (values[0] ?? null) : null;
}

function hasActivePlatformResultFacets(facets: FacetState): boolean {
  return (
    facets.benchmark.length > 0 ||
    facets.scale_factor.length > 0 ||
    facets.phase.length > 0 ||
    facets.execution_mode.length > 0 ||
    facets.tuning_mode.length > 0 ||
    facets.trust_tier.length > 0 ||
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

function matchesPlatformIndexFacets(row: PlatformIndexRowRow, facets: FacetState): boolean {
  if (!matchesMultiFilter(row.benchmark, facets.benchmark)) return false;
  if (!matchesMultiFilter(String(row.scale_factor), facets.scale_factor)) return false;
  if (!matchesOptionalFilter(row.phase, facets.phase)) return false;
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

function matchesTuningFacet(row: PlatformIndexRowRow, selected: string[]): boolean {
  return selected.length === 0 || selected.includes(row.tuning_mode ?? "untuned");
}

function matchesDeploymentFacet(row: PlatformIndexRowRow, selected: string[]): boolean {
  if (selected.length === 0) return true;
  const deployment = rowDeploymentClass(row);
  return deployment !== null && selected.includes(deployment);
}

function rowDeploymentClass(row: PlatformIndexRowRow): string | null {
  return row.deployment_class ?? null;
}

function rowShape(row: PlatformIndexRowRow): string | null {
  return row.instance_or_warehouse ?? null;
}

function compareIdForPlatformRow(row: PlatformIndexRowRow): string {
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

function buildTrendCohorts(rows: PlatformIndexRowRow[]): TrendCohort[] {
  const groups = new Map<string, TrendCohort>();
  for (const row of rows) {
    const primaryMetric = normalizeTrendMetric(row.primary_metric);
    const key = `${row.benchmark}-sf${row.scale_factor}-${row.phase}-${primaryMetric}`;
    let cohort = groups.get(key);
    if (!cohort) {
      cohort = {
        key,
        label: `${humanizeBenchmark(row.benchmark)} · SF ${row.scale_factor} · ${row.phase}`,
        primaryMetric,
        entries: [],
      };
      groups.set(key, cohort);
    }
    cohort.entries.push(row);
  }

  return [...groups.values()]
    .map((cohort) => ({
      ...cohort,
      entries: [...cohort.entries].sort((a, b) => a.run_date.localeCompare(b.run_date)),
    }))
    .filter(
      (cohort) =>
        cohort.entries.filter((entry) => trendValue(entry, cohort.primaryMetric) !== null).length >= 2,
    )
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
}

function PlatformRow({ entry, checked, onToggle }: PlatformRowProps) {
  return (
    <tr class="hover:bg-gray-50" data-testid={entry.result_id}>
      <td class="table-td">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          class="h-4 w-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
          aria-label={`Select ${entry.result_id} for comparison`}
        />
      </td>
      <td class="table-td font-medium">{humanizeBenchmark(entry.benchmark)}</td>
      <td class="table-td">SF {entry.scale_factor}</td>
      <td class="table-td text-gray-500">{entry.run_date}</td>
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
