// Regression coverage for the review findings on the timeout/eviction path
// in `src/db.ts`: a dead DuckDB-WASM worker's pending requests are dropped
// (never resolved or rejected) by the vendored library's own `onError`/
// `onClose` handlers, so an in-flight `conn.query(...)` never settles.
//
// This file drives `getDb()`/`queryRows()` end to end against a fake
// `duckdb.AsyncDuckDB` whose behavior is scripted per test, rather than
// mocking individual internal helpers, so it exercises the real init and
// eviction code paths.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// vi.mock factories are hoisted above the rest of this file, so every class
// and piece of shared state they reference has to live inside vi.hoisted()
// too - a plain top-level `class` declared below would be a TDZ reference
// error at mock-evaluation time.
const hoisted = vi.hoisted(() => {
  interface FakeRow {
    toJSON: () => Record<string, unknown>;
  }
  interface FakeRows {
    toArray: () => FakeRow[];
  }

  function rows(data: Array<Record<string, unknown>>): FakeRows {
    return { toArray: () => data.map((row) => ({ toJSON: () => row, ...row })) };
  }

  // Answers every SQL shape the readiness ladder and typed queries in db.ts
  // issue. Deliberately permissive: matches by SQL shape rather than pinning
  // exact table lists, so it doesn't need updating when SNAPSHOT_READY_SCANS
  // changes.
  function healthyQueryImpl(sql: string): FakeRows {
    if (/read_model_version/i.test(sql)) return rows([{ read_model_version: 10 }]);
    if (/^ATTACH/i.test(sql)) return rows([]);
    if (/^SET /i.test(sql)) return rows([]);
    if (/COUNT\(\*\)/i.test(sql)) return rows([{ n: 1 }]);
    if (/WHERE result_id\s*=/i.test(sql)) return rows([{ result_id: "r1" }]);
    if (/FROM bench\.\w+/i.test(sql)) return rows([{ result_id: "r1" }]);
    return rows([{ ok: 1 }]);
  }

  // Mirrors FakeConnection's hang-when-dead behavior for the prepared-
  // statement path, so a parameterised query can pin the worst case the
  // review's arithmetic is built on: `statement.query()` times out, and both
  // `statement.close()` and `conn.close()` cleanup calls hang too (see T3).
  class FakeStatement {
    dead: boolean;
    query: (...params: unknown[]) => Promise<FakeRows>;
    close: () => Promise<void>;

    constructor(dead: boolean) {
      this.dead = dead;
      this.query = () => {
        if (this.dead) return new Promise(() => {});
        return Promise.resolve(healthyQueryImpl("prepared"));
      };
      this.close = () => {
        if (this.dead) return new Promise(() => {});
        return Promise.resolve();
      };
    }
  }

  class FakeConnection {
    dead: boolean;
    // Set only for the R2 "terminated-after-init" scenario: the owning
    // instance whose `terminated` flag this connection's first query()
    // flips, simulating a *sibling* call's eviction terminating the worker
    // out from under this in-flight query (see DuckDbTerminatedError).
    terminatedBy: FakeAsyncDuckDB | null;
    query: (sql: string) => Promise<FakeRows>;
    close: () => Promise<void>;
    prepare: (sql: string) => Promise<FakeStatement>;

    constructor(dead: boolean, terminatedBy: FakeAsyncDuckDB | null = null) {
      this.dead = dead;
      this.terminatedBy = terminatedBy;
      this.query = (sql: string) => {
        if (this.dead) return new Promise(() => {}); // never settles - the onError bug
        if (this.terminatedBy) {
          // Mirrors the vendored bridge exactly: `postTask` resolves with
          // `undefined` when the worker is already gone, and
          // `RecordBatchReader.from(undefined)` throws this TypeError
          // synchronously - confirmed against this project's own
          // apache-arrow dependency (see the docblock on
          // DuckDbTerminatedError in src/db.ts).
          this.terminatedBy.terminated = true;
          return Promise.reject(new TypeError("Cannot read properties of undefined (reading 'peek')"));
        }
        return Promise.resolve(healthyQueryImpl(sql));
      };
      this.close = () => {
        if (this.dead) return new Promise(() => {}); // cleanup on a dead worker hangs too
        return Promise.resolve();
      };
      this.prepare = async () => new FakeStatement(this.dead);
    }
  }

  // Queue of behaviors consumed in construction order, one per
  // `new duckdb.AsyncDuckDB(...)` call (i.e. one per fresh worker).
  // "terminated-after-init" (R2): every `connect()` after the one used
  // during `getDb()`'s own init returns a connection whose first query
  // simulates a sibling's eviction terminating this worker mid-flight.
  // "slow-query" holds the worker for ten seconds during the first page read.
  type InstanceBehavior =
    | "healthy"
    | "dead-after-init"
    | "dead-during-init"
    | "terminated-after-init"
    | "slow-query";
  const nextInstanceBehaviors: InstanceBehavior[] = [];
  const instances: FakeAsyncDuckDB[] = [];

  class FakeAsyncDuckDB {
    id: number;
    behavior: InstanceBehavior;
    terminate: () => Promise<void>;
    connectCount = 0;
    // Flipped by a connection's query() in the "terminated-after-init"
    // scenario, and by `terminate()` itself - mirrors the real bridge's
    // `isDetached()`, which is exactly `!this._worker`.
    terminated = false;

    constructor() {
      this.behavior = nextInstanceBehaviors.shift() ?? "healthy";
      this.id = instances.length + 1;
      this.terminate = vi.fn(async () => {
        this.terminated = true;
      });
      instances.push(this);
    }

    isDetached(): boolean {
      return this.terminated;
    }

    async instantiate(): Promise<null> {
      return null;
    }

    async registerFileURL(): Promise<void> {
      return undefined;
    }

    async connect(): Promise<FakeConnection> {
      this.connectCount += 1;
      const isDead =
        this.behavior === "dead-during-init" ||
        (this.behavior === "dead-after-init" && this.connectCount > 1);
      const terminatedBy =
        this.behavior === "terminated-after-init" && this.connectCount > 1 ? this : null;
      const conn = new FakeConnection(isDead, terminatedBy);
      if (this.behavior === "slow-query" && this.connectCount === 2) {
        conn.query = async () => {
          await new Promise((resolve) => setTimeout(resolve, 10_000));
          return healthyQueryImpl("SELECT 1");
        };
      }
      return conn;
    }
  }

  return { nextInstanceBehaviors, instances, FakeAsyncDuckDB };
});

