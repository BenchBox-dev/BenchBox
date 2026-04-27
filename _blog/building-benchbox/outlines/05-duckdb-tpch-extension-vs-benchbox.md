---
title: "DuckDB tpch extension vs BenchBox TPCH: same benchmark, different goals"
series: building-benchbox
post_number: 5
type: architecture-design
tags: [benchbox, duckdb, tpch, benchmarking, architecture, methodology]
status: OUTLINE
---

# Outline: DuckDB tpch extension vs BenchBox TPCH

> DuckDB's built in `tpch` extension is a great fast path for local experimentation, while BenchBox's TPCH stack is designed for reproducibility, cross-platform execution, and benchmark workflow control.

## Positioning

**Series fit**: Building BenchBox (engineering decision and trade-off post)

**Non-overlap with existing draft**: `_blog/benchbox-in-action/drafts/06-platform-specific-optimization-patterns.md` is about TPC-DS DataFrame optimization patterns across Polars, DataFusion, and PySpark. This post will stay on TPCH architecture and workflow differences between DuckDB extension mode and BenchBox mode.

## Thesis

DuckDB's `tpch` extension and BenchBox's TPCH implementation solve different problems, and treating them as interchangeable leads to unfair comparisons and wrong conclusions. Extension mode is optimized for simplicity inside DuckDB. BenchBox mode is optimized for controlled benchmarking workflows that need artifacts, validation hooks, query parameter control, and portability beyond DuckDB.

## Audience

- Engineers benchmarking DuckDB locally who want to know when extension mode is enough
- BenchBox users deciding whether to run direct DuckDB TPCH commands or full BenchBox workflows
- Maintainers designing benchmark tooling and debating build-vs-adopt trade-offs

## Structure

### 1. The confusion: "Aren't these the same TPCH?" (~250 words)

**Goal**: Define the exact comparison and why it matters.

**Key points**:
- Both paths execute TPCH, but with different product goals.
- Extension path is database-native and concise.
- BenchBox path is benchmark-framework-native and explicit about phases, outputs, and reproducibility.
- Comparing raw elapsed time across both without framing is misleading.

**Evidence needed**:
- DuckDB `PRAGMA tpch(1)` and `CALL dbgen(sf=...)` docs.
- BenchBox CLI run flow with phases and result artifacts.

### 2. What DuckDB extension mode gives you (~350 words)

**Goal**: Show strengths and constraints of the DuckDB extension as documented by DuckDB.

**Key points**:
- Setup is minimal: `INSTALL tpch; LOAD tpch; CALL dbgen(sf=...)`.
- Query execution via `PRAGMA tpch(query_id)`.
- Supports parallel data generation controls via `children` and `step`.
- `sf=0` generates schema without data.
- Limitation from docs: `PRAGMA tpch` uses predefined bind parameters.
- Limitation from docs: `tpch_answers()` includes only a subset of scale factors.

**Evidence needed**:
- DuckDB TPCH extension documentation section and examples.
- DuckDB benchmark handbook guidance on fixed bind parameters.

### 3. What BenchBox TPCH mode gives you (~450 words)

**Goal**: Explain why BenchBox implements a full TPCH stack instead of shelling out to extension-only behavior.

**Key points**:
- Data generation uses official `dbgen` binary paths with precompiled fallback and auto compilation logic.
- Query generation uses official `qgen` with seed and scale-aware parameterization.
- Query text translation path supports non-DuckDB targets via source/target dialect conversion.
- Workflow includes separate phases (`generate`, `load`, `power`, `throughput`, `maintenance`) and structured result artifacts.
- Validation and reporting hooks exist for row counts and TPC-style test flows.
- Practical value: one workflow can run the same benchmark family across multiple platforms.

**Evidence needed**:
- `benchbox/core/tpch/generator.py`, `benchbox/core/tpch/queries.py`, `benchbox/core/tpch/benchmark.py`.
- `benchbox/platforms/duckdb.py` for schema/load/execute integration.
- README TPCH capability summary and CLI examples.

### 4. Side-by-side comparison matrix (~300 words)

**Goal**: Present trade-offs without advocacy.

**Matrix dimensions**:
- Setup complexity
- Data generation location and control
- Query parameter control
- Reproducibility artifacts
- Cross-platform portability
- Compliance and validation affordances
- Best use case

