import { useEffect, useMemo, useState } from "preact/hooks";
import type { RoutableProps } from "preact-router";
import { getDb, queryRows } from "@/db";
import { ErrorMessage } from "@/components/ErrorMessage";
import { FacetDrawer, FacetRail, type ActiveFacetChip, type FacetGroup } from "@/components/FacetRail";
import { QueryRowsSkeleton } from "@/components/LoadingSpinner";
import { arraySerde, stringSerde, useUrlState } from "@/lib/useUrlState";
import {
  buildFacetCountQuery,
  buildFacetSql,
  buildSelectQuery,
  DEFAULT_ROW_LIMIT,
  UNLIMITED_ROW_LIMIT,
  type BuiltQuery,
  type QueryFilterState,
  type QuerySort,
} from "@/lib/queryFilters";
import { getTableSchema, type SchemaColumn } from "@/lib/duckdbSchema";
import { useFacetField } from "@/lib/facetModel";
import { toDateWindowFacet, toggleFacetValue } from "@/lib/facetMatching";
import { STARTER_QUERY_CATEGORIES, starterQueriesByCategory, type StarterQueryCategory } from "@/lib/starterQueries";
import { useDocumentTitle } from "@/lib/useDocumentTitle";
import { memoizedSnapshotQueryRows } from "@/lib/duckdbQueries";
import { formatQueryCell, formatQueryColumnLabel, formatQueryFacetValue } from "@/lib/queryLabels";
import {
  EXPLORER_PERFORMANCE_MARKS,
  EXPLORER_PERFORMANCE_MEASURES,
  markExplorerPerformance,
  measureExplorerPerformance,
} from "@/lib/performanceMarks";

const EMPTY_STRING_ARRAY: string[] = [];

interface FacetBucket {
  value: string;
  count: number;
  [key: string]: unknown;
}

type ResultRow = Record<string, unknown>;

const DEFAULT_COLUMNS = [
  "benchmark",
  "platform",
  "scale_factor",
  "run_date",
  "power_score",
  "geomean_ms",
  "trust_label",
];
const TABLE_RENDER_LIMIT = 200;
const TABLE_RENDER_INCREMENT = 200;

