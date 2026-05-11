/**
 * DuckDB-WASM data access layer.
 *
 * DuckDB-WASM is the sole browser store for every user-visible explorer
 * metric. Pages read results, rankings, matrix cells, detail timings, and
 * cohort summaries through `queryRows` or typed helpers in
 * `lib/duckdbQueries.ts`. Committed JSON bundles are source inputs - they
 * flow into `results.duckdb` via the Python pipeline and are not fetched at
 * runtime for metric rendering.
 *
 * The WASM bundle is large (~6 MB compressed). We initialise lazily, on
 * first `getDb()` call, so the app shell paints before DuckDB downloads.
 *
 * Usage:
 *   const rows = await queryRows<MyRow>("SELECT ... FROM bench.results");
 *
 * If `results.duckdb` cannot be attached (network failure, 404, corrupt
 * file), `getDb()` rejects - there is no JSON fallback. Pages surface the
 * error to the user rather than silently rendering empty state.
 */

import * as duckdb from "@duckdb/duckdb-wasm";

import { LOCAL_DUCKDB_BUNDLES } from "@/lib/duckdbBundles";
import {
  EXPLORER_PERFORMANCE_MARKS,
  EXPLORER_PERFORMANCE_MEASURES,
  markExplorerPerformance,
  measureExplorerPerformance,
} from "@/lib/performanceMarks";

let dbInstance: duckdb.AsyncDuckDB | null = null;
let initPromise: Promise<duckdb.AsyncDuckDB> | null = null;
let initFailures = 0;
const INIT_FAILURE_LIMIT = 3;
const SNAPSHOT_READY_ATTEMPTS = 8;
const SNAPSHOT_READY_DELAY_MS = 100;
const QUERY_RETRY_ATTEMPTS = 3;
const QUERY_RETRY_DELAY_MS = 100;
let initError: Error | null = null;

type DuckDBConnection = Awaited<ReturnType<duckdb.AsyncDuckDB["connect"]>>;

// Required column contract for the canonical `bench.results` table.
//
// The Results Explorer feature has not shipped with a legacy public snapshot,
// so browser code should fail fast when the current read-model contract is
// absent instead of tolerating partial schemas until a deeper query hits a
// Binder Error. Keep this list aligned with the browser `bench.results`
// contract exposed by `docs/development/browser-duckdb-schema.sql`.
//
// Builder source: `benchbox/core/explorer_pipeline/duckdb_builder.py`.
const BENCH_RESULTS_REQUIRED_COLUMNS = [
  "result_id",
  "benchmark",
  "scale_factor",
  "platform",
  "platform_id",
  "driver_version",
  "run_date",
  "power_score",
  "total_duration_s",
  "geomean_ms",
  "display_geomean_ms",
  "query_count",
  "logical_query_count",
  "has_display_timing",
  "valid_query_count",
  "missing_query_count",
  "zero_timing_count",
  "display_exclusion_reason",
  "comparison_exclusion_reason",
  "ranking_exclusion_reason",
  "trust_label",
  "visibility",
  "platform_version",
  "execution_mode",
  "tuning_mode",
  "tuning_hash",
  "test_type",
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
  "compliance_class",
  "is_ranking_eligible",
  "has_plans",
  "plans_published",
  "has_tuning",
  "bundle_download_url",
] as const;

// Required scans must be queryable AND non-empty for the snapshot to be
// considered ready. Optional scans must be queryable (so we know the table
// is attached and the schema exists), but an empty result is acceptable —
// the explorer's detail/query/short-id paths already handle missing data
// gracefully, so blocking the entire UI on these is an over-strict gate
// that produces an infinite spinner for valid snapshots.
const SNAPSHOT_READY_SCANS = [
  {
    label: "results",
    sql: "SELECT result_id FROM bench.results LIMIT 1",
    required: true,
  },
  {
    label: "platform_index_rows",
    sql: "SELECT result_id FROM bench.platform_index_rows LIMIT 1",
    required: true,
  },
  {
    label: "benchmark_rankings",
    sql: "SELECT result_id FROM bench.benchmark_rankings LIMIT 1",
    required: true,
  },
  {
    label: "benchmark_matrix_cells",
    sql: "SELECT result_id FROM bench.benchmark_matrix_cells LIMIT 1",
    required: true,
  },
  {
    label: "result_detail_metrics",
    sql: "SELECT result_id FROM bench.result_detail_metrics LIMIT 1",
    required: true,
  },
  {
    label: "query_display_timings",
    sql: "SELECT result_id FROM bench.query_display_timings LIMIT 1",
    required: false,
  },
  {
    label: "query_executions",
    sql: "SELECT result_id FROM bench.query_executions LIMIT 1",
    required: false,
  },
  {
    label: "short_ids",
    sql: "SELECT result_id FROM bench.short_ids LIMIT 1",
    required: false,
  },
] as const;

