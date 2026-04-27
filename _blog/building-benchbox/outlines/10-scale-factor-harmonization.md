---
title: "One SF, one gigabyte: harmonizing scale factors across BenchBox"
series: building-benchbox
post_number: 10
type: architecture-design
tags: [benchbox, methodology, scale-factor, benchmarks, data-generation, design-decision]
status: OUTLINE
---

# Outline: Scale factor harmonization

---

## Theme

Before v0.2.1, `--scale 1` meant wildly different output sizes across BenchBox benchmarks. TPC-H
SF=1 was 1 GB (per spec). TSBS DevOps SF=1 was about 470 MB. CoffeeShop SF=1 was 6 GB. NYC Taxi
SF=1 was 96 MB. AMPLab SF=1 was 450 MB. There was no convention; each benchmark inherited its
own historical defaults.

That made any cross-benchmark intuition (cost, runtime, storage budget) useless. "Run everything
at SF=1" was a meaningless instruction.

v0.2.1 harmonizes the adjustable benchmarks to a single target: **roughly 1 GB of uncompressed
CSV at SF=1**. Spec-locked benchmarks (TPC-H, TPC-DS, SSB, ClickBench, DataVault) are unchanged.
Output sizes for affected benchmarks change as a result.

This post covers the design decision: why we picked 1 GB, why we made it backwards-incompatible,
which benchmarks moved how far, and the second-order constraints we hit (quadratic growth in
TSBS, sample-rate ceilings in NYC Taxi, corpus exhaustion in FlightData).

---

## Thesis

A scale factor is only useful if it means roughly the same thing across benchmarks. The
harmonization isn't about matching TPC-H's specific 1 GB target; it's about making `--scale N`
predictable enough that users can budget time, storage, and money against it without
benchmark-specific lookup tables.

---

## Hook

> Before v0.2.1, `--scale 1` could mean 96 MB or 6 GB depending on which benchmark you ran.

---

## TL;DR

BenchBox v0.2.1 retunes 7 benchmarks with adjustable scale factors so that SF=1 produces
roughly 1 GB of uncompressed CSV. CoffeeShop dropped from 6 GB to about 1 GB at SF=1; AMPLab
grew from 450 MB to about 1.1 GB; H2ODB grew 10x. Spec-locked benchmarks (TPC-H, TPC-DS, SSB,
ClickBench, DataVault) are unchanged. The change is backwards-incompatible by design: the old
defaults were inconsistent enough that cross-benchmark reasoning at the same SF was unreliable.

---

## Section breakdown

### 1. The problem: SF=1 meant nothing in particular (~300 words)

Open with the inconsistency. Walk through what SF=1 meant for each affected benchmark **before
v0.2.1**:

| Benchmark | SF=1 size (before) | What SF=1 actually meant |
| --- | --- | --- |
| CoffeeShop | ~6 GB | 78M order_lines, plus customers/products/orders |
| JoinOrder | ~5 GB | ~73M rows across 21 IMDB tables |
| AMPLab | ~450 MB | 50K documents, 100K rankings, 1M uservisits |
| H2ODB | ~100 MB | 1M base_trips |
| TSBS DevOps | ~470 MB | 100 hosts x 1 day at 10s intervals |
| NYC Taxi | ~96 MB | 1/100 sample of one year of yellow taxi |
| FlightData | n/a (new) | (added in v0.2.1) |

Then walk through the spec-locked side:

| Benchmark | SF=1 size | Determined by |
| --- | --- | --- |
| TPC-H | ~1 GB | TPC spec |
| TPC-DS | ~2 GB | TPC spec |
| SSB | inherits TPC-H schema scale | Academic spec |
| ClickBench | fixed (single dataset) | ClickBench spec |
| DataVault | inherits TPC-H | TPC-H schema |

The takeaway: when you said `--scale 1` to BenchBox, the output size depended entirely on which
benchmark you picked. There was no shared baseline. Resource budgeting required per-benchmark
lookup.

### 2. Why pick 1 GB? (~250 words)

The 1 GB target wasn't pulled out of thin air. Three reasons converged on it:

1. **TPC-H already uses it.** TPC-H SF=1 is approximately 1 GB by spec, and TPC-H is the
   benchmark BenchBox users run most often. Aligning the rest of the catalog with TPC-H's
   convention preserves whatever intuition users have already built.
2. **It fits in working memory on common dev machines.** A 1 GB uncompressed CSV typically
   needs 2 to 4 GB of working memory across data generation, loading, and query execution.
   That fits a developer laptop without forcing swap.
3. **It scales linearly to useful sizes.** SF=10 lands at roughly 10 GB, SF=100 at roughly
   100 GB. These are the sizes users actually want for "small benchmark", "real benchmark",
   and "stress benchmark." Making SF=1 mean 1 GB makes the scale ratio useful.

