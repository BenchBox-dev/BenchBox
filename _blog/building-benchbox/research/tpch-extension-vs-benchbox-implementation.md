# Research: DuckDB tpch extension vs BenchBox TPCH implementation

Research notes for planned Building BenchBox post:
`_blog/building-benchbox/outlines/05-duckdb-tpch-extension-vs-benchbox.md`

---

## Scope and framing

This research compares two TPCH execution paths:

1. DuckDB native `tpch` extension path (`CALL dbgen`, `PRAGMA tpch`).
2. BenchBox TPCH implementation path (official `dbgen` and `qgen` tooling, platform adapter workflow, phase orchestration, result artifacts).

The goal is not to pick a winner. The goal is to explain design intent, capability boundaries, and fair comparison methodology.

---

## Overlap and duplication check

Reviewed:
`_blog/benchbox-in-action/drafts/06-platform-specific-optimization-patterns.md`

Finding:
- Low topical overlap.
- Draft #6 is TPC-DS DataFrame optimization behavior across Polars, DataFusion, and PySpark.
- New post scope is TPCH architecture and workflow trade-offs between DuckDB extension mode and BenchBox mode.

Guardrail:
- Avoid repeating the "per-query outlier investigation" narrative from draft #6.
- Keep this post centered on implementation surfaces, reproducibility, and execution phases.

---

## Primary sources

### A) DuckDB documentation

1. DuckDB TPCH extension docs
   - URL: https://duckdb.org/docs/stable/core_extensions/tpch.html
   - Key points extracted:
   - Extension install/load flow (`INSTALL tpch; LOAD tpch`).
   - Data generation via `CALL dbgen(sf=<value>)`.
   - `sf=0` generates schema only.
   - Parallel generation controls with `children` and `step`.
   - Existing tables are not automatically dropped before regeneration.
   - Query execution via `PRAGMA tpch(<query_number>)`.
   - `PRAGMA tpch` uses predefined bind parameters.
   - `tpch_answers()` currently includes expected answers for SF 0.01, 0.1, and 1.

2. DuckDB benchmark handbook
   - URL: https://duckdb.org/docs/stable/guides/performance/benchmarking.html
   - Key point extracted:
   - For prescribed benchmark execution with fixed bind values, DuckDB recommends using benchmark frameworks rather than the simplified built-in entry point.

### B) BenchBox codebase

1. TPCH public class wrapper
   - File: `benchbox/tpch.py`
   - Evidence:
   - API exposes generation, schema SQL, query retrieval, streams, and benchmark compatibility helpers.

2. TPCH benchmark core
   - File: `benchbox/core/tpch/benchmark.py`
   - Evidence:
   - Integrates TPCH query manager and data generator.
   - Uses seed/scale-aware query retrieval.
   - Supports dialect translation path from source to target.

3. TPCH data generation implementation
   - File: `benchbox/core/tpch/generator.py`
   - Evidence:
   - Uses official dbgen binary path discovery and precompiled fallback.
   - Supports parallel chunked generation and streaming generation modes.
   - Validates generated data and regeneration logic.

4. TPCH query generation implementation
   - File: `benchbox/core/tpch/queries.py`
   - Evidence:
   - Uses official qgen binary.
   - Supports seed and scale factor behavior.
   - Handles query text cleanup and compatibility transforms.

5. DuckDB platform adapter integration
   - File: `benchbox/platforms/duckdb.py`
   - Evidence:
   - Applies runtime config (memory, threads, profiling).
   - Handles schema creation, data loading, query execution, plan capture hooks.

6. TPC binary resolution helper
   - File: `benchbox/utils/tpc_compilation.py`
   - Evidence:
   - Centralized precompiled binary selection and compile fallback for dbgen/qgen.

7. BenchBox README TPCH section
   - File: `README.md` (TPC-H detailed example)
   - Evidence:
   - Project-level claim set for TPCH coverage and workflow usage.

---

## Compare matrix (working draft)

