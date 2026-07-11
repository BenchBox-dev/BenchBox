---
title: Throughput Result Alignment
status: reference
owner: quality-extract-throughput-runner
created: 2026-04-14
---

# Throughput Result Alignment

Companion doc for `quality-extract-throughput-runner`. Maps
`TPCHThroughputStreamResult`, `TPCHThroughputTestResult` (from
`benchbox/core/tpch/throughput_test.py`) field-by-field against their
TPC-DS counterparts to decide what lands on the shared
`ThroughputStreamResult` / `ThroughputResult` base versus the per-spec
subclass.

---

## Stream Result: TPCHThroughputStreamResult ↔ TPCDSThroughputStreamResult

Both dataclasses are **completely identical** - every field, type, and
default matches.

| Field | TPC-H type | TPC-DS type | Classification |
|---|---|---|---|
| `stream_id` | `int` | `int` | **shared** |
| `start_time` | `float` | `float` | **shared** |
| `end_time` | `float` | `float` | **shared** |
| `duration` | `float` | `float` | **shared** |
| `queries_executed` | `int` | `int` | **shared** |
| `queries_successful` | `int` | `int` | **shared** |
| `queries_failed` | `int` | `int` | **shared** |
| `query_results` | `list[dict]` (default `[]`) | `list[dict]` (default `[]`) | **shared** |
| `success` | `bool` (default `True`) | `bool` (default `True`) | **shared** |
| `error` | `Optional[str]` (default `None`) | `Optional[str]` (default `None`) | **shared** |

**Outcome:** `ThroughputStreamResult` in `core.throughput.result` replaces
both. The existing names become aliases in their respective modules for
backward compatibility:
```python
# tpch/throughput_test.py
TPCHThroughputStreamResult = ThroughputStreamResult
# tpcds/throughput_test.py
TPCDSThroughputStreamResult = ThroughputStreamResult
```

---

## Test Result: TPCHThroughputTestResult ↔ TPCDSThroughputTestResult

| Field | TPC-H | TPC-DS | Classification |
|---|---|---|---|
| `config` | `TPCHThroughputTestConfig` | `TPCDSThroughputTestConfig` | **TPC-H only** / **TPC-DS only** - different types |
| `start_time` | `str` | `str` | **shared** |
| `end_time` | `str` | `str` | **shared** |
| `total_time` | `float` | `float` | **shared** |
| `throughput_at_size` | `float` | `float` | **shared** |
| `streams_executed` | `int` | `int` | **shared** |
| `streams_successful` | `int` | `int` | **shared** |
| `stream_results` | `list[TPCHThroughputStreamResult]` | `list[TPCDSThroughputStreamResult]` | **shared** (both are `ThroughputStreamResult`) |
| `query_throughput` | `float` (default `0.0`) | `float` (default `0.0`) | **shared** |
| `success` | `bool` (default `True`) | `bool` (default `True`) | **shared** |
| `errors` | `list[str]` (default `[]`) | `list[str]` (default `[]`) | **shared** |
| `scale_factor` | property → `config.scale_factor` | property → `config.scale_factor` | **shared pattern** |

**Spec-specific fields:** only `config` differs (different type). No other
spec-specific fields exist - both dataclasses are structurally equivalent.

**Outcome:** `ThroughputResult` base in `core.throughput.result` holds all
fields except `config`. The existing `TPCHThroughputTestResult` and
`TPCDSThroughputTestResult` in their respective modules retain their field
names and public API unchanged. Their `stream_results` field type becomes
`list[ThroughputStreamResult]` (functionally identical since both
`TPCH/DS ThroughputStreamResult` are aliases to the same type).

---

## Success-Rate Gate Difference

**Update (`throughput-timeout-leak-and-success-gates`, 2026-07):** TPC-DS's
gate is now configurable, mirroring TPC-H. The two hard-coded `0.7` literals
that previously existed (the run-level gate in `run()` and the per-stream
gate in `_finalize_stream_success()`) have been replaced with a single
`TPCDSThroughputTestConfig.min_success_rate` field (default `0.70`), which
`validate_results()` also now reads instead of a third hard-coded `0.7`.

