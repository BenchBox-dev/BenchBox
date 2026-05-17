---
title: "Reworking JoinOrder around the IMDb 2013 dataset"
series: building-benchbox
post_number: 14
type: architecture-design
tags: [benchbox, joinorder, job, imdb, provenance, benchmark-data]
meta_description: "How a community report led BenchBox to replace generated JoinOrder data with the real IMDb 2013 JOB dataset and make dataset identity explicit."
status: draft
---

# Reworking JoinOrder around the IMDb 2013 dataset

> JoinOrder is supposed to test query optimizers on real-world correlations. BenchBox v0.3.0 changes `joinorder` so the data contract matches that purpose.

**TL;DR**: A community report showed that BenchBox's old JoinOrder data did not preserve the real-world structure that makes the Join Order Benchmark useful. v0.3.0 changes `joinorder` to use the IMDb 2013 JOB dataset at scale factor 1, adds all 113 JOB SQL queries, records dataset identity in result bundles, and moves the old generated data to `joinorder_synthetic`.

---

On May 9, 2026, GitHub user `@partychicken` filed issue #289 against BenchBox.[^issue-289] The report was not about a typo or a missing query. It was about the benchmark contract.

BenchBox had a JoinOrder-shaped workload: the schema existed, queries could be wired through the framework, and generated data made smoke tests easy. But the data was not the real IMDb dataset used by the Join Order Benchmark papers. That distinction matters because JOB is not just a schema and query list. It is a workload designed around real-world data correlations that make cardinality estimation hard.

The reporter made the risk explicit: with generated data that does not preserve those correlations, an optimizer can look better than it should because the data is easier than the benchmark was designed to be.

v0.3.0 fixes that. `joinorder` now means the real IMDb 2013 Join Order Benchmark dataset, at one fixed scale. The old generated workload is still useful for development, but it has a different name and should not be used as published JOB evidence.

In this post, "canonical" means the reference JOB data contract: the fixed IMDb 2013 dataset and the 113-query workload used by the Join Order Benchmark papers. It does not mean every future reduced dataset, generated test fixture, or schema-compatible approximation.

## What the report changed

The original JOB paper, "How Good Are Query Optimizers, Really?", chose IMDb deliberately.[^job-2015] The follow-up VLDB Journal paper kept that focus on real-world optimizer behavior.[^job-2018] IMDb data has skew, correlations, and uneven distributions. Those properties are exactly what make optimizer cardinality estimates fail in interesting ways. If an optimizer thinks predicates are independent when the real data says otherwise, it may pick a very poor join order. That failure mode is the signal JOB was built to expose, and uniformly random synthetic data erases it: independence assumptions can become accidentally accurate, simple statistical assumptions can look better than they should, and the benchmark stops measuring what it was designed to measure even while every query runs to completion.

Issue #289 argued that generated JoinOrder data removes the hard part:

> In other words, uniform random generation removes the very property that JOB was designed to test.

That sentence is the core of the change. BenchBox's generated data was not useless. It helped exercise loaders, table creation, query registration, and basic platform tests. But it was not a comparable JOB run. A result produced on that data should not sit next to a result produced on the real IMDb dataset as if they measured the same workload.

The report also proposed the shape of the fix:

> remove/disable the scaling capability for the JOB workload. Instead, BenchBox could simply reference and ingest the original frozen IMDB dataset.

That is the direction v0.3.0 takes.

| What the report asked for | What v0.3.0 ships |
| --- | --- |
| Disable synthetic scaling for JOB | `joinorder` accepts only `--scale 1` |
| Use the original frozen IMDb dataset | `joinorder` uses the IMDb 2013 JOB dataset |
| Keep JOB faithful to its purpose | All 113 JOB SQL queries are embedded and checked |
| Avoid misleading results | The generated workload is renamed `joinorder_synthetic` |

We are grateful for the report because it forced a useful distinction: schema-compatible data is not the same thing as benchmark-compatible data.

## Why scale factor 1 is intentional

Most BenchBox benchmarks support scale factors because the data generator can produce a smaller or larger version of the workload. That makes iteration easier. It also lets users run smoke tests before spending time on larger data.