vi.mock("@duckdb/duckdb-wasm", () => ({
  selectBundle: vi.fn(async () => ({ mainModule: "duckdb.wasm", mainWorker: "duckdb-worker.js" })),
  ConsoleLogger: class {},
  LogLevel: { WARNING: 3 },
  DuckDBDataProtocol: { HTTP: 1 },
  AsyncDuckDB: hoisted.FakeAsyncDuckDB,
}));

vi.mock("@/lib/duckdbBundles", () => ({
  LOCAL_DUCKDB_BUNDLES: {},
}));

vi.mock("@/lib/performanceMarks", () => ({
  EXPLORER_PERFORMANCE_MARKS: {},
  EXPLORER_PERFORMANCE_MEASURES: {},
  markExplorerPerformance: vi.fn(),
  measureExplorerPerformance: vi.fn(),
}));

import {
  _DUCKDB_QUERY_TIMEOUT_MS_FOR_TEST,
  _getInitFailuresForTest,
  _resetDbStateForTest,
  resetDuckDbInitializationFailures,
  DUCKDB_USER_QUERY_TIMEOUT_MS,
  getDb,
  queryRows,
} from "@/db";

class FakeWorker {
  addEventListener(): void {}
  removeEventListener(): void {}
  terminate(): void {}
}