| | TPC-H | TPC-DS |
|---|---|---|
| Gate expression | `streams_successful / num_streams >= config.min_success_rate` | `streams_successful / max(num_streams, 1) >= config.min_success_rate` |
| Default threshold | `0.99` (from `TPCHThroughputTestConfig.min_success_rate`) | `0.70` (from `TPCDSThroughputTestConfig.min_success_rate`) |
| Configurable? | Yes | Yes |

**Spec citation (both benchmarks): none exists.** Neither the TPC-H
specification nor the TPC-DS specification v4.0.0 defines a partial-success
/ "acceptable failure rate" allowance for the Throughput Test. Checked
directly against the specification PDFs bundled in this repo
(`_sources/tpc-h/specification.pdf`, `_sources/tpc-ds/specification/
specification_4.0.0.pdf`):

- TPC-H specification, Clause 5.1.1.6: *"A failed run is defined as a run
  that did not complete successfully due to unforeseen system failures."*
  There is no companion clause tolerating a percentage of stream or query
  failures in a compliant run.
- The TPC-H spec's only "1%" / "0.99" occurrences are unrelated numeric
  *result-value* tolerances for ratio/AVG aggregate validation (Clause
  2.2.4.2), not a query- or stream-failure allowance. The previous comment
  in `TPCHThroughputTestConfig` ("TPC-H spec allows up to 1% query failures
  in production environments") was an invented citation; it has been
  corrected.
- The TPC-DS specification has no equivalent clause either; its "success"
  occurrences are about individual operations (e.g. data-maintenance
  functions, Data Accessibility Test) completing, not a benchmark-wide
  partial-success tolerance.

**Conclusion:** both `0.99` and `0.70` are BenchBox-internal tolerances for
treating a throughput run as "usable" for iterative development/CI despite
some stream or query failures. Neither is an official TPC compliance gate;
a result with `streams_successful < num_streams` (TPC-H) or any
sub-100%-successful stream (TPC-DS) is not eligible for TPC-compliant/
audited reporting regardless of how these config knobs are set. This is now
documented directly on each config dataclass (`min_success_rate`
docstring/comment) rather than only here.

**Outcome:** The success-rate gate is NOT extracted to `StreamRunner`. Each
spec's `run()` applies its own gate after `StreamRunner.compute_metrics()`
returns, reading its own dataclass's `min_success_rate` field. This
preserves TPC-H's configurable threshold and gives TPC-DS the same
single-source-of-truth pattern instead of duplicated hard-coded literals.

**Gate coupling (review follow-up):** for TPC-DS, `min_success_rate` now
drives *both* gates -- the run-level stream-success gate in `run()` and the
per-stream query-success gate in `_finalize_stream_success()`. Before this
change these were two independent hardcoded `0.7` literals that happened to
share a value; a user tuning one gate now necessarily tunes the other
identically, since both read the same config field. There is no mechanism
today to set the run-level and per-stream thresholds independently. This is
a documentation-only note -- no behavior changed from the single-source-of-
truth refactor itself; it is called out here because it's a discoverability
gap for anyone reaching for `min_success_rate` expecting it to affect only
one of the two gates. (TPC-H's `min_success_rate` has always had this same
shape: see `TPCHThroughputTestConfig` -- its gate is run-level only, TPC-H
has no per-stream query-success sub-gate, so no coupling applies there.)

---

## Timed-Out Stream Leak (`throughput-timeout-leak-and-success-gates`, 2026-07)

`StreamRunner.execute()` previously enforced its per-stream timeout via
`future.result(timeout=timeout)` inside a `concurrent.futures.as_completed()`
loop. This is dead code: `as_completed()` only yields a future once it is
already `done()`, so calling `.result(timeout=...)` on it can never raise
`TimeoutError` — the loop would silently wait as long as the slowest stream
took, with no timeout enforcement at all in practice.

**Fix:** the timeout is now passed to `as_completed(pending, timeout=...)`
itself (bounding the whole wait), with a fallback loop that classifies any
still-pending future as timed-out/leaked when that call raises
`TimeoutError`. This is a detection-accuracy fix only; the
`streams_executed` / `streams_successful` / `errors` accounting contract for
every future -- whether processed via the main loop or the timeout fallback
-- is unchanged (see `StreamRunner.execute()`'s shared `_record_completed_future`
helper).

A leaked/timed-out stream is now:
- Always logged via `logger.warning(...)`, not gated on `config.verbose`
  (previously gated, meaning it could be entirely silent).
- Recorded in `result.errors` with an explicit message noting the stream's
  worker thread may still be running and holding its DB connection (Python
  cannot forcibly cancel a running thread).

An opt-in, default-OFF `cancel_on_timeout` config flag (mirrored on both
`TPCHThroughputTestConfig` and `TPCDSThroughputTestConfig`) adds cooperative
cancellation: `StreamRunner.execute()` gives every stream a `threading.Event`
and sets the timed-out stream's event; each spec's `_execute_stream` query
loop polls its own event between queries and stops early if set, marking
the stream unsuccessful. This lets a leaked stream actually wind down soon
after a timeout instead of running unbounded — the only safe mechanism,
since Python threads cannot be hard-killed. **Update (`throughput-executor-
nonblocking-shutdown`, 2026-07, see below):** `execute()` no longer blocks
its own return on a leaked thread either way — see "Non-Blocking Executor
Shutdown" below for how this composes with cooperative cancellation.

**Stale cancel-event leak across reused configs (review follow-up):**
`config._stream_cancel_events` is set purely by presence, and each spec's
per-query check historically looked it up via `getattr(config,
"_stream_cancel_events", None)` alone, without checking
`config.cancel_on_timeout`. If a caller reuses the same config object
across multiple `run()` calls -- run 1 with `cancel_on_timeout=True` where a
stream times out and its `Event` gets `set()`, then run 2 reusing that same
config object with `cancel_on_timeout=False` -- `StreamRunner.execute()`
would skip refreshing `_stream_cancel_events` entirely (since cooperative
cancel is off), leaving the stale, already-set `Event` from run 1 in place;
run 2's `_execute_stream` would then observe it by presence and immediately
mark that stream cancelled/unsuccessful even though nothing in run 2 timed
out.

**Fix (belt and suspenders):**
1. `StreamRunner.execute()` now explicitly resets `config._stream_cancel_events
   = {}` whenever cooperative cancel is *not* enabled for that call, instead
   of leaving whatever dict (or absence of one) a prior call left behind.
2. Both specs' cancel-event lookup (`TPCHThroughputTest._resolve_cancel_event`,
   and the equivalent inline lookup in
   `TPCDSThroughputTest._execute_stream`) additionally gate on
   `config.cancel_on_timeout` directly, so a stale attribute value could
   never take effect even if (1) were ever skipped or bypassed.

