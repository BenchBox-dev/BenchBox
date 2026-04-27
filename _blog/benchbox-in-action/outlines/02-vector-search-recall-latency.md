---
title: "BenchBox in action: vector search across six engines (and what recall@k does to your numbers)"
series: benchbox-in-action
post_number: 2
status: OUTLINED
date: TBD
tags: [benchmarking, benchbox, mcp, vector-search, ann, recall, methodology]
slug: benchbox-in-action-vector-search-recall-latency
meta_description: "Running BenchBox's vector search benchmark across DuckDB, pgvector, Snowflake, ClickHouse, StarRocks, and Doris reveals why reporting ANN latency without recall@k is misleading. A methodology story."
---

# Outline: Vector search across six engines (and what recall@k does to your numbers)

## Thesis

Vector search is the first BenchBox benchmark where correctness is a continuous metric, not a pass/fail gate.
Q5 (ANN cosine search via HNSW index) runs the same SQL as Q1 (exact cosine search), but some engines accelerate it
with an approximate index, trading recall for speed. If you report only latency across platforms, you are comparing
exact search on some engines against approximate search on others. BenchBox's recall@10 column makes that visible.

## Why this fits the series

- Workflow arc is identical to post #1 (MCP discovery, CLI execution, MCP analysis, methodology insight)
- The methodology insight is self-contained and surprising: the "fastest" engine on Q5 may simply be the least accurate
- v0.2.1 ships the exact six-dialect vector search benchmark needed to demonstrate this
- No platform advocacy required: the finding is about how to read the numbers, not about which engine to choose

---

## Section 1: The question (~200 words)

**Key points:**
- TPC-H, TPC-DS, ClickBench: correctness is binary. Run the query, validate against reference answers. Pass or fail.
- Vector search is different. Approximate nearest neighbor (ANN) search accepts a controlled loss of correctness in
  exchange for lower latency. The tradeoff is measured by recall@k: what fraction of the true top-k results appear
  in the approximate top-k.
- Six SQL engines now ship native vector distance functions. Each translates the same kNN intent into different syntax
  (`array_cosine_similarity`, `cosine_similarity`, `1 - cosine_distance`, `<=>`, `cosineDistance`,
  `VECTOR_COSINE_SIMILARITY`). Some also support HNSW indexes that make Q5 approximate.
- The question: when we run the same six queries across all six engines, do the latency numbers tell the whole story?

**Hook sentence (blockquote):**
> "The six queries in BenchBox's vector search benchmark look routine until you notice an extra column in the results: `recall_at_10`. That column changes everything about how you read the latency numbers next to it."

**TL;DR (draft for frontmatter, 280 chars target):**
> BenchBox's vector search benchmark runs 6 queries across 6 SQL engines, including Q5, which uses the same SQL as exact search but benefits from HNSW indexing when available. Comparing mean latency across engines hides whether each engine is doing exact or approximate search. Recall@10 surfaces the difference.

---

## Section 2: MCP exploration (~300 words)

**Narrative:** Start with `list_available` to discover the benchmark and supported platforms, then drill into Q5.

**Key points to hit:**
- `list_available` shows `vector_search` benchmark with 6 platforms: duckdb, postgresql (pgvector),
  snowflake, clickhouse, starrocks, doris
- `get_benchmark_info(benchmark="vector_search")` returns the 6 queries with descriptions:
  - Q1: kNN cosine exact (top-10) -- ground truth via brute-force scan
  - Q2: kNN L2-distance exact (top-10)
  - Q3: Filtered kNN cosine, single category (top-10)
  - Q4: Large-k cosine (top-100) -- used internally to compute recall@10 ground truth
  - Q5: ANN cosine via HNSW index when available (top-10) -- same SQL as Q1, different execution path
  - Q6: Multi-category filtered cosine (top-20)
- `get_query_details` on Q5 reveals the design intent: identical SQL to Q1, but the load phase creates an HNSW index
  on platforms that support it (StarRocks 3.x, Doris 2.x, ClickHouse with Vector index). DuckDB and pgvector
  fall back to exact scan.