beforeEach(() => {
  _resetDbStateForTest();
  hoisted.nextInstanceBehaviors.length = 0;
  hoisted.instances.length = 0;

  vi.stubGlobal("Worker", FakeWorker);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      status: 200,
      blob: async () => new Blob(),
    })),
  );
  if (!URL.createObjectURL) {
    // jsdom doesn't implement these; db.ts only uses them to name a blob.
    (URL as unknown as { createObjectURL: () => string }).createObjectURL = () => "blob:fake";
    (URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = () => {};
  }
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("DuckDB instance eviction and recovery", () => {
  // T1: a timeout on a query must evict the cached instance so the *next*
  // queryRows() call gets a genuinely fresh worker - not just clear
  // dbInstance while initPromise keeps returning the same dead AsyncDuckDB
  // (see evictDb() in src/db.ts). The reviewer's finding was that the commit
  // as written left initPromise cached, making eviction a no-op.
  //
  // A single queryRows() call no longer retries a DuckDbTimeoutError itself
  // (see the "deliberately NOT retried" note on DUCKDB_QUERY_TIMEOUT_MS in
  // src/db.ts - a second attempt that also timed out would double the cost of
  // a call that already spends close to the full budget on one attempt), so
  // this drives eviction and recovery through two separate calls instead of
  // one call retrying internally.
  it("T1: after a query times out, it evicts the instance so the *next* call gets a different AsyncDuckDB instance", async () => {
    vi.useFakeTimers();
    hoisted.nextInstanceBehaviors.push("dead-after-init", "healthy");

    const db1 = await getDb();
    expect(hoisted.instances).toHaveLength(1);

    const firstCall = queryRows("SELECT 1 AS ok");
    const firstAssertion = expect(firstCall).rejects.toThrow(/did not respond within/i);
    await vi.runAllTimersAsync();
    await firstAssertion;

    // The dead worker must actually be torn down, not merely dereferenced.
    expect(hoisted.instances[0]).toBe(db1);
    expect(hoisted.instances[0]?.terminate).toHaveBeenCalled();

    // A second, independent call must build a fresh AsyncDuckDB instead of
    // reusing the one that just proved it can go silent.
    const secondCall = queryRows("SELECT 1 AS ok");
    await vi.runAllTimersAsync();
    const result = await secondCall;
    expect(result).toEqual([{ ok: 1 }]);
    expect(hoisted.instances).toHaveLength(2);

    const db2 = await getDb();
    expect(db2).not.toBe(db1);
    expect((db2 as unknown as { id: number }).id).toBe(2);
  });

  // T2: a hang during init (instantiate/registerFileURL/connect/ATTACH/SET -
  // none of which were guarded before this fix) must settle rather than
  // leave `initPromise` unresolved forever, must increment `initFailures`
  // so the INIT_FAILURE_LIMIT escape hatch can ever trip, and a later call
  // must still be able to recover once the environment is healthy again.
  it("T2: a hang during init settles, counts as a failure, and a later call recovers", async () => {
    vi.useFakeTimers();
    hoisted.nextInstanceBehaviors.push("dead-during-init");

    expect(_getInitFailuresForTest()).toBe(0);

    const initPromise = getDb();
    // Attach the rejection assertion before advancing the fake clock, so the
    // rejection has a handler the instant it settles - otherwise Node flags
    // it as an unhandled rejection during the timer advance below, even
    // though it's `await`ed a few lines later.
    const initAssertion = expect(initPromise).rejects.toThrow(/did not respond within/i);
    await vi.runAllTimersAsync();
    await initAssertion;

    expect(_getInitFailuresForTest()).toBe(1);
    expect(hoisted.instances).toHaveLength(1);
    // The worker behind the failed init must be torn down, not leaked.
    expect(hoisted.instances[0]?.terminate).toHaveBeenCalled();

    // A later call, against a healthy environment, must still recover -
    // the module must not be permanently wedged by one init failure.
    hoisted.nextInstanceBehaviors.push("healthy");
    const recovered = await getDb();
    expect(recovered).toBeTruthy();
    expect(hoisted.instances).toHaveLength(2);
  });

  // T3: pin the worst-case wall-clock cost of one queryRows() call that hits
  // a persistently dead worker, so this can't silently regress. This used to
  // model the ladder as three executions (queryRows retries a
  // DuckDbTimeoutError up to QUERY_ERROR_RETRY_ATTEMPTS times), but that
  // undercounted the real worst case: the review found the parameterised
  // path pays for *two* cleanup calls per attempt (statement close AND
  // connection close, not just connection close), putting three real
  // attempts at 17.1s against an 8s budget. The fix (see the "deliberately
  // NOT retried" note on DUCKDB_QUERY_TIMEOUT_MS in src/db.ts) is to not
  // retry a timeout within a single call at all, and to skip the cleanup
  // round-trips once the instance has been evicted - closing a connection
  // whose worker was just terminated can only spend
  // DUCKDB_CLEANUP_TIMEOUT_MS logging an error, never succeed. So the real
  // worst case for this bound is the query timeout alone, whether or not a
  // prepared statement was in play.
  it("T3: one queryRows() call against a dead worker costs one query timeout, not three attempts plus cleanup", async () => {
    vi.useFakeTimers();
    hoisted.nextInstanceBehaviors.push("dead-after-init");

    const start = Date.now();
    // A parameterised query exercises `conn.prepare()` too - the shape the
    // review's arithmetic was built on - to prove eviction skips cleanup for
    // both the statement and the connection, not just the connection.
    const queryPromise = queryRows("SELECT 1 AS ok WHERE 1 = ?", [1]);
    const assertion = expect(queryPromise).rejects.toThrow(/did not respond within/i);
    await vi.runAllTimersAsync();
    await assertion;
    const elapsedMs = Date.now() - start;

    // Exactly one query timeout - no cleanup round-trip (the instance was
    // evicted) and no retry backoff (a DuckDbTimeoutError is never retried
    // within a single call).
    expect(elapsedMs).toBe(_DUCKDB_QUERY_TIMEOUT_MS_FOR_TEST);
    expect(elapsedMs).toBeLessThan(8_000);

    // The dead instance must still be evicted so a later, independent call
    // recovers rather than reusing it.
    hoisted.nextInstanceBehaviors.push("healthy");
    const recovered = await queryRows("SELECT 1 AS ok");
    expect(recovered).toEqual([{ ok: 1 }]);
    expect(hoisted.instances).toHaveLength(2);
  });

  // R2: the vendored bridge's `postTask` resolves `undefined` (rather than
  // rejecting) when a *sibling* call's eviction has already nulled
  // `_worker`. `conn.query()`/`statement.query()` immediately hand that to
  // `apache-arrow`'s `RecordBatchReader.from()`, which throws a TypeError -
  // not the timeout this module already classifies. Without checking
  // `db.isDetached()` in the catch, that TypeError would reach the UI raw,
  // unretried and unexplained; this pins that it is reclassified as
  // `DuckDbTerminatedError` and transparently retried instead.
  it("R2: a query terminated by a sibling's eviction while in flight is reclassified and retried, not thrown as a raw TypeError", async () => {
    vi.useFakeTimers();
    hoisted.nextInstanceBehaviors.push("terminated-after-init", "healthy");

    const db1 = await getDb();
    expect(hoisted.instances).toHaveLength(1);
    expect((db1 as unknown as { isDetached: () => boolean }).isDetached()).toBe(false);

    // queryRows's own retry loop backs off with a real `setTimeout` between
    // attempts (see QUERY_RETRY_DELAY_MS), which needs the fake clock
    // advanced or it never fires.
    const resultPromise = queryRows("SELECT 1 AS ok");
    await vi.runAllTimersAsync();
    const result = await resultPromise;

    // Resolved via queryRows's own retry loop (DuckDbTerminatedError IS
    // transient, unlike DuckDbTimeoutError) against a freshly built worker -
    // never surfaced as an unclassified TypeError.
    expect(result).toEqual([{ ok: 1 }]);
    expect(hoisted.instances).toHaveLength(2);
    expect(hoisted.instances[0]?.terminate).toHaveBeenCalled();
  });

  it("starts a queued page read's timeout after a slow user query finishes", async () => {
    vi.useFakeTimers();
    hoisted.nextInstanceBehaviors.push("slow-query");
    const db = await getDb();
    const slow = queryRows("SELECT expensive_operation()", [], DUCKDB_USER_QUERY_TIMEOUT_MS);
    const pageRead = queryRows("SELECT 1 AS ok");
    await vi.advanceTimersByTimeAsync(6_000);
    expect(hoisted.instances[0]?.terminate).not.toHaveBeenCalled();
    // Only initialization and the slow query have acquired a connection.
    expect(hoisted.instances[0]?.connectCount).toBe(2);
    await vi.advanceTimersByTimeAsync(4_000);
    expect(await slow).toEqual([{ ok: 1 }]);
    expect(await pageRead).toEqual([{ ok: 1 }]);
    expect(await getDb()).toBe(db);
    expect(hoisted.instances[0]?.terminate).not.toHaveBeenCalled();
  });

  it("terminates user SQL at its hard cutoff and releases queued reads to a fresh worker", async () => {
    vi.useFakeTimers();
    hoisted.nextInstanceBehaviors.push("dead-after-init", "healthy");
    await getDb();
    const start = Date.now();
    const slow = queryRows("SELECT expensive_operation()", [], DUCKDB_USER_QUERY_TIMEOUT_MS);
    const assertion = expect(slow).rejects.toThrow(/did not respond within/i);
    const pageRead = queryRows("SELECT 1 AS ok");
    await vi.runAllTimersAsync();
    await assertion;
    expect(Date.now() - start).toBe(DUCKDB_USER_QUERY_TIMEOUT_MS);
    expect(hoisted.instances[0]?.terminate).toHaveBeenCalled();
    expect(await pageRead).toEqual([{ ok: 1 }]);
    expect(hoisted.instances).toHaveLength(2);
  });

  it("allows an explicit retry after three initialization failures without resetting healthy state", async () => {
    vi.mocked(fetch).mockRejectedValue(new Error("HTTP unavailable"));
    for (let i = 0; i < 3; i++) {
      await expect(getDb()).rejects.toThrow("HTTP unavailable");
    }
    vi.mocked(fetch).mockResolvedValue({ ok: true, blob: async () => new Blob() } as Response);
    await expect(queryRows("SELECT 1")).rejects.toThrow("init failed 3 times; aborting");
    expect(fetch).toHaveBeenCalledTimes(3);
    resetDuckDbInitializationFailures();
    expect(await queryRows("SELECT 1")).toEqual([{ ok: 1 }]);
    const healthy = await getDb();
    resetDuckDbInitializationFailures();
    expect(await getDb()).toBe(healthy);
    expect(hoisted.instances).toHaveLength(1);
  });
});

it("does not retry a timeout whose SQL text resembles a transient error", async () => {
  vi.useFakeTimers();
  hoisted.nextInstanceBehaviors.push("dead-after-init", "healthy");
  await getDb();
  const pending = queryRows("SELECT fieldsLength FROM slow_table", [], DUCKDB_USER_QUERY_TIMEOUT_MS);
  const assertion = expect(pending).rejects.toThrow(/did not respond within/);
  await vi.runAllTimersAsync();
  await assertion;
  expect(hoisted.instances).toHaveLength(1);
});
