import { dateWindowCutoffIso, type DateWindowFacet } from "@/lib/facetModel";

export interface QueryFilterState {
  benchmarks: string[];
  platforms: string[];
  scaleFactors: string[];
  tuningModes: string[];
  trustTiers: string[];
  validationStatuses: string[];
  costStatuses: string[];
  costModelVersions: string[];
  deploymentClasses?: string[];
  cloudProviders: string[];
  cloudRegions: string[];
  instanceOrWarehouses?: string[];
  instanceTypes: string[];
  warehouseSizes: string[];
  storageFormats: string[];
  hasCost: "all" | "yes" | "no";
  dateWindow: DateWindowFacet;
}

export interface QuerySort {
  column: string;
  direction: "asc" | "desc";
}

export interface BuiltQuery {
  sql: string;
  params: unknown[];
}

const ALLOWED_COLUMNS = new Set([
  "result_id",
  "benchmark",
  "scale_factor",
  "platform",
  "driver_version",
  "run_date",
  "power_score",
  "total_duration_s",
  "geomean_ms",
  "query_count",
  "trust_label",
  "visibility",
  "platform_version",
  "execution_mode",
  "tuning_mode",
  "tuning_hash",
  "test_type",
  "phase",
  "primary_metric",
  "validation_status",
  "cost_usd",
  "normalized_cost_usd",
  "cost_model_version",
  "cost_model_source",
  "cost_scope",
  "cost_status",
  "billing_unit",
  "pricing_region",
  "deployment_class",
  "cloud_provider",
  "cloud_region",
  "instance_or_warehouse",
  "instance_type",
  "warehouse_size",
  "node_count",
  "cluster_size",
  "storage_format",
  "storage_tier",
]);

function expandListFilter(
  column: string,
  values: string[],
  clauses: string[],
  params: unknown[],
) {
  if (values.length === 0) return;
  clauses.push(`${column} IN (${values.map(() => "?").join(", ")})`);
  params.push(...values);
}

export function buildWhereClause(filters: QueryFilterState): BuiltQuery {
  const clauses: string[] = [];
  const params: unknown[] = [];

  expandListFilter("benchmark", filters.benchmarks, clauses, params);
  expandListFilter("platform", filters.platforms, clauses, params);
  if (filters.scaleFactors.length > 0) {
    clauses.push(`scale_factor IN (${filters.scaleFactors.map(() => "?").join(", ")})`);
    params.push(...filters.scaleFactors.map((value) => Number(value)));
  }
  expandListFilter("tuning_mode", filters.tuningModes, clauses, params);
  expandListFilter("trust_label", filters.trustTiers, clauses, params);
  expandListFilter("validation_status", filters.validationStatuses, clauses, params);
  expandListFilter("cost_status", filters.costStatuses, clauses, params);
  expandListFilter("cost_model_version", filters.costModelVersions, clauses, params);
  expandListFilter("deployment_class", filters.deploymentClasses ?? [], clauses, params);
  expandListFilter("cloud_provider", filters.cloudProviders, clauses, params);
  expandListFilter("cloud_region", filters.cloudRegions, clauses, params);
  expandListFilter(
    "instance_or_warehouse",
    uniqueStrings([
      ...(filters.instanceOrWarehouses ?? []),
      ...filters.instanceTypes,
      ...filters.warehouseSizes,
    ]),
    clauses,
    params,
  );
  expandListFilter("storage_format", filters.storageFormats, clauses, params);

  if (filters.hasCost === "yes") clauses.push("cost_usd IS NOT NULL");
  if (filters.hasCost === "no") clauses.push("cost_usd IS NULL");

  const cutoff = dateWindowCutoffIso(filters.dateWindow);
  if (cutoff) {
    clauses.push("run_date >= ?");
    params.push(cutoff);
  }

  return {
    sql: clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "",
    params,
  };
}

export const DEFAULT_ROW_LIMIT = 10000;
export const UNLIMITED_ROW_LIMIT = Number.MAX_SAFE_INTEGER;

export function buildSelectQuery(
  filters: QueryFilterState,
  columns: string[],
  sort: QuerySort,
  limit: number = DEFAULT_ROW_LIMIT,
): BuiltQuery {
  const safeColumns = columns.filter((column) => ALLOWED_COLUMNS.has(column));
  const projection = safeColumns.length > 0 ? safeColumns.join(", ") : "result_id";
  const safeSortColumn = ALLOWED_COLUMNS.has(sort.column) ? sort.column : "run_date";
  const safeDirection = sort.direction === "asc" ? "ASC" : "DESC";
  const where = buildWhereClause(filters);
  const safeLimit = Number.isFinite(limit) && limit > 0 ? Math.floor(limit) : DEFAULT_ROW_LIMIT;
  return {
    sql: `SELECT ${projection} FROM bench.results ${where.sql} ORDER BY ${safeSortColumn} ${safeDirection} LIMIT ${safeLimit}`,
    params: where.params,
  };
}

