---
title: "BenchBox v0.3.0: JoinOrder fix, sketch coverage, and /prompts/"
series: building-benchbox
post_number: 13
type: release-notes
tags: [benchbox, release, joinorder, mcp, prompts, sketch-functions, read-primitives, write-primitives]
meta_description: "BenchBox v0.3.0 fixes JoinOrder by moving to the real IMDb 2013 JOB dataset, adds 113 JOB queries, expands sketch coverage, and ships a /prompts/ page."
status: draft
---

# BenchBox v0.3.0: JoinOrder fix, sketch coverage, and /prompts/

> BenchBox v0.3.0 fixes an important JoinOrder comparability issue and adds broader coverage for approximate aggregates and sketch workflows.

**TL;DR**: `joinorder` now uses the real IMDb 2013 Join Order Benchmark dataset at scale factor 1 instead of synthetic data. The release also expands approximate-aggregate and sketch-lifecycle coverage in the primitives benchmarks and ships `/prompts/`, a static landing page that turns benchmark choices into copyable instructions for coding agents.

---

BenchBox v0.3.0 is built around a narrower goal than v0.2.1. The previous release expanded the catalog with new platforms, new benchmarks, and harmonized scale factors. This release focuses on benchmark trust: when BenchBox says it is running a known workload, the data and query contract should match what users expect.

The largest change is JoinOrder. A community report pointed out that BenchBox's old JoinOrder data was uniformly-random synthetic data and did not exercise the real-world correlations that the Join Order Benchmark was designed around. v0.3.0 fixes that by making `joinorder` use the real IMDb 2013 JOB dataset at scale factor 1.

When we use the word "canonical" for JoinOrder, we mean the fixed IMDb 2013 dataset and JOB query set used by the benchmark papers, not a synthetic approximation.

The second theme is approximate analytics. BenchBox now covers more of the path that modern engines expose for approximate aggregates and sketches: one-shot approximate read queries, persisted sketch state, merge queries, storage-size checks, and parameter sweeps where the engine surface supports them.

The landing site release also adds a `/prompts/` page. It is not a new BenchBox runtime command. It helps a visitor choose a platform, benchmark, scale, and interface, then copy a prompt into a coding agent that can run BenchBox through the CLI or MCP.

## Release highlights

- **JoinOrder now uses the real IMDb 2013 JOB dataset.** This fixes a user-raised comparability issue where synthetic data was being used for JoinOrder runs.
- **All 113 Join Order Benchmark SQL queries are included.** Query IDs follow the expected JOB shape, such as `1a`, `2b`, and `15a`.
- **JoinOrder is fixed at scale factor 1.** JOB is a fixed dataset, so `joinorder` no longer pretends that smaller synthetic scales are comparable to the real workload.
- **Result bundles can carry dataset identity.** Manifest-backed datasets can record `dataset_version`, `manifest_hash`, and `data_archive_hash`.
- **`read_primitives` adds approximate aggregate coverage** for approximate distinct counts, approximate quantiles, and approximate top-k.
- **`write_primitives` adds sketch lifecycle coverage** for persist, merge, requery, storage-size validation, and parameter sweeps where supported.
- **`/prompts/` helps users start agent-assisted BenchBox runs** with copyable CLI or MCP instructions and safer defaults for local and cloud runs.

## At a glance

| Area | What changed in v0.3.0 | Why it matters |
| --- | --- | --- |
| JoinOrder data | `joinorder` uses the real IMDb 2013 JOB dataset at SF=1 | Fixes a user-raised comparability issue |
| JoinOrder queries | 113 JOB SQL queries, with reference cardinalities and predicate tests | Runs the optimizer workload readers expect |
| Dataset identity | Result bundles can record dataset version and hashes | Published results can be audited later |
| Approximate reads | `read_primitives` adds approximate aggregate coverage | Users can test approximate behavior without writing one-off queries |
| Sketch writes | `write_primitives` adds sketch persist, merge, requery, storage-size, and sweep coverage | Users can measure more of the sketch lifecycle |
| Agent prompts | `/prompts/` emits copyable CLI or MCP agent instructions | Visitors get a safer starting point for agent-assisted benchmarking |

## JoinOrder now means the real JOB dataset

On May 9, 2026, GitHub user `@partychicken` filed issue #289 about BenchBox's JoinOrder data generation.[^issue-289] The report was direct: JOB was designed around real IMDb data because real-world correlations, skew, and non-uniform distributions are exactly what make join order optimization hard. The synthetic data BenchBox was generating was useful for development, but it did not preserve that property.

