import { useEffect, useState } from "preact/hooks";
import { useUrlState, stringSerde } from "@/lib/useUrlState";
import type { RoutableProps } from "preact-router";
import type { PlatformIndexRowRow } from "@/lib/duckdbQueries";
import { getPlatformIndexRows } from "@/lib/duckdbQueries";
import { humanizeBenchmark, fmtScore, fmtGeomean, errMsg } from "@/utils";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Breadcrumb } from "@/components/Breadcrumb";
import { TrustBadge, ValidationBadge } from "@/components/TrustBadge";
import { TuningBadge, tuningLabel } from "@/components/TuningBadge";
import { ChartPanel } from "@/components/ChartPanel";
import type { SortState } from "@/types";
import { useDocumentTitle } from "@/lib/useDocumentTitle";

interface PlatformIndexProps extends RoutableProps {
  platform?: string;
}

type PlatformSortKey = "benchmark" | "scale_factor" | "run_date" | "power_score" | "geomean_ms";

export function PlatformIndex({ platform = "" }: PlatformIndexProps) {
  const [rows, setRows] = useState<PlatformIndexRowRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [tuningFilter, setTuningFilter] = useUrlState<string>("tuning", "all", stringSerde);
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
    // Fetch the whole view so we can also accept legacy display-name URLs.
    // Cost: the view projects bare columns over `results`, which is tens of KB
    // in the committed corpus. The previous implementation paid the same cost
    // via manifest.json, so this is not a regression.
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

  const platformResultsRaw =
    tuningFilter === "all" ? allPlatformResults : allPlatformResults.filter((r) => r.tuning_mode === tuningFilter);

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

  function handleCompare() {
    const ids = [...selected].join(",");
    window.location.href = `/results/compare?ids=${encodeURIComponent(ids)}`;
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
          {selected.size >= 2 && (
            <button class="btn-primary" onClick={handleCompare}>
              Compare {selected.size} results
            </button>
          )}
        </div>
      </div>

      {platformResults.length === 0 ? (
        <p class="text-gray-500">No results found for platform: {platformDisplayName}.</p>
      ) : (
        <div class="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
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
              {platformResults.map((r) => (
                <PlatformRow
                  key={r.result_id}
                  entry={r}
                  checked={selected.has(r.result_id)}
                  onToggle={() => toggleSelect(r.result_id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected.size === 1 && <p class="mt-3 text-sm text-gray-500">Select at least one more result to compare.</p>}

      {platformResultsRaw.length >= 2 && (
        <div class="mt-8">
          <ChartPanel
            context={{
              kind: "summary",
              summary: null,
              historical: platformResultsRaw,
            }}
          />
        </div>
      )}
    </div>
  );
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
