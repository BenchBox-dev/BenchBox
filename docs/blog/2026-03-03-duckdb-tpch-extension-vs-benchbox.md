---
blogpost: true
date: Mar 3, 2026
author: Joe Harris
series: building-benchbox
post_number: 5
type: architecture-design
tags: benchbox, duckdb, tpch, benchmarking, methodology, comparison, workflow
meta_description: "DuckDB's tpch extension and BenchBox both run TPC-H, but they answer different questions. We compare scope, workflow control, and timing boundaries."
---

# DuckDB `tpch` Extension vs BenchBox TPC-H

> Same benchmark name, different contract: fast in-engine checks vs full benchmark workflow control.

**TL;DR**: DuckDB's `tpch` extension gives you the fastest path to a local TPC-H query inside DuckDB. BenchBox gives you full benchmark workflow control: official `dbgen`/`qgen` tooling, explicit phases, maintenance operations, and structured outputs much closer to an official TPC-H run shape. Use the extension for quick checks; use BenchBox when you need the full workflow.

---

## Introduction

DuckDB's `tpch` extension was a major inspiration for BenchBox. The simplicity of `INSTALL tpch; LOAD tpch; CALL dbgen(...)` set the bar for developer experience, and we wanted to match that ease of entry while adding workflow structure around it.

Where the two paths diverge is scope. The extension keeps everything inside DuckDB: data generation, query execution, and answer validation through a concise pragma interface. BenchBox wraps the full TPC-H lifecycle (official `dbgen`/`qgen` binaries, explicit phases, maintenance operations, structured result files) and makes each step independently observable.

One easy comparison mistake is to treat one number from `PRAGMA tpch(1)` and one number from a full `benchbox run` as a direct speed ranking. That mixes engine query timing and workflow timing into one metric.

In this post, we compare both implementations in practical terms, then show a fair comparison protocol you can run yourself.

## The comparison problem

Both paths run TPC-H, the Transaction Processing Performance Council analytical benchmark with 22 queries and standardized data-generation rules. That shared label makes them look interchangeable.

In practice, they are not interchangeable because they execute different scopes of work.

DuckDB extension mode keeps the workflow inside DuckDB. You load the extension, generate data, and execute query templates through built-in entry points. This is concise and effective for local exploration.

BenchBox mode runs TPC-H as an explicit sequence of steps. Data generation, loading, query execution, validation hooks, and result export are all visible steps in the run. This adds plumbing, but it gives you run tracking and comparability over time.

The practical effect is simple:

- Extension path often answers: "How quickly can I run this benchmark operation inside DuckDB?"
- BenchBox path often answers: "How did the full benchmark workflow behave, and what evidence did it produce?"

Both are valid. They answer different questions.

## DuckDB extension mode

DuckDB's extension flow is intentionally minimal.

```sql
INSTALL tpch;
LOAD tpch;
CALL dbgen(sf=1);
PRAGMA tpch(1);
```

