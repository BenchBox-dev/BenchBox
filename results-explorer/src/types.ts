// ---------------------------------------------------------------------------
// Detail result types - assembled in the browser from DuckDB rows via
// getDetailResult() in lib/duckdbQueries.ts.
// ---------------------------------------------------------------------------

export interface Environment {
  os?: string;
  arch?: string;
  cpu_count?: number;
  memory_gb?: number;
  python?: string;
  cpu_model?: string;
  cpu_family?: string;
  cpu_identity_provenance?: "measured" | "user_attested" | "inferred";
  [key: string]: string | number | boolean | null | undefined;
}

export interface QueryTiming {
  query_id: string;
  duration_ms: number;
  status: "pass" | "fail";
  run_type: string | null;
  iter: number | null;
  stream: number | null;
}

export interface QueryDisplayTiming {
  query_id: string;
  display_ms: number | null;
  sample_count: number;
  is_valid_display_timing: boolean;
  timing_exclusion_reason: string | null;
}

export interface CostDeploymentFields {
  normalized_cost_usd?: number | null;
  cost_model_version?: string | null;
  cost_model_source?: string | null;
  cost_scope?: string | null;
  cost_status?: string | null;
  billing_unit?: string | null;
  pricing_region?: string | null;
  deployment_class?: string | null;
  cloud_provider?: string | null;
  cloud_region?: string | null;
  instance_or_warehouse?: string | null;
  instance_type?: string | null;
  warehouse_size?: string | null;
  node_count?: number | null;
  cluster_size?: string | null;
  storage_format?: string | null;
  storage_tier?: string | null;
}

export interface DetailResult extends CostDeploymentFields {
  result_id: string;
  benchmark: string;
  scale_factor: number;
  platform: string;
  platform_id: string;
  driver_version: string | null;
  run_date: string;
  total_duration_s: number;
  geomean_ms: number | null;
  display_geomean_ms: number | null;
  power_score: number | null;
  has_display_timing: boolean;
  logical_query_count?: number;
  valid_query_count: number;
  missing_query_count: number;
  zero_timing_count: number;
  display_exclusion_reason: string | null;
  comparison_exclusion_reason: string | null;
  ranking_exclusion_reason: string | null;
  environment: Environment;
  queries: QueryTiming[];
  display_timings: QueryDisplayTiming[];
  has_plans: boolean;
  // True only when the explorer pipeline has actually copied a *.plans.json
  // sidecar to the published bundles directory. ``has_plans`` reflects only
  // source-side detection and is unsafe to use as a download-link gate
  // because the pipeline excludes plan sidecars from bundle discovery
  // (see _project/scripts/explorer_pipeline/pipeline.py). Optional so older
  // SQL paths that don't yet emit this field default to undefined → falsy.
  plans_published?: boolean | null;
  has_tuning: boolean;
  bundle_download_url: string;
  trust_label: string;
  visibility: string;
  // How the run was paid for. "unspecified" when the bundle declares no
  // funding. Orthogonal to trust_label: a vendor-supplied result can be
  // employer-funded, and a community submission can be vendor-sponsored.
  funding: string;
  // Extended fields (null for bundles predating these fields)
  platform_version: string | null;
  execution_mode: string | null;
  tuning_mode: string | null;
  // Self-derived, display-only tuning fingerprint. Kept for legacy bundles;
  // never a join/dedup/grouping key.
  tuning_hash: string | null;
  // ADR-1 bundle-emitted tuning identities, ingested verbatim from the
  // bundle's platform.tuning summary (see explorer_pipeline/transformer.py):
  // the canonical requested-config hash and the physical applied-ledger hash.
  // Null/undefined for legacy bundles predating these fields (optional so
  // fixtures/factories and SQL paths predating them default to undefined).
  // Display-only, like tuning_hash.
  requested_config_hash?: string | null;
  applied_ledger_hash?: string | null;
  // ADR-1 tuning verified-state, ingested verbatim from platform.tuning:
  // not_applicable / noop / applied_unverified / applied_verified / failed.
  // applied_verified is earned only via the post-load introspection receipt's
  // corroboration. Null/undefined for legacy bundles predating the applied
  // ledger (treated as "unknown"). Distinct from validation_status (run/query).
  tuning_validation_status?: string | null;
  // ADR-1 per-statement introspection receipt, carried verbatim from the
  // {stem}.applied.json companion's "receipt" sub-object as an opaque JSON
  // string (see explorer_pipeline/transformer.py::_applied_receipt). The
  // explorer parses it only to display the recorded verdicts and NEVER
  // recomputes a verdict or a corroboration decision from it. Null/undefined
  // when no receipt was published (introspection did not run, legacy bundle).
  applied_receipt?: string | null;
  // ADR-3 seam: explicit tuning-policy generation marker, ingested verbatim
  // from platform.tuning (see explorer_pipeline/transformer.py); never derived
  // from benchbox_version. Null/undefined for legacy bundles predating the
  // field -- the ComparabilityReceipt treats that absence as the "pre-seam"
  // generation. Display-only, like the hashes above; never a match key.
  tuning_policy_generation?: string | null;
  test_type: string | null;
  validation_status: string | null;
  cost_usd: number | null;
  compliance_class: string | null;
  // ADR-2 §3: platform-rendered physical tuning mechanisms and, for
  // platforms that expose one, the physical rendering strategy used. Empty
  // array / null / undefined for bundles that never recorded a logical
  // tuning profile. Optional so existing fixtures/factories predating this
  // field don't need updating.
  physical_mechanisms?: string[];
  physical_rendering_id?: string | null;
}