export function buildFacetCountQuery(
  column: string,
  filters: QueryFilterState,
  options: { exclude?: keyof QueryFilterState; derived?: "has_cost" | "date_window" } = {},
): BuiltQuery {
  const effective: QueryFilterState = {
    ...filters,
    benchmarks: options.exclude === "benchmarks" ? [] : filters.benchmarks,
    platforms: options.exclude === "platforms" ? [] : filters.platforms,
    scaleFactors: options.exclude === "scaleFactors" ? [] : filters.scaleFactors,
    tuningModes: options.exclude === "tuningModes" ? [] : filters.tuningModes,
    trustTiers: options.exclude === "trustTiers" ? [] : filters.trustTiers,
    validationStatuses:
      options.exclude === "validationStatuses" ? [] : filters.validationStatuses,
    costStatuses: options.exclude === "costStatuses" ? [] : filters.costStatuses,
    costModelVersions:
      options.exclude === "costModelVersions" ? [] : filters.costModelVersions,
    deploymentClasses:
      options.exclude === "deploymentClasses" ? [] : filters.deploymentClasses,
    cloudProviders: options.exclude === "cloudProviders" ? [] : filters.cloudProviders,
    cloudRegions: options.exclude === "cloudRegions" ? [] : filters.cloudRegions,
    instanceOrWarehouses:
      options.exclude === "instanceOrWarehouses" ? [] : filters.instanceOrWarehouses,
    instanceTypes: options.exclude === "instanceTypes" ? [] : filters.instanceTypes,
    warehouseSizes: options.exclude === "warehouseSizes" ? [] : filters.warehouseSizes,
    storageFormats: options.exclude === "storageFormats" ? [] : filters.storageFormats,
    hasCost: options.exclude === "hasCost" ? "all" : filters.hasCost,
    dateWindow: options.exclude === "dateWindow" ? "all" : filters.dateWindow,
  };
  const where = buildWhereClause(effective);

  if (options.derived === "has_cost") {
    return {
      sql: `
        SELECT CASE WHEN cost_usd IS NULL THEN 'no' ELSE 'yes' END AS value, COUNT(*) AS count
        FROM bench.results
        ${where.sql}
        GROUP BY 1
        ORDER BY 1
      `,
      params: where.params,
    };
  }

  if (options.derived === "date_window") {
    const cutoff30 = dateWindowCutoffIso("30d")!;
    const cutoff90 = dateWindowCutoffIso("90d")!;
    const cutoff365 = dateWindowCutoffIso("365d")!;
    const baseParams = where.params;
    // When other filters produce a WHERE clause, append AND; otherwise open a
    // fresh WHERE. Without this, an empty where.sql produces invalid SQL like
    // `FROM bench.results AND run_date >= ?`.
    const cutoffClause = where.sql ? `${where.sql} AND run_date >= ?` : "WHERE run_date >= ?";
    return {
      sql: `
        SELECT '30d'  AS value, COUNT(*) AS count FROM bench.results ${cutoffClause}
        UNION ALL
        SELECT '90d',  COUNT(*) FROM bench.results ${cutoffClause}
        UNION ALL
        SELECT '365d', COUNT(*) FROM bench.results ${cutoffClause}
        ORDER BY value
      `,
      params: [...baseParams, cutoff30, ...baseParams, cutoff90, ...baseParams, cutoff365],
    };
  }

  if (!ALLOWED_COLUMNS.has(column)) {
    throw new Error(`Unsupported facet column: ${column}`);
  }

  return {
    sql: `
      SELECT CASE WHEN ${column} IS NULL THEN 'unknown' ELSE CAST(${column} AS VARCHAR) END AS value, COUNT(*) AS count
      FROM bench.results
      ${where.sql}
      GROUP BY 1
      ORDER BY count DESC, value ASC
    `,
    params: where.params,
  };
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values)];
}

export function buildFacetSql(
  filters: QueryFilterState,
  columns: string[],
  sort: QuerySort = { column: "run_date", direction: "desc" },
  limit: number = DEFAULT_ROW_LIMIT,
): string {
  const query = buildSelectQuery(filters, columns, sort, limit);
  let paramIndex = 0;
  return query.sql.replace(/\?/g, () => renderSqlLiteral(query.params[paramIndex++]));
}

function renderSqlLiteral(value: unknown): string {
  if (value === null || value === undefined) return "NULL";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "NULL";
  if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
  // Escape single quotes and backslashes for DuckDB string literals.
  const escaped = String(value).split("\\").join("\\\\").split("'").join("''");
  return `'${escaped}'`;
}