- `run_benchmark` with `dry_run=True` across all six platforms: shows which platforms will build the HNSW index
  during the load phase and which will not.

**What to show:** Representative `get_benchmark_info` output snippet showing Q5 description. A brief dry-run
output table showing index creation step (present or absent per platform).

**Transition:** "The dry run flagged three platforms as HNSW-capable and three as falling back to exact scan.
That asymmetry is the entire story."

---

## Section 3: CLI execution (~300 words)

**Narrative:** Show the actual run commands and representative output for two contrasting platforms.

**Commands to show:**

```bash
# Run vector search on all six platforms at SF0.1 (100k vectors, 128-dim)
benchbox run --platform duckdb       --benchmark vector-search --scale 0.1
benchbox run --platform postgresql   --benchmark vector-search --scale 0.1
benchbox run --platform snowflake    --benchmark vector-search --scale 0.1
benchbox run --platform clickhouse-cloud --benchmark vector-search --scale 0.1
benchbox run --platform starrocks    --benchmark vector-search --scale 0.1
benchbox run --platform doris        --benchmark vector-search --scale 0.1
```

**What was held constant vs varied:**
- Constant: SF0.1 (100k vectors, 128 dimensions, 2 query vectors), same query set (Q1-Q6), cold cache
- Varied: platform, index presence (HNSW on 3 of 6), dialect SQL translation

**Key output to highlight:** A results table showing, for Q5 specifically:

| Platform     | Q5 latency (ms) | recall@10 | Index used |
|--------------|-----------------|-----------|------------|
| DuckDB       | [TBD]           | 1.000     | none (exact fallback) |
| pgvector     | [TBD]           | 1.000     | none (exact fallback) |
| Snowflake    | [TBD]           | 1.000     | none (exact fallback) |
| ClickHouse   | [TBD]           | [TBD]     | HNSW       |
| StarRocks    | [TBD]           | [TBD]     | HNSW       |
| Doris        | [TBD]           | [TBD]     | HNSW       |

**Note for drafting:** Populate with real benchmark numbers when this post reaches RESEARCH status.
The placeholders above encode the structural finding even before numbers are collected.

**Transition:** "Three engines report recall@10 = 1.000 on Q5. Three engines report something less.
That split is the first signal that mean latency across all six will be a misleading number."

---

## Section 4: MCP analysis (~600 words)

**Narrative:** Use BenchBox's MCP analysis tools to surface the recall-latency tradeoff.

**Sub-sections:**

### The latency ranking (and why it is incomplete)

- `analyze_results` across all 6 platforms sorts by mean Q5 latency
- The HNSW-capable platforms appear faster on Q5
- But: they are also reporting recall < 1.0, while the exact-search platforms report recall = 1.0
- Comparing these latency numbers is comparing different things

**What to show:** A two-column table: "Sorted by Q5 latency" vs "Sorted by Q5 latency at recall >= 0.95"
These two rankings are different. That difference is the finding.

### Q1 vs Q5 per platform (the speedup table)

- `get_query_details` on Q1 and Q5 for each platform reveals the speedup factor
- For exact-search platforms: Q5 latency ~= Q1 latency (no index benefit, recall = 1.0)
- For HNSW platforms: Q5 latency < Q1 latency, with recall < 1.0
- Speedup and recall move together: more speedup = lower recall

**What to show:** Per-platform Q1 vs Q5 comparison table with speedup factor and recall@10.

### Chart recommendation

- `suggest_charts` recommends a recall vs latency scatter plot for Q5 results
- X axis: Q5 latency (ms), Y axis: recall@10
- Platforms cluster into two groups: top-left (exact, high recall, higher latency) and
  somewhere on the recall-latency frontier (HNSW, lower recall, lower latency)
- The Pareto frontier question: which HNSW platforms get the best recall per millisecond?

