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
// Empty reads keep retrying for the warm-up window; this is a safety cap for
// pathological clocks or zero-delay test timers rather than the normal stop.
const QUERY_RETRY_ATTEMPTS = 100;
const QUERY_ERROR_RETRY_ATTEMPTS = 3;
const QUERY_RETRY_DELAY_MS = 100;
// Keep a genuinely empty query bounded below the browser suite's shortest
// data-wait attempt (8s). Linear backoff here previously held the page in its
// loading skeleton for the full 15s cold window, so the recovery navigation
// could never run. Frequent re-reads also do more useful work warming the
// missing HTTP-backed row group than sleeping progressively longer.
const QUERY_EMPTY_RETRY_DELAY_MS = 50;
// How long after the snapshot is attached an EMPTY result is treated as a cold
// read worth re-issuing rather than the truth. Cold init measures P95 ~1s, so
// this is generous; outside it, empty returns immediately.
const COLD_SNAPSHOT_EMPTY_RETRY_WINDOW_MS = 15_000;
// Set when the snapshot is attached and validated; 0 until then.
let snapshotReadyAt = 0;
let initError: Error | null = null;

type DuckDBConnection = Awaited<ReturnType<duckdb.AsyncDuckDB["connect"]>>;

async function createCspBoundWorker(workerPath: string): Promise<Worker> {
  const workerUrl = new URL(workerPath, window.location.href);
  if (workerUrl.origin !== window.location.origin) {
    throw new Error(`DuckDB worker must be same-origin: ${workerUrl.origin}`);
  }
  const response = await fetch(workerUrl);
  if (!response.ok) {
    throw new Error(`DuckDB worker fetch failed: HTTP ${response.status}`);
  }
  const blobUrl = URL.createObjectURL(await response.blob());
  const worker = new Worker(blobUrl);
  const revokeBlobUrl = () => {
    URL.revokeObjectURL(blobUrl);
  };
  worker.addEventListener("message", revokeBlobUrl, { once: true });
  worker.addEventListener("error", revokeBlobUrl, { once: true });
  return worker;
}

// Keep this value aligned with
// `_project/scripts/explorer_pipeline/contract.py::EXPLORER_READ_MODEL_VERSION`.
// `results-explorer/src/lib/__tests__/db-remediation-pin.test.ts` pins the
// browser constant against an independently reviewed contract value and
// exercises the older/equal/newer compatibility policy below.
const EXPECTED_READ_MODEL_VERSION = 7;

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

// Exported for unit-test coverage of the read-model version guard.
export async function _verifyReadModelVersionForTest(
  conn: DuckDBConnection,
): Promise<void> {
  return verifyReadModelVersion(conn);
}

// Exported for unit-test coverage of initialization ordering. The version
// guard must run before schema-readiness probes so stale snapshots fail with
// the actionable read-model message instead of a lower-level DuckDB error.
export async function _validateAttachedSnapshotForTest(
  conn: DuckDBConnection,
): Promise<void> {
  return validateAttachedSnapshot(conn);
}

export const _EXPECTED_READ_MODEL_VERSION_FOR_TEST = EXPECTED_READ_MODEL_VERSION;
export const _COLD_EMPTY_READ_MAX_DELAY_MS_FOR_TEST =
  QUERY_RETRY_ATTEMPTS * QUERY_EMPTY_RETRY_DELAY_MS;

async function verifyReadModelVersion(conn: DuckDBConnection): Promise<void> {
  const found = await readSnapshotReadModelVersion(conn);
  if (found < EXPECTED_READ_MODEL_VERSION) {
    throwReadModelVersionError(found);
  }
  if (found > EXPECTED_READ_MODEL_VERSION) {
    console.warn(
      `DuckDB snapshot read-model v${found}; UI expects v${EXPECTED_READ_MODEL_VERSION}. ` +
        "Proceeding with forward-compatible reads.",
    );
  }
}

async function readSnapshotReadModelVersion(conn: DuckDBConnection): Promise<number> {
  let lastError: unknown = null;
  for (let attempt = 1; attempt <= SNAPSHOT_READY_ATTEMPTS; attempt += 1) {
    try {
      const result = await conn.query("SELECT read_model_version FROM bench.metadata LIMIT 1");
      const row = result.toArray()[0]?.toJSON();
      const version = Number(row?.read_model_version ?? 0);
      return Number.isInteger(version) && version >= 0 ? version : 0;
    } catch (error: unknown) {
      if (isMissingReadModelMetadataError(error)) {
        return 0;
      }
      lastError = error;
      if (!isTransientDuckDbSnapshotError(error)) {
        throw error;
      }
      await sleep(SNAPSHOT_READY_DELAY_MS * attempt);
    }
  }
  throw lastError instanceof Error
    ? lastError
    : new Error("DuckDB snapshot read-model version did not become query-ready");
}

