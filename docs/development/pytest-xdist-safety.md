<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Pytest xdist Safety

```{tags} contributor, guide, testing
```

BenchBox defaults to pytest-xdist for local runs, but some parts of the test
suite also create native thread pools, parse large module trees, or spawn
subprocess-heavy workloads. That combination is enough to make a developer
machine unresponsive if worker counts are not capped early enough.

This page records the debugging outcome and the guardrails that must remain in
place when contributors change pytest configuration, xdist behavior, or
concurrency-heavy tests.

## Executive Summary

Two root causes were identified and fixed:

1. **Worker oversubscription** (found first): `-n 8` with uncapped workers
   created ~3.9 GB RSS and 181 threads on 114 tests. Fixed by an early-loaded
   plugin that caps macOS to 2 workers.

2. **`setproctitle` → `launchservicesd` storm** (found second, the real
   beachball driver): Even with workers capped to 2, the macOS beachball
   persisted during large suite runs. The root cause was `setproctitle()`:
   xdist calls it twice per test (~200 calls/second) to update worker process
   titles. On macOS this triggers `launchservicesd` to continuously rebuild its
   process registry, consuming **200%+ CPU** and **~900 MB RSS**. Fixed by
   patching `worker_title` to a no-op on macOS via stack walking in
   `pytest_configure`.

## Investigation Timeline

### Phase 1: Worker Oversubscription (Original Finding)

A minimal reproducer with 114 tests showed that `-n 8` created too many workers:

```bash
uv run -- python -m pytest -vv -n 8 \
  tests/unit/test_release_sync.py \
  tests/unit/test_marker_strategy.py \
  tests/unit/platforms/dataframe/test_unified_frame.py
```

This was solved by capping workers to 2 on macOS via
[`_benchbox_pytest_xdist_safety.py`](../../_benchbox_pytest_xdist_safety.py).

### Phase 2: Persistent Beachball (New Finding)

After the worker cap, the beachball still occurred during real test runs
(12,900+ tests). Systematic monitoring revealed `launchservicesd` as the #1
CPU consumer at **200%+ CPU**, not pytest.

### Phase 2 Controlled Experiments

| Experiment | launchservicesd CPU | Result |
|---|---|---|
| Baseline (no tests) | 0% | Normal |
| Pure CPU load (no pytest) | 0% | Not CPU-related |
| Serial pytest (`-n 0`, 2380 tests) | 0% | Not file I/O |
| 2 concurrent serial pytests | 0% | Not concurrent Python |
| Parallel collection only (`-n 2 --collect-only`) | 0% | Not collection |
| Parallel execution (`-n 2`, 2380 tests) | **228%** | **xdist-specific** |
| Parallel with output `/dev/null` | **211%** | Not terminal rendering |
| Parallel with `setproctitle` C ext disabled | **0%** | **ROOT CAUSE** |
| Parallel with `worker_title` patched to no-op | **0%** | **FIX CONFIRMED** |

## Root Cause: `setproctitle` → `launchservicesd`

The `setproctitle` package (installed as a transitive dependency via `mutmut`)
provides a C extension that modifies process titles via macOS kernel APIs.
xdist's `remote.py` calls `setproctitle()` twice per test execution:

```python
# xdist/remote.py lines 224-230
worker_title("[pytest-xdist running] %s" % item.nodeid)  # before test
worker_title("[pytest-xdist idle]")                        # after test
```

At ~100+ tests/second per worker, this generates ~200+ kernel-level process
title updates per second. On macOS, each update notifies `launchservicesd`
which rebuilds its process registry. The daemon cannot keep up and enters a
sustained high-CPU loop that:

- Consumes 200%+ CPU (2 full cores)
- Grows to ~900 MB RSS
- Triggers `runningboardd` at ~50% CPU
- Starves `WindowServer` and the terminal app of responsive CPU/memory
- Causes the macOS beachball

### Why the Initial Investigation Missed This

The original 114-test reproducer was too small to trigger the effect. At low
test counts, `setproctitle` calls are infrequent enough that `launchservicesd`
handles them without stress. The threshold appears to be around several hundred
tests in parallel before `launchservicesd` CPU becomes dominant.

## Current Protections

### 1. Early xdist cap

[`_benchbox_pytest_xdist_safety.py`](../../_benchbox_pytest_xdist_safety.py)
is loaded from [`pytest.ini`](../../pytest.ini) using:

```ini
-p _benchbox_pytest_xdist_safety
```

That plugin:

- rewrites the last effective `-n` or `--numprocesses` argument before xdist
  startup
- caps macOS local runs to `2` workers by default
- prints a clear message when it rewrites a request
- honors `BENCHBOX_MAX_XDIST_WORKERS` for explicit local experiments

This must remain an **early** hook. Re-implementing the cap in
`pytest_configure` is not equivalent.

### 2. `setproctitle` suppression on macOS

