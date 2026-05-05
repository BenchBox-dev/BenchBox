-- browser-duckdb-schema.sql
-- Frozen DuckDB DDL for the ten canonical browser metric tables and views.
--
-- Originating TODO: explorer-canonical-browser-duckdb-read-model (W1 deliverable)
-- Locked: 2026-04-18
--
-- Rules:
--   - Base tables are populated by the Python pipeline in one transaction per build.
--   - Views project only bare column references (G-11 compliance).
--   - No arithmetic, aggregation, CASE, or window functions in view projections.
--   - ATTACH ... (READ_ONLY) is enforced at the browser layer; DDL never runs in-browser.

-- ---------------------------------------------------------------------------
-- Supporting tables (required by result_detail_metrics view)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS result_environment (
    result_id        VARCHAR PRIMARY KEY,
    os               VARCHAR,
    arch             VARCHAR,
    cpu_count        INTEGER,
    memory_gb        DOUBLE,
    python           VARCHAR
);

CREATE TABLE IF NOT EXISTS result_phase_durations (
    result_id        VARCHAR NOT NULL,
    phase            VARCHAR NOT NULL,
    duration_s       DOUBLE  NOT NULL,
    PRIMARY KEY (result_id, phase)
);

-- ---------------------------------------------------------------------------
-- Table 1: results
-- One row per result bundle. Extends the current 19-column stub to cover all
-- user-visible fields across every explorer surface.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS results (
    result_id            VARCHAR  PRIMARY KEY,
    benchmark            VARCHAR  NOT NULL,
    scale_factor         DOUBLE   NOT NULL,
    platform             VARCHAR  NOT NULL,
    platform_id          VARCHAR  NOT NULL,
    driver_version       VARCHAR,
    run_date             VARCHAR  NOT NULL,
    power_score          DOUBLE,
    total_duration_s     DOUBLE   NOT NULL,
    geomean_ms           DOUBLE,
    display_geomean_ms   DOUBLE,
    query_count          INTEGER  NOT NULL,
    trust_label          VARCHAR  NOT NULL,
    visibility           VARCHAR  NOT NULL,
    platform_version     VARCHAR,
    execution_mode       VARCHAR,
    tuning_mode          VARCHAR,
    tuning_hash          VARCHAR,
    test_type            VARCHAR,
    validation_status    VARCHAR,
    cost_usd             DOUBLE,
    normalized_cost_usd  DOUBLE,
    cost_model_version   VARCHAR,
    cost_model_source    VARCHAR,
    cost_scope           VARCHAR,
    cost_status          VARCHAR  NOT NULL,
    billing_unit         VARCHAR,
    pricing_region       VARCHAR,
    deployment_class     VARCHAR,
    cloud_provider       VARCHAR,
    cloud_region         VARCHAR,
    instance_or_warehouse VARCHAR,
    storage_format       VARCHAR,
    instance_type        VARCHAR,
    warehouse_size       VARCHAR,
    node_count           INTEGER,
    cluster_size         VARCHAR,
    storage_tier         VARCHAR,
    compliance_class     VARCHAR,
    is_ranking_eligible  BOOLEAN  NOT NULL,
    has_plans            BOOLEAN  NOT NULL,
    plans_published      BOOLEAN  NOT NULL,
    has_tuning           BOOLEAN  NOT NULL,
    bundle_download_url  VARCHAR  NOT NULL
);

-- ---------------------------------------------------------------------------
-- Table 2: query_display_timings
-- One row per (result_id, query_id). The canonical per-query display timing.
-- display_ms is the median of passing measurement runs; null when all failed.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS query_display_timings (
    result_id    VARCHAR  NOT NULL,
    query_id     VARCHAR  NOT NULL,
    display_ms   DOUBLE,
    sample_count INTEGER  NOT NULL,
    PRIMARY KEY (result_id, query_id)
);

-- ---------------------------------------------------------------------------
-- Table 3: query_executions
-- One row per individual query execution run (raw timing data).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS query_executions (
    result_id    VARCHAR  NOT NULL,
    query_id     VARCHAR  NOT NULL,
    duration_ms  DOUBLE   NOT NULL,
    status       VARCHAR  NOT NULL,
    run_type     VARCHAR,
    iter         INTEGER,
    stream       INTEGER
);