The TPC-H `_resolve_cancel_event` docstring previously claimed "absent
[cancel_on_timeout] (the default), this always returns None" -- true only
because presence of `_stream_cancel_events` used to imply
`cancel_on_timeout` was set on *this* call, which the config-reuse case
violates. The docstring has been corrected to describe the invariant the
code now actually guarantees (the explicit `cancel_on_timeout` gate),
independent of whatever `_stream_cancel_events` currently holds.

**Max-workers/timeout interaction (review follow-up, no behavior change):**
the per-stream timeout enforced via `as_completed(pending, timeout=...)`
bounds the *whole* remaining wait, not each future individually. Treating it
as equivalent to a true per-stream timeout relies on every stream starting
to run immediately (no queueing), which holds only when `max_workers >=
num_streams` -- the default, since `max_workers` falls back to
`num_streams` when unset. If a caller explicitly sets `max_workers <
num_streams`, later streams queue behind earlier ones but are still charged
against the same start-of-window deadline, so a queued stream could be
reported as timed-out before it ever executes a single query.
`StreamRunner.execute()` now logs a `logger.warning(...)` when this
mis-configuration is detected (`max_workers < num_streams` and a timeout is
set); default behavior (unset or `max_workers >= num_streams`) is
unaffected.

---

## Non-Blocking Executor Shutdown (`throughput-executor-nonblocking-shutdown`, 2026-07)

`throughput-timeout-leak-and-success-gates` (above) fixed timeout
*detection* (a leaked stream is now always logged and recorded in
`result.errors`) but explicitly deferred a residual problem: `execute()`
ran its streams inside a `with concurrent.futures.ThreadPoolExecutor(...)`
block. The context manager's implicit `__exit__` calls
`shutdown(wait=True)`, which blocks until *every* submitted thread
returns — including a leaked one. With cooperative cancellation off (the
default), a genuinely hung stream therefore still blocked `execute()`
itself for as long as the stream kept running, and with it the whole
throughput phase and any subsequent phase (e.g. data maintenance).