function isMissingReadModelMetadataError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return (
    /Table with name "?metadata"? does not exist/i.test(message) ||
    /Referenced column "?read_model_version"? not found/i.test(message) ||
    /Binder Error:.*read_model_version/i.test(message)
  );
}

async function validateAttachedSnapshot(conn: DuckDBConnection): Promise<void> {
  await verifyReadModelVersion(conn);
  // COUNT(*) can be satisfied from metadata for this projection view.
  // Run the same projection PlatformIndex uses so a cold HTTP-backed
  // snapshot is query-ready before the cached DB instance is exposed.
  await waitForSnapshotRows(conn);
}

function throwReadModelVersionError(found: number): never {
  const remediation = import.meta.env.DEV
    ? "Restart npm run dev or run npm run dev:snapshot to rebuild the local Explorer data."
    : "Refresh the published snapshot or ask a maintainer to rebuild the Explorer data.";
  throw new Error(
    `DuckDB snapshot read-model v${found}; UI requires v${EXPECTED_READ_MODEL_VERSION}. ` +
      `${remediation} Check the deployed results.duckdb file.`,
  );
}

function quoteSqlLiteral(value: string): string {
  return `'${value.replace(/'/g, "''")}'`;
}

/**
 * Probe that a KEYED lookup works, not just an unkeyed scan.
 *
 * The `LIMIT 1` scans above prove a table is attached and has at least one
 * reachable row. They do NOT prove the snapshot is fully readable: on a cold
 * HTTP-backed `results.duckdb` those scans are satisfied by the first row group
 * while `WHERE result_id = ?` for a row further into the file still returns
 * zero. `queryRows` does not swallow that — it is a genuine empty read — so the
 * detail page renders "No result found" for a real id, and index surfaces
 * render a heading with missing rows. That is the flake the e2e suite kept
 * hitting (see docs/operations/browser-ci.md, 2026-07-29 correction).
 *
 * `ORDER BY result_id DESC LIMIT 1` forces the whole `result_id` column to be
 * materialized, so the id we probe with is deliberately NOT the one the cheap
 * scans already reached. `result_detail_metrics` is a LEFT JOIN projection over
 * `results`, so every id in `results` must resolve there — an empty answer
 * means the snapshot is still incomplete, never that the row legitimately
 * does not exist.
 */
/**
 * Every snapshot table must be FULLY readable before the snapshot is exposed.
 *
 * Narrowing this list does not work: each time it covered only the tables one
 * failing surface read, the race simply moved to the next surface. A single-id
 * keyed probe left Compare failing on `short_ids`; adding `short_ids` left it
 * failing on the per-query evidence tables. The per-query tables are also the
 * largest, so they are the most likely to be partially readable, not the least.
 *
 * Optional tables are included for free: an empty table has COUNT(*) 0 and
 * materializes 0 rows, so it agrees trivially.
 */
const SNAPSHOT_COMPLETENESS_TABLES = SNAPSHOT_READY_SCANS.map((scan) => scan.label);

/**
 * Probe that every row is readable, not merely the first one.
 *
 * `COUNT(*)` is answered from the file's metadata without reading row groups,
 * so it reports the TRUE total even while the data pages are still arriving.
 * Materializing the `result_id` column forces those pages to be read. When the
 * two disagree the snapshot is only partially readable — the state in which a
 * keyed lookup for a row in a not-yet-readable group returns zero rows.
 *
 * This is what a single keyed probe cannot catch: proving one id resolves says
 * nothing about the other ids a page will ask for. Compare in particular reads
 * several specific ids at once, and kept failing under a single-id probe.
 */
async function probeSnapshotCompleteness(conn: DuckDBConnection): Promise<string | null> {
  for (const table of SNAPSHOT_COMPLETENESS_TABLES) {
    const countRows = (await conn.query(`SELECT COUNT(*) AS n FROM bench.${table}`)).toArray() as Array<{
      n?: unknown;
    }>;
    const expected = Number(countRows[0]?.n ?? 0);
    if (!Number.isFinite(expected)) continue;
    const materialized = (await conn.query(`SELECT result_id FROM bench.${table}`)).toArray().length;
    if (materialized !== expected) {
      return `${table} materialized ${materialized} of ${expected} row(s)`;
    }
  }
  return null;
}