**Planned framing**:
- Extension: quick local SQL experiments inside DuckDB.
- BenchBox: benchmark orchestration and reproducible workflows across engines.

### 5. Benchmark methodology: fair experiments, not apples-to-oranges timing (~350 words)

**Goal**: Define comparison protocol readers can reproduce.

**Key points**:
- Separate "engine execution" from "framework orchestration" timing.
- Run at least two scales (`SF=0.01`, `SF=1`) and report environment.
- Use identical query subsets for direct SQL timing where possible.
- Report both end-to-end command time and in-query execution totals.
- Call out when data is reused versus regenerated.

**Evidence needed**:
- Existing BenchBox DuckDB timing verification notes in `_blog/platform-deep-dives/research/duckdb-architecture-verification-2026-02-20.md`.
- New controlled runs for this post.

### 6. Decision guide: when to use each path (~200 words)

**Goal**: Give readers practical guidance.

**Decision table**:
- "I need a 60-second sanity check in DuckDB" -> extension mode.
- "I need repeatable runs, result files, and phase control" -> BenchBox.
- "I need cross-platform TPCH comparability" -> BenchBox.
- "I need only one local query right now" -> extension mode.

### 7. What we learned building BenchBox (~150 words)

**Goal**: Close with architecture-level lessons.

**Key points**:
- Wrapping standards benchmarks is not just about query text.
- Reproducibility infrastructure is a first-class feature, not overhead.
- "Simple path" and "controlled path" should coexist, with explicit trade-offs.

## Benchmark Plan (for research and draft)

1. DuckDB extension baseline:
   - `INSTALL tpch; LOAD tpch; CALL dbgen(sf=0.01); PRAGMA tpch(1);`
2. BenchBox direct smoke:
   - `benchbox run --platform duckdb --benchmark tpch --scale 0.01 --phases power --non-interactive`
3. BenchBox full lifecycle:
   - `benchbox run --platform duckdb --benchmark tpch --scale 1 --phases generate,load,power --non-interactive`
4. Optional parity subset timing:
   - Use query subset (`Q1,Q6,Q14,Q21`) in BenchBox and equivalent direct SQL in DuckDB shell.

## References & Resources

- DuckDB TPCH extension docs: https://duckdb.org/docs/stable/core_extensions/tpch.html
- DuckDB benchmark handbook, TPC-H query caveat: https://duckdb.org/docs/stable/guides/performance/benchmarking.html
- BenchBox TPCH public API: `/benchbox/tpch.py`
- BenchBox TPCH benchmark core: `/benchbox/core/tpch/benchmark.py`
- BenchBox TPCH data generator: `/benchbox/core/tpch/generator.py`
- BenchBox TPCH query manager: `/benchbox/core/tpch/queries.py`
- BenchBox DuckDB adapter: `/benchbox/platforms/duckdb.py`
- BenchBox TPCH package overview: `/benchbox/core/tpch/__init__.py`
- BenchBox TPC binary resolver: `/benchbox/utils/tpc_compilation.py`

## Research Notes (Not for Publication)

### Key sources to quote or paraphrase

1. DuckDB docs on `CALL dbgen` behavior (`sf=0`, `children`, `step`) and non-overwrite warning.
2. DuckDB docs on `PRAGMA tpch` fixed bind parameters and `tpch_answers` scale limitations.
3. BenchBox code paths showing `dbgen` and `qgen` usage plus phase-based execution.

### Open questions

- [ ] Do we include throughput and maintenance phase comparisons, or keep scope to power mode?
- [ ] Should we include a small "hybrid workflow" section (extension for exploration, BenchBox for tracked runs)?
- [ ] Which hardware profile will be the canonical reference environment for all reported numbers?

### Counterarguments to address

1. "BenchBox is slower than extension mode, so it is worse."
   - Response: clarify what is measured and what functionality is included in each path.
2. "If DuckDB already has TPCH built in, framework layers are unnecessary."
   - Response: true for some local use cases, not true for multi-phase reproducible benchmarking workflows.

*Status: OUTLINE COMPLETE | Target: 1,900-2,300 words | Type: Architecture/Design*