We did not pick 1 GB because it's optimal for any specific platform. We picked it because it's
the size that already had the most operational practice around it, and because aligning to a
single number meant *picking one*, and TPC-H's number was the obvious one to pick.

### 3. The design decision: backwards-incompatible by intent (~200 words)

This is the most opinionated section. The harmonization changes output sizes for existing
benchmarks at the same SF. Existing scripts will produce different data than they did before.
We chose this over the alternatives:

**Alternative 1**: keep old defaults, add a new `--scale-target=1gb` flag.
- Rejected: opt-in harmonization defeats the point. The whole purpose is to make `--scale 1`
  mean the same thing without flag knowledge.

**Alternative 2**: introduce a new benchmark version (e.g., `coffeeshop-v2`).
- Rejected: every benchmark would carry forward its old definition forever, and users would
  have to remember which version produces which size.

**Alternative 3**: change the meaning of SF=1 silently.
- Adopted, with explicit changelog notice and `--force datagen` recommended for users with
  cached data.

The principle: BenchBox is a benchmarking tool, not a regression test. Comparability across
benchmarks at the same SF matters more than comparability against a single benchmark's old
output across BenchBox versions. Cross-version comparisons of the same benchmark at the same
SF were already fragile (driver versions, query rewrites, format changes).

### 4. What changed, per benchmark (~400 words)

This is the data section. One subsection per affected benchmark, with old and new SF=1 numbers.

#### CoffeeShop (-83%)
- Old SF=1: 78M order_lines, ~6 GB
- New SF=1: 13.26M order_lines, ~1 GB
- Why this much: CoffeeShop was the largest outlier. Its previous default produced a benchmark
  that was nearly impossible to fit alongside TPC-H or TPC-DS in a single multi-benchmark run
  on most hardware.

#### JoinOrder (-80%)
- Old SF=1: ~73M rows across 21 IMDB tables, ~5 GB
- New SF=1: proportionally reduced across 21 tables, ~1 GB
- Why proportional: JoinOrder's benchmark value depends on the cross-table cardinality
  ratios. Reducing each table by the same factor preserves the join behavior the benchmark
  is designed to exercise.

#### AMPLab (+150%)
- Old SF=1: 50K documents, 100K rankings, 1M uservisits, ~450 MB
- New SF=1: 125K documents, 250K rankings, 2.5M uservisits, ~1.1 GB
- AMPLab grew. The original defaults were small enough that any modern engine completed every
  query in milliseconds, making the benchmark useless for differentiation at SF=1.

#### H2ODB (+900%)
- Old SF=1: 1M base_trips, ~100 MB
- New SF=1: 10M base_trips, ~1 GB
- H2ODB also grew, by an order of magnitude. The previous default was a tutorial-sized dataset.

#### TSBS DevOps (+100%)
- Old SF=1: 100 hosts x 1 day at 10s intervals, ~466 MB
- New SF=1: 100 hosts x 2 days at 10s intervals, ~932 MB
- A note on TSBS: only `num_hosts` scales linearly with SF. Duration is fixed at 2 days to
  avoid quadratic growth (hosts x days x rate at every interval). We accepted "close to target"
  here instead of forcing an exact 1 GB fit, because preserving linear host-based scaling
  mattered more than squeezing out the last ~70 MB.

#### NYC Taxi (+1000%)
- Old SF=1: 1/100 sample of yellow taxi, ~96 MB
- New SF=1: 1/10 sample of yellow taxi, ~8.46M trips, ~960 MB
- A note on NYC Taxi: the sample rate saturates at 1.0. SF=10 and above use the full
  yellow-taxi corpus (BenchBox warns at SF=10 to make this explicit).

#### FlightData (new)
- SF=1: ~25.46M flights (about 41 months of BTS data), ~1 GB
- A note on FlightData: the BTS corpus is finite (456 months from 1987 to 2024). SF >=11.12
  exhausts the corpus and BenchBox warns.

### 5. Second-order constraints we hit (~250 words)

The 1 GB target sounded simple. It got complicated. Three benchmarks needed special handling
because naive linear scaling broke at higher SFs:

**TSBS DevOps: quadratic growth**

TSBS naturally scales in two dimensions: number of hosts and duration. Multiplying both by SF
means SF=10 produces 100x the data, not 10x. We fixed duration at 2 days and scale only
`num_hosts`. This is a benchmark-specific correctness fix, not a general scale factor decision.

**NYC Taxi: sample-rate ceiling**

NYC Taxi's "scale factor" controls a sample rate over a fixed historical corpus. The formula
`sample_rate = min(1.0, SF / 10.0)` saturates at SF=10 (sample rate hits 1.0). Above SF=10,
asking for "more data" is meaningless, the corpus is already fully consumed. BenchBox warns at
SF=10 rather than silently capping.

