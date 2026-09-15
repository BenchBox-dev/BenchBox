---
title: "Results Explorer release"
blogpost: true
status: draft
date: September 15, 2026
author: Joe Harris
series: building-benchbox
post_number: 18
type: architecture-design
tags: [benchbox, results-explorer, benchmarking, geekbench, llm-leaderboards, duckdb-wasm, provenance]
meta_description: "The BenchBox Results Explorer shares verifiable, reproducible benchmark results publicly. Inspirations, the trust model, and a screenshot tour of the Explorer."
---

# Results Explorer release

BenchBox makes data platform benchmarking simple by executing consistent and clearly documented benchmarking using well-known (and clearly defined) benchmarks against a large set of popular data platforms using the most popular language for data engineering.

The new [Results Explorer](https://benchbox.dev/results/) feature allows you to share verifiable and reproducible benchmarking results publicly so the data engineering community can benefit from shared efforts. Previously, a BenchBox user could only see their own results. All runs for a comparison had to be conducted by them at their own expense.

Likewise, benchmarking blog posts and PR announcements are (at best) backed up by results on GitHub shared as shell scripts and CSVs. It's time-consuming to validate the shared assets and determine whether they are trustworthy and reproducible. Common concerns: ran with very large compute, used special tunings, used a modified benchmark, used a specific cloud provider, etc.

---

## Inspirations

BenchBox's Results Explorer has two strong inspirations: Geekbench's shared CPU benchmarks and AI/LLM leaderboards.

Geekbench allows you to benchmark the performance of your own computer and share the results. The results are widely used when new CPUs are released. For example, coverage of the new iPhone A20 processor that mentions "more than 20% faster" is based on comparing Geekbench scores.

* [Geekbench Browser: iOS benchmarks](https://browser.geekbench.com/ios-benchmarks)

![Geekbench Browser single-core chart for iOS devices, led by iPad Pro 13-inch (M5) at 3558.](../images/geekbench_browser_ipad_single_core.png)

* [Tom's Hardware: Apple's A20 Pro shatters Geekbench 7 single-core record](https://www.tomshardware.com/pc-components/cpus/apples-a20-pro-shatters-geekbench-7-single-core-record-2nm-chip-beats-desktop-intel-core-i9-and-amd-ryzen-9-by-up-to-32-percent)

![Tom's Hardware table of Geekbench scores by Apple A-series generation, from A16 Bionic to A20 Pro, with single-thread and multi-thread improvement percentages.](../images/tomshardware_apple_a_series_geekbench.png)

AI/LLM leaderboards have become a ubiquitous feature of the AI arms race. These leaderboards synthesize LLM performance across diverse benchmarks to provide a holistic view of highly variable performance (sound familiar?). There are a number of these leaderboards, but a few good examples are:

* [Terminal-Bench leaderboard](https://hub.harborframework.com/datasets/terminal-bench/terminal-bench/latest?tab=leaderboard&leaderboard=4-0-0)

![Terminal-Bench 4.0 leaderboard listing agent, model, effort, accuracy, release date, tokens, and cost for each entry.](../images/terminal_bench_leaderboard.png)

* [Arena text leaderboard: Pareto frontier](https://arena.ai/leaderboard/text/pareto)

![Arena Pareto frontier chart plotting model Arena score against price, with Pareto-optimal models listed on the right.](../images/arena_pareto_frontier.png)

* [LLM Stats](https://llm-stats.com/)

![LLM Stats Performance Index for reasoning, listing composite scores alongside blended price per million tokens.](../images/llm_stats_performance_index.png)

* [Scale Labs agentic leaderboards](https://labs.scale.com/leaderboard?category=agentic)

![Scale Labs leaderboard cards for several agentic benchmarks, each ranking models with scores and error bars.](../images/scale_labs_leaderboards.png)

---

## Trust model

BenchBox result publication relies on a trust model using hashed outputs and consistent machine IDs.

* Machine ID is generated and reused consistently so runs from the same hardware can be compared.
* A result integrity hash is calculated when a run completes. It validates that the result has not been modified.
* Result submissions go through a GitHub PR review by BenchBox maintainers before public release.

To provide reproducible results, BenchBox result "bundles" include all of the details necessary to interpret and (if needed) reproduce and validate the benchmarking. Bundles specify:

1. **Hardware used**: CPU type/name, physical/logical cores, total RAM, OS kernel, and client-to-engine locality
2. **BenchBox version**: Git commit hash and release version
3. **Platform version**: DuckDB v2.0.0-preview, DataFusion 46.0, ClickHouse 24.8, etc.
4. **Benchmark configuration**: Scale factor, execution phase, memory limits, thread pools, and optimizer flags

To support public sharing of results, BenchBox v0.4.0 improved the bundle output with additional details:

1. **Run Validation**: Per-query checksums, row counts, and schema validation against known references.
2. **Run Provenance**: User type (maintainer, vendor, or community) and funding (employer, personal, free-trial, grant, vendor-sponsored).

---

## Walkthrough

- Six sections
- Each answers one question
- Tabs: Overview, Benchmarks, Platforms, Compare, Find runs, Open local result

### 1. Overview

![Results Explorer Overview: 22 supported benchmarks (16 with public results), 244 published runs, 13 platforms with public results, 37 rankings, and a Recent results table.](../images/results_explorer_overview.png)

- Path: `/results/`
- Question: what's in the corpus, and what's new?
- No filters needed to start
- Top stats: benchmarks, published runs, platforms, rankings
- Recent results feed
- Shortcuts: run a benchmark, compare your result, submit a bundle

### 2. Platforms

![DuckDB platform page: 80 published runs across 16 benchmarks, with filters for benchmark, scale, phase, tuning, platform version, hardware, and run date, plus the Measurement basis selector.](../images/results_explorer_platform_duckdb.png)

- Paths: `/results/platforms/`, `/results/p/:platform/`
- Organized by engine
- One engine across workloads
- Version history: did releases get faster or regress?
- DuckDB today: 7 versions, 1.0.0 through a 2.0.0 alpha
- Hardware filters: architecture, CPU family, memory
- Pick the measurement basis:
  - Passes: all warm, warmup only, or one named warm pass
  - Reduce by median or min
- Whole-run wall-clock totals: context only
- No CPU-time basis

### 3. Benchmarks

![TPC-H Results at SF 1, power phase: 12 published runs with power score, geomean, query count, trust and validation badges, architecture, and CPU family.](../images/results_explorer_benchmark_tpch_sf1.png)

- Paths: `/results/benchmarks/`, `/results/:benchmark/`
- Organized by workload
- Performance depends on queries, schema, and scale
- One ranking per scale factor and phase
- No apples-to-oranges: SF 1 never ranks against SF 10
- Badges: trust tier, validation, tuning
- Tick two or more rows to open Compare
- Drill into the per-query matrix: is the lead broad, or one outlier query?

### 4. Compare

![Compare page for DuckDB 1.3.2 vs DataFusion 53.0.0 on TPC-H SF 1: Before you compare lists 3 warnings, and the Comparison summary shows a 1.30x power score ratio, 17 of 22 query wins, and p50/p90/p99 latency.](../images/results_explorer_compare_tpch_sf1.png)

- Path: `/results/compare?ids=...`
- Head-to-head, up to four runs
- Example: [DuckDB vs DataFusion, TPC-H SF 1](https://benchbox.dev/results/compare?ids=103f8e02,15e9b720)
- "Before you compare":
  - Checks benchmark, scale, and phase match
  - Lists other differences as warnings
  - Here: date window, platform version, driver version
- Comparison summary:
  - Leading run and power score ratio
  - Per-query wins
  - Latency profile: p50, p90, p99
- Platform and hardware: which axes differ, which are not recorded
- Scale mismatch: winner not claimed

![Compare page for DuckDB TPC-DS SF 1 vs SF 10: guardrails suppress the winner claim because scale factors differ.](../images/compare_scale_mismatch.png)

### 5. Find runs

![Find runs page with Advanced SQL open, running a DuckDB-WASM query over bench.results in the browser.](../images/results_explorer_find_runs_sql.png)

- Path: `/results/query`
- Two jobs: search and SQL
- Search: find runs that match your environment
- Filters: platform and version, benchmark and scale factor, provenance
- Advanced SQL: questions the built-in views don't answer
- DuckDB-WASM, entirely in the browser
- Queries a static `results.duckdb` file
- No backend
- Start from starter queries, or build SQL from filters
- Download CSV or JSON

### 6. Open local result

![Local preview of a TPC-H SF 1 DuckDB result: the banner says the file has not been uploaded, reviewed, or added to the public rankings.](../images/results_explorer_local_result.png)

- Path: `/results/local`
- Question: how do I check my own run before sharing it?
- "Open local result": pick a result JSON
- Parsed in the browser; nothing uploaded
- Same cards, tables, and charts as public runs
- Preview only:
  - Checks schema shape
  - Derives timings
  - Shows the recorded validation status
- Does not re-verify checksums, classify tuning, or decide eligibility
- `benchbox submit` does that
- "Submit for public review" links to the contribution guide

---

## How it works

- No backend
- Static site on GitHub Pages
- Queries run in your browser via DuckDB-WASM
- Fast, cheap, can't go down

---

## Contribute in 3 steps

1. Run a benchmark

   ```bash
   uv run -- benchbox run --platform duckdb --benchmark tpch --scale 1
   ```

2. Package with `benchbox submit`

   - Set one stable, private salt
   - Reuse it for every submission

   ```bash
   export BENCHBOX_MACHINE_ID_SALT="<stable-private-random-value>"
   uv run -- benchbox submit --last --output ./submission
   ```

3. Open a PR against `published-results`

   - Fork [BenchBox-dev/BenchBox](https://github.com/BenchBox-dev/BenchBox)
   - Copy `submission/bundle/` and the manifest into `results-data/bundles/`
   - Regenerate the inventory: `uv run -- python scripts/generate_corpus_inventory.py --write`
   - Maintainers review before anything goes public

Full details: [Contributing Benchmark Results](https://benchbox.dev/docs/contributing-results.html)

---

## Next steps

- Explore the data: [benchbox.dev/results](https://benchbox.dev/results/)
- Inspect your own runs: **Open local result**
- Contribute one back: `benchbox submit`, then a PR

---

## References

1. [BenchBox Results Explorer](https://benchbox.dev/results/)
2. [Geekbench Browser: iOS benchmarks](https://browser.geekbench.com/ios-benchmarks)
3. [Tom's Hardware: Apple's A20 Pro shatters Geekbench 7 single-core record](https://www.tomshardware.com/pc-components/cpus/apples-a20-pro-shatters-geekbench-7-single-core-record-2nm-chip-beats-desktop-intel-core-i9-and-amd-ryzen-9-by-up-to-32-percent)
4. [Terminal-Bench leaderboard](https://hub.harborframework.com/datasets/terminal-bench/terminal-bench/latest?tab=leaderboard&leaderboard=4-0-0)
5. [Arena text leaderboard: Pareto frontier](https://arena.ai/leaderboard/text/pareto)
6. [LLM Stats](https://llm-stats.com/)
7. [Scale Labs agentic leaderboards](https://labs.scale.com/leaderboard?category=agentic)
8. [Contributing Benchmark Results](https://benchbox.dev/docs/contributing-results.html)