| Dimension | DuckDB `tpch` extension | BenchBox TPCH implementation |
| --- | --- | --- |
| Setup path | SQL extension install/load in DuckDB | BenchBox CLI/API workflow with adapters |
| Data generation location | In-engine via `CALL dbgen` | External official dbgen binary with managed lifecycle |
| Query execution entry point | `PRAGMA tpch(query_id)` | Generated query text + adapter execution |
| Query parameter control | Predefined bind parameters in `PRAGMA tpch` | Seed and scale-aware qgen-driven query generation |
| Cross-platform portability | DuckDB only | Multiple platforms via dialect translation and adapters |
| Artifact model | Primarily database state and query output | Structured run results, phase timing, metadata, validation outputs |
| Best fit | Fast local TPCH exploration in DuckDB | Reproducible benchmark workflows and cross-platform studies |

---

## Benchmark and evidence plan

### Measurement principles

- Keep two timing categories separate:
1. Engine-centric query execution timing.
2. End-to-end benchmark workflow timing.
- Keep environment and data reuse policy explicit.
- Do not compare end-to-end framework workflow time directly against single SQL command time without qualification.

### Planned command set

1. DuckDB extension quick run
```sql
INSTALL tpch;
LOAD tpch;
CALL dbgen(sf=0.01);
PRAGMA tpch(1);
```

2. BenchBox TPCH smoke
```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.01 --phases power --non-interactive
```

3. BenchBox TPCH generate+load+power
```bash
benchbox run --platform duckdb --benchmark tpch --scale 1 --phases generate,load,power --non-interactive
```

4. Optional parity subset comparison
- BenchBox: `--queries Q1,Q6,Q14,Q21`
- DuckDB: execute equivalent TPCH SQL query texts manually in the same environment.

### Data to capture per run

- Machine profile (CPU, RAM, storage, OS)
- DuckDB version and BenchBox version
- Scale factor and phase list
- Whether database/data artifacts were reused
- End-to-end wall time
- In-query execution totals where available
- Result artifact paths (for BenchBox runs)

---

## Gaps remaining

- [ ] Run and archive fresh side-by-side measurements specifically for this post.
- [ ] Decide whether to include throughput/maintenance mode, or keep scope to generation+power.
- [ ] Confirm if any DuckDB extension behavior changed in latest stable release before drafting final narrative.

---

## Draft claim boundaries

Safe claims based on current evidence:
- The two implementations target different operational goals.
- DuckDB extension path is concise and effective for local in-engine experimentation.
- BenchBox path provides additional workflow controls and artifacts that are outside extension scope.

Claims that require new measured evidence before publication:
- Any absolute performance ranking.
- Any percentage overhead claims for one path versus the other.
- Any recommendation tied to specific scale factors without fresh run data.

---

## References

1. DuckDB TPCH extension docs: https://duckdb.org/docs/stable/core_extensions/tpch.html
2. DuckDB benchmark handbook: https://duckdb.org/docs/stable/guides/performance/benchmarking.html
3. BenchBox TPCH wrapper: `/Users/joe/Developer/BenchBox/benchbox/tpch.py`
4. BenchBox TPCH benchmark core: `/Users/joe/Developer/BenchBox/benchbox/core/tpch/benchmark.py`
5. BenchBox TPCH generator: `/Users/joe/Developer/BenchBox/benchbox/core/tpch/generator.py`
6. BenchBox TPCH queries: `/Users/joe/Developer/BenchBox/benchbox/core/tpch/queries.py`
7. BenchBox DuckDB adapter: `/Users/joe/Developer/BenchBox/benchbox/platforms/duckdb.py`
8. BenchBox TPC compilation helper: `/Users/joe/Developer/BenchBox/benchbox/utils/tpc_compilation.py`
9. BenchBox README TPCH example section: `/Users/joe/Developer/BenchBox/README.md`

---

*Research status: READY FOR DRAFT after benchmark evidence run update*