const TRANSIENT_DUCKDB_SNAPSHOT_ERROR_PATTERNS = [
  /offset is out of bounds/i,
  /fieldsLength/i,
];

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, ms));
}

// Exported for unit-test coverage of w5 (optional snapshot tables must not
// block readiness when empty). Not part of the public surface — call sites
// outside this module should keep going through `getDb()`.
export async function _waitForSnapshotRowsForTest(
  conn: DuckDBConnection,
): Promise<void> {
  return waitForSnapshotRows(conn);
}

// Exported for unit-test coverage of the bench.results column guard.
export async function _verifyBenchResultsColumnsForTest(
  conn: DuckDBConnection,
): Promise<void> {
  return verifyBenchResultsColumns(conn);
}

export const _BENCH_RESULTS_REQUIRED_COLUMNS_FOR_TEST = BENCH_RESULTS_REQUIRED_COLUMNS;

async function verifyBenchResultsColumns(conn: DuckDBConnection): Promise<void> {
  const result = await conn.query(
    "SELECT column_name FROM information_schema.columns" +
      " WHERE table_catalog = 'bench' AND table_name = 'results'",
  );
  const present = new Set<string>(
    result.toArray().map((row) => String(row.toJSON().column_name ?? "")),
  );
  const missing = BENCH_RESULTS_REQUIRED_COLUMNS.filter((column) => !present.has(column));
  if (missing.length === 0) return;
  throw new Error(
    `DuckDB snapshot 'bench.results' is missing required columns: ${missing.join(", ")}.` +
      " Regenerate the snapshot via 'benchbox explorer build' or check the deployed" +
      " results.duckdb file.",
  );
}

async function waitForSnapshotRows(conn: DuckDBConnection): Promise<void> {
  let lastError: unknown = null;
  for (let attempt = 1; attempt <= SNAPSHOT_READY_ATTEMPTS; attempt += 1) {
    try {
      const requiredCounts: Array<readonly [string, number]> = [];
      for (const scan of SNAPSHOT_READY_SCANS) {
        const result = await conn.query(scan.sql);
        if (scan.required) {
          requiredCounts.push([scan.label, result.toArray().length] as const);
        }
        // Optional scans only need to be queryable; we don't track row counts
        // because empty is acceptable.
      }
      const emptyRequired = requiredCounts
        .filter(([, rowCount]) => rowCount === 0)
        .map(([label]) => label);
      if (emptyRequired.length === 0) return;
      lastError = new Error(
        `DuckDB snapshot readiness returned empty required scan(s): ${emptyRequired.join(", ")}`,
      );
    } catch (error: unknown) {
      lastError = error;
      if (!isTransientDuckDbSnapshotError(error)) throw error;
    }
    await sleep(SNAPSHOT_READY_DELAY_MS * attempt);
  }
  throw lastError instanceof Error ? lastError : new Error("DuckDB snapshot did not become query-ready");
}

// Reset the retry counter when the browser reports a network recovery so a
// transient same-origin asset or snapshot outage doesn't permanently disable
// DuckDB for the tab.
if (typeof window !== "undefined") {
  window.addEventListener("online", () => {
    initFailures = 0;
    initError = null;
  });
}

/**
 * Initialise DuckDB-WASM and load the results database.
 * Calling this multiple times is safe - it returns the cached instance.
 * After {@link INIT_FAILURE_LIMIT} consecutive failures we stop retrying so a
 * persistently broken environment doesn't burn bandwidth.
 */
