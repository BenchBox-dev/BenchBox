---
title: "Introducing the BenchBox Results Explorer"
blogpost: true
status: draft
date: September 15, 2026
author: Joe Harris
series: building-benchbox
post_number: 16
type: architecture-design
tags: [benchbox, results-explorer, benchmarking, geekbench, llm-leaderboards, duckdb-wasm, provenance]
meta_description: "Results Explorer allows BenchBox users to share and compare their own benchmarking results with results shared by the BenchBox community. Anyone can submit a run for publication through a pull request."
---

# Introducing the BenchBox Results Explorer

> A Geekbench for data platform benchmarks

**TL;DR**: Results Explorer allows BenchBox users to share and compare their own benchmarking results with results shared by the BenchBox community. Anyone can submit a run for publication through a pull request.

BenchBox makes data platform benchmarking simple by executing consistent and clearly documented benchmarking using well-known (and clearly defined) benchmarks against a large set of popular data platforms using the most popular language for data engineering.

The new [Results Explorer](https://benchbox.dev/results/) feature allows you to share verifiable and reproducible benchmarking results publicly so the data engineering community can benefit from shared efforts. Previously, a BenchBox user could only see their own results. All runs for a comparison had to be conducted by them at their own expense.

Likewise, benchmarking blog posts and PR announcements are (at best) backed up by results on GitHub shared as shell scripts and CSVs. It's time-consuming to validate the shared assets and determine whether they are trustworthy and reproducible. Common concerns: ran with very large compute, used special tunings, used a modified benchmark, used a specific cloud provider, etc.

A shared benchmark result is only useful if someone else can easily understand how it was run and easily compare it to other results.

---

## Inspirations

BenchBox's Results Explorer has two strong inspirations: Geekbench's shared CPU benchmarks and AI/LLM leaderboards.

Geekbench allows you to benchmark the performance of your own computer and share the results. The results are widely used when new CPUs are released. For example, coverage of the new iPhone A20 processor that mentions "more than 20% faster" is based on comparing Geekbench scores.

* [Geekbench Browser: iOS benchmarks](https://browser.geekbench.com/ios-benchmarks)

![Geekbench Browser single-core chart for iOS devices, led by iPad Pro 13-inch (M5) at 3558.](../images/geekbench_browser_ipad_single_core.png)

* [Tom's Hardware: Apple's A20 Pro shatters Geekbench 7 single-core record](https://www.tomshardware.com/pc-components/cpus/apples-a20-pro-shatters-geekbench-7-single-core-record-2nm-chip-beats-desktop-intel-core-i9-and-amd-ryzen-9-by-up-to-32-percent)

![Tom's Hardware table of Geekbench scores by Apple A-series generation, from A16 Bionic to A20 Pro, with single-thread and multi-thread improvement percentages.](../images/tomshardware_apple_a_series_geekbench.png)

We borrowed Geekbench's path from a local run to a public page others can inspect and compare, not its single headline score: BenchBox ranks runs only within one benchmark, scale factor, and phase.

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
3. **Platform version**: DuckDB 1.4.4, 1.5.5, 2.0.0-alpha38615, etc.
4. **Benchmark configuration**: Scale factor, execution phase, memory limits, thread pools, and optimizer flags

To support public sharing of results, BenchBox v0.4.0 improved the bundle output with additional details:

1. **Run Validation**: Per-query checksums, row counts, and schema validation against known references.
2. **Run Provenance**: User type (maintainer, vendor, or community) and funding (employer, personal, free-trial, grant, vendor-sponsored).

---

## Walkthrough

The Explorer has six tabs: Overview, Benchmarks, Platforms, Compare, Find runs, and Open local result. Each one answers a single question, and every run you see links through to its own result page.

### 1. Overview

![Results Explorer Overview: 22 supported benchmarks (16 with public results), 244 published runs reviewed by BenchBox maintainers, 13 platforms with public results, and 37 rankings across 12 ranked platforms.](../images/results_explorer_overview_stats.png)

Overview (`/results/`) answers the first question anyone asks: what's here, and what's new? You don't need to set a filter. Four counts sit at the top: supported benchmarks, published runs, platforms, and rankings. As of this post, that's 244 published runs across 13 platforms. This initial set of results is exclusively small scale (scale factor 10 or smaller) and maintainer-run today. It is intended to seed the project and demonstrate its value. Below the counts, Recent results lists the latest arrivals, and three numbered shortcuts take you from running a benchmark to comparing your result to submitting a bundle.

### 2. Benchmarks

![Benchmarks index: each benchmark with public results and a strip of runs published per week over the last 26 weeks, led by TPC-H with 44 runs, SSB with 32, and TPC-DS with 22.](../images/results_explorer_benchmarks_index.png)

Benchmarks (`/results/benchmarks/`) lists every benchmark with public results, next to a strip showing how many runs arrived each week over the last 26 weeks. TPC-H leads with 44 runs.

![TPC-H Results page filtered to SF 10: 7 published runs, 22 queries, power phase, with filters for scale, phase, tuning, platform version, trust tier, platform, validation, hardware, and run date.](../images/results_explorer_benchmark_tpch_sf10_filters.png)

Pick a benchmark and its page (`/results/:benchmark/`) shows one ranking at a time. Every ranking holds one scale factor and one test phase, because performance depends on the queries, the schema, and the data size. Scale factor (SF) sets the data size; for TPC-H, SF 10 is about 10 GB. That rule keeps an SF 1 run from ever ranking against an SF 10 run. TPC-H at SF 10 in the power phase holds seven published runs, one for each DuckDB release.

![Analysis section for TPC-H SF 10: display geomean (lower is better) and Power@Size (higher is better) for seven DuckDB releases, from the 2.0.0 alpha at 128 ms and 281,041 down to 1.0.0 at 208 ms and 173,508.](../images/results_explorer_benchmark_tpch_sf10_analysis.png)

The Analysis section sets two measures side by side: display geomean, where lower is better, and Power@Size, where higher is better. The 2.0.0 alpha leads on both, at 128 ms and 281,041. Release order doesn't hold all the way down: 1.3.2 sits at 189 ms and 198,175, behind 1.2.2.

![Box plots of per-query latency for seven DuckDB releases on TPC-H SF 10, with a note that the spread is across different queries, not repeated runs of the same query.](../images/results_explorer_benchmark_tpch_sf10_boxplot.png)

A box plot shows how much latency varies from query to query within each run. The spread comes from different queries, not repeated runs of the same query, so a long whisker marks a slow query rather than run-to-run noise.

![More views panel with eight additional analyses drawn from the TPC-H SF 10 ranking, including a query matrix, percentiles, a CDF, and a histogram.](../images/results_explorer_benchmark_tpch_sf10_more_views.png)

More views holds eight further analyses drawn from the same ranking, including a query matrix, percentiles, a CDF (the share of queries finished by each latency), and a histogram. The query matrix shows whether a lead holds across queries or rests on one outlier.

### 3. Platforms

![Platforms index: each platform with public results and a strip of runs published per week over the last 26 weeks, led by DuckDB with 80 runs, DataFusion with 45, and ClickHouse Local with 38.](../images/results_explorer_platforms_index.png)

Platforms (`/results/platforms/`) lists every platform with the same weekly strip. DuckDB has the most published runs, with 80.

![DuckDB platform page filtered to TPC-H at SF 10: 7 of 80 published runs across 16 benchmarks, with filters for benchmark, scale, phase, tuning, platform version, trust tier, validation, hardware, and run date.](../images/results_explorer_platform_duckdb_filters.png)

A platform page (`/results/p/:platform/`) follows one engine across every workload it has run. It's also where version history lives: did a release get faster, or did it regress? Filtered to TPC-H at SF 10, the DuckDB page shows seven releases that ran on Apple silicon on the same day, with no tuning. Architecture, CPU family, and memory filters let you line up versions on similar hardware, when the runs record it.

The measurement basis decides which timings you see. Choose all warm passes, the warmup pass alone, or a single named warm pass, then reduce each query's timings by median or min. Whole-run wall-clock totals appear for context only, and there is no CPU-time basis.

![DuckDB platform results table for TPC-H SF 10 with four versions selected, including v1.6.0.dev365, v1.5.5, and v1.4.4. Unselected rows explain that the selection limit is reached, and a tray at the bottom offers Compare 4 selected.](../images/results_explorer_platform_duckdb_selection.png)

Each version in the results table links to that run's page, and its checkbox adds the run to a comparison. Power score (higher is better) climbs from 173,508 on 1.0.0 to 281,041 on the 2.0.0 alpha, which the table lists under its driver build, v1.6.0.dev365. The climb isn't steady: 1.3.2 scored 198,175, below 1.2.2's 228,201. A tray at the bottom of the page collects your picks. After four, the remaining rows explain that the selection limit is reached.

### 4. Compare

![TPC-H Comparison of four DuckDB runs at SF 10: Before you compare lists 2 warnings (platform version and driver version), and the Comparison summary shows v1.6.0.dev365 leading at 1.42x the lowest selected run, winning 20 of 22 queries, with p50 111 ms, p90 274 ms, and p99 395 ms.](../images/results_explorer_compare_duckdb_summary.png)

Compare (`/results/compare?ids=...`) puts up to four runs side by side. The screenshots follow [four DuckDB releases on TPC-H SF 10](https://benchbox.dev/results/compare?ids=6235bd1a,47bdcef5,282a4d75,19b96c85): the 2.0.0 alpha, 1.5.5, 1.4.4, and 1.3.2. Before it shows any numbers, a "Before you compare" panel confirms the runs share a benchmark, scale factor, and phase, then lists every other difference as a warning. These runs carry two, platform version and driver version, which are exactly the differences we want to measure.

The Comparison summary comes next. In these runs, the 2.0.0 alpha's power score was 1.42x that of the lowest selected run, 1.3.2, and the summary counts 20 of 22 queries where the alpha wins. Its latency profile reads 111 ms at p50, 274 ms at p90, and 395 ms at p99.

![Compare page bars for four DuckDB releases showing geomean and Power@Size, from the 2.0.0 alpha at 128 ms and 281,041 to 1.3.2 at 189 ms and 198,175, above a per-query matrix of timings for each run.](../images/results_explorer_compare_duckdb_matrix.png)

Below the summary, bars compare each run's geomean and Power@Size, and a query matrix lays out every query's time for every run, so you can see where a release gained or lost ground.

![Box plots and a CDF of per-query latency for DuckDB 2.0.0 alpha, 1.5.5, 1.4.4, and 1.3.2 on TPC-H SF 10. The 2.0.0 alpha's CDF curve sits furthest left.](../images/results_explorer_compare_duckdb_distribution.png)

Box plots and a CDF show each release's whole latency distribution. The 2.0.0 alpha's curve sits furthest left, so more of its queries finish sooner. Further down, a Platform and hardware panel marks which details differ between runs and which were never recorded. When runs don't share a scale factor, Compare still shows the evidence but won't name a winner.

### 5. Result pages

![Result page for the DuckDB 2.0.0 alpha on TPC-H at SF 10, power phase, Public ID 875f8968: power score 281,041, maintainer run that passed validation, wall-clock total 38.96 s, no tuning, with Find a run to compare and Download bundle buttons.](../images/results_explorer_result_duckdb_header.png)

Every run you see links through to its own page (`/results/r/:id`). The 2.0.0 alpha's page shows its power score of 281,041, its scale factor and phase, its trust and validation state, a wall-clock total of 38.96 seconds, and its tuning mode. Find a run to compare starts a comparison from this run, and Download bundle takes the canonical JSON with you, for your own analysis or to set up a corroborating run.

![Charts on the DuckDB 2.0.0 alpha result page: per-query latency bars for all 22 TPC-H queries, a box plot of the spread across queries, and a CDF.](../images/results_explorer_result_duckdb_charts.png)

Further down, the page charts each query's time, the spread across queries, and a CDF, followed by a run receipt with provenance and hardware details when recorded.

### 6. Find runs

Find runs (`/results/query`) does two jobs. The first is search: filter by benchmark and platform, or search by platform, version, or public ID, then select up to four runs to compare. The second is SQL, for questions the built-in views don't answer. Open Advanced SQL, load a starter query or build one from your current filters, and run it. Your browser does the work. DuckDB-WASM queries a static `results.duckdb` file, with no backend involved. When you're done, download the filtered rows as CSV or JSON.

### 7. Open local result

Open local result (`/results/local`) answers the question every contributor has before sharing: how does my run look? Pick a result JSON file and the Explorer parses it in your browser. Nothing is uploaded, and a banner says so. Your run gets the same cards, tables, and charts as a public result.

It's a preview, though. The Explorer checks the file's shape, derives timings, and shows the validation status the run recorded. It doesn't re-verify checksums, classify tuning, or decide whether the run can be submitted. `benchbox submit` does that, and the Submit for public review button links to the guide that walks you through it.

---

## How it works

The Explorer has no application server, account system, or server-side database. A static build turns curated result bundles into a DuckDB snapshot and downloadable JSON, GitHub Pages serves both, and DuckDB-WASM runs every query in your browser.

```text
curated result bundles -> static build -> results.duckdb -> Explorer pages and Find runs
                                  `-> JSON bundles -> Download bundle
```

That keeps the site cheap to run and the evidence portable: use the pages, query the snapshot, or leave with the bundle.

---

## Contribute in 3 steps

1. Run a benchmark

   ```bash
   uv add benchbox --extra duckdb
   uv run -- benchbox run --platform duckdb --benchmark tpch --scale 1
   ```

2. Package with `benchbox submit`

   - One private, stable salt pseudonymizes your machine ID
   - A new salt per run breaks comparability across your submissions
   - Keep it out of the repo and the PR

   ```bash
   export BENCHBOX_MACHINE_ID_SALT="<stable-private-random-value>"
   uv run -- benchbox submit --last --dry-run
   uv run -- benchbox submit --last --output ./submission
   ```

   - Refuses runs that aren't submittable
   - Writes the bundle plus a SHA-256 manifest
   - The hash covers file integrity, not query correctness

3. Open a PR against `published-results`

   - Fork [BenchBox-dev/BenchBox](https://github.com/BenchBox-dev/BenchBox)
   - Copy `submission/bundle/` and the manifest into `results-data/bundles/`
   - Regenerate the inventory: `uv run -- python scripts/generate_corpus_inventory.py --write`
   - Maintainers review the PR
   - Merged runs appear in the Explorer after a later curated publish, not at merge
   - Community results carry a Community submission label and are currently excluded from ranked tables. We will re-evaluate their inclusion over the coming months.

Full details: [Contributing Benchmark Results](https://benchbox.dev/docs/contributing-results.html)

---

## Next steps

- Explore the data: [benchbox.dev/results](https://benchbox.dev/results/)
- Inspect your own runs: **Open local result**
- Contribute one back: `benchbox submit`, then a PR
- Tell us what to cover next: which benchmarks, platforms, and scales? Start a [BenchBox discussion](https://github.com/BenchBox-dev/BenchBox/discussions).

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
