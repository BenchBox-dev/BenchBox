/**
 * Starter SQL templates for the Query workbench.
 *
 * Each template reads from the canonical ten-table DuckDB browser schema
 * defined in `docs/development/browser-duckdb-schema.sql`. Templates are
 * grouped by analyst question category so the workbench can render them
 * as section headers. Category coverage mirrors the W5 checklist in
 * `_project/TODO/.../explorer-canonical-browser-duckdb-read-model.yaml`:
 * results, per-query timings, cohort comparisons, trust/tuning
 * breakdowns, and detail drill-down.
 */

export type StarterQueryCategory =
  | "results"
  | "cost_and_deployment"
  | "per_query_timings"
  | "cohort_comparisons"
  | "trust_and_tuning"
  | "detail_drilldown";

export interface StarterQuery {
  id: string;
  category: StarterQueryCategory;
  label: string;
  description: string;
  sql: string;
}

export const STARTER_QUERY_CATEGORIES: Record<StarterQueryCategory, string> = {
  results: "Results",
  cost_and_deployment: "Cost & deployment",
  per_query_timings: "Per-query timings",
  cohort_comparisons: "Ranking comparisons",
  trust_and_tuning: "Trust & tuning",
  detail_drilldown: "Detail drill-down",
};

export const STARTER_QUERIES: StarterQuery[] = [
  {
    id: "recent_results",
    category: "results",
    label: "Recent results",
    description: "The 25 most recent result bundles with headline metrics.",
    sql: `SELECT result_id, benchmark, scale_factor, platform, run_date, power_score, display_geomean_ms
FROM bench.results
ORDER BY run_date DESC
LIMIT 25;`,
  },
  {
    id: "platform_geomean_by_benchmark",
    category: "results",
    label: "Best display geomean per platform, per benchmark",
    description: "Lowest display_geomean_ms for each (benchmark, scale_factor, platform).",
    sql: `SELECT benchmark, scale_factor, platform,
       MIN(display_geomean_ms) AS best_display_geomean_ms,
       COUNT(*)                AS runs
FROM bench.results
WHERE display_geomean_ms IS NOT NULL
GROUP BY benchmark, scale_factor, platform
ORDER BY benchmark, scale_factor, best_display_geomean_ms ASC;`,
  },
  {
    id: "normalized_cost_leaderboard",
    category: "cost_and_deployment",
    label: "Normalized cost leaderboard",
    description: "Comparable cloud rows ranked by BenchBox-computed normalized USD and deployment shape.",
    sql: `SELECT benchmark, scale_factor, platform,
       normalized_cost_usd, cost_status, cost_model_version,
       cloud_provider, cloud_region, warehouse_size, instance_type, storage_format
FROM bench.results
WHERE cost_status = 'normalized'
ORDER BY normalized_cost_usd ASC NULLS LAST
LIMIT 50;`,
  },
  {
    id: "cost_status_by_cloud",
    category: "cost_and_deployment",
    label: "Cost status by cloud and region",
    description: "Counts normalized, local-not-applicable, and unavailable cost rows by emitted deployment facets.",
    sql: `SELECT cost_status,
       COALESCE(cloud_provider, 'unknown') AS cloud_provider,
       COALESCE(cloud_region, pricing_region, 'unknown') AS region,
       cost_model_version,
       COUNT(*) AS runs
FROM bench.results
GROUP BY
       cost_status,
       COALESCE(cloud_provider, 'unknown'),
       COALESCE(cloud_region, pricing_region, 'unknown'),
       cost_model_version
ORDER BY runs DESC, cost_status, cloud_provider, region;`,
  },
  {
    id: "slowest_queries_for_platform",
    category: "per_query_timings",
    label: "Slowest queries for a platform",
    description: "Top 20 per-query display timings for DuckDB on TPC-H SF0.1. Edit the WHERE clause to retarget.",
    sql: `SELECT t.query_id, t.display_ms, t.sample_count, r.result_id
FROM bench.query_display_timings t
JOIN bench.results r USING (result_id)
WHERE r.benchmark = 'tpch'
  AND r.scale_factor = 0.1
  AND r.platform_id = 'duckdb'
ORDER BY t.display_ms DESC NULLS LAST
LIMIT 20;`,
  },
  {
    id: "query_execution_samples",
    category: "per_query_timings",
    label: "All execution samples for a query",
    description: "Individual iter/stream samples for Q1 on a specific result. Change the result_id and query_id as needed.",
    sql: `SELECT iter, stream, run_type, duration_ms, status
FROM bench.query_executions
WHERE result_id = (SELECT result_id FROM bench.results ORDER BY run_date DESC LIMIT 1)
  AND query_id = 'Q1'
ORDER BY iter, stream;`,
  },
  {
    id: "cohort_leaderboard",
    category: "cohort_comparisons",
    label: "Ranking leaderboard",
    description: "Ranked platforms within a (benchmark, scale_factor, phase) ranking using the persisted ranks.",
    sql: `SELECT rank, platform, platform_version, tuning_mode, trust_label,
       power_score, display_geomean_ms, cost_usd
FROM bench.benchmark_rankings
WHERE benchmark = 'tpch'
  AND scale_factor = 0.1
  AND phase = 'power'
ORDER BY rank NULLS LAST, display_geomean_ms ASC;`,
  },
  {
    id: "cohort_query_matrix",
    category: "cohort_comparisons",
    label: "Ranking query-timing matrix",
    description: "Platform × query timing grid for a ranking - the same cells used by the benchmark matrix UI.",
    sql: `SELECT c.platform_id, c.query_id, c.display_ms
FROM bench.benchmark_matrix_cells c
WHERE c.benchmark = 'tpch'
  AND c.scale_factor = 0.1
  AND c.phase = 'power'
ORDER BY c.platform_id, c.query_id;`,
  },
  {
    id: "cross_cohort_platform_presence",
    category: "cohort_comparisons",
    label: "Platform coverage across rankings",
    description: "How many rankings each platform appears in, via the meta-leaderboard's cohort_metadata table.",
    sql: `SELECT platform_id, platform,
       COUNT(DISTINCT cohort_key) AS cohorts_entered,
       AVG(rank)                  AS avg_rank
FROM bench.cohort_metadata
WHERE rank IS NOT NULL
GROUP BY platform_id, platform
ORDER BY cohorts_entered DESC, avg_rank ASC NULLS LAST;`,
  },
  {
    id: "trust_tuning_breakdown",
    category: "trust_and_tuning",
    label: "Result counts by trust × tuning",
    description: "How many runs live at each (trust_label, tuning_mode) crossing.",
    sql: `SELECT trust_label, COALESCE(tuning_mode, '-') AS tuning_mode, COUNT(*) AS runs
FROM bench.results
GROUP BY trust_label, tuning_mode
ORDER BY trust_label, tuning_mode;`,
  },
  {
    id: "ranking_eligible_only",
    category: "trust_and_tuning",
    label: "Ranking-eligible rows only",
    description: "Filter to results that meet the canonical ranking-eligibility rule used by the leaderboard.",
    sql: `SELECT benchmark, scale_factor, platform, trust_label, tuning_mode,
       display_geomean_ms, power_score, run_date
FROM bench.results
WHERE is_ranking_eligible = TRUE
ORDER BY benchmark, scale_factor, display_geomean_ms ASC NULLS LAST;`,
  },
  {
    id: "compliance_class_mix",
    category: "trust_and_tuning",
    label: "Compliance class mix per benchmark",
    description: "Breakdown of compliance_class values per benchmark - spots rankings dominated by unofficial runs.",
    sql: `SELECT benchmark, COALESCE(compliance_class, 'unclassified') AS compliance_class,
       COUNT(*) AS runs
FROM bench.results
GROUP BY benchmark, compliance_class
ORDER BY benchmark, runs DESC;`,
  },
  {
    id: "detail_query_timings",
    category: "detail_drilldown",
    label: "Detail page timings",
    description: "The display_ms timings shown on a ResultDetail page for the most recent result.",
    sql: `WITH latest AS (
  SELECT result_id FROM bench.results ORDER BY run_date DESC LIMIT 1
)
SELECT query_id, display_ms, sample_count
FROM bench.query_display_timings
WHERE result_id = (SELECT result_id FROM latest)
ORDER BY query_id;`,
  },
  {
    id: "detail_phase_durations",
    category: "detail_drilldown",
    label: "Per-phase durations for a result",
    description: "Phase-level durations (load/power/throughput/…) for the most recent result.",
    sql: `WITH latest AS (
  SELECT result_id FROM bench.results ORDER BY run_date DESC LIMIT 1
)
SELECT phase, duration_s
FROM bench.result_phase_durations
WHERE result_id = (SELECT result_id FROM latest)
ORDER BY duration_s DESC;`,
  },
];

export function starterQueriesByCategory(): Record<StarterQueryCategory, StarterQuery[]> {
  const grouped: Record<StarterQueryCategory, StarterQuery[]> = {
    results: [],
    cost_and_deployment: [],
    per_query_timings: [],
    cohort_comparisons: [],
    trust_and_tuning: [],
    detail_drilldown: [],
  };
  for (const query of STARTER_QUERIES) grouped[query.category].push(query);
  return grouped;
}