**FlightData: corpus exhaustion**

FlightData consumes BTS monthly data files. With ~41 months per SF unit, SF >=11.12 exhausts
the 456-month corpus. Above that, asking for more data again means asking for data that doesn't
exist. BenchBox warns rather than silently capping.

These three cases share a pattern: scale factor is a useful abstraction up to the point where
the underlying data source has natural limits. We surfaced those limits as warnings so users
hit them with their eyes open.

### 6. What about TPC-H, TPC-DS, SSB, ClickBench, DataVault? (~150 words)

These are spec-locked. We didn't touch them.

- **TPC-H** and **TPC-DS** define their own SF semantics in their official specs. Changing
  output sizes would break TPC compliance.
- **SSB** is built on TPC-H's schema and inherits its scaling.
- **ClickBench** is a single-dataset benchmark with fixed size; SF doesn't apply.
- **DataVault** is a TPC-H-derived schema with TPC-H row counts.

These benchmarks' SF=1 sizes happen to be close to (TPC-H, ClickBench, DataVault) or larger
than (TPC-DS at ~2 GB) the 1 GB target, so the harmonization doesn't create a large
discontinuity even where it doesn't apply.

### 7. What this means for users (~200 words)

**If you've been using BenchBox at SF=1 already**: outputs for the 7 affected benchmarks will
differ. Cached data should be regenerated with `--force datagen` to match the new baselines,
or you'll be running queries against pre-harmonization data that doesn't match the
documentation.

**If you're new to BenchBox**: SF=1 now means roughly 1 GB across all adjustable benchmarks.
SF=0.01 (the BenchBox default for smoke tests) means roughly 10 MB. SF=10 means roughly 10 GB
for benchmarks that have not hit a documented corpus ceiling. That mental model now mostly holds,
which is a major improvement over "SF=1 means whatever each benchmark inherited historically."

**For multi-benchmark runs**: storage and runtime budgeting at the same SF is now meaningful.
A pipeline that runs all adjustable benchmarks at SF=1 will produce roughly 7 GB of
uncompressed data (1 GB per benchmark), plus whatever the spec-locked benchmarks contribute.

**For published results**: results from before v0.2.1 are not directly comparable to results
from v0.2.1+ for the affected benchmarks. The benchmark didn't change; the data size did.

### 8. What we'd do differently (~150 words)

Two things we'd revisit:

1. **Pick the target earlier.** This harmonization is a v0.2.1 change because the catalog grew
   to a size where the inconsistency became painful. Picking a target at v0.1.0 would have
   meant fewer affected benchmarks and no backwards-incompatibility window.
2. **Surface the SF-vs-data-size relationship more prominently in `--dry-run`.** Today,
   `--dry-run` shows what BenchBox will do but doesn't always show the resulting data size up
   front. A 1 GB target makes that math easy enough that we should put it in the dry-run
   output.

### 9. Try it yourself (~100 words)

```bash
# Generate at SF=1 and check the resulting data size for an affected benchmark
benchbox run --platform duckdb --benchmark coffeeshop --scale 1 --phases generate

# Compare to a spec-locked benchmark
benchbox run --platform duckdb --benchmark tpch --scale 1 --phases generate

# Check what changed: --dry-run shows the planned data generation
benchbox run --dry-run ./preview --platform duckdb --benchmark amplab --scale 1
```

The `--phases generate` flag stops after data generation, useful for sanity-checking output
sizes before running queries.

---

## Word count target

~1,800 words. Slightly longer than a typical building-benchbox post because the per-benchmark
detail section is essential to the post's value (users need to see the actual numbers).

---

## Post structure (architecture/design template)

```
# One SF, one gigabyte: harmonizing scale factors across BenchBox

> Before v0.2.1, `--scale 1` could mean 96 MB or 6 GB depending on which benchmark you ran.

**TL;DR**: ...

---

## The problem: SF=1 meant nothing in particular
## Why pick 1 GB?
## The design decision: backwards-incompatible by intent
## What changed, per benchmark
  ### CoffeeShop (-83%)
  ### JoinOrder (-80%)
  ### AMPLab (+150%)
  ### H2ODB (+900%)
  ### TSBS DevOps
  ### NYC Taxi
  ### FlightData (new)
## Second-order constraints we hit
## What about TPC-H, TPC-DS, SSB, ClickBench, DataVault?
## What this means for users
## What we'd do differently
## Try it yourself

---

## References
```

---

## Images

Both images generated and committed to `_blog/building-benchbox/images/` and synced to `docs/blog/images/`.