CREATE INDEX IF NOT EXISTS idx_query_executions_result
    ON query_executions (result_id);

-- ---------------------------------------------------------------------------
-- View 4: result_detail_metrics (G-11 compliant)
-- Projection over results + result_environment + result_phase_durations.
-- Used by the ResultDetail page to load all detail data in one query.
-- Only bare column references are projected (no arithmetic or aggregation).
-- ---------------------------------------------------------------------------

CREATE VIEW IF NOT EXISTS result_detail_metrics AS
SELECT
    r.result_id,
    r.benchmark,
    r.scale_factor,
    r.platform,
    r.platform_id,
    r.driver_version,
    r.run_date,
    r.power_score,
    r.total_duration_s,
    r.geomean_ms,
    r.display_geomean_ms,
    r.query_count,
    r.trust_label,
    r.visibility,
    r.platform_version,
    r.execution_mode,
    r.tuning_mode,
    r.tuning_hash,
    r.test_type,
    r.validation_status,
    r.cost_usd,
    r.normalized_cost_usd,
    r.cost_model_version,
    r.cost_model_source,
    r.cost_scope,
    r.cost_status,
    r.billing_unit,
    r.pricing_region,
    r.deployment_class,
    r.cloud_provider,
    r.cloud_region,
    r.instance_or_warehouse,
    r.instance_type,
    r.warehouse_size,
    r.node_count,
    r.cluster_size,
    r.storage_format,
    r.storage_tier,
    r.compliance_class,
    r.has_plans,
    r.plans_published,
    r.has_tuning,
    r.bundle_download_url,
    e.os,
    e.arch,
    e.cpu_count,
    e.memory_gb,
    e.python
FROM results r
LEFT JOIN result_environment e USING (result_id);

-- ---------------------------------------------------------------------------
-- Table 5: benchmark_matrix_cells
-- One row per (benchmark, scale_factor, phase, result_id, query_id).
-- Denormalized from query_display_timings so the BenchmarkIndex matrix loads
-- one table scan per cohort instead of joining across all results.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS benchmark_matrix_cells (
    benchmark    VARCHAR  NOT NULL,
    scale_factor DOUBLE   NOT NULL,
    phase        VARCHAR  NOT NULL,
    result_id    VARCHAR  NOT NULL,
    platform_id  VARCHAR  NOT NULL,
    query_id     VARCHAR  NOT NULL,
    display_ms   DOUBLE,
    PRIMARY KEY (benchmark, scale_factor, phase, result_id, query_id)
);

CREATE INDEX IF NOT EXISTS idx_matrix_cells_cohort
    ON benchmark_matrix_cells (benchmark, scale_factor, phase);

-- ---------------------------------------------------------------------------
-- Table 6: benchmark_rankings
-- One row per (benchmark, scale_factor, phase, result_id).
-- Pre-computed ranking data for the BenchmarkIndex matrix and ranks views.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS benchmark_rankings (
    benchmark          VARCHAR  NOT NULL,
    scale_factor       DOUBLE   NOT NULL,
    phase              VARCHAR  NOT NULL,
    result_id          VARCHAR  NOT NULL,
    platform_id        VARCHAR  NOT NULL,
    platform           VARCHAR  NOT NULL,
    short_id           VARCHAR  NOT NULL,
    trust_label        VARCHAR  NOT NULL,
    tuning_mode        VARCHAR,
    tuning_hash        VARCHAR,
    execution_mode     VARCHAR,
    compliance_class   VARCHAR,
    run_date           VARCHAR  NOT NULL,
    is_ranking_eligible BOOLEAN NOT NULL,
    power_score        DOUBLE,
    display_geomean_ms DOUBLE,
    sample_geomean_ms  DOUBLE,
    cost_usd           DOUBLE,
    primary_metric     VARCHAR  NOT NULL,
    primary_order      VARCHAR  NOT NULL,
    rank               INTEGER,
    total_in_cohort    INTEGER  NOT NULL,
    percentile_p50     DOUBLE,
    percentile_p90     DOUBLE,
    percentile_p95     DOUBLE,
    percentile_p99     DOUBLE,
    -- Cohort-relative speedup ratios - pre-materialised so frontends never
    -- recompute them TS-side.
    --   speedup_vs_best              ∈ (0, 1]  - best row = 1.0, worse < 1.0.
    --   speedup_vs_slowest_in_cohort ≥ 1.0     - slowest row = 1.0, better > 1.0.
    speedup_vs_best              DOUBLE,
    speedup_vs_slowest_in_cohort DOUBLE,
    PRIMARY KEY (benchmark, scale_factor, phase, result_id)
);