JoinOrder is different. The public benchmark now uses a fixed real-world dataset. That is why `joinorder --scale 0.01` is not part of v0.3.0.

A smaller public JOB workload would need more than fewer rows. It would need:

- correlated data that preserves the properties JOB is meant to expose
- reference cardinalities for the smaller data
- clear labeling so users do not compare it with full JOB
- a stable data-delivery contract
- tests that prove the query semantics still match the intended workload

Without those pieces, a smaller workload would create a false sense of comparability. It might be fast and convenient, but it would not be the Join Order Benchmark in the sense users expect.

The generated data remains useful for development and smoke-test coverage. It now has the explicit name `joinorder_synthetic`. That label is important. It keeps test data from being confused with comparable benchmark data.

## What the reference dataset means in BenchBox

In v0.3.0, the reference JoinOrder dataset means three things.

First, the dataset is fixed. BenchBox's package is derived from the Harvard Dataverse `imdb_pg11` archive, DOI `10.7910/DVN/2QYZBT`, restored into PostgreSQL and converted to the 21-table JOB schema. The manifest identifies that BenchBox data contract as:

```toml
dataset_version = "joinorder-imdb-2013-v1"
```

Second, the archive is verified. BenchBox records a manifest hash and a logical data archive hash, so result bundles can identify which data contract they used.

Third, the dataset is structured as the 21-table JOB schema. The largest table, `cast_info`, has 36,244,344 rows. The full table list and per-table hashes live in the data manifest rather than in this post, because the manifest is the durable source of truth.

This is not a legal claim about IMDb redistribution. It is an engineering statement about data identity: BenchBox can say which dataset version a result used, which manifest described it, and which logical archive content was verified.

## Query coverage changed too

The data change would be incomplete without the query set. v0.3.0 includes all 113 JOB SQL queries.

The query manager exposes IDs in the familiar JOB shape, such as `1a`, `2b`, and `15a`. The test suite checks that all 113 queries are registered and parse as PostgreSQL-flavored SQL.

The release also adds reference cardinalities and predicate-focused fixture tests. Those checks help protect the two most important parts of the benchmark:

1. The query catalog should contain the workload users expect.
2. The predicates should keep the intended semantics as the code evolves.

DataFrame query coverage exists for the same query IDs, but that statement needs careful interpretation. Query ID coverage is not the same as saying every DataFrame platform produces equally comparable JOB results. Platform capability, expression support, and execution behavior still matter. The release makes the workload available; users should still interpret cross-engine comparisons with the usual benchmark care.

## Result identity is part of the fix

Once a benchmark depends on a real-world dataset, result identity matters more. A timing number without the data contract is not auditable later, and unauditable benchmark numbers make later comparisons hard to resolve.

v0.3.0 adds three fields that result bundles can use for manifest-backed datasets:

- `dataset_version`: the named data contract
- `manifest_hash`: the manifest that described the expected data
- `data_archive_hash`: the logical archive content

For JoinOrder, this helps separate three cases that should not be mixed:

1. old BenchBox generated data
2. the real IMDb 2013 JOB dataset
3. any future reduced or alternate dataset, if one is ever added

Those fields are not a replacement for full methodology. Hardware, engine version, adapter configuration, query selection, concurrency, and measurement mode still matter. But dataset identity removes one common ambiguity: readers can tell which data contract a result used.

## Provenance and redistribution

Real-world datasets bring provenance questions that generated benchmark data does not. BenchBox documents the JoinOrder dataset version, archive hash, manifest hash, Dataverse source, and IMDb attribution. The data license note records the source and what users should know about redistribution.

We should be precise here. v0.3.0 treats the current re-hosted Parquet archive as an accepted release-risk decision by the project, not as BenchBox-cleared for broad commercial redistribution. It makes that decision explicit and documents the data identity so users understand what is being downloaded and measured.

There are stricter approaches we may consider later:

- written permission for the redistributed archive
- direct Dataverse fetch with local conversion
- a bring-your-own dataset path for environments with stricter policies

Those would improve the provenance story, but they also add setup cost. For v0.3.0, the default path prioritizes a verified first run against the real JOB dataset.

