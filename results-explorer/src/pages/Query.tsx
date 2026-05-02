import { useEffect, useMemo, useState } from "preact/hooks";
import type { RoutableProps } from "preact-router";
import { getDb, queryRows } from "@/db";
import { ErrorMessage } from "@/components/ErrorMessage";
import { FacetDrawer, type ActiveFacetChip, type FacetGroup } from "@/components/FacetRail";
import { LoadingSpinner } from "@/components/LoadingSpinner";
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
import { useFacetField, type DateWindowFacet } from "@/lib/facetModel";
import { STARTER_QUERY_CATEGORIES, starterQueriesByCategory, type StarterQueryCategory } from "@/lib/starterQueries";
import { useDocumentTitle } from "@/lib/useDocumentTitle";

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
  const [cloudProviders, setCloudProviders] = useFacetField("cloud_provider");
  const [cloudRegions, setCloudRegions] = useFacetField("cloud_region");
  const [instanceTypes, setInstanceTypes] = useUrlState<string[]>("instance_type", EMPTY_STRING_ARRAY, arraySerde);
  const [warehouseSizes, setWarehouseSizes] = useUrlState<string[]>("warehouse_size", EMPTY_STRING_ARRAY, arraySerde);
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
      cloudProviders,
      cloudRegions,
      instanceTypes,
      warehouseSizes,
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
      hasCost,
      instanceTypes,
      platforms,
      scaleFactors,
      storageFormats,
      trustTiers,
      tuningModes,
      validationStatuses,
      warehouseSizes,
    ],
  );
  const queryColumns = useMemo(
    () => (visibleColumns.includes("result_id") ? visibleColumns : ["result_id", ...visibleColumns]),
    [visibleColumns],
  );
  const activeFilters = useMemo(() => applySchemaFilterSupport(filters, schema), [filters, schema]);
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
    if (schema.length === 0 || visibleColumns.length === 0) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

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
    if (schemaColumns.has("cloud_provider")) {
      facetQueries.cloud_provider = buildFacetCountQuery("cloud_provider", activeFilters, {
        exclude: "cloudProviders",
      });
    }
    if (schemaColumns.has("cloud_region")) {
      facetQueries.cloud_region = buildFacetCountQuery("cloud_region", activeFilters, { exclude: "cloudRegions" });
    }
    if (schemaColumns.has("instance_type")) {
      facetQueries.instance_type = buildFacetCountQuery("instance_type", activeFilters, { exclude: "instanceTypes" });
    }
    if (schemaColumns.has("warehouse_size")) {
      facetQueries.warehouse_size = buildFacetCountQuery("warehouse_size", activeFilters, {
        exclude: "warehouseSizes",
      });
    }
    if (schemaColumns.has("storage_format")) {
      facetQueries.storage_format = buildFacetCountQuery("storage_format", activeFilters, {
        exclude: "storageFormats",
      });
    }
    const selectQuery = buildSelectQuery(activeFilters, queryColumns, sort, rowLimit);

    Promise.all([
      queryRows<ResultRow>(selectQuery.sql, selectQuery.params),
      Promise.all(
        Object.entries(facetQueries).map(async ([key, query]) => [
          key,
          await queryRows<FacetBucket>(query.sql, query.params),
        ]),
      ),
    ])
      .then(([nextRows, facetEntries]) => {
        if (cancelled) return;
        setRows(nextRows);
        setFacetCounts(Object.fromEntries(facetEntries));
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "DuckDB query failed");
        setLoading(false);
      });
  }, [activeFilters, queryColumns, rowLimit, schema, sort, visibleColumns]);

  const sqlColumns = useMemo(() => [...new Set(sqlRows.flatMap((row) => Object.keys(row)))], [sqlRows]);

  if (error) return <ErrorMessage message={error} />;
  if (schema.length === 0 && loading) return <LoadingSpinner message="Loading query workbench..." />;

  const columnNames = schema.map((column) => column.name);
  const mobileFacetGroups: FacetGroup[] = [
    makeFacetGroup("benchmark", "Benchmark", facetCounts.benchmark ?? [], benchmarks),
    makeFacetGroup("platform", "Platform", facetCounts.platform ?? [], platforms),
    makeFacetGroup("scale_factor", "Scale", facetCounts.scale_factor ?? [], scaleFactors, (value) => `SF ${value}`),
    makeFacetGroup("tuning_mode", "Tuning", facetCounts.tuning_mode ?? [], tuningModes),
    makeFacetGroup("trust_tier", "Trust", facetCounts.trust_label ?? [], trustTiers),
    makeFacetGroup("validation_status", "Validation", facetCounts.validation_status ?? [], validationStatuses),
    makeFacetGroup("cost_status", "Cost status", facetCounts.cost_status ?? [], costStatuses),
    makeFacetGroup("cost_model", "Cost model", facetCounts.cost_model_version ?? [], costModelVersions),
    makeFacetGroup("cloud_provider", "Cloud provider", facetCounts.cloud_provider ?? [], cloudProviders),
    makeFacetGroup("cloud_region", "Cloud region", facetCounts.cloud_region ?? [], cloudRegions),
    makeFacetGroup("instance_type", "Instance", facetCounts.instance_type ?? [], instanceTypes),
    makeFacetGroup("warehouse_size", "Warehouse", facetCounts.warehouse_size ?? [], warehouseSizes),
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
    ...makeActiveChips("scale_factor", "Scale", scaleFactors, setScaleFactors, (value) => `SF ${value}`),
    ...makeActiveChips("tuning_mode", "Tuning", tuningModes, setTuningModes),
    ...makeActiveChips("trust_tier", "Trust", trustTiers, setTrustTiers),
    ...makeActiveChips("validation_status", "Validation", validationStatuses, setValidationStatuses),
    ...makeActiveChips("cost_status", "Cost status", costStatuses, setCostStatuses),
    ...makeActiveChips("cost_model", "Cost model", costModelVersions, setCostModelVersions),
    ...makeActiveChips("cloud_provider", "Cloud provider", cloudProviders, setCloudProviders),
    ...makeActiveChips("cloud_region", "Cloud region", cloudRegions, setCloudRegions),
    ...makeActiveChips("instance_type", "Instance", instanceTypes, setInstanceTypes),
    ...makeActiveChips("warehouse_size", "Warehouse", warehouseSizes, setWarehouseSizes),
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
    const next = selected.includes(value) ? selected.filter((candidate) => candidate !== value) : [...selected, value];
    setSelected(next);
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
      case "cloud_provider":
        toggleMulti(value, cloudProviders, setCloudProviders);
        break;
      case "cloud_region":
        toggleMulti(value, cloudRegions, setCloudRegions);
        break;
      case "instance_type":
        toggleMulti(value, instanceTypes, setInstanceTypes);
        break;
      case "warehouse_size":
        toggleMulti(value, warehouseSizes, setWarehouseSizes);
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
    setCloudProviders([]);
    setCloudRegions([]);
    setInstanceTypes([]);
    setWarehouseSizes([]);
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
      <div class="mb-6">
        <h1 class="text-3xl font-bold text-gray-900">Results Query Workbench</h1>
        <p class="mt-2 max-w-3xl text-sm text-gray-600">
          Query the <code class="rounded bg-gray-100 px-1 font-mono text-xs">results.duckdb</code> snapshot in-browser
          with shareable facet state, schema-driven columns, CSV export, and an optional read-only SQL scratchpad.
        </p>
      </div>

      <div class="grid gap-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <section class="flex min-w-0 flex-col gap-4 lg:col-start-2">
          <div
            data-testid="query-result-summary"
            class="order-1 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-200 bg-white p-4 shadow-sm lg:order-2"
          >
            <div class="text-sm text-gray-500">
              {rows.length} matching result bundle(s)
              {rowLimitMode === "default" && rows.length >= DEFAULT_ROW_LIMIT && (
                <span class="ml-2 text-xs text-amber-600">
                  (capped at {DEFAULT_ROW_LIMIT.toLocaleString()} - add more filters to narrow)
                </span>
              )}
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <div class="flex items-center gap-2 text-sm text-gray-600">
                <span class="font-medium">Rows:</span>
                <div class="flex overflow-hidden rounded-md border border-gray-300" role="group" aria-label="Result row limit">
                  {(["default", "all"] as const).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      class={`px-3 py-1.5 text-sm ${
                        rowLimitMode === mode
                          ? "bg-brand-600 text-white"
                          : "bg-white text-gray-600 hover:bg-gray-50"
                      }`}
                      aria-pressed={rowLimitMode === mode}
                      onClick={() => setRowLimitRaw(mode)}
                    >
                      {mode === "default" ? "Default" : "All"}
                    </button>
                  ))}
                </div>
              </div>
              <button class="btn btn-secondary" onClick={buildSqlFromFilters}>
                Build SQL From Filters
              </button>
              <button class="btn btn-secondary" onClick={downloadCsv}>
                Download CSV
              </button>
              <button class="btn btn-secondary" onClick={downloadJson}>
                Download JSON
              </button>
            </div>
            {downloadError && <div class="w-full text-sm text-red-600">{downloadError}</div>}
          </div>

          <div data-testid="query-mobile-filter-drawer" class="order-2 lg:hidden">
            <FacetDrawer
              groups={mobileFacetGroups}
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
              <LoadingSpinner message="Querying results.duckdb..." />
            ) : (
              <div class="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
                <div class="flex flex-wrap items-center justify-between gap-2 border-b border-gray-200 bg-white px-4 py-3 text-sm text-gray-500">
                  <span>
                    Showing {visibleRows.length.toLocaleString()} of {rows.length.toLocaleString()} returned rows
                  </span>
                  <span>Query limit: {rowLimitMode === "all" ? "all" : DEFAULT_ROW_LIMIT.toLocaleString()}</span>
                </div>
                <table class="min-w-full divide-y divide-gray-200">
                  <thead class="bg-gray-50">
                    <tr>
                      {visibleColumns.map((column) => (
                        <th key={column} class="table-th cursor-pointer select-none" onClick={() => toggleSort(column)}>
                          {column}
                          {sort.column === column ? (sort.direction === "asc" ? " ↑" : " ↓") : ""}
                        </th>
                      ))}
                      <th class="table-th" />
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-gray-100 bg-white">
                    {visibleRows.map((row) => (
                      <tr key={String(row.result_id)} class="hover:bg-gray-50">
                        {visibleColumns.map((column) => (
                          <td key={column} class="table-td">
                            {formatCell(row[column])}
                          </td>
                        ))}
                        <td class="table-td text-right">
                          <a href={`/results/r/${row.result_id}`} class="text-xs font-medium no-underline">
                            View →
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {visibleRows.length < rows.length && (
                  <div class="border-t border-gray-200 bg-gray-50 px-4 py-3 text-center">
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

          <details class="order-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
            <summary class="cursor-pointer text-sm font-medium text-gray-900">Advanced SQL</summary>
            <div class="mt-4 space-y-4">
              <StarterQueries onSelect={loadStarterQuery} />
              <textarea
                class="min-h-40 w-full rounded-lg border border-gray-300 p-3 font-mono text-sm"
                value={sqlText}
                onInput={(event) => setSqlText((event.target as HTMLTextAreaElement).value)}
              />
              <div class="flex items-center gap-2">
                <button class="btn btn-secondary" onClick={runSql}>
                  Run SQL
                </button>
                {sqlError && <span class="text-sm text-red-600">{sqlError}</span>}
              </div>
              {sqlRows.length > 0 && (
                <div class="overflow-x-auto rounded-lg border border-gray-200">
                  <div class="border-b border-gray-200 bg-white px-4 py-3 text-sm text-gray-500">
                    Showing {visibleSqlRows.length.toLocaleString()} of {sqlRows.length.toLocaleString()} SQL rows
                  </div>
                  <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                      <tr>
                        {sqlColumns.map((column) => (
                          <th key={column} class="table-th">
                            {column}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-100 bg-white">
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
                  {visibleSqlRows.length < sqlRows.length && (
                    <div class="border-t border-gray-200 bg-gray-50 px-4 py-3 text-center">
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
            class="order-5 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-200 bg-white p-4 shadow-sm lg:order-1"
          >
            <div>
              <h2 class="text-base font-semibold text-gray-900">Visible Columns</h2>
              <p class="text-xs text-gray-500">
                Driven from DuckDB <code class="rounded bg-gray-100 px-1 font-mono">bench.results</code> introspection.
              </p>
            </div>
            <div class="flex flex-wrap gap-2">
              {columnNames.map((column) => (
                <label
                  key={column}
                  class="inline-flex items-center gap-2 rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-600"
                >
                  <input
                    type="checkbox"
                    checked={visibleColumns.includes(column)}
                    onChange={() => toggleColumn(column)}
                  />
                  {column}
                </label>
              ))}
            </div>
          </div>
        </section>

        <aside
          data-testid="query-desktop-filters"
          class="hidden space-y-4 lg:sticky lg:top-4 lg:col-start-1 lg:row-start-1 lg:block lg:self-start"
        >
          <FacetSection
            label="Benchmark"
            buckets={facetCounts.benchmark ?? []}
            selected={benchmarks}
            onToggle={(value) => toggleMulti(value, benchmarks, setBenchmarks)}
          />
          <FacetSection
            label="Platform"
            buckets={facetCounts.platform ?? []}
            selected={platforms}
            onToggle={(value) => toggleMulti(value, platforms, setPlatforms)}
          />
          <FacetSection
            label="Scale"
            buckets={facetCounts.scale_factor ?? []}
            selected={scaleFactors}
            onToggle={(value) => toggleMulti(value, scaleFactors, setScaleFactors)}
            formatLabel={(value) => `SF ${value}`}
          />
          <FacetSection
            label="Tuning"
            buckets={facetCounts.tuning_mode ?? []}
            selected={tuningModes}
            onToggle={(value) => toggleMulti(value, tuningModes, setTuningModes)}
          />
          <FacetSection
            label="Trust"
            buckets={facetCounts.trust_label ?? []}
            selected={trustTiers}
            onToggle={(value) => toggleMulti(value, trustTiers, setTrustTiers)}
          />
          <FacetSection
            label="Validation"
            buckets={facetCounts.validation_status ?? []}
            selected={validationStatuses}
            onToggle={(value) => toggleMulti(value, validationStatuses, setValidationStatuses)}
          />
          <FacetSection
            label="Cost status"
            buckets={facetCounts.cost_status ?? []}
            selected={costStatuses}
            onToggle={(value) => toggleMulti(value, costStatuses, setCostStatuses)}
          />
          <FacetSection
            label="Cost model"
            buckets={facetCounts.cost_model_version ?? []}
            selected={costModelVersions}
            onToggle={(value) => toggleMulti(value, costModelVersions, setCostModelVersions)}
          />
          <FacetSection
            label="Cloud provider"
            buckets={facetCounts.cloud_provider ?? []}
            selected={cloudProviders}
            onToggle={(value) => toggleMulti(value, cloudProviders, setCloudProviders)}
          />
          <FacetSection
            label="Cloud region"
            buckets={facetCounts.cloud_region ?? []}
            selected={cloudRegions}
            onToggle={(value) => toggleMulti(value, cloudRegions, setCloudRegions)}
          />
          <FacetSection
            label="Instance"
            buckets={facetCounts.instance_type ?? []}
            selected={instanceTypes}
            onToggle={(value) => toggleMulti(value, instanceTypes, setInstanceTypes)}
          />
          <FacetSection
            label="Warehouse"
            buckets={facetCounts.warehouse_size ?? []}
            selected={warehouseSizes}
            onToggle={(value) => toggleMulti(value, warehouseSizes, setWarehouseSizes)}
          />
          <FacetSection
            label="Storage"
            buckets={facetCounts.storage_format ?? []}
            selected={storageFormats}
            onToggle={(value) => toggleMulti(value, storageFormats, setStorageFormats)}
          />
          <SingleFacetSection
            label="Has cost"
            options={[{ value: "all", count: rows.length }, ...(facetCounts.has_cost ?? [])]}
            current={hasCost}
            onSelect={setHasCost}
          />
          <SingleFacetSection
            label="Date window"
            options={[{ value: "all", count: rows.length }, ...(facetCounts.date_window ?? [])]}
            current={dateWindow}
            onSelect={setDateWindow}
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
  formatLabel: (value: string) => string = (value) => value,
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
  formatLabel: (value: string) => string = (value) => value,
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

function FacetSection({
  label,
  buckets,
  selected,
  onToggle,
  formatLabel = (value: string) => value,
}: {
  label: string;
  buckets: FacetBucket[];
  selected: string[];
  onToggle: (value: string) => void;
  formatLabel?: (value: string) => string;
}) {
  if (buckets.length === 0) return null;
  return (
    <section class="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <h2 class="mb-3 text-sm font-semibold text-gray-900">{label}</h2>
      <div class="space-y-2">
        {buckets.map((bucket) => (
          <label key={bucket.value} class="flex items-center justify-between gap-2 text-sm text-gray-600">
            <span class="inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={selected.includes(bucket.value)}
                onChange={() => onToggle(bucket.value)}
              />
              {formatLabel(bucket.value)}
            </span>
            <span class="text-xs text-gray-400">{bucket.count}</span>
          </label>
        ))}
      </div>
    </section>
  );
}

function SingleFacetSection({
  label,
  options,
  current,
  onSelect,
}: {
  label: string;
  options: FacetBucket[];
  current: string;
  onSelect: (value: string) => void;
}) {
  return (
    <section class="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <h2 class="mb-3 text-sm font-semibold text-gray-900">{label}</h2>
      <div class="flex flex-wrap gap-2">
        {options.map((option) => (
          <button
            key={option.value}
            class={`rounded-full px-3 py-1 text-xs font-medium ${
              current === option.value ? "bg-brand-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
            onClick={() => onSelect(option.value)}
          >
            {option.value}
            {option.count > 0 ? ` (${option.count})` : ""}
          </button>
        ))}
      </div>
    </section>
  );
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return String(value);
}

function projectVisibleRow(row: ResultRow, visibleColumns: string[]): ResultRow {
  return Object.fromEntries(visibleColumns.map((column) => [column, row[column]]));
}

function applySchemaFilterSupport(filters: QueryFilterState, schema: SchemaColumn[]): QueryFilterState {
  const columns = new Set(schema.map((column) => column.name));
  return {
    ...filters,
    costStatuses: columns.has("cost_status") ? filters.costStatuses : [],
    costModelVersions: columns.has("cost_model_version") ? filters.costModelVersions : [],
    cloudProviders: columns.has("cloud_provider") ? filters.cloudProviders : [],
    cloudRegions: columns.has("cloud_region") ? filters.cloudRegions : [],
    instanceTypes: columns.has("instance_type") ? filters.instanceTypes : [],
    warehouseSizes: columns.has("warehouse_size") ? filters.warehouseSizes : [],
    storageFormats: columns.has("storage_format") ? filters.storageFormats : [],
  };
}

function toDateWindowFacet(value: string): DateWindowFacet {
  if (value === "30d" || value === "90d" || value === "365d") return value;
  return "all";
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
    <section aria-label="Starter queries" class="rounded-lg border border-gray-200 bg-gray-50 p-3">
      <h3 class="mb-2 text-sm font-semibold text-gray-900">Starter queries</h3>
      <p class="mb-3 text-xs text-gray-500">Load a read-only template into the editor below and customise it.</p>
      <div class="space-y-3">
        {categoryOrder.map((category) => {
          const items = grouped[category];
          if (items.length === 0) return null;
          return (
            <div key={category}>
              <div class="mb-1 text-xs font-medium uppercase tracking-wide text-gray-500">
                {STARTER_QUERY_CATEGORIES[category]}
              </div>
              <div class="flex flex-wrap gap-2">
                {items.map((query) => (
                  <button
                    key={query.id}
                    type="button"
                    class="rounded-full border border-gray-300 bg-white px-3 py-1 text-xs font-medium text-gray-700 hover:bg-brand-50 hover:text-brand-700"
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