CREATE INDEX IF NOT EXISTS idx_benchmark_rankings_cohort
    ON benchmark_rankings (benchmark, scale_factor, phase);

-- ---------------------------------------------------------------------------
-- View 7: platform_index_rows (G-11 compliant)
-- Projection over results for the PlatformIndex page.
-- Exposes all columns needed by the platform browse surface as bare references.
-- ---------------------------------------------------------------------------

CREATE VIEW IF NOT EXISTS platform_index_rows AS
SELECT
    result_id,
    benchmark,
    scale_factor,
    platform,
    platform_id,
    driver_version,
    run_date,
    power_score,
    total_duration_s,
    geomean_ms,
    display_geomean_ms,
    query_count,
    trust_label,
    tuning_mode,
    execution_mode,
    compliance_class,
    cost_usd,
    normalized_cost_usd,
    cost_model_version,
    cost_model_source,
    cost_scope,
    cost_status,
    billing_unit,
    pricing_region,
    deployment_class,
    cloud_provider,
    cloud_region,
    instance_or_warehouse,
    instance_type,
    warehouse_size,
    node_count,
    cluster_size,
    storage_format,
    storage_tier
FROM results;

-- ---------------------------------------------------------------------------
-- Table 8: cohort_metadata
-- One row per (cohort_key, result_id) - every publishable result variant
-- in the cohort, with its own rank. A platform may appear more than once
-- per cohort (e.g. different tuning_mode or trust_label); the pipeline
-- never dedupes or hides variants. The UI is responsible for any
-- display-time collapsing it wants to do. tuning_mode, trust_label, and
-- short_id are carried alongside so Home can label/group variants
-- without joining benchmark_rankings.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS cohort_metadata (
    cohort_key     VARCHAR  NOT NULL,
    benchmark      VARCHAR  NOT NULL,
    scale_factor   DOUBLE   NOT NULL,
    phase          VARCHAR  NOT NULL,
    cohort_label   VARCHAR  NOT NULL,
    cohort_href    VARCHAR  NOT NULL,
    platform_count INTEGER  NOT NULL,
    primary_metric VARCHAR  NOT NULL,
    primary_order  VARCHAR  NOT NULL,
    platform_id    VARCHAR  NOT NULL,
    platform       VARCHAR  NOT NULL,
    result_id      VARCHAR  NOT NULL,
    short_id       VARCHAR  NOT NULL,
    tuning_mode    VARCHAR,
    trust_label    VARCHAR  NOT NULL,
    rank           INTEGER,
    metric_value   DOUBLE,
    speedup_vs_best DOUBLE,
    PRIMARY KEY (cohort_key, result_id)
);

CREATE INDEX IF NOT EXISTS idx_cohort_metadata_key
    ON cohort_metadata (cohort_key);

CREATE INDEX IF NOT EXISTS idx_cohort_metadata_platform
    ON cohort_metadata (cohort_key, platform_id);

-- ---------------------------------------------------------------------------
-- Table 9: meta_leaderboard
-- One row per platform - pre-computed cross-cohort summary.
-- avg_rank and n_cohorts are computed by Python (not a view) to satisfy G-11.
-- Serves the Home page hero meta-leaderboard panel.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS meta_leaderboard (
    platform_id  VARCHAR  PRIMARY KEY,
    platform     VARCHAR  NOT NULL,
    avg_rank     DOUBLE,
    n_cohorts    INTEGER  NOT NULL
);

-- ---------------------------------------------------------------------------
-- Table 10: short_ids
-- short_id -> result_id mapping for compact Compare URLs.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS short_ids (
    short_id   VARCHAR  PRIMARY KEY,
    result_id  VARCHAR  NOT NULL UNIQUE
);