The `tpch` extension documentation highlights several practical features ([DuckDB TPC-H extension docs](https://duckdb.org/docs/stable/core_extensions/tpch)):

- `CALL dbgen(sf=<value>)` handles TPC-H data generation in-engine.
- `sf=0` creates schema without generating data.
- `children` and `step` allow chunked and parallelized data-generation control.
- Existing tables are not dropped automatically during regeneration.

For query execution, `PRAGMA tpch(query_id)` provides direct query access with predefined bind behavior ([DuckDB TPC-H extension docs](https://duckdb.org/docs/stable/core_extensions/tpch), [DuckDB benchmarking guide](https://duckdb.org/docs/stable/guides/performance/benchmarks)).

DuckDB also exposes `tpch_answers()`, with documented expected answers currently for SF 0.01, 0.1, and 1 ([DuckDB TPC-H extension docs](https://duckdb.org/docs/stable/core_extensions/tpch)).

Why this path is strong:

- Very low setup overhead.
- Direct SQL ergonomics.
- Good fit for fast local iteration.

Where this path is narrower:

- It is DuckDB specific by design.
- Query bind behavior is predefined at the extension entry point.
- DuckDB's `tpch` extension does not support RF1/RF2 maintenance operations (the TPC-H insert and delete refresh functions that simulate ongoing data maintenance).
- Workflow metadata and artifact structure are not the primary interface.

Maintenance support note: the documented extension API covers `tpch` (pragma), `tpch_queries`, and `tpch_answers`, with no RF1/RF2 maintenance entry points ([DuckDB TPC-H extension docs](https://duckdb.org/docs/stable/core_extensions/tpch)).

## BenchBox TPC-H mode

BenchBox runs TPC-H as an end-to-end process, not only as query execution.

At implementation level, BenchBox TPC-H has three core layers:

1. Data generation layer
2. Query generation layer
3. Benchmark orchestration layer

### Data generation path

BenchBox uses official TPC tooling paths (`dbgen`) with precompiled binary lookup and compile fallback. That design supports both development and packaged environments where source trees may be absent.

Generator behavior includes scale-factor validation, parallel chunk generation, streaming generation compatibility paths, and regeneration control based on validation state.

### Query generation path

BenchBox uses official `qgen` for TPC-H query generation, with seed-aware and scale-aware behavior. Translation and compatibility handling are applied where needed by the benchmark layer.

This matters when you want:

- Explicit seed and permutation control over generated queries.
- Consistent query handling beyond one platform boundary.
- A workflow that can extend to multi-platform studies.

### Orchestration and execution path

BenchBox exposes explicit phases and artifacts.

```bash
$ benchbox run --platform duckdb --benchmark tpch --scale 0.01 --phases power --non-interactive
```

```bash
$ benchbox run --platform duckdb --benchmark tpch --scale 1 --phases generate,load,power --non-interactive
```

This phase model enables isolation of generation vs execution timing, controlled reuse policies, and structured result files for follow-up analysis.

BenchBox also includes TPC-H maintenance operations (RF1 and RF2) in code, and wires maintenance into the official benchmark flow as phase 3.

BenchBox also includes an official-benchmark orchestration path that runs power, throughput, and maintenance tests together and computes `QphH@Size` (the TPC-H composite performance metric that combines power and throughput scores at a given scale factor). This makes BenchBox much closer to full TPC-H run structure than extension-only query execution.

## Side-by-side capability matrix

| Dimension | DuckDB `tpch` extension | BenchBox TPC-H implementation |
| --- | --- | --- |
| Primary objective | Fast in-engine TPC-H workflow in DuckDB | Full benchmark workflow orchestration |
| Setup path | `INSTALL` and `LOAD` extension | BenchBox CLI/API run orchestration |
| Data generation | `CALL dbgen(...)` inside DuckDB | Official `dbgen` lifecycle with binary resolution and validation hooks |
| Query execution interface | `PRAGMA tpch(query_id)` | `qgen` generation plus adapter execution path |
| Query parameter control | Predefined bind behavior in pragma entry point | Seed-aware and scale-aware query generation controls |
| TPC-H run-shape alignment | Query-oriented extension path | Power + throughput + maintenance orchestration with `QphH@Size` calculation |
| Phase control | Not phase-oriented by default | Explicit `generate`, `load`, `power`, `throughput`, `maintenance` phases |
| Maintenance operations (RF1/RF2) | Not available in extension API | Implemented and integrated into official benchmark flow |
| Artifacts | Database objects and immediate query output | Structured result files with phase and run metadata |
| Platform scope | DuckDB only | DuckDB plus cross-platform workflow patterns |
| Best fit | Local exploratory checks and quick experiments | Phase-controlled benchmark runs and comparative workflow analysis |

A practical interpretation is that extension mode reduces startup friction, while BenchBox increases workflow observability.

### Query extraction example: fixed extension text vs generated BenchBox text

You can see the query-model difference directly by extracting query text.

DuckDB extension (`tpch_queries()`):

```sql
SELECT query FROM tpch_queries() WHERE query_nr = 6;
-- WHERE l_shipdate >= CAST('1994-01-01' AS date)
--   AND l_discount BETWEEN 0.05 AND 0.07
--   AND l_quantity < 24;
```

BenchBox (`TPCHBenchmark.get_query`, translated to DuckDB dialect):

```python
bench.get_query(6, seed=0, scale_factor=1.0, dialect="duckdb")
# ... l_shipdate >= CAST('1993-01-01' AS DATE) ...
# ... l_discount BETWEEN 0.02 - 0.01 AND 0.02 + 0.01 ...
# ... l_quantity < 24

bench.get_query(6, seed=7, scale_factor=1.0, dialect="duckdb")
# ... l_shipdate >= CAST('1994-01-01' AS DATE) ...
# ... l_discount BETWEEN 0.08 - 0.01 AND 0.08 + 0.01 ...
# ... l_quantity < 25
```

BenchBox can also derive different substitutions from TPC-H stream permutations:

```python
bench.get_query(6, params={"stream_id": 0}, scale_factor=1.0, dialect="duckdb")
bench.get_query(6, params={"stream_id": 1}, scale_factor=1.0, dialect="duckdb")
```

In a quick SF1 vs SF10 text check with fixed seed (`42`), only Q11 changed in this local run, where the HAVING threshold factor changed from `0.0001000000` to `0.0000100000`.

### Measured two-scale snapshot (Q1 subset)

To keep timing boundaries explicit, we ran a bounded comparison at two scales using query subset `Q1`.

- Extension engine timing boundary: median of 3 measured `PRAGMA tpch(1)` runs after warmup.
- Extension workflow boundary: `INSTALL + LOAD + CALL dbgen + first PRAGMA tpch(1)`.
- BenchBox engine timing boundary: `summary.timing.geometric_mean_ms` from result JSON.
- BenchBox workflow boundary: shell wall-clock `real` from `/usr/bin/time -p`.

| Scale | Extension engine timing (ms) | BenchBox engine timing (ms) | Extension workflow timing (ms) | BenchBox workflow timing (ms) |
| --- | ---: | ---: | ---: | ---: |
| 0.01 | 5.572 | 8.0 | 138.193 | 2310 |
| 1 | 39.071 | 31.3 | 4651.215 | 2360 |

Notice the crossover: at SF 0.01, the extension workflow is 16x faster end-to-end because BenchBox's fixed overhead (process spawning, binary resolution, phase orchestration) dominates when the actual data and query work is tiny. At SF 1, that fixed overhead is amortized and BenchBox's parallelized external `dbgen` path completes faster than the extension's in-process generation. Engine timing stays comparable at both scales because both paths ultimately execute the same DuckDB query engine.

This is not an official benchmark report. It is a bounded methodology sample showing why boundary labeling matters.

### Evidence snapshot

Commands used:

```bash
# BenchBox path
$ uv run benchbox run --platform duckdb --benchmark tpch --scale 0.01 \
    --phases generate,load,power --queries 1 --force datagen --non-interactive
$ uv run benchbox run --platform duckdb --benchmark tpch --scale 1 \
    --phases generate,load,power --queries 1 --force datagen --non-interactive
```

```sql
-- DuckDB extension path (captured via Python duckdb API)
INSTALL tpch; LOAD tpch; CALL dbgen(sf=<scale>); PRAGMA tpch(1);
```

Captured artifacts (available in the BenchBox repository):

- Extension measurements: `tpch-extension-vs-benchbox-measurements-2026-03-02.json`
- BenchBox SF 0.01 result: `tpch_sf001_duckdb_sql_20260302_092013_6f872099.json`
- BenchBox SF 1 result: `tpch_sf1_duckdb_sql_20260302_092035_1b6dd90b.json`

## Fair comparison methodology

If you want to compare these paths responsibly, separate two timing categories:

1. Engine-centric query-path timing.
2. End-to-end workflow timing.

Then hold all other factors constant:

- Hardware and OS.
- DuckDB and BenchBox versions.
- Scale factor and query subset.
- Reuse policy for data and database state.

### Test environment

- **Hardware**: Apple Silicon Mac mini class host, 10 CPU cores, 16 GB RAM
- **OS**: macOS 26.3 (`Darwin 25.3.0`, arm64)
- **DuckDB**: 1.4.3
- **BenchBox**: 0.1.3
- **Python**: 3.11.12
- **Benchmark**: TPC-H, scales 0.01 and 1, query subset `Q1`
- **Methodology**:
  - Extension: 1 warmup plus 3 measured `PRAGMA tpch(1)` runs after `dbgen`
  - BenchBox: `generate,load,power` with `--queries 1 --force datagen`, wall time from `/usr/bin/time -p`
- **Limitations**: Query subset mode is not official TPC-H compliant; this sample is for compare-and-contrast methodology, not certification reporting
- **Compliance caveat**: BenchBox includes official run-shape components, but this post is not a TPC-certified audited result

### Suggested protocol

1. Run extension mode for in-engine setup and query checks.
2. Run BenchBox at matching scale and query subset.
3. Report engine and workflow timing separately.
4. State data reuse policy explicitly.

Without these caveats, timing numbers are easy to over-interpret.

## Decision guide

| If your question is... | Prefer this path | Why |
| --- | --- | --- |
| "Can I run a quick local TPC-H check in DuckDB right now?" | DuckDB extension | Lowest setup overhead and direct SQL entry points |
| "Can I separate generation, load, and execution cleanly?" | BenchBox | Phase model is explicit and scriptable |
| "Can I keep structured artifacts for later comparison?" | BenchBox | Result files and metadata are first-class outputs |
| "Can I run something close to full TPC-H official structure?" | BenchBox | Includes power, throughput, maintenance flow, and `QphH@Size` calculation path |
| "Can I do a one-off query sanity check?" | DuckDB extension | Fast feedback loop |
| "Can I apply one workflow pattern across more than one platform?" | BenchBox | Orchestration and dialect handling are designed for portability |

In practice, these paths can complement each other. Teams often use extension mode for immediate local checks and BenchBox for tracked runs.

## Try it yourself

If you want to pressure-test these conclusions on your machine, a short exercise is enough.

1. Run one extension-path query at SF 0.01.
2. Run one BenchBox `power` subset at SF 0.01.
3. Repeat at SF 1 and compare engine timing and workflow timing separately.

```sql
INSTALL tpch;
LOAD tpch;
CALL dbgen(sf=0.01);
PRAGMA tpch(1);
```

```bash
$ benchbox run --platform duckdb --benchmark tpch --scale 0.01 \
    --phases generate,load,power --queries 1 --force datagen --non-interactive
```

Write down what question each number answers. That habit prevents most comparison errors.

## What we learned building BenchBox

Benchmark engineering is not only query execution.

Phase boundaries, query-generation controls, maintenance support, and artifact capture can look like overhead until you need to compare runs over time, explain a regression, or port the same workflow shape to another platform.

At the same time, concise in-engine workflows are valuable. The right design is not one path replacing the other. The right design is clear boundaries and explicit trade-offs.

## Conclusion

DuckDB's `tpch` extension and BenchBox's TPC-H implementation share a benchmark name, but they serve different operational goals.

If your goal is fast local exploration inside DuckDB, extension mode is a strong choice.

If your goal is full benchmark workflow control, including a run structure much closer to official TPC-H (power, throughput, maintenance), BenchBox is the better fit.

Quick checklist for future comparisons:

1. Label each timing number as engine or workflow.
2. Keep scale, query subset, and reuse policy explicit.
3. Avoid ranking tools from a single mixed-boundary metric.

We built BenchBox to make workflow guarantees explicit. We would love to hear how you combine both paths in practice. Open an issue and share your workflow.

---

## References

1. [DuckDB TPC-H extension docs](https://duckdb.org/docs/stable/core_extensions/tpch)
2. [DuckDB benchmarking guide](https://duckdb.org/docs/stable/guides/performance/benchmarks)
3. [BenchBox TPC-H benchmark core](https://github.com/joeharris76/BenchBox/blob/main/benchbox/core/tpch/benchmark.py)
4. [BenchBox TPC-H generator](https://github.com/joeharris76/BenchBox/blob/main/benchbox/core/tpch/generator.py)
5. [BenchBox TPC-H query manager](https://github.com/joeharris76/BenchBox/blob/main/benchbox/core/tpch/queries.py)
6. [BenchBox TPC-H maintenance implementation](https://github.com/joeharris76/BenchBox/blob/main/benchbox/core/tpch/maintenance_test.py)
7. [BenchBox official benchmark flow](https://github.com/joeharris76/BenchBox/blob/main/benchbox/core/tpch/official_benchmark.py)
