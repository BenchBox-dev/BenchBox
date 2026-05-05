/**
 * Typed query helpers for the canonical browser DuckDB contract.
 *
 * Every user-visible explorer metric must originate from one of these helpers
 * (or a direct SQL query against the same attached `bench` schema). Pages must
 * not recompute display reductions, ranks, or aggregates in TypeScript -
 * canonical values live in the tables defined by
 * `docs/development/browser-duckdb-schema.sql`.
 */

import { queryRows } from "@/db";
import type { FacetWhereClause } from "@/lib/facetModel";
import type {
  BenchmarkSummary,
  CostDeploymentFields,
  DetailResult,
  Environment,
  MetaCohort,
  MetaLeaderboard,
  MetaPlatform,
  MetaRank,
  PercentileStats,
  PlatformRow,
  QueryDisplayTiming,
  QueryTiming,
} from "@/types";

// ---------------------------------------------------------------------------
// Row shapes - one-to-one with the DDL in browser-duckdb-schema.sql
// ---------------------------------------------------------------------------

export interface ResultRow extends CostDeploymentFields {
  result_id: string;
  benchmark: string;
  scale_factor: number;
  platform: string;
  platform_id: string;
  driver_version: string | null;
  run_date: string;
  power_score: number | null;
  total_duration_s: number;
  geomean_ms: number | null;
  display_geomean_ms: number | null;
  query_count: number;
  trust_label: string;
  visibility: string;
  platform_version: string | null;
  execution_mode: string | null;
  tuning_mode: string | null;
  tuning_hash: string | null;
  test_type: string | null;
  validation_status: string | null;
  cost_usd: number | null;
  compliance_class: string | null;
  is_ranking_eligible: boolean;
  has_plans: boolean;
  plans_published: boolean;
  has_tuning: boolean;
  bundle_download_url: string;
}

export interface ResultDetailMetricsRow extends Omit<ResultRow, "is_ranking_eligible" | "visibility"> {
  visibility: string;
  os: string | null;
  arch: string | null;
  cpu_count: number | null;
  memory_gb: number | null;
  python: string | null;
}

export interface QueryDisplayTimingRow {
  result_id: string;
  query_id: string;
  display_ms: number | null;
  sample_count: number;
}

export interface QueryExecutionRow {
  result_id: string;
  query_id: string;
  duration_ms: number;
  status: string;
  run_type: string | null;
  iter: number | null;
  stream: number | null;
}

export interface BenchmarkMatrixCellRow {
  benchmark: string;
  scale_factor: number;
  phase: string;
  result_id: string;
  platform_id: string;
  query_id: string;
  display_ms: number | null;
}

export interface BenchmarkRankingRow extends CostDeploymentFields {
  benchmark: string;
  scale_factor: number;
  phase: string;
  result_id: string;
  platform_id: string;
  platform: string;
  short_id: string;
  trust_label: string;
  platform_version?: string | null;
  validation_status?: string | null;
  tuning_mode: string | null;
  tuning_hash: string | null;
  execution_mode: string | null;
  compliance_class: string | null;
  run_date: string;
  is_ranking_eligible: boolean;
  power_score: number | null;
  display_geomean_ms: number | null;
  sample_geomean_ms: number | null;
  cost_usd: number | null;
  primary_metric: string;
  primary_order: "asc" | "desc";
  rank: number | null;
  total_in_cohort: number;
  percentile_p50: number | null;
  percentile_p90: number | null;
  percentile_p95: number | null;
  percentile_p99: number | null;
  speedup_vs_best: number | null;
  speedup_vs_slowest_in_cohort: number | null;
}

export interface PlatformIndexRowRow extends CostDeploymentFields {
  result_id: string;
  short_id: string;
  benchmark: string;
  scale_factor: number;
  phase: string;
  platform: string;
  platform_id: string;
  driver_version: string | null;
  run_date: string;
  power_score: number | null;
  total_duration_s: number;
  geomean_ms: number | null;
  display_geomean_ms: number | null;
  query_count: number;
  trust_label: string;
  validation_status?: string | null;
  tuning_mode: string | null;
  execution_mode: string | null;
  compliance_class: string | null;
  cost_usd: number | null;
  primary_metric: string;
}