v0.3.0 changes the public behavior of `joinorder`:

- `joinorder` uses the real IMDb 2013 Join Order Benchmark dataset.
- It accepts only `--scale 1`.
- The old synthetic data path is renamed `joinorder_synthetic` and kept out of the released benchmark list.
- Old synthetic result bundles have been renamed so they are not confused with results from the real IMDb dataset.

This is a breaking change, but it is the right kind of breaking change. The previous behavior made it too easy to produce a result labeled "JoinOrder" that was not comparable to the workload described by the JOB papers. After v0.3.0, the benchmark name carries a clearer contract.

The tradeoff is also explicit: there is no small public JoinOrder scale in this release. A small workload may be useful later, but it needs its own validated data contract. Taking a random slice or generating smaller synthetic tables would bring back the same comparability problem under a different label.

We wrote a deeper post on this change in [Reworking JoinOrder around the IMDb 2013 dataset](./14-joinorder-canonical-rework.md).

## Query coverage and dataset identity

The data change is paired with query coverage. BenchBox now includes all 113 Join Order Benchmark SQL queries. The query manager exposes the expected IDs, and the test suite checks that all 113 are registered and parse as PostgreSQL-flavored JOB SQL.

The release also adds provenance plumbing for real-world benchmark datasets. Manifest-backed result bundles can carry:

- `dataset_version`: which dataset contract the result used
- `manifest_hash`: which manifest described the dataset
- `data_archive_hash`: which logical archive content was verified

Those fields do not make benchmark results universal. Hardware, engine version, platform settings, query selection, and run methodology still matter. They do make one important question easier to answer later: "Which data did this result use?"

That matters for JoinOrder because the dataset itself is part of the benchmark. If two results are labeled `joinorder`, but one used synthetic data and the other used the real IMDb dataset, those results should not be compared or aggregated.

## More approximate aggregate coverage

`read_primitives` now includes five approximate aggregate queries:

| Query | What it measures |
| --- | --- |
| `approx_count_distinct_simple` | Approximate distinct count for one value |
| `approx_count_distinct_groupby` | Approximate distinct count per group |
| `approx_quantile_groupby` | Approximate single quantile per group |
| `approx_quantiles_array` | Multiple approximate quantiles from one aggregate |
| `approx_top_k_lineitem` | Approximate most-frequent values |

This also fixes a naming problem. The older `intrinsic_appx_median` query used an exact percentile expression despite the "appx" name. In v0.3.0, that work is named `approx_quantile_groupby`, and the supported PySpark and DataFusion paths use sketch-backed quantile implementations.

DataFrame support is more explicit as well. Polars, PySpark, and DataFusion expose sketch-backed APIs for `approx_count_distinct_*`, while Pandas, Modin, and cuDF fall back to exact implementations where a sketch API is not available. Dask uses HLL for the single-value distinct query, but still falls back to exact implementations for the grouped distinct and quantile cases. The five query IDs do not all mean sketch-backed execution on every DataFrame platform, and two (`approx_quantiles_array`, `approx_top_k_lineitem`) remain PySpark-only at the DataFrame layer. The documentation calls that out so users do not accidentally compare exact and approximate implementations as if they were the same workload.

## Sketch workflows now cover persistence and merge

Approximate aggregate functions are useful, but they are only one part of the modern sketch workflow. Many engines also let users build sketch state, store it, merge it later, and extract an estimate without scanning raw rows again.

That lifecycle belongs in `write_primitives`, not `read_primitives`, because it involves creating tables, storing state, and reading that state back later. v0.3.0 adds sketch workloads for:

- DataSketches-style Theta, KLL, and Top-K workflows where engines expose them, with documented substitutions and skips for BigQuery, Redshift, ClickHouse, and current DuckDB extension drift
- DuckDB CPC and REQ variants
- ClickHouse aggregate-state sketch variants
- Redshift HLL coverage where Redshift has native support

The new workloads cover persist, merge, and requery behavior. They also add storage-size validation for the main sketch operations, because persisted sketches have two important costs: how long they take to merge and how much state they store.

Parameter sweeps make the tradeoff visible where supported. For example, KLL configurations can be compared by size and accuracy settings instead of treated as one fixed black box. That matters when a team is deciding whether sketch state is worth storing in production tables.