## What users need to change

If you ran JoinOrder before v0.3.0, treat those results as generated-data results. Do not compare them directly with v0.3.0 `joinorder` results.

The new command is straightforward:

```bash
uv add "benchbox[duckdb]"
uv run benchbox run --platform duckdb --benchmark joinorder --scale 1
```

The first run downloads and verifies the dataset before executing queries.

If your automation used a smaller JoinOrder scale, update it. `joinorder` now accepts only scale factor 1. If you need generated data for development or smoke coverage, use the explicitly named synthetic workload instead of publishing those numbers as JOB results.

## What we learned

The main lesson is simple: benchmark names are promises.

When users see `joinorder`, they bring expectations from the Join Order Benchmark papers. They expect a workload shaped by real IMDb correlations, not just tables with familiar names. Generated data can be useful, but if it does not preserve the property the benchmark exists to test, it needs a different label.

There's also a provenance lesson worth calling out: dataset version, manifest hash, and archive hash are boring fields until someone asks why two published results disagree. They earn their place by being there when an auditor needs them.

Finally, convenience has a limit. It stops where it makes results misleading. A small generated JoinOrder run is convenient. It is not a substitute for the real JOB dataset. v0.3.0 draws that boundary.

## Bottom line

BenchBox v0.3.0 turns `joinorder` into the benchmark users expected: real IMDb 2013 JOB data, all 113 queries, fixed scale, and auditable dataset identity.

That came from community feedback. The implementation goes beyond the initial report in a few places, especially around dataset identity, but the core correction is the one issue #289 identified: JOB needs real-world data because real-world correlations are the benchmark.

If you use JoinOrder to evaluate optimizers, upgrade with care. Old generated-data results belong in a separate bucket. New `joinorder` results use the real JOB dataset and should be treated as a new, stricter baseline.

---

## References

- GitHub issue: [#289, "[JOB] Uniformly random data generation undermines the benchmark's core motivation - real-world data correlations matter"](https://github.com/joeharris76/BenchBox/issues/289)
- JoinOrder paper: [How Good Are Query Optimizers, Really?](https://www.vldb.org/pvldb/vol9/p204-leis.pdf)
- JoinOrder follow-up paper: [Query Optimization Through the Looking Glass, and What We Found Running the Join Order Benchmark](https://db.in.tum.de/~leis/papers/lookingglass.pdf)
- Query corpus: [gregrahn/join-order-benchmark](https://github.com/gregrahn/join-order-benchmark)
- Dataset DOI: [10.7910/DVN/2QYZBT](https://doi.org/10.7910/DVN/2QYZBT)
- Changelog entry: `CHANGELOG.md` (`[0.3.0] - 2026-05-16`)
- JoinOrder benchmark docs: `docs/benchmarks/join-order.md`, `docs/reference/python-api/benchmarks/joinorder.rst`
- JoinOrder data manifest: `benchbox/core/joinorder/data_manifest.toml`
- JoinOrder data license note: `benchbox/core/joinorder/DATA-LICENSE.md`
- JoinOrder licensing decision: `_project/decisions/joinorder-canonical-data-licensing-2026-05-12.md`
- Release overview: [BenchBox v0.3.0: JoinOrder fix, sketch coverage, and /prompts/](./13-v0-3-0-release-overview.md)

[^issue-289]: GitHub issue #289, "[JOB] Uniformly random data generation undermines the benchmark's core motivation - real-world data correlations matter," filed by `@partychicken` on May 9, 2026. The issue asks BenchBox to remove synthetic scaling for JOB and use the original frozen IMDb dataset.
[^job-2015]: Leis, V., Gubichev, A., Mirchev, A., Boncz, P., Kemper, A., and Neumann, T. "How Good Are Query Optimizers, Really?" PVLDB 9(3), 204-215, 2015.
[^job-2018]: Leis, V., Radke, B., Gubichev, A., Mirchev, A., Boncz, P., Kemper, A., and Neumann, T. "Query Optimization Through the Looking Glass, and What We Found Running the Join Order Benchmark." VLDB Journal 27(5), 643-668, 2018.