export interface CohortMetadataRow {
  cohort_key: string;
  benchmark: string;
  scale_factor: number;
  phase: string;
  cohort_label: string;
  cohort_href: string;
  /** Count of ranking-eligible rows with non-null primary metrics. */
  platform_count: number;
  primary_metric: string;
  primary_order: "asc" | "desc";
  platform_id: string;
  platform: string;
  result_id: string;
  short_id: string;
  tuning_mode: string | null;
  trust_label: string;
  rank: number | null;
  metric_value: number | null;
  speedup_vs_best: number | null;
}

export interface MetaLeaderboardRow {
  platform_id: string;
  platform: string;
  avg_rank: number | null;
  n_cohorts: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const RESULTS_SNAPSHOT_PATH = "/results/data/results.duckdb";
const snapshotQueryCache = new Map<string, Promise<unknown>>();

interface SnapshotRowsQuery {
  sql: string;
  params?: readonly unknown[];
}

interface SnapshotQueryCacheOptions<T> {
  cacheResult?: (result: T) => boolean;
}

interface SnapshotRowsCacheOptions {
  cacheEmpty?: boolean;
}

function currentSnapshotCacheKey(): string {
  if (typeof window === "undefined") return RESULTS_SNAPSHOT_PATH;
  return new URL(RESULTS_SNAPSHOT_PATH, window.location.origin).href;
}

function memoizedSnapshotQuery<T>(
  key: string,
  loader: () => Promise<T>,
  options: SnapshotQueryCacheOptions<T> = {},
): Promise<T> {
  const cacheKey = `${currentSnapshotCacheKey()}\u0000${key}`;
  const cached = snapshotQueryCache.get(cacheKey);
  if (cached) return cached as Promise<T>;

  const promise = loader()
    .then((result) => {
      if (options.cacheResult && !options.cacheResult(result)) {
        snapshotQueryCache.delete(cacheKey);
      }
      return result;
    })
    .catch((error: unknown) => {
      snapshotQueryCache.delete(cacheKey);
      throw error;
    });
  snapshotQueryCache.set(cacheKey, promise);
  return promise;
}

export function clearDuckdbQueryCachesForTests() {
  snapshotQueryCache.clear();
}

export function memoizedSnapshotQueryRows<T>(
  key: string,
  query: SnapshotRowsQuery,
  options: SnapshotRowsCacheOptions = {},
): Promise<T[]> {
  const params = query.params ?? [];
  return memoizedSnapshotQuery(
    `rows:${key}\u0000${query.sql}\u0000${JSON.stringify(params)}`,
    () => (params.length > 0 ? queryRows<T>(query.sql, [...params]) : queryRows<T>(query.sql)),
    {
      cacheResult:
        options.cacheEmpty === false
          ? (rows) => rows.length > 0
          : undefined,
    },
  );
}

export async function listResults(where: FacetWhereClause = { sql: "", params: [] }): Promise<ResultRow[]> {
  const sql = `SELECT * FROM bench.results ${where.sql} ORDER BY run_date DESC`;
  return memoizedSnapshotQueryRows<ResultRow>("list-results", { sql, params: where.params }, { cacheEmpty: false });
}

export async function getResultDetailMetrics(resultId: string): Promise<ResultDetailMetricsRow | null> {
  const rows = await queryRows<ResultDetailMetricsRow>(
    "SELECT * FROM bench.result_detail_metrics WHERE result_id = ?",
    [resultId],
  );
  return rows[0] ?? null;
}

export async function getQueryDisplayTimings(resultId: string): Promise<QueryDisplayTimingRow[]> {
  return queryRows<QueryDisplayTimingRow>(
    "SELECT result_id, query_id, display_ms, sample_count" +
      " FROM bench.query_display_timings" +
      " WHERE result_id = ?" +
      " ORDER BY query_id",
    [resultId],
  );
}

export async function getQueryExecutions(resultId: string): Promise<QueryExecutionRow[]> {
  return queryRows<QueryExecutionRow>(
    "SELECT result_id, query_id, duration_ms, status, run_type, iter, stream" +
      " FROM bench.query_executions" +
      " WHERE result_id = ?" +
      " ORDER BY query_id," +
      " CASE WHEN stream IS NULL THEN 0 ELSE stream END," +
      " CASE WHEN iter IS NULL THEN 0 ELSE iter END",
    [resultId],
  );
}

/**
 * Compose a DetailResult from the canonical DuckDB tables.
 *
 * Returns null when the result_id is not present in `result_detail_metrics`.
 * display_timings and queries are read verbatim from their canonical tables;
 * this helper performs only shape pivoting (wide-row → nested Environment
 * object, row arrays with presentation-ready fields).
 */
export async function getDetailResult(resultId: string): Promise<DetailResult | null> {
  const [wide, timingRows, executionRows] = await Promise.all([
    getResultDetailMetrics(resultId),
    getQueryDisplayTimings(resultId),
    getQueryExecutions(resultId),
  ]);
  if (!wide) return null;

  const environment: Environment = {};
  if (wide.os !== null) environment.os = wide.os;
  if (wide.arch !== null) environment.arch = wide.arch;
  if (wide.cpu_count !== null) environment.cpu_count = wide.cpu_count;
  if (wide.memory_gb !== null) environment.memory_gb = wide.memory_gb;
  if (wide.python !== null) environment.python = wide.python;

  const display_timings: QueryDisplayTiming[] = timingRows.map((r) => ({
    query_id: r.query_id,
    display_ms: r.display_ms,
    sample_count: r.sample_count,
  }));

  const queries: QueryTiming[] = executionRows.map((r) => ({
    query_id: r.query_id,
    duration_ms: r.duration_ms,
    status: r.status === "pass" || r.status === "fail" ? r.status : "fail",
    run_type: r.run_type,
    iter: r.iter,
    stream: r.stream,
  }));

  return {
    result_id: wide.result_id,
    benchmark: wide.benchmark,
    scale_factor: wide.scale_factor,
    platform: wide.platform,
    platform_id: wide.platform_id,
    driver_version: wide.driver_version,
    run_date: wide.run_date,
    total_duration_s: wide.total_duration_s,
    geomean_ms: wide.geomean_ms,
    display_geomean_ms: wide.display_geomean_ms,
    power_score: wide.power_score,
    environment,
    queries,
    display_timings,
    has_plans: wide.has_plans,
    plans_published: wide.plans_published,
    has_tuning: wide.has_tuning,
    bundle_download_url: wide.bundle_download_url,
    trust_label: wide.trust_label,
    visibility: wide.visibility,
    platform_version: wide.platform_version,
    execution_mode: wide.execution_mode,
    tuning_mode: wide.tuning_mode,
    tuning_hash: wide.tuning_hash,
    test_type: wide.test_type,
    validation_status: wide.validation_status,
    cost_usd: wide.cost_usd,
    normalized_cost_usd: wide.normalized_cost_usd,
    cost_model_version: wide.cost_model_version,
    cost_model_source: wide.cost_model_source,
    cost_scope: wide.cost_scope,
    cost_status: wide.cost_status,
    billing_unit: wide.billing_unit,
    pricing_region: wide.pricing_region,
    cloud_provider: wide.cloud_provider,
    cloud_region: wide.cloud_region,
    instance_type: wide.instance_type,
    warehouse_size: wide.warehouse_size,
    node_count: wide.node_count,
    cluster_size: wide.cluster_size,
    storage_format: wide.storage_format,
    storage_tier: wide.storage_tier,
    compliance_class: wide.compliance_class,
  };
}

export async function getBenchmarkMatrixCells(
  benchmark: string,
  scaleFactor: number,
  phase: string,
): Promise<BenchmarkMatrixCellRow[]> {
  return queryRows<BenchmarkMatrixCellRow>(
    "SELECT benchmark, scale_factor, phase, result_id, platform_id, query_id, display_ms" +
      " FROM bench.benchmark_matrix_cells" +
      " WHERE benchmark = ? AND scale_factor = ? AND phase = ?" +
      " ORDER BY platform_id, query_id",
    [benchmark, scaleFactor, phase],
  );
}

export async function getBenchmarkRanking(
  benchmark: string,
  scaleFactor: number,
  phase: string,
): Promise<BenchmarkRankingRow[]> {
  return queryRows<BenchmarkRankingRow>(
    "SELECT br.*, r.normalized_cost_usd, r.cost_model_version, r.cost_model_source," +
      " r.cost_scope, r.cost_status, r.billing_unit, r.pricing_region," +
      " r.deployment_class, r.cloud_provider, r.cloud_region, r.instance_or_warehouse," +
      " r.storage_format" +
      " FROM bench.benchmark_rankings br" +
      " LEFT JOIN bench.results r USING (result_id)" +
      " WHERE br.benchmark = ? AND br.scale_factor = ? AND br.phase = ?" +
      " ORDER BY br.rank NULLS LAST, br.platform_id",
    [benchmark, scaleFactor, phase],
  );
}

/**
 * Fetch phase-duration rows and return them grouped by result_id.
 *
 * Each result_id maps to a `{ phase → duration_s }` record. result_ids with
 * no phase rows are omitted from the map - the caller is expected to treat
 * a missing entry as null `phase_durations`.
 */
export async function getResultPhaseDurations(resultIds: string[]): Promise<Map<string, Record<string, number>>> {
  const result = new Map<string, Record<string, number>>();
  if (resultIds.length === 0) return result;
  const placeholders = resultIds.map(() => "?").join(", ");
  const rows = await queryRows<{ result_id: string; phase: string; duration_s: number }>(
    `SELECT result_id, phase, duration_s FROM bench.result_phase_durations` + ` WHERE result_id IN (${placeholders})`,
    resultIds,
  );
  for (const row of rows) {
    let bucket = result.get(row.result_id);
    if (!bucket) {
      bucket = {};
      result.set(row.result_id, bucket);
    }
    bucket[row.phase] = row.duration_s;
  }
  return result;
}

/**
 * Compose a BenchmarkSummary from the canonical DuckDB tables.
 *
 * Returns null when the cohort has no rankings or no matrix cells - callers
 * should render an empty state. All numeric values (ranks, geomeans,
 * percentiles, per-query display_ms) are read verbatim from the pipeline-
 * pre-computed tables; this helper performs only shape pivoting (row-major
 * → `{platforms[], query_ids[]}`), not any reduction.
 */
export async function getBenchmarkSummaryFromDuckDB(
  benchmark: string,
  scaleFactor: number,
  phase: string,
): Promise<BenchmarkSummary | null> {
  return memoizedSnapshotQuery(
    `benchmark-summary:${benchmark}\u0000${scaleFactor}\u0000${phase}`,
    () => loadBenchmarkSummaryFromDuckDB(benchmark, scaleFactor, phase),
  );
}

async function loadBenchmarkSummaryFromDuckDB(
  benchmark: string,
  scaleFactor: number,
  phase: string,
): Promise<BenchmarkSummary | null> {
  const [rankingRows, cellRows] = await Promise.all([
    getBenchmarkRanking(benchmark, scaleFactor, phase),
    getBenchmarkMatrixCells(benchmark, scaleFactor, phase),
  ]);
  if (rankingRows.length === 0) return null;

  const phaseDurationsByResult = await getResultPhaseDurations(rankingRows.map((r) => r.result_id));

  const queryIds = [...new Set(cellRows.map((c) => c.query_id))].sort();
  const cellsByResult = new Map<string, Map<string, number | null>>();
  for (const cell of cellRows) {
    let byQuery = cellsByResult.get(cell.result_id);
    if (!byQuery) {
      byQuery = new Map();
      cellsByResult.set(cell.result_id, byQuery);
    }
    byQuery.set(cell.query_id, cell.display_ms);
  }

  const platforms: PlatformRow[] = rankingRows.map((row) => {
    const byQuery = cellsByResult.get(row.result_id);
    const timings: Record<string, number | null> = {};
    for (const qid of queryIds) {
      timings[qid] = byQuery?.get(qid) ?? null;
    }
    const percentileStats: PercentileStats | null =
      row.percentile_p50 !== null &&
      row.percentile_p90 !== null &&
      row.percentile_p95 !== null &&
      row.percentile_p99 !== null
        ? {
            p50: row.percentile_p50,
            p90: row.percentile_p90,
            p95: row.percentile_p95,
            p99: row.percentile_p99,
          }
        : null;
    return {
      result_id: row.result_id,
      short_id: row.short_id,
      platform_id: row.platform_id,
      platform: row.platform,
      platform_version: row.platform_version ?? null,
      tuning_mode: row.tuning_mode,
      tuning_hash: row.tuning_hash,
      execution_mode: row.execution_mode,
      trust_label: row.trust_label,
      validation_status: row.validation_status ?? null,
      run_date: row.run_date,
      is_ranking_eligible: row.is_ranking_eligible,
      power_score: row.power_score,
      display_geomean_ms: row.display_geomean_ms,
      sample_geomean_ms: row.sample_geomean_ms,
      cost_usd: row.cost_usd,
      normalized_cost_usd: row.normalized_cost_usd,
      cost_model_version: row.cost_model_version,
      cost_model_source: row.cost_model_source,
      cost_scope: row.cost_scope,
      cost_status: row.cost_status,
      billing_unit: row.billing_unit,
      pricing_region: row.pricing_region,
      deployment_class: row.deployment_class,
      cloud_provider: row.cloud_provider,
      cloud_region: row.cloud_region,
      instance_or_warehouse: row.instance_or_warehouse,
      storage_format: row.storage_format,
      compliance_class: row.compliance_class,
      percentile_stats: percentileStats,
      phase_durations: phaseDurationsByResult.get(row.result_id) ?? null,
      timings,
    };
  });

  const first = rankingRows[0]!;
  return {
    benchmark,
    scale_factor: scaleFactor,
    phase,
    query_ids: queryIds,
    platforms,
    cell_reduction: "median_successful_measurement_ms",
    ranking: {
      primary_metric: first.primary_metric,
      secondary_metric: first.primary_metric === "power_score" ? "display_geomean_ms" : "power_score",
      primary_order: first.primary_order,
    },
  };
}

export async function getPlatformIndexRows(platformId?: string): Promise<PlatformIndexRowRow[]> {
  return memoizedSnapshotQuery(
    `platform-index:${platformId ?? "*"}`,
    () => loadPlatformIndexRows(platformId),
    { cacheResult: (rows) => rows.length > 0 },
  );
}

function loadPlatformIndexRows(platformId?: string): Promise<PlatformIndexRowRow[]> {
  const sql =
    "SELECT" +
    " r.result_id," +
    " COALESCE(si.short_id, '') AS short_id," +
    " r.benchmark," +
    " r.scale_factor," +
    " CASE WHEN br.phase IS NOT NULL THEN br.phase WHEN r.test_type IS NOT NULL THEN r.test_type ELSE 'power' END AS phase," +
    " r.platform," +
    " r.platform_id," +
    " r.driver_version," +
    " r.run_date," +
    " r.power_score," +
    " r.total_duration_s," +
    " r.geomean_ms," +
    " r.display_geomean_ms," +
    " r.query_count," +
    " r.trust_label," +
    " r.validation_status," +
    " r.tuning_mode," +
    " r.execution_mode," +
    " r.compliance_class," +
    " r.cost_usd," +
    " r.normalized_cost_usd," +
    " r.cost_model_version," +
    " r.cost_model_source," +
    " r.cost_scope," +
    " r.cost_status," +
    " r.billing_unit," +
    " r.pricing_region," +
    " r.deployment_class," +
    " r.cloud_provider," +
    " r.cloud_region," +
    " r.instance_or_warehouse," +
    " r.storage_format," +
    " CASE WHEN br.primary_metric IS NOT NULL THEN br.primary_metric WHEN r.power_score IS NOT NULL THEN 'power_score' ELSE 'display_geomean_ms' END" +
    " AS primary_metric" +
    " FROM bench.results r" +
    " LEFT JOIN bench.short_ids si ON si.result_id = r.result_id" +
    " LEFT JOIN bench.benchmark_rankings br ON br.result_id = r.result_id";
  if (platformId === undefined) {
    return queryRows<PlatformIndexRowRow>(`${sql} ORDER BY r.run_date DESC`);
  }
  return queryRows<PlatformIndexRowRow>(`${sql} WHERE r.platform_id = ? ORDER BY r.run_date DESC`, [platformId]);
}

export async function getCohort(cohortKey: string): Promise<CohortMetadataRow[]> {
  return memoizedSnapshotQuery(
    `cohort:${cohortKey}`,
    () =>
      queryRows<CohortMetadataRow>(
        "SELECT * FROM bench.cohort_metadata" +
          " WHERE cohort_key = ?" +
          " ORDER BY rank NULLS LAST, platform_id, result_id",
        [cohortKey],
      ),
  );
}

export async function getMetaLeaderboard(): Promise<MetaLeaderboardRow[]> {
  return memoizedSnapshotQuery(
    "meta-leaderboard",
    () =>
      queryRows<MetaLeaderboardRow>(
        "SELECT platform_id, platform, avg_rank, n_cohorts" +
          " FROM bench.meta_leaderboard" +
          " ORDER BY avg_rank NULLS LAST, platform_id",
      ),
  );
}

/**
 * Load the full nested MetaLeaderboard shape used by the Home page.
 *
 * Combines `bench.meta_leaderboard` (per-platform avg_rank/n_cohorts) with
 * `bench.cohort_metadata` (every publishable variant row per cohort) and
 * pivots them into the TS render shape. Returns null when no cohorts exist
 * (fresh corpus with no ≥2-platform cohorts yet).
 *
 * The pipeline already enforces "best rank wins" when the same platform has
 * multiple variants in a cohort (see `_build_meta_leaderboard.platform_agg`),
 * but cohort_metadata keeps every variant. We replicate the best-rank pick
 * for the per-platform `ranks[cohort_key]` map so the Home summary row is
 * stable regardless of variant ordering on disk.
 */
export async function getMetaLeaderboardData(): Promise<MetaLeaderboard | null> {
  return memoizedSnapshotQuery("meta-leaderboard-data", loadMetaLeaderboardData);
}

async function loadMetaLeaderboardData(): Promise<MetaLeaderboard | null> {
  const [platformRows, cohortRows] = await Promise.all([
    queryRows<MetaLeaderboardRow>(
      "SELECT platform_id, platform, avg_rank, n_cohorts" +
        " FROM bench.meta_leaderboard" +
        " ORDER BY avg_rank NULLS LAST, platform_id",
    ),
    // Filter to leaderboard-eligible cohorts (≥2 rankable platforms) to match the
    // pipeline's `_build_meta_leaderboard` selection. Single-platform cohorts
    // carry no ranks and would only bloat the pivot - excluding them here
    // keeps the round-trip small on large corpora.
    queryRows<CohortMetadataRow>(
      "SELECT * FROM bench.cohort_metadata" +
        " WHERE platform_count >= 2" +
        " ORDER BY benchmark, scale_factor, phase, rank NULLS LAST, platform_id, result_id",
    ),
  ]);

  if (cohortRows.length === 0) return null;

  const cohortsByKey = new Map<string, MetaCohort>();
  // (platform_id, cohort_key) → best (lowest-rank) variant row seen so far.
  const bestByPair = new Map<string, CohortMetadataRow>();

  for (const row of cohortRows) {
    let cohort = cohortsByKey.get(row.cohort_key);
    if (!cohort) {
      cohort = {
        key: row.cohort_key,
        benchmark: row.benchmark,
        scale_factor: row.scale_factor,
        phase: row.phase,
        label: row.cohort_label,
        href: row.cohort_href,
        platform_count: row.platform_count,
        primary_metric: row.primary_metric,
        primary_order: row.primary_order,
        platforms: [],
      };
      cohortsByKey.set(row.cohort_key, cohort);
    }
    cohort.platforms!.push({
      platform_id: row.platform_id,
      platform: row.platform,
      result_id: row.result_id,
      rank: row.rank,
      metric_value: row.metric_value,
      speedup_vs_best: row.speedup_vs_best,
      primary_metric: row.primary_metric,
      primary_order: row.primary_order,
    });

    if (row.rank === null) continue;
    const pairKey = `${row.platform_id}\u0000${row.cohort_key}`;
    const prev = bestByPair.get(pairKey);
    if (prev === undefined || (prev.rank !== null && row.rank < prev.rank)) {
      bestByPair.set(pairKey, row);
    }
  }

  const ranksByPlatform = new Map<string, Record<string, MetaRank>>();
  for (const [pairKey, row] of bestByPair) {
    const pid = pairKey.split("\u0000")[0]!;
    let ranks = ranksByPlatform.get(pid);
    if (!ranks) {
      ranks = {};
      ranksByPlatform.set(pid, ranks);
    }
    ranks[row.cohort_key] = {
      rank: row.rank!,
      total: row.platform_count,
      metric_value: row.metric_value,
      speedup_vs_best: row.speedup_vs_best,
    };
  }

  const platforms: MetaPlatform[] = platformRows.map((row) => ({
    platform_id: row.platform_id,
    platform: row.platform,
    ranks: ranksByPlatform.get(row.platform_id) ?? {},
    avg_rank: row.avg_rank,
    n_cohorts: row.n_cohorts,
  }));

  return {
    // generated_at is not stored per-row in DuckDB; callers that need it can
    // read the corpus generated_at from elsewhere. Home doesn't display it.
    generated_at: "",
    cohorts: [...cohortsByKey.values()],
    platforms,
  };
}

/**
 * Return the primary metric for a benchmark by reading the DuckDB-persisted
 * ranking rows. The canonical source is the pipeline-written
 * `bench.benchmark_rankings.primary_metric` column - there is deliberately no
 * TypeScript-side family mirror here so the registry cannot drift from
 * `RANKING_METRIC_BY_FAMILY` in `benchbox/core/explorer_pipeline/models.py`.
 *
 * Falls back to `"display_geomean_ms"` only when the benchmark has no rows
 * yet (empty corpus), matching Python's `_DEFAULT_RANKING`.
 */
export async function getPrimaryMetricForBenchmark(benchmark: string): Promise<"power_score" | "display_geomean_ms"> {
  const rows = await queryRows<{ primary_metric: string }>(
    "SELECT DISTINCT primary_metric FROM bench.benchmark_rankings WHERE benchmark = ? LIMIT 1",
    [benchmark],
  );
  const metric = rows[0]?.primary_metric;
  return metric === "power_score" ? "power_score" : "display_geomean_ms";
}

const SHORT_ID_PATTERN = /^[0-9a-f]{8,}$/i;

export async function resolveShortId(id: string): Promise<string> {
  if (!SHORT_ID_PATTERN.test(id)) return id;
  const rows = await queryRows<{ result_id: string }>("SELECT result_id FROM bench.short_ids WHERE short_id = ?", [id]);
  return rows[0]?.result_id ?? id;
}

export async function toShortIds(fullIds: string[]): Promise<string[]> {
  if (fullIds.length === 0) return [];
  const placeholders = fullIds.map(() => "?").join(", ");
  const rows = await queryRows<{ short_id: string; result_id: string }>(
    `SELECT short_id, result_id FROM bench.short_ids WHERE result_id IN (${placeholders})`,
    fullIds,
  );
  const byFull = new Map(rows.map((r) => [r.result_id, r.short_id]));
  return fullIds.map((id) => byFull.get(id) ?? id);
}