**What to show:** Describe the scatter chart shape (or render ASCII version via BenchBox's chart tools).

### What aggregate means hide

- Mean latency across Q1-Q6 for each platform: mixes exact-search queries (Q1, Q2, Q3, Q6)
  with the ANN query (Q5)
- A platform that is fast on Q5 because it is doing approximate search gets rewarded in the aggregate mean
- This is like benchmarking a lossy compression algorithm and reporting only compression speed without
  reporting the decompression quality

---

## Section 5: Methodology insight (~500 words)

**The core argument:**

Aggregate latency benchmarks for ANN systems are only valid if recall is held constant across all engines being
compared. BenchBox's vector search benchmark makes this explicit by tracking recall@10 as a first-class output,
not a footnote.

**Sub-points:**

1. **The right comparison unit is an operating point, not a platform.** An HNSW index has tunable parameters
   (efSearch in HNSW, nprobe in IVF). The "operating point" is a (latency, recall) pair at specific parameter
   settings. Comparing platforms means comparing their operating points at the same recall level.

2. **BenchBox surfaces this without extra configuration.** Q4 (top-100 exact scan) provides the ground truth
   for computing recall@10 on Q5. The recall calculation happens automatically in BenchBox's metrics layer.
   You do not need to design a separate ground-truth run.

3. **The `--benchmark-option` flags let you explore the recall-latency curve.** Once you know which platforms
   use HNSW, you can vary efSearch/nprobe to find the operating point where a target recall (e.g., 95%) is met.
   That is the right denominator for a latency comparison.

4. **Exact search is a valid choice.** Three platforms in this run do not build HNSW indexes and execute Q5
   as an exact scan. That gives recall@10 = 1.000. Whether the tradeoff is worth it depends on the application.
   BenchBox presents the data; it does not recommend a recall target.

**Closing thought for section:**
The same principle applies to any benchmark with a quality metric alongside a speed metric: embedding quality,
query result precision, text similarity. Vector search just makes the tradeoff unusually visible because the
SQL is identical but the execution paths diverge.

---

## Section 6: Test environment (~200 words)

**Template to fill in at research/draft stage:**

```
Hardware: [local machine spec for embedded platforms; cloud tier for managed]
Platforms:
  - DuckDB [version]
  - PostgreSQL [version] + pgvector [version]
  - Snowflake [edition/size]
  - ClickHouse Cloud [tier]
  - StarRocks [version]
  - Doris [version]
Benchmark: BenchBox vector_search SF0.1 (100k vectors, 128 dimensions)
Methodology: Single power run per platform, cold cache, query order Q1-Q6
Raw results: [link to published-results branch when run]
Limitations:
  - Single query vector per run (not a multi-query QPS benchmark)
  - SF0.1 (~600K rows) is below production scale; HNSW benefits may differ at SF1 and SF10
  - Index tuning parameters are BenchBox defaults, not platform-tuned
  - Cloud platforms subject to resource contention
```

---

## Word count targets by section

| Section | Target |
|---------|--------|
| 1. The question | 200 words |
| 2. MCP exploration | 300 words |
| 3. CLI execution | 300 words |
| 4. MCP analysis | 600 words |
| 5. Methodology insight | 500 words |
| 6. Test environment | 200 words |
| **Total** | **~2,100 words** |

Within series target of 2,000-2,500 words.

---

## Research checklist (for RESEARCH status)

- [ ] Run vector_search benchmark on all 6 platforms at SF0.1
- [ ] Confirm which platforms build HNSW index during load phase
- [ ] Collect Q5 recall@10 and latency for all platforms
- [ ] Collect Q1 latency for all platforms (ground truth comparison)
- [ ] Run `analyze_results` and capture MCP output
- [ ] Run `suggest_charts` and capture recommendation
- [ ] Render recall vs latency scatter (ASCII or PNG)
- [ ] Note any dialect/version-specific issues (StarRocks L2 version gate, Doris cosine_distance workaround)
- [ ] Fill in test environment section with real version numbers

## References to check at research stage

- DuckDB array functions docs (`array_cosine_similarity`, `array_distance`)
- pgvector: HNSW index support added in pgvector 0.5.0 (confirm current BenchBox behavior)
- ClickHouse: Approximate Nearest Neighbor search via `annoy` or `hnsw` index types
- StarRocks: `VECTOR` column type and HNSW support (3.x docs)
- Doris: `cosine_distance` function docs, vector index status
- Snowflake: `VECTOR_COSINE_SIMILARITY` docs, HNSW index availability