**Fix:** `execute()` now manages the `ThreadPoolExecutor` manually (no
`with` block) and calls `executor.shutdown(wait=False)` in a `finally`.
`shutdown(wait=False)` only stops the executor from accepting new
submissions — it does not touch, join, or wait on threads that are already
running. This is deliberately **not** a thread-kill: Python cannot forcibly
stop a running thread, and this change does not attempt to. A leaked
thread is *abandoned*, not killed — it keeps running `stream_fn` to
completion in the background, entirely decoupled from the caller of
`execute()`.

**Healthy-path behavior is unchanged.** When every stream completes before
the timeout (or no timeout is set), every future is already `done()` by
the time the `as_completed()`/fallback loop finishes, so
`shutdown(wait=False)` has nothing left to wait for — it is a no-op
compared to the old `shutdown(wait=True)`. Only the hung-stream shutdown
path changes; default timeout behavior for healthy runs is unaffected.

### Zombie connection ownership

A leaked stream's database connection is owned and opened by that
stream's own `_execute_stream` implementation (TPC-H's and TPC-DS's
`throughput_test.py` each open/close their own connection per stream).
`StreamRunner.execute()` never held or touched that connection directly,
and this change does not alter that: the connection is closed by the
stream's own `finally` block whenever that thread's `stream_fn` call
eventually returns — naturally, or sooner if cooperative cancellation
(`cancel_on_timeout=True`) is enabled and the stream notices its cancel
event between queries. `execute()` returning early does not close, orphan,
or leak the connection any differently than before; it only stops
*waiting* for that closure to happen before returning control to the
caller.

### TTT / accounting semantics for a stream that outlives `execute()`

No accounting behavior changes here — a leaked stream was **already**
excluded from `result.stream_results` (and therefore from TTT and
`streams_successful`) under the old, blocking behavior, because
`_record_completed_future()` is only invoked for futures observed as
`done()`; a still-pending leaked future never reaches it. It contributes
only to `result.streams_executed` (incremented in the timeout fallback
loop) and to `result.errors` (the leak-surfacing message). This item
changes *when* `execute()` returns, not *what* gets counted — the
`streams_executed` / `streams_successful` / `errors` contract from
`throughput-timeout-leak-and-success-gates` is unchanged.

### Residual hazard: overlap with a subsequent phase

This is the hazard `throughput-timeout-leak-and-success-gates` explicitly
deferred. Because `execute()` (and therefore the whole throughput phase)
can now return while a leaked stream's thread is still running, a caller
that immediately proceeds to a subsequent phase (e.g. TPC-DS data
maintenance) can now genuinely overlap with that zombie thread still
issuing queries and holding a connection against the same database. This
was already possible in principle before this change (Python cannot
forcibly cancel a thread either way), but the old blocking `shutdown(wait=
True)` accidentally provided a de facto (unbounded, and therefore
unreliable as a guarantee) serialization between the throughput phase and
whatever ran next, simply because `execute()` could not return until the
zombie finished. That accidental serialization is now gone by design.

Mitigating this overlap is the job of `cancel_on_timeout=True`: it bounds
the zombie's remaining lifetime to roughly one more query instead of
leaving it unbounded, shrinking (but not eliminating, since Python still
cannot force a thread to stop mid-query) the window in which a subsequent
phase can run concurrently with it. Callers whose downstream phases are
sensitive to this overlap (e.g. connection-pool exhaustion, contention on
a shared DB) should enable cooperative cancellation and/or leave headroom
between phases; `StreamRunner.execute()` does not — and, given Python's
threading constraints, cannot — provide a stronger guarantee than that.

---

## Duplicate Cluster Targeted (R-06)

The 77-line pylint R0801 cluster (`tpcds:200-276` ↔ `tpch:149-226`) is the
`concurrent.futures` executor block + metrics calculation inside `run()`.
This is the sole extraction target for `StreamRunner`:

1. `StreamRunner.execute()` - concurrent executor, future collection,
   timeout/error handling.
2. `StreamRunner.compute_metrics()` - TTT calculation from first-stream
   start to last-stream end, Throughput@Size, query throughput.

Everything outside this block (setup, preflight for TPC-DS, success-rate
gate, verbose logging after completion) stays spec-local.