// ---------------------------------------------------------------------------
// Benchmark summary types - rows are read from DuckDB tables such as
// benchmark_matrix_cells and benchmark_rankings (see results.duckdb).
// ---------------------------------------------------------------------------

export interface RankingConfig {
  primary_metric: string;
  secondary_metric: string;
  primary_order: "asc" | "desc";
}

/** P50/P90/P95/P99 of per-query display_ms medians for a single platform. */
export interface PercentileStats {
  p50: number;
  p90: number;
  p95: number;
  p99: number;
}

export interface PlatformRow extends CostDeploymentFields {
  result_id: string;
  /** 8+ hex-char sha256 prefix for compact Compare URLs; "" when the
   *  pipeline has no short-ID map for this row. */
  short_id: string;
  platform_id: string;
  platform: string;
  platform_version: string | null;
  tuning_mode: string | null;
  tuning_hash: string | null;
  execution_mode: string | null;
  trust_label: string;
  /** Funding disclosure; "unspecified" when the bundle declares none. */
  funding: string;
  validation_status?: string | null;
  run_date: string;
  is_ranking_eligible: boolean;
  has_display_timing: boolean;
  logical_query_count?: number;
  valid_query_count: number;
  missing_query_count: number;
  zero_timing_count: number;
  display_exclusion_reason: string | null;
  comparison_exclusion_reason: string | null;
  ranking_exclusion_reason: string | null;
  power_score: number | null;
  display_geomean_ms: number | null;
  sample_geomean_ms: number | null;
  cost_usd: number | null;
  compliance_class: string | null;
  /** Null for rows produced by pipeline versions that predate this field. */
  percentile_stats: PercentileStats | null;
  /** Phase durations in seconds keyed by phase name; null for pre-pipeline rows. */
  phase_durations: Record<string, number> | null;
  timings: Record<string, number | null>;
  timing_eligibility: Record<string, Pick<QueryDisplayTiming, "is_valid_display_timing" | "timing_exclusion_reason">>;
}

export interface BenchmarkSummary {
  benchmark: string;
  scale_factor: number;
  phase: string;
  query_ids: string[];
  platforms: PlatformRow[];
  cell_reduction: string;
  ranking: RankingConfig | null;
}

// ---------------------------------------------------------------------------
// Meta-leaderboard - render shape for the Home cross-benchmark panel.
// Sourced from bench.meta_leaderboard + bench.cohort_metadata via
// `getMetaLeaderboardData()` in lib/duckdbQueries.ts.
// ---------------------------------------------------------------------------

export interface MetaRank {
  rank: number;
  total: number;
  metric_value?: number | null;
  speedup_vs_best?: number | null;
}

export interface MetaPlatform {
  platform_id: string;
  platform: string;
  /** cohort_key → {rank, total} for cohorts the platform participated in. */
  ranks: Record<string, MetaRank>;
  avg_rank: number | null;
  n_cohorts: number;
}

export interface MetaCohortPlatform {
  platform_id: string;
  platform: string;
  result_id: string;
  rank: number | null;
  metric_value: number | null;
  speedup_vs_best: number | null;
  primary_metric: string;
  primary_order: "asc" | "desc";
  has_display_timing: boolean;
  logical_query_count?: number;
  valid_query_count: number;
  missing_query_count: number;
  zero_timing_count: number;
  display_exclusion_reason: string | null;
  comparison_exclusion_reason: string | null;
  ranking_exclusion_reason: string | null;
}

export interface MetaCohort {
  key: string;
  benchmark: string;
  scale_factor: number;
  phase: string;
  label: string;
  href: string;
  /** Count of ranking-eligible platforms with non-null primary metrics. */
  platform_count: number;
  cohort_ranked_count: number;
  cohort_ranking_exclusion_reason: string | null;
  primary_metric: string;
  primary_order: "asc" | "desc";
  platforms?: MetaCohortPlatform[];
}

export interface MetaLeaderboard {
  generated_at: string;
  cohorts: MetaCohort[];
  platforms: MetaPlatform[];
}

// ---------------------------------------------------------------------------
// Sorting helpers
// ---------------------------------------------------------------------------

export type SortDirection = "asc" | "desc";

export interface SortState<K extends string> {
  key: K;
  direction: SortDirection;
}
