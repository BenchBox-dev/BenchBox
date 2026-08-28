import { formatFacetDisplayValue } from "@/lib/facetDisplay";
import {
  formatDurationSeconds,
  formatLatencyMs,
  formatPlainNumber,
  formatPowerScore,
  formatUsd,
} from "@/lib/metricFormatters";
import { humanizeBenchmark } from "@/utils";

const QUERY_ID_COLLATOR = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});

export function compareQueryIds(a: string, b: string): number {
  return QUERY_ID_COLLATOR.compare(a, b) || a.localeCompare(b);
}

/**
 * Sort and deduplicate query identifiers.
 *
 * Dedup is defensive: callers (RankTable, QueryHeatmap, QueryHistogram) use
 * the result both for column ordering AND as React keys. A duplicate id in
 * the input would produce React key collisions and break reconciliation,
 * which is the bug class captured in
 * `_project/blind-spots/2026-04-29-143205-react-key-collision-class.md`.
 * Stable order on duplicates would not have helped there: only one of the
 * duplicates can ever survive as a column, so the right answer is to drop
 * the duplicates at the boundary rather than push composite-key gymnastics
 * into every column-iterating component.
 */
export function sortQueryIds(queryIds: readonly string[]): string[] {
  const seen = new Set<string>();
  const unique: string[] = [];
  for (const id of queryIds) {
    if (seen.has(id)) continue;
    seen.add(id);
    unique.push(id);
  }
  return unique.sort(compareQueryIds);
}

export function queryDisplayLabel(queryId: string): string {
  return queryId;
}

const QUERY_COLUMN_LABELS: Record<string, string> = {
  result_id: "Result ID",
  benchmark: "Benchmark",
  platform: "Platform",
  scale_factor: "Scale",
  run_date: "Run date",
  power_score: "Power score (higher is better)",
  total_duration_s: "Total duration",
  geomean_ms: "Geomean latency (lower is better)",
  display_geomean_ms: "Display geomean (lower is better)",
  query_count: "Queries",
  trust_label: "Trust tier",
  visibility: "Visibility",
  platform_version: "Platform version",
  execution_mode: "Execution mode",
  tuning_mode: "Tuning",
  tuning_hash: "Tuning hash",
  test_type: "Phase",
  validation_status: "Validation",
  cost_usd: "Cost",
  normalized_cost_usd: "Normalized cost",
  cost_model_version: "Cost model",
  cost_scope: "Cost scope",
  cost_status: "Cost status",
  deployment_class: "Deployment",
  cloud_provider: "Cloud provider",
  cloud_region: "Cloud region",
  instance_or_warehouse: "Instance / warehouse",
  storage_format: "Storage format",
};

const PUBLIC_IDENTIFIER_FACETS = new Set(["platform", "cloud_region", "instance_or_warehouse", "cost_model"]);

export function formatQueryColumnLabel(column: string): string {
  return QUERY_COLUMN_LABELS[column] ?? formatFacetDisplayValue(column, column);
}

export function formatQueryFacetValue(key: string, value: string): string {
  const trimmed = value.trim();
  if (trimmed === "") return "unknown";
  if (key === "benchmark") return humanizeBenchmark(trimmed);
  if (key === "scale_factor") return `SF ${trimmed}`;
  if (PUBLIC_IDENTIFIER_FACETS.has(key)) return trimmed;
  return formatFacetDisplayValue(key, trimmed);
}

export function formatQueryCell(column: string, value: unknown): string {
  if (value === null || value === undefined || value === "") {
    if (column === "power_score") return "No power score";
    if (column === "geomean_ms" || column === "display_geomean_ms") return "No timing recorded";
    if (column === "total_duration_s") return "No duration recorded";
    if (column === "cost_usd" || column === "normalized_cost_usd") return "No cost recorded";
    return "Not recorded";
  }
  if (column === "run_date") return formatRunDate(value);
  if (column === "power_score") return typeof value === "number" ? formatPowerScore(value).valueText : String(value);
  if (column === "geomean_ms" || column === "display_geomean_ms") {
    return typeof value === "number" ? formatLatencyMs(value).valueText : String(value);
  }
  if (column === "total_duration_s") {
    const seconds = typeof value === "number" ? value : Number(value);
    return Number.isFinite(seconds) ? formatDurationSeconds(seconds).valueText : String(value);
  }
  if (column === "cost_usd" || column === "normalized_cost_usd") {
    return typeof value === "number" ? formatUsd(value).valueText : String(value);
  }
  if (typeof value === "string") return formatQueryFacetValue(column, value);
  if (column === "scale_factor") return `SF ${value}`;
  return formatPlainCell(value);
}

function formatRunDate(value: unknown): string {
  const text = String(value);
  return text.length >= 10 ? text.slice(0, 10) : text;
}

function formatPlainCell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return formatPlainNumber(value).valueText;
  return String(value);
}