async function probeKeyedLookup(conn: DuckDBConnection): Promise<string | null> {
  const idRows = (
    await conn.query("SELECT result_id FROM bench.results ORDER BY result_id DESC LIMIT 1")
  ).toArray() as Array<{ result_id?: unknown }>;
  const probeId = idRows[0]?.result_id;
  if (typeof probeId !== "string" || probeId === "") return "results returned no probe id";

  const keyed = (
    await conn.query(
      `SELECT result_id FROM bench.result_detail_metrics WHERE result_id = ${quoteSqlLiteral(probeId)} LIMIT 1`,
    )
  ).toArray();
  if (keyed.length === 0) {
    return `keyed lookup for ${probeId} returned no rows from result_detail_metrics`;
  }
  return null;
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
      if (emptyRequired.length === 0) {
        const failure = (await probeSnapshotCompleteness(conn)) ?? (await probeKeyedLookup(conn));
        if (failure === null) return;
        lastError = new Error(`DuckDB snapshot readiness: ${failure}`);
      } else {
        lastError = new Error(
          `DuckDB snapshot readiness returned empty required scan(s): ${emptyRequired.join(", ")}`,
        );
      }
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
    const worker = await createCspBoundWorker(bundle.mainWorker!);
    const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
    const db = new duckdb.AsyncDuckDB(logger, worker);
    const mainModule = new URL(bundle.mainModule, window.location.href).href;
    const pthreadWorker = bundle.pthreadWorker
      ? new URL(bundle.pthreadWorker, window.location.href).href
      : undefined;
    await db.instantiate(mainModule, pthreadWorker);

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
      await validateAttachedSnapshot(conn);
      await conn.query("SET enable_external_access = false");
      await conn.query("SET lock_configuration = true");
    } finally {
      await conn.close();
    }

    dbInstance = db;
    snapshotReadyAt = Date.now();
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
  for (let attempt = 1; ; attempt += 1) {
    try {
      const rows = await queryRowsOnce<T>(sql, params);
      if (rows.length > 0 || !isColdEmptyRead(attempt)) return rows;
      // Empty, and the snapshot is still warming: re-read rather than let a
      // cold zero-row answer reach the UI as "no such result". See
      // shouldRetryColdEmptyRead.
      await sleep(QUERY_EMPTY_RETRY_DELAY_MS);
      continue;
    } catch (error: unknown) {
      if (!shouldRetryTransientQueryError(error, attempt)) {
        throw error;
      }
      await sleep(QUERY_RETRY_DELAY_MS * attempt);
    }
  }
}

/**
 * Whether an empty result should be re-read rather than believed.
 *
 * A cold HTTP-backed snapshot answers a keyed lookup with ZERO ROWS — not an
 * error — while the row group holding that key is still unreadable. `queryRows`
 * does not swallow errors, so nothing else catches this: the detail page
 * renders "No result found" for a real id and index surfaces render a heading
 * with missing rows.
 *
 * Gating a readiness probe on it is not enough. Three progressively stricter
 * gates were measured (keyed probe, then per-table completeness, then
 * completeness across every table) and each time the race simply moved to
 * whichever surface read a range the gate had not forced. Readability is not
 * monotonic per query, so the retry has to live where the read happens.
 *
 * Bounded to a short window after init, because that is the only time the
 * snapshot is cold. Outside it an empty answer returns immediately, so a
 * genuinely missing id stays fast. Retrying can never invent a row: an empty
 * result that is really empty stays empty and is returned as such.
 */
export function shouldRetryColdEmptyRead(
  attempt: number,
  now: number,
  readyAt: number,
): boolean {
  if (attempt >= QUERY_RETRY_ATTEMPTS) return false;
  if (readyAt === 0) return false;
  return now - readyAt <= COLD_SNAPSHOT_EMPTY_RETRY_WINDOW_MS;
}

function isColdEmptyRead(attempt: number): boolean {
  return shouldRetryColdEmptyRead(attempt, Date.now(), snapshotReadyAt);
}

export function shouldRetryTransientQueryError(error: unknown, attempt: number): boolean {
  return isTransientDuckDbSnapshotError(error) && attempt < QUERY_ERROR_RETRY_ATTEMPTS;
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