- `sf1_before_after.png`: comparison bar chart of SF=1 sizes per benchmark, before vs. after harmonization
- `tsbs_quadratic.png`: line chart showing linear (hosts only) vs. quadratic (hosts x duration) TSBS growth

Generated via `scripts/_render_blog_charts.py` using data in `scripts/_chart_data/`.

---

## Narrative angle

This post is a methodology decision, not a feature announcement. The structure follows the
building-benchbox template (Problem -> What we tried -> What we built -> What we learned), but
the "What we tried" is implicit (we tried the alternatives we list and rejected them).

The tone is honest about the backwards-incompatibility. We didn't smuggle this change in. We
made it deliberately because the alternative (a tool whose `--scale` flag meant nothing in
particular) was worse than the migration cost.

The voice should match the building-benchbox series: "we" throughout, evidence-based, honest
about trade-offs, no platform advocacy. The data comes from the changelog, the test file
`tests/unit/generators/test_scale_factor_harmonization.py`, and the per-benchmark generators
under `benchbox/core/`.

---

## Reference

- Changelog entry: `CHANGELOG.md` (`[0.2.1] - 2026-04-22`, "Scale factor harmonization" bullet)
- Companion post: `09-v0-2-1-release-summary.md` (full release notes for v0.2.1)
- Test coverage: `tests/unit/generators/test_scale_factor_harmonization.py`
- Per-benchmark generators: `benchbox/core/{coffeeshop,joinorder,amplab,h2odb,tsbs_devops,nyctaxi,flightdata}/`

---

## References & Resources

**Source files (modified for harmonization)**:
- `/Users/joe/Developer/BenchBox/benchbox/core/coffeeshop/generator.py`
- `/Users/joe/Developer/BenchBox/benchbox/core/joinorder/generator.py`
- `/Users/joe/Developer/BenchBox/benchbox/core/amplab/generator.py`
- `/Users/joe/Developer/BenchBox/benchbox/core/h2odb/generator.py`
- `/Users/joe/Developer/BenchBox/benchbox/core/tsbs_devops/generator.py`
- `/Users/joe/Developer/BenchBox/benchbox/core/nyctaxi/downloader.py`
- `/Users/joe/Developer/BenchBox/benchbox/core/flightdata/downloader.py`

**Spec definitions**:
- `/Users/joe/Developer/BenchBox/benchbox/core/results/benchmark_specs.py` (SF=1 row counts per
  benchmark, ~lines 257-535)

**Test coverage**:
- `/Users/joe/Developer/BenchBox/tests/unit/generators/test_scale_factor_harmonization.py`
  (139 lines, validates 0.8-1.3 GB target band)

**Documentation (updated)**:
- `/Users/joe/Developer/BenchBox/docs/benchmarks/{coffeeshop,join-order,amplab,h2odb,tsbs-devops,nyctaxi,flightdata}.md`

**Implementing commits**:
- `5865743bb` (2026-04-07) chore: record planning item for scale factor harmonization
- `a1c50d7ae` (2026-04-07) feat(benchmarks): harmonize SF1 baseline sizes (26 files, +434 lines)
- `842f097af` (2026-04-07) docs(benchmarks): update SF=1 baselines and compression support
- `f7dc3535` (2026-04-08) fix: harmonize large SF behavior
- `0cc4a8de` (2026-04-08) docs: document scale factor ceiling reasoning

**Per-benchmark size data (from research, all SF=1, uncompressed CSV)**:
- CoffeeShop: 6 GB -> ~1 GB (78M -> 13.26M order_lines)
- JoinOrder: ~5 GB -> ~1 GB (proportional reduction across 21 tables)
- AMPLab: ~450 MB -> ~1.1 GB (2.5x increase)
- H2ODB: ~100 MB -> ~1 GB (1M -> 10M trips, 10x)
- TSBS DevOps: ~466 MB -> ~932 MB (100 hosts x 1 day -> 100 hosts x 2 days; duration fixed to
  avoid quadratic growth)
- NYC Taxi: ~960 MB at 1/10 sample of yellow taxi (~8.46M trips); SF>=10 saturates corpus
- FlightData: ~1 GB at ~41 months of BTS data (~25.46M flights); SF>=11.12 exhausts corpus

**Spec-locked (unchanged)**:
- TPC-H: ~1 GB at SF=1 (TPC spec)
- TPC-DS: ~2 GB at SF=1 (TPC spec)
- SSB: inherits TPC-H scaling
- ClickBench: single fixed dataset
- DataVault: inherits TPC-H schema

**External references**:
- TPC-H specification (for the SF=1 = 1 GB convention): http://www.tpc.org/tpch/
- TPC-DS specification: http://www.tpc.org/tpcds/
- BTS On-Time Performance dataset (FlightData source): https://www.transtats.bts.gov/