export function Query(_: RoutableProps) {
  useDocumentTitle("Query · BenchBox Results");
  const [benchmarks, setBenchmarks] = useFacetField("benchmark");
  const [platforms, setPlatforms] = useFacetField("platform");
  const [scaleFactors, setScaleFactors] = useFacetField("scale_factor");
  const [tuningModes, setTuningModes] = useFacetField("tuning_mode");
  const [trustTiers, setTrustTiers] = useFacetField("trust_tier");
  const [validationStatuses, setValidationStatuses] = useFacetField("validation_status");
  const [costStatuses, setCostStatuses] = useFacetField("cost_status");
  const [costModelVersions, setCostModelVersions] = useUrlState<string[]>(
    "cost_model",
    EMPTY_STRING_ARRAY,
    arraySerde,
  );
  const [deploymentClasses, setDeploymentClasses] = useFacetField("deployment_class");
  const [cloudProviders, setCloudProviders] = useFacetField("cloud_provider");
  const [cloudRegions, setCloudRegions] = useFacetField("cloud_region");
  const [instanceOrWarehouses, setInstanceOrWarehouses] = useFacetField("instance_or_warehouse");
  const [storageFormats, setStorageFormats] = useFacetField("storage_format");
  const [rowLimitRaw, setRowLimitRaw] = useUrlState<string>("limit", "default", stringSerde);
  const [hasCost, setHasCost] = useUrlState<string>("has_cost", "all", stringSerde);
  const [dateWindow, setDateWindowFacet] = useFacetField("date_window");
  const setDateWindow = (value: string) => setDateWindowFacet(toDateWindowFacet(value));
  const [schema, setSchema] = useState<SchemaColumn[]>([]);
  const [visibleColumns, setVisibleColumns] = useState<string[]>([]);
  const [rows, setRows] = useState<ResultRow[]>([]);
  const [facetCounts, setFacetCounts] = useState<Record<string, FacetBucket[]>>({});
  const [sort, setSort] = useState<QuerySort>({ column: "run_date", direction: "desc" });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sqlText, setSqlText] = useState("SELECT * FROM bench.results ORDER BY run_date DESC");
  const [sqlRows, setSqlRows] = useState<ResultRow[]>([]);
  const [sqlError, setSqlError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [visibleResultLimit, setVisibleResultLimit] = useState(TABLE_RENDER_LIMIT);
  const [visibleSqlLimit, setVisibleSqlLimit] = useState(TABLE_RENDER_LIMIT);
  const rowLimitMode = rowLimitRaw === "all" ? "all" : "default";
  const rowLimit = rowLimitMode === "all" ? UNLIMITED_ROW_LIMIT : DEFAULT_ROW_LIMIT;

  const filters: QueryFilterState = useMemo(
    () => ({
      benchmarks,
      platforms,
      scaleFactors,
      tuningModes,
      trustTiers,
      validationStatuses,
      costStatuses,
      costModelVersions,
      deploymentClasses,
      cloudProviders,
      cloudRegions,
      instanceOrWarehouses,
      instanceTypes: EMPTY_STRING_ARRAY,
      warehouseSizes: EMPTY_STRING_ARRAY,
      storageFormats,
      hasCost: hasCost === "yes" || hasCost === "no" ? hasCost : "all",
      dateWindow,
    }),
    [
      benchmarks,
      cloudProviders,
      cloudRegions,
      costModelVersions,
      costStatuses,
      dateWindow,
      deploymentClasses,
      hasCost,
      instanceOrWarehouses,
      platforms,
      scaleFactors,
      storageFormats,
      trustTiers,
      tuningModes,
      validationStatuses,
    ],
  );
  const queryColumns = useMemo(
    () => (visibleColumns.includes("result_id") ? visibleColumns : ["result_id", ...visibleColumns]),
    [visibleColumns],
  );
  const activeFilters = useMemo(() => applySchemaFilterSupport(filters, schema), [filters, schema]);
  const facetQueries = useMemo(
    () => (schema.length === 0 ? null : buildQueryFacetCountQueries(activeFilters, schema)),
    [activeFilters, schema],
  );
  const selectQuery = useMemo(
    () =>
      visibleColumns.length === 0
        ? null
        : buildSelectQuery(activeFilters, queryColumns, sort, rowLimit),
    [activeFilters, queryColumns, rowLimit, sort, visibleColumns.length],
  );
  const visibleRows = rows.slice(0, visibleResultLimit);
  const visibleSqlRows = sqlRows.slice(0, visibleSqlLimit);

  useEffect(() => {
    setVisibleResultLimit(TABLE_RENDER_LIMIT);
  }, [activeFilters, queryColumns, rowLimit, sort]);

  useEffect(() => {
    setVisibleSqlLimit(TABLE_RENDER_LIMIT);
  }, [sqlRows]);

  useEffect(() => {
    if (rowLimitRaw === "default" || rowLimitRaw === "all") return;
    setRowLimitRaw("default");
  }, [rowLimitRaw, setRowLimitRaw]);

  useEffect(() => {
    let cancelled = false;
    getTableSchema("results")
      .then((columns) => {
        if (cancelled) return;
        setSchema(columns);
        setVisibleColumns((current) =>
          current.length > 0
            ? current
            : DEFAULT_COLUMNS.filter((column) => columns.some((item) => item.name === column)),
        );
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load schema");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (facetQueries === null) return;
    let cancelled = false;
    setError(null);

    Promise.all(
      Object.entries(facetQueries).map(async ([key, query]) => [
        key,
        await memoizedSnapshotQueryRows<FacetBucket>(`query-facet:${key}`, query),
      ]),
    )
      .then((facetEntries) => {
        if (cancelled) return;
        setFacetCounts(Object.fromEntries(facetEntries));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "DuckDB query failed");
      });
    return () => {
      cancelled = true;
    };
  }, [facetQueries]);

  useEffect(() => {
    if (selectQuery === null) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    queryRows<ResultRow>(selectQuery.sql, selectQuery.params)
      .then((nextRows) => {
        if (cancelled) return;
        setRows(nextRows);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "DuckDB query failed");
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectQuery]);

  useEffect(() => {
    if (loading || rows.length === 0 || visibleColumns.length === 0) return;
    markExplorerPerformance(EXPLORER_PERFORMANCE_MARKS.QUERY_WORKBENCH_RENDERED, {
      once: true,
      detail: { rowCount: rows.length, columnCount: visibleColumns.length },
    });
    measureExplorerPerformance(
      EXPLORER_PERFORMANCE_MEASURES.QUERY_WORKBENCH_RENDER_AFTER_DB,
      EXPLORER_PERFORMANCE_MARKS.DB_INIT_READY,
      EXPLORER_PERFORMANCE_MARKS.QUERY_WORKBENCH_RENDERED,
      { once: true },
    );
  }, [loading, rows.length, visibleColumns.length]);

  const sqlColumns = useMemo(() => [...new Set(sqlRows.flatMap((row) => Object.keys(row)))], [sqlRows]);

  if (error) return <ErrorMessage message={error} />;
  if (schema.length === 0 && loading) {
    return (
      <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <QueryRowsSkeleton message="Loading query workbench..." />
      </div>
    );
  }

  const columnNames = schema.map((column) => column.name);
  const facetGroups: FacetGroup[] = [
    makeFacetGroup("benchmark", "Benchmark", facetCounts.benchmark ?? [], benchmarks),
    makeFacetGroup("platform", "Platform", facetCounts.platform ?? [], platforms),
    makeFacetGroup("scale_factor", "Scale", facetCounts.scale_factor ?? [], scaleFactors),
    makeFacetGroup("tuning_mode", "Tuning", facetCounts.tuning_mode ?? [], tuningModes),
    makeFacetGroup("trust_tier", "Trust", facetCounts.trust_label ?? [], trustTiers),
    makeFacetGroup("validation_status", "Validation", facetCounts.validation_status ?? [], validationStatuses),
    makeFacetGroup("cost_status", "Cost status", facetCounts.cost_status ?? [], costStatuses),
    makeFacetGroup("cost_model", "Cost model", facetCounts.cost_model_version ?? [], costModelVersions),
    makeFacetGroup("deployment_class", "Deployment", facetCounts.deployment_class ?? [], deploymentClasses),
    makeFacetGroup("cloud_provider", "Cloud provider", facetCounts.cloud_provider ?? [], cloudProviders),
    makeFacetGroup("cloud_region", "Cloud region", facetCounts.cloud_region ?? [], cloudRegions),
    makeFacetGroup(
      "instance_or_warehouse",
      "Instance / warehouse",
      facetCounts.instance_or_warehouse ?? [],
      instanceOrWarehouses,
    ),
    makeFacetGroup("storage_format", "Storage", facetCounts.storage_format ?? [], storageFormats),
    makeFacetGroup(
      "has_cost",
      "Has cost",
      [{ value: "all", count: rows.length }, ...(facetCounts.has_cost ?? [])],
      [hasCost],
      formatHasCostLabel,
    ),
    makeFacetGroup(
      "date_window",
      "Date window",
      [{ value: "all", count: rows.length }, ...(facetCounts.date_window ?? [])],
      [dateWindow],
      formatDateWindowLabel,
    ),
  ].filter((group) => group.options.length > 0);
  const activeFilterChips: ActiveFacetChip[] = [
    ...makeActiveChips("benchmark", "Benchmark", benchmarks, setBenchmarks),
    ...makeActiveChips("platform", "Platform", platforms, setPlatforms),
    ...makeActiveChips("scale_factor", "Scale", scaleFactors, setScaleFactors),
    ...makeActiveChips("tuning_mode", "Tuning", tuningModes, setTuningModes),
    ...makeActiveChips("trust_tier", "Trust", trustTiers, setTrustTiers),
    ...makeActiveChips("validation_status", "Validation", validationStatuses, setValidationStatuses),
    ...makeActiveChips("cost_status", "Cost status", costStatuses, setCostStatuses),
    ...makeActiveChips("cost_model", "Cost model", costModelVersions, setCostModelVersions),
    ...makeActiveChips("deployment_class", "Deployment", deploymentClasses, setDeploymentClasses),
    ...makeActiveChips("cloud_provider", "Cloud provider", cloudProviders, setCloudProviders),
    ...makeActiveChips("cloud_region", "Cloud region", cloudRegions, setCloudRegions),
    ...makeActiveChips("instance_or_warehouse", "Instance / warehouse", instanceOrWarehouses, setInstanceOrWarehouses),
    ...makeActiveChips("storage_format", "Storage", storageFormats, setStorageFormats),
    ...(hasCost === "all"
      ? []
      : [{
          key: "has_cost",
          label: `Has cost: ${formatHasCostLabel(hasCost)}`,
          onClear: () => setHasCost("all"),
        }]),
    ...(dateWindow === "all"
      ? []
      : [{
          key: "date_window",
          label: `Date: ${formatDateWindowLabel(dateWindow)}`,
          onClear: () => setDateWindow("all"),
        }]),
  ];

  function toggleMulti(value: string, selected: string[], setSelected: (next: string[]) => void) {
    setSelected(toggleFacetValue(selected, value));
  }

  function toggleColumn(column: string) {
    setVisibleColumns((current) => {
      if (current.includes(column)) {
        return current.filter((candidate) => candidate !== column);
      }
      return [...current, column];
    });
  }

  function toggleSort(column: string) {
    setSort((current) =>
      current.column === column
        ? { column, direction: current.direction === "asc" ? "desc" : "asc" }
        : { column, direction: "asc" },
    );
  }

  function toggleQueryFacet(groupKey: string, value: string) {
    switch (groupKey) {
      case "benchmark":
        toggleMulti(value, benchmarks, setBenchmarks);
        break;
      case "platform":
        toggleMulti(value, platforms, setPlatforms);
        break;
      case "scale_factor":
        toggleMulti(value, scaleFactors, setScaleFactors);
        break;
      case "tuning_mode":
        toggleMulti(value, tuningModes, setTuningModes);
        break;
      case "trust_tier":
        toggleMulti(value, trustTiers, setTrustTiers);
        break;
      case "validation_status":
        toggleMulti(value, validationStatuses, setValidationStatuses);
        break;
      case "cost_status":
        toggleMulti(value, costStatuses, setCostStatuses);
        break;
      case "cost_model":
        toggleMulti(value, costModelVersions, setCostModelVersions);
        break;
      case "deployment_class":
        toggleMulti(value, deploymentClasses, setDeploymentClasses);
        break;
      case "cloud_provider":
        toggleMulti(value, cloudProviders, setCloudProviders);
        break;
      case "cloud_region":
        toggleMulti(value, cloudRegions, setCloudRegions);
        break;
      case "instance_or_warehouse":
        toggleMulti(value, instanceOrWarehouses, setInstanceOrWarehouses);
        break;
      case "storage_format":
        toggleMulti(value, storageFormats, setStorageFormats);
        break;
      case "has_cost":
        setHasCost(value);
        break;
      case "date_window":
        setDateWindow(value);
        break;
    }
  }

  function resetQueryFilters() {
    setBenchmarks([]);
    setPlatforms([]);
    setScaleFactors([]);
    setTuningModes([]);
    setTrustTiers([]);
    setValidationStatuses([]);
    setCostStatuses([]);
    setCostModelVersions([]);
    setDeploymentClasses([]);
    setCloudProviders([]);
    setCloudRegions([]);
    setInstanceOrWarehouses([]);
    setStorageFormats([]);
    setHasCost("all");
    setDateWindow("all");
  }

  function buildSqlFromFilters() {
    setSqlText(buildFacetSql(activeFilters, visibleColumns, sort, rowLimit));
  }

  function downloadJson() {
    setDownloadError(null);
    try {
      const exportName = `benchbox-query-export-${Date.now()}.json`;
      const blob = new Blob([JSON.stringify(rows.map((row) => projectVisibleRow(row, visibleColumns)), null, 2)], {
        type: "application/json;charset=utf-8",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = exportName;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      setDownloadError(err instanceof Error ? err.message : "JSON export failed");
    }
  }

  function loadStarterQuery(sql: string) {
    setSqlText(sql);
    setSqlError(null);
    setSqlRows([]);
  }

  async function downloadCsv() {
    const db = await getDb();
    const conn = await db.connect();
    // Filename is interpolated into a COPY TO ... SQL literal below. DuckDB
    // does not parameterize the file path, so we pin the name to a strict
    // whitelist so a future edit can't accidentally introduce SQL injection.
    const exportName = `benchbox-query-export-${Date.now()}.csv`;
    if (!/^benchbox-query-export-\d+\.csv$/.test(exportName)) {
      setDownloadError("Internal error: unexpected export filename");
      return;
    }
    const selectQuery = buildSelectQuery(activeFilters, visibleColumns, sort, UNLIMITED_ROW_LIMIT);
    let statement: {
      query: (...params: unknown[]) => Promise<unknown>;
      close?: () => Promise<void>;
    } | null = null;

    setDownloadError(null);
    try {
      statement = await conn.prepare(
        `COPY (${selectQuery.sql}) TO '${exportName}' (FORMAT CSV, HEADER, DELIMITER ',')`,
      );
      await statement.query(...selectQuery.params);
      const buffer = await db.copyFileToBuffer(exportName);
      const csvBytes = new Uint8Array(buffer.byteLength);
      csvBytes.set(buffer);
      const blob = new Blob([csvBytes], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = exportName;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      setDownloadError(err instanceof Error ? err.message : "CSV export failed");
    } finally {
      if (statement?.close) {
        await statement.close();
      }
      await conn.close();
      await db.dropFile(exportName).catch(() => null);
    }
  }

  async function runSql() {
    setSqlError(null);
    try {
      const nextRows = await queryRows<ResultRow>(sqlText);
      setSqlRows(nextRows);
    } catch (err: unknown) {
      setSqlError(err instanceof Error ? err.message : "SQL query failed");
      setSqlRows([]);
    }
  }

  return (
    <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <div class="mb-6 lg:mb-3">
        <h1 class="text-3xl font-bold text-[var(--bb-data-fg-primary)]">Results Query Workbench</h1>
        <p class="mt-2 max-w-3xl text-sm text-[var(--bb-data-fg-muted)]">
          Query the <code class="rounded bg-[var(--bb-surface-app)] px-1 font-mono text-xs">results.duckdb</code> snapshot in-browser
          with shareable facet state, schema-driven columns, CSV export, and an optional read-only SQL scratchpad.
        </p>
      </div>

      <div class="grid gap-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <section class="flex min-w-0 flex-col gap-4 lg:col-start-2">
          <div
            data-testid="query-result-summary"
            class="order-1 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] p-4 shadow-sm lg:order-2"
          >
            <div class="text-sm text-[var(--bb-data-fg-muted)]">
              {rows.length} matching result bundle(s)
              {rowLimitMode === "default" && rows.length >= DEFAULT_ROW_LIMIT && (
                <span class="ml-2 text-xs text-[var(--bb-tone-warning-fg)]">
                  (capped at {DEFAULT_ROW_LIMIT.toLocaleString()} - add more filters to narrow)
                </span>
              )}
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <div class="flex items-center gap-2 text-sm text-[var(--bb-data-fg-muted)]">
                <span class="font-medium">Rows:</span>
                <div class="flex overflow-hidden rounded-md border border-[var(--bb-data-border-strong)]" role="group" aria-label="Result row limit">
                  {(["default", "all"] as const).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      class={`px-3 py-1.5 text-sm ${
                        rowLimitMode === mode
                          ? "bg-[var(--bb-accent-hover)] text-[var(--bb-fg-primary)]"
                          : "bg-[var(--bb-surface-data)] text-[var(--bb-data-fg-muted)] hover:bg-[var(--bb-surface-data-muted)]"
                      }`}
                      aria-pressed={rowLimitMode === mode}
                      onClick={() => setRowLimitRaw(mode)}
                    >
                      {mode === "default" ? "Default" : "All"}
                    </button>
                  ))}
                </div>
              </div>
              <button class="btn btn-secondary" onClick={downloadCsv}>
                Download CSV (visible columns)
              </button>
              <button class="btn btn-secondary" onClick={downloadJson}>
                Download JSON (visible columns)
              </button>
            </div>
            <p class="w-full text-xs text-[var(--bb-data-fg-muted)]">
              Exports include the currently visible columns only; row View links keep hidden result IDs available.
            </p>
            {downloadError && <div class="w-full text-sm text-[var(--bb-tone-danger-fg)]">{downloadError}</div>}
          </div>

          <div data-testid="query-mobile-filter-drawer" class="order-2 lg:hidden">
            <FacetDrawer
              groups={facetGroups}
              resultCount={rows.length}
              activeChips={activeFilterChips}
              onToggle={toggleQueryFacet}
              onReset={resetQueryFilters}
              open={mobileFiltersOpen}
              onOpenChange={setMobileFiltersOpen}
            />
          </div>

          <div data-testid="query-results-panel" class="order-3">
            {loading ? (
              <QueryRowsSkeleton
                message="Querying results.duckdb..."
                columns={visibleColumns.length || DEFAULT_COLUMNS.length}
              />
            ) : (
              <div class="overflow-hidden rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] shadow-sm">
                <div class="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-4 py-3 text-sm text-[var(--bb-data-fg-muted)]">
                  <span>
                    Showing {visibleRows.length.toLocaleString()} of {rows.length.toLocaleString()} returned rows
                  </span>
                  <span>Query limit: {rowLimitMode === "all" ? "all" : DEFAULT_ROW_LIMIT.toLocaleString()}</span>
                  <span class="bb-scroll-affordance" data-testid="query-results-scroll-hint">← scroll →</span>
                </div>
                <div class="overflow-x-auto">
                  <table class="min-w-full w-max divide-y divide-[var(--bb-data-border)]">
                    <thead class="bg-[var(--bb-surface-data-muted)]">
                      <tr>
                        {visibleColumns.map((column) => (
                          <th
                            key={column}
                            class="table-th cursor-pointer select-none"
                            onClick={() => toggleSort(column)}
                          >
                            {formatQueryColumnLabel(column)}
                            {sort.column === column ? (sort.direction === "asc" ? " ↑" : " ↓") : ""}
                          </th>
                        ))}
                        <th class="table-th sticky right-0 z-10 bg-[var(--bb-surface-data-muted)]" />
                      </tr>
                    </thead>
                    <tbody class="divide-y divide-[var(--bb-data-border)] bg-[var(--bb-surface-data)]">
                      {visibleRows.map((row) => (
                        <tr key={String(row.result_id)} class="hover:bg-[var(--bb-surface-data-muted)]">
                          {visibleColumns.map((column) => (
                            <td key={column} class="table-td">
                              {formatQueryCell(column, row[column])}
                            </td>
                          ))}
                          <td class="table-td sticky right-0 z-10 bg-[var(--bb-surface-data)] text-right">
                            <a href={`/results/r/${row.result_id}`} class="text-xs font-medium no-underline">
                              View →
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {visibleRows.length < rows.length && (
                  <div class="border-t border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-4 py-3 text-center">
                    <button
                      type="button"
                      class="btn btn-secondary"
                      onClick={() => setVisibleResultLimit((limit) => limit + TABLE_RENDER_INCREMENT)}
                    >
                      Show more results
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>

          <details class="order-4 rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] p-4 shadow-sm">
            <summary class="cursor-pointer text-sm font-medium text-[var(--bb-data-fg-primary)]">Advanced SQL</summary>
            <div class="mt-4 space-y-4">
              <button class="btn btn-secondary" onClick={buildSqlFromFilters}>
                Build SQL From Filters
              </button>
              <StarterQueries onSelect={loadStarterQuery} />
              <textarea
                class="min-h-40 w-full rounded-lg border border-[var(--bb-data-border-strong)] p-3 font-mono text-sm"
                value={sqlText}
                onInput={(event) => setSqlText((event.target as HTMLTextAreaElement).value)}
              />
              <div class="flex items-center gap-2">
                <button class="btn btn-secondary" onClick={runSql}>
                  Run SQL
                </button>
                {sqlError && (
                  <span role="alert" class="text-sm text-[var(--bb-tone-danger-fg)]">
                    {sqlError}
                  </span>
                )}
              </div>
              {sqlRows.length > 0 && (
                <div class="overflow-hidden rounded-lg border border-[var(--bb-data-border)]">
                  <div class="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-4 py-3 text-sm text-[var(--bb-data-fg-muted)]">
                    <span>Showing {visibleSqlRows.length.toLocaleString()} of {sqlRows.length.toLocaleString()} SQL rows</span>
                    <span class="bb-scroll-affordance" data-testid="query-sql-scroll-hint">← scroll →</span>
                  </div>
                  <div class="overflow-x-auto">
                    <table class="min-w-full w-max divide-y divide-[var(--bb-data-border)]">
                      <thead class="bg-[var(--bb-surface-data-muted)]">
                        <tr>
                          {sqlColumns.map((column) => (
                            <th key={column} class="table-th">
                              {column}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody class="divide-y divide-[var(--bb-data-border)] bg-[var(--bb-surface-data)]">
                        {visibleSqlRows.map((row, index) => (
                          <tr key={index}>
                            {sqlColumns.map((column) => (
                              <td key={column} class="table-td">
                                {formatCell(row[column])}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {visibleSqlRows.length < sqlRows.length && (
                    <div class="border-t border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-4 py-3 text-center">
                      <button
                        type="button"
                        class="btn btn-secondary"
                        onClick={() => setVisibleSqlLimit((limit) => limit + TABLE_RENDER_INCREMENT)}
                      >
                        Show more SQL rows
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          </details>

          <div
            data-testid="query-visible-columns"
            class="order-5 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] p-4 shadow-sm lg:order-1"
          >
            <div>
              <h2 class="text-base font-semibold text-[var(--bb-data-fg-primary)]">Visible Columns</h2>
              <p class="text-xs text-[var(--bb-data-fg-muted)]">
                Driven from DuckDB <code class="rounded bg-[var(--bb-surface-app)] px-1 font-mono">bench.results</code> introspection.
              </p>
            </div>
            <div class="flex flex-wrap gap-2">
              {columnNames.map((column) => (
                <label
                  key={column}
                  class="inline-flex items-center gap-2 rounded-full bg-[var(--bb-surface-app)] px-3 py-1 text-xs text-[var(--bb-data-fg-muted)]"
                  title={column}
                >
                  <input
                    type="checkbox"
                    aria-label={formatQueryColumnLabel(column)}
                    checked={visibleColumns.includes(column)}
                    onChange={() => toggleColumn(column)}
                  />
                  <span>{formatQueryColumnLabel(column)}</span>
                  <code class="rounded bg-[var(--bb-surface-app)] px-1 font-mono text-[10px] text-[var(--bb-data-fg-subtle)]">{column}</code>
                </label>
              ))}
            </div>
          </div>
        </section>

        <aside
          data-testid="query-desktop-filters"
          class="hidden space-y-4 lg:sticky lg:top-4 lg:col-start-1 lg:row-start-1 lg:block lg:self-start"
        >
          <FacetRail
            groups={facetGroups}
            resultCount={rows.length}
            activeChips={activeFilterChips}
            onToggle={toggleQueryFacet}
            onReset={resetQueryFilters}
          />
        </aside>
      </div>
    </div>
  );
}

function makeFacetGroup(
  key: string,
  label: string,
  buckets: FacetBucket[],
  selected: string[],
  formatLabel: (value: string) => string = (value) => formatQueryFacetValue(key, value),
): FacetGroup {
  return {
    key,
    label,
    selected,
    options: buckets.map((bucket) => ({
      value: bucket.value,
      label: formatLabel(bucket.value),
      count: bucket.count,
    })),
  };
}

function makeActiveChips(
  keyPrefix: string,
  label: string,
  selected: string[],
  setSelected: (next: string[]) => void,
  formatLabel: (value: string) => string = (value) => formatQueryFacetValue(keyPrefix, value),
): ActiveFacetChip[] {
  return selected.map((value) => ({
    key: `${keyPrefix}:${value}`,
    label: `${label}: ${formatLabel(value)}`,
    onClear: () => setSelected(selected.filter((candidate) => candidate !== value)),
  }));
}

function formatHasCostLabel(value: string): string {
  if (value === "all") return "All";
  return value === "yes" ? "Has cost" : "No cost";
}

function formatDateWindowLabel(value: string): string {
  if (value === "all") return "All";
  return `Last ${value}`;
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return String(value);
}

function projectVisibleRow(row: ResultRow, visibleColumns: string[]): ResultRow {
  return Object.fromEntries(visibleColumns.map((column) => [column, row[column]]));
}

function buildQueryFacetCountQueries(
  activeFilters: QueryFilterState,
  schema: SchemaColumn[],
): Record<string, BuiltQuery> {
  const schemaColumns = new Set(schema.map((column) => column.name));
  const facetQueries: Record<string, BuiltQuery> = {
    benchmark: buildFacetCountQuery("benchmark", activeFilters, { exclude: "benchmarks" }),
    platform: buildFacetCountQuery("platform", activeFilters, { exclude: "platforms" }),
    scale_factor: buildFacetCountQuery("scale_factor", activeFilters, { exclude: "scaleFactors" }),
    tuning_mode: buildFacetCountQuery("tuning_mode", activeFilters, { exclude: "tuningModes" }),
    trust_label: buildFacetCountQuery("trust_label", activeFilters, { exclude: "trustTiers" }),
    validation_status: buildFacetCountQuery("validation_status", activeFilters, { exclude: "validationStatuses" }),
    has_cost: buildFacetCountQuery("cost_usd", activeFilters, { exclude: "hasCost", derived: "has_cost" }),
    date_window: buildFacetCountQuery("run_date", activeFilters, { exclude: "dateWindow", derived: "date_window" }),
  };
  if (schemaColumns.has("cost_status")) {
    facetQueries.cost_status = buildFacetCountQuery("cost_status", activeFilters, { exclude: "costStatuses" });
  }
  if (schemaColumns.has("cost_model_version")) {
    facetQueries.cost_model_version = buildFacetCountQuery("cost_model_version", activeFilters, {
      exclude: "costModelVersions",
    });
  }
  if (schemaColumns.has("deployment_class")) {
    facetQueries.deployment_class = buildFacetCountQuery("deployment_class", activeFilters, {
      exclude: "deploymentClasses",
    });
  }
  if (schemaColumns.has("cloud_provider")) {
    facetQueries.cloud_provider = buildFacetCountQuery("cloud_provider", activeFilters, {
      exclude: "cloudProviders",
    });
  }
  if (schemaColumns.has("cloud_region")) {
    facetQueries.cloud_region = buildFacetCountQuery("cloud_region", activeFilters, { exclude: "cloudRegions" });
  }
  if (schemaColumns.has("instance_or_warehouse")) {
    facetQueries.instance_or_warehouse = buildFacetCountQuery("instance_or_warehouse", activeFilters, {
      exclude: "instanceOrWarehouses",
    });
  }
  if (schemaColumns.has("storage_format")) {
    facetQueries.storage_format = buildFacetCountQuery("storage_format", activeFilters, {
      exclude: "storageFormats",
    });
  }
  return facetQueries;
}

function applySchemaFilterSupport(filters: QueryFilterState, schema: SchemaColumn[]): QueryFilterState {
  const columns = new Set(schema.map((column) => column.name));
  return {
    ...filters,
    costStatuses: columns.has("cost_status") ? filters.costStatuses : [],
    costModelVersions: columns.has("cost_model_version") ? filters.costModelVersions : [],
    deploymentClasses: columns.has("deployment_class") ? filters.deploymentClasses : [],
    cloudProviders: columns.has("cloud_provider") ? filters.cloudProviders : [],
    cloudRegions: columns.has("cloud_region") ? filters.cloudRegions : [],
    instanceOrWarehouses: columns.has("instance_or_warehouse") ? filters.instanceOrWarehouses : [],
    instanceTypes: [],
    warehouseSizes: [],
    storageFormats: columns.has("storage_format") ? filters.storageFormats : [],
  };
}

function StarterQueries({ onSelect }: { onSelect: (sql: string) => void }) {
  const grouped = starterQueriesByCategory();
  const categoryOrder: StarterQueryCategory[] = [
    "results",
    "cost_and_deployment",
    "per_query_timings",
    "cohort_comparisons",
    "trust_and_tuning",
    "detail_drilldown",
  ];
  return (
    <section aria-label="Starter queries" class="rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] p-3">
      <h3 class="mb-2 text-sm font-semibold text-[var(--bb-data-fg-primary)]">Starter queries</h3>
      <p class="mb-3 text-xs text-[var(--bb-data-fg-muted)]">Load a read-only template into the editor below and customise it.</p>
      <div class="space-y-3">
        {categoryOrder.map((category) => {
          const items = grouped[category];
          if (items.length === 0) return null;
          return (
            <div key={category}>
              <div class="mb-1 text-xs font-medium uppercase tracking-wide text-[var(--bb-data-fg-muted)]">
                {STARTER_QUERY_CATEGORIES[category]}
              </div>
              <div class="flex flex-wrap gap-2">
                {items.map((query) => (
                  <button
                    key={query.id}
                    type="button"
                    class="rounded-full border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-1 text-xs font-medium text-[var(--bb-data-fg-primary)] hover:bg-[var(--bb-tone-info-bg)] hover:text-[var(--bb-accent-hover)]"
                    title={query.description}
                    onClick={() => onSelect(query.sql)}
                  >
                    {query.label}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