export async function getDb(): Promise<duckdb.AsyncDuckDB> {
  if (dbInstance) return dbInstance;
  if (initPromise) return initPromise;
  if (initFailures >= INIT_FAILURE_LIMIT && initError) {
    throw new Error(
      `DuckDB-WASM init failed ${initFailures} times; aborting. Last error: ${initError.message}`,
    );
  }

  initPromise = (async () => {
    markExplorerPerformance(EXPLORER_PERFORMANCE_MARKS.DB_INIT_START, { once: true });
    const bundle = await duckdb.selectBundle(LOCAL_DUCKDB_BUNDLES);
    const worker = new Worker(bundle.mainWorker!);
    const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
    const db = new duckdb.AsyncDuckDB(logger, worker);
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);

    const dbUrl = new URL("/results/data/results.duckdb", window.location.origin).href;
    // directIO=true signals to DuckDB-WASM's HTTP runtime that this file
    // is a candidate for byte-range reads. In practice - with duckdb-wasm
    // 1.32.0 and a registered URL - the runtime still falls back to a
    // single whole-file GET on ATTACH. A March 2026 experiment also
    // tried `db.open({filesystem: {reliableHeadRequests: true,
    // forceFullHTTPReads: false}})` before registering: page loads
    // succeed but the runtime still issues a single whole-file GET (the
    // full DB size, not <=10% per RG-2). `allowFullHTTPReads: false`
    // makes the runtime error on first attach (upstream issue
    // duckdb/duckdb-wasm#1984: "If false, always error"). The buggy
    // "Perform a full GET anyways" code path in runtime_browser.ts has
    // not been removed in 1.32.0; tracked as
    // `enable-duckdb-wasm-http-range-reads-for-registered-urls`.
    await db.registerFileURL("results.duckdb", dbUrl, duckdb.DuckDBDataProtocol.HTTP, true);
    const conn = await db.connect();
    try {
      await conn.query("ATTACH 'results.duckdb' AS bench (READ_ONLY)");
      // COUNT(*) can be satisfied from metadata for this projection view.
      // Run the same projection PlatformIndex uses so a cold HTTP-backed
      // snapshot is query-ready before the cached DB instance is exposed.
      await waitForSnapshotRows(conn);
      // Convert "Binder Error in deep page query" into "DuckDB snapshot is
      // missing column X" at init time. See `BENCH_RESULTS_REQUIRED_COLUMNS`.
      await verifyBenchResultsColumns(conn);
    } finally {
      await conn.close();
    }

    dbInstance = db;
    markExplorerPerformance(EXPLORER_PERFORMANCE_MARKS.DB_INIT_READY, { once: true });
    measureExplorerPerformance(
      EXPLORER_PERFORMANCE_MEASURES.DB_INIT,
      EXPLORER_PERFORMANCE_MARKS.DB_INIT_START,
      EXPLORER_PERFORMANCE_MARKS.DB_INIT_READY,
      { once: true },
    );
    return db;
  })().catch((error: unknown) => {
    initPromise = null;
    initFailures += 1;
    initError = error instanceof Error ? error : new Error(String(error));
    throw error;
  });

  return initPromise;
}

/**
 * Convenience: run a single SQL query and return rows as plain objects.
 * The caller is responsible for ensuring the database is attached.
 */
export async function queryRows<T>(
  sql: string,
  params: unknown[] = [],
): Promise<T[]> {
  let lastError: unknown = null;
  for (let attempt = 1; attempt <= QUERY_RETRY_ATTEMPTS; attempt += 1) {
    try {
      return await queryRowsOnce<T>(sql, params);
    } catch (error: unknown) {
      lastError = error;
      if (!isTransientDuckDbSnapshotError(error) || attempt === QUERY_RETRY_ATTEMPTS) {
        throw error;
      }
      await sleep(QUERY_RETRY_DELAY_MS * attempt);
    }
  }
  throw lastError instanceof Error ? lastError : new Error("DuckDB query failed");
}

async function queryRowsOnce<T>(
  sql: string,
  params: unknown[] = [],
): Promise<T[]> {
  const db = await getDb();
  const conn = await db.connect();
  let statement: duckdb.AsyncPreparedStatement | null = null;
  try {
    const result =
      params.length === 0
        ? await conn.query(sql)
        : await ((statement = await conn.prepare(sql)).query(...params));
    return result.toArray().map((row) => row.toJSON() as T);
  } finally {
    if (statement) {
      await statement.close();
    }
    await conn.close();
  }
}

function isTransientDuckDbSnapshotError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return TRANSIENT_DUCKDB_SNAPSHOT_ERROR_PATTERNS.some((pattern) => pattern.test(message));
}
