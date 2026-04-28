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

let dbInstance: duckdb.AsyncDuckDB | null = null;
let initPromise: Promise<duckdb.AsyncDuckDB> | null = null;
let initFailures = 0;
const INIT_FAILURE_LIMIT = 3;
let initError: Error | null = null;

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
    } finally {
      await conn.close();
    }

    dbInstance = db;
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