The exact support matrix differs by engine. Some engines expose portable Apache DataSketches binary state. ClickHouse exposes a similar lifecycle through aggregate-state functions, but its binary format is not portable across engines. Redshift exposes HLL, but not KLL or Top-K. DuckDB sits in a third category: the community `datasketches` extension is the source of its Theta/KLL/Top-K coverage, but the currently-loaded build only exports CPC, REQ, KLL, and HLL. Theta and frequent-items (Top-K) are tracked as upstream-extension drift, so on DuckDB those parts of the workload show up as skipped rather than measured until the extension catches up. BenchBox keeps those differences visible instead of hiding them behind a single "supported" label.

## A page for agent-assisted runs

The landing site release adds [Instruct an agent](/prompts/), a page with the heading "Instruct a coding agent to use BenchBox."

The page is for a common first-run workflow: a user wants a coding agent to set up and run a benchmark correctly. Instead of asking the user to hand-write an instruction from memory, the page lets them choose:

- goal: test one platform or compare platforms
- surface: CLI or MCP
- interface: SQL or DataFrame
- deployment model: local, self-hosted, or managed cloud
- platform, benchmark, and scale

It then emits a copyable prompt. If MCP is selected, it includes the MCP configuration shape. If a managed cloud platform is selected, the generated instruction starts with dependency and status checks, then a dry run, before any live benchmark command.

The default path is intentionally conservative: local DuckDB, TPC-H, and SF 0.01. For managed platforms, the prompt tells the agent not to ask for secrets in chat or the browser. If credentials are missing, the agent should stop and summarize what is missing instead of guessing.

The page does not change how BenchBox runs benchmarks. There is no new `benchbox prompts` command, no new MCP prompt-rendering tool, and no public JSON catalog. Platform inclusion comes from BenchBox runtime metadata, while hand-authored configuration is used for labels and safety copy.

## Smaller changes worth knowing

Two implementation changes are worth calling out because they affect future benchmark coverage.

First, validation queries can now use `ValidationQuery.platform_overrides`. That lets a benchmark declare engine-specific validation SQL or an explicit skip, which is useful for sketch state because engines expose different storage and merge functions.

Second, PySpark gained aggregate persist/merge support for DataFrame sketch workflows. That gives the DataFrame path a way to run sketch lifecycle work through DataFrame managers rather than treating every sketch workload as SQL-only.

## Try it yourself

For a quick smoke run:

```bash
uv add "benchbox[duckdb]"
uv run benchbox run --platform duckdb --benchmark tpch --scale 0.01
```

For the new prompt page:

```text
/prompts/
```

For JoinOrder, remember that the public benchmark is the full fixed dataset:

```bash
uv run benchbox run --platform duckdb --benchmark joinorder --scale 1
```

The first JoinOrder run downloads and verifies the dataset before executing queries.

## Changed behavior to be aware of

- **`joinorder` is now fixed at SF=1.** Scripts that pass smaller JoinOrder scale factors need to change.
- **Old JoinOrder synthetic results are not comparable to v0.3.0 JoinOrder results.** Treat them as a different workload.
- **The old synthetic data path is now `joinorder_synthetic`.** It remains useful for development and smoke coverage, but it is not the released comparable benchmark.
- **Approximate DataFrame paths differ by engine.** Some are sketch-backed; others are exact fallbacks. Check the coverage matrix before comparing them.

## Bottom line

v0.3.0 is a benchmark-trust release. The JoinOrder fix makes a well-known optimizer benchmark mean what readers expect it to mean. The approximate and sketch additions make more of the modern analytics surface measurable without one-off query files. The prompt page makes the first agent-assisted run easier to start without adding a new runtime API.

If you ran `joinorder` before v0.3.0, treat old results as synthetic and do not compare them directly with the new IMDb-backed runs. If you use the approximate or sketch workloads, check the support notes for each engine and benchmark the capability you actually intend to rely on.

---

## References

- Changelog entry: `CHANGELOG.md` (`[0.3.0] - 2026-05-16`)
- JoinOrder issue: [GitHub issue #289](https://github.com/joeharris76/BenchBox/issues/289)
- JoinOrder paper: [How Good Are Query Optimizers, Really?](https://www.vldb.org/pvldb/vol9/p204-leis.pdf)
- Companion post: [Reworking JoinOrder around the IMDb 2013 dataset](./14-joinorder-canonical-rework.md)
- Approximate functions reference: `docs/benchmarks/read-primitives-approximate-functions.md`
- Sketch functions reference: `docs/benchmarks/write-primitives-sketch-functions.md`
- Prompt route decision: `_project/decisions/landing-prompts-route.md`

[^issue-289]: GitHub issue #289, "[JOB] Uniformly random data generation undermines the benchmark's core motivation - real-world data correlations matter," filed by `@partychicken` on May 9, 2026.