[`tests/conftest.py`](../../tests/conftest.py) patches `worker_title` to a
no-op on macOS in xdist worker processes. The implementation uses stack walking
because xdist's `remote.py` executes in an `execnet` `__channelexec__`
namespace: `import xdist.remote` loads a different module object than the one
actually executing. The stack walk only patches frames whose `__name__` is
`"__channelexec__"` and that have a callable `worker_title`, so unrelated
frames with a `worker_title` name are ignored.

This must remain in `pytest_configure` (not earlier) because it needs
`config.workerinput` to detect worker processes.

### 3. Native thread limits

[`tests/conftest.py`](../../tests/conftest.py) sets native-library thread caps
before importing heavy modules:

- `POLARS_MAX_THREADS=2`
- `OMP_NUM_THREADS=1`
- `MKL_NUM_THREADS=1`
- `OPENBLAS_NUM_THREADS=1`
- `NUMEXPR_NUM_THREADS=1`

Those are still necessary. The xdist cap prevents runaway worker counts, while
these limits prevent each worker from using the whole machine by itself.

### 4. DuckDB thread control

DuckDB does not reliably obey the generic thread environment variables above.
BenchBox therefore patches `duckdb.connect()` in `tests/conftest.py` so test
connections default to `config={"threads": "2"}` unless a test explicitly
overrides that value.

Do not replace this with `config.option.duckdb_threads` or another controller
side-only setting. That path was already shown to be ineffective.

### 5. Regression coverage

[`tests/unit/test_xdist_safety.py`](../../tests/unit/test_xdist_safety.py)
asserts that:

- macOS defaults cap to `2`
- the environment override works
- `-n auto` is capped
- explicit `-n 8` style requests are rewritten
- the last effective `-n` wins when pytest sees multiple `-n` occurrences
- `setproctitle` is suppressed on macOS workers (direct stack-walk test)
- unrelated frames with a `worker_title` global are left untouched

If you change xdist startup behavior, update those tests in the same change.

## Before/After Validation

The reproducer above was run across `-n 0/1/2/4/8` before and after the final
fix. The critical signal is that requested `-n 4` and `-n 8` now collapse to
the same resource profile as safe `-n 2`.

| Requested `-n` | Before fix | After fix |
|---|---|---|
| `0` | `14.1s`, `590 MB`, `21` threads, `3` procs | `11.9s`, `589 MB`, `21` threads, `2` procs |
| `1` | `19.7s`, `749 MB`, `37` threads, `3` procs | `18.0s`, `751 MB`, `37` threads, `4` procs |
| `2` | `19.2s`, `1292 MB`, `59` threads, `6` procs | `18.0s`, `1294 MB`, `61` threads, `4` procs |
| `4` | `20.0s`, `2368 MB`, `102` threads, `7` procs | `18.4s`, `1293 MB`, `60` threads, `5` procs |
| `8` | `23.1s`, `3882 MB`, `181` threads, `13` procs | `18.4s`, `1292 MB`, `59` threads, `5` procs |

Direct sanity checks after the fix:

- `pytest -n 4 ...` reports `created: 2/2 workers`
- `pytest -n 8 ...` reports `created: 2/2 workers`

## Contributor Checklist

If you touch pytest config, xdist startup, import patterns, or concurrency-heavy
tests, do all of the following:

1. Keep the early plugin in [`pytest.ini`](../../pytest.ini), or replace it with
   something equally early.
2. Do not move the worker cap into `pytest_configure`.
3. Keep native thread limits at the top of [`tests/conftest.py`](../../tests/conftest.py).
4. Keep the DuckDB thread patch unless you have measured proof of a better
   replacement.
5. Keep the `setproctitle` suppression in `pytest_configure`. If `setproctitle`
   is re-enabled, verify that `launchservicesd` stays below 10% CPU during a
   12,000+ test parallel run.
6. Re-run the reproducer matrix at `-n 0/1/2/4/8`.
7. Collect resource data, not just pass/fail. At minimum record wall time, peak
   RSS, thread count, process count, `launchservicesd` CPU, and whether
   requested `-n 4` or `-n 8` actually created only two workers on macOS.

## Useful Commands

Run the regression tests:

```bash
uv run -- python -m pytest -n 0 tests/unit/test_xdist_safety.py -vv
```

Run the reproducer serially:

```bash
uv run -- python -m pytest -vv -n 0 \
  tests/unit/test_release_sync.py \
  tests/unit/test_marker_strategy.py \
  tests/unit/platforms/dataframe/test_unified_frame.py
```

Run the reproducer with a capped explicit request:

```bash
uv run -- python -m pytest -vv -n 8 \
  tests/unit/test_release_sync.py \
  tests/unit/test_marker_strategy.py \
  tests/unit/platforms/dataframe/test_unified_frame.py
```

Temporarily override the cap for a deliberate experiment:

```bash
BENCHBOX_MAX_XDIST_WORKERS=3 uv run -- python -m pytest -vv -n 3 <target>
```

That override is for measurement only. Do not use it as evidence that the
default should be raised unless you also capture the same before/after resource
metrics documented above.
