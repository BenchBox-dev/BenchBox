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

| | TPC-H | TPC-DS |
|---|---|---|
| Gate expression | `streams_successful / num_streams >= config.min_success_rate` | `streams_successful / max(num_streams, 1) >= 0.7` |
| Default threshold | `0.99` (from `TPCHThroughputTestConfig.min_success_rate`) | Hard-coded `0.7` |
| Configurable? | Yes - `TPCHThroughputTestConfig.min_success_rate` | No (must_preserve: keep 0.7 as default; `quality-extract-throughput-runner` makes it config-overridable) |

**Outcome:** The success-rate gate is NOT extracted to `StreamRunner`. Each
spec's `run()` applies its own gate after `StreamRunner.compute_metrics()`
returns. This preserves TPC-H's configurable threshold and TPC-DS's 70%
contract.

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
