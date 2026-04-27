---
title: "BenchBox v0.2.1: MPP wave, vector search, and harmonized scale factors"
series: building-benchbox
post_number: 9
type: release-notes
tags: [benchbox, release, changelog, vector-search, doris, starrocks, singlestore, cedardb, questdb, gluten, clickhouse, scale-factor]
status: OUTLINE
---

# Outline: BenchBox v0.2.1 release summary

---

## Theme

v0.2.1 is the **platform and benchmark expansion release**. Six new platform adapters, two new
benchmarks, a major NYC Taxi expansion, scale factor harmonization across most adjustable
benchmarks, and the ClickHouse adapter split into three deployment modes. The Beta promotion in
v0.2.0 made it possible to absorb this much surface area in a single release without
destabilizing the core path.

The headline changes are:

1. **Six new platform adapters**: Apache Doris, CedarDB, StarRocks, SingleStore, QuestDB, Apache
   Gluten + Velox.
2. **Two new benchmarks**: Vector Search (kNN/ANN with recall@k metric) and FlightData
   (20 analytical queries over US BTS aviation data).
3. **NYC Taxi expansion**: Green Taxi, For-Hire Vehicle (FHV), and High-Volume FHV trip records
   alongside Yellow Taxi.
4. **Scale factor harmonization**: 7 benchmarks with adjustable scale factors now target
   ~1 GB uncompressed CSV at SF=1.
5. **ClickHouse split into three platforms**: `clickhouse-local`, `clickhouse-server`,
   `clickhouse-cloud` driven by a `deployment_mode` contract.
6. **TPC-DS-OBT defaults to parquet output**.
7. **DataFrame mode coverage** expanded to 5 more benchmarks.
8. **Apache Doris and StarRocks stability work** across data loading, dialects, and Docker startup.
9. **SQL compatibility subsystem** (`benchbox/sql_compat/`) added to centralize gating, query
   variants, rewrites, schema emission, and DDL optimization.

---

## TL;DR (draft bullets)

- **Six new platform adapters** ship in v0.2.1: Apache Doris, CedarDB, StarRocks, SingleStore,
  QuestDB, and Apache Gluten + Velox.
- **Vector Search benchmark** introduces BenchBox's first correctness-and-latency metric pair:
  6 kNN/ANN queries reporting recall@k alongside latency, with dialect variants for DuckDB,
  pgvector, Snowflake, ClickHouse, StarRocks, and Doris.
- **FlightData benchmark** adds 20 analytical queries over US BTS on-time aviation data, with
  DataFrame support out of the box.
- **NYC Taxi expansion** adds Green Taxi, For-Hire Vehicle, and High-Volume FHV trip records;
  selected via `--benchmark-option taxi_types=...`.
- **Scale factor harmonization**: 7 benchmarks (CoffeeShop, JoinOrder, AMPLab, H2ODB, TSBS DevOps,
  NYC Taxi, FlightData) now target roughly 1 GB at SF=1. Spec-locked benchmarks are unchanged.
- **ClickHouse split into three platforms**: `clickhouse-local`, `clickhouse-server`,
  `clickhouse-cloud`, with bare `clickhouse` retained as a deprecated migration alias.
- **TPC-DS-OBT now writes parquet by default** for smaller output and better handling of wide,
  sparse tables. Use `--benchmark-option output_format=dat` to keep the old `.dat` behavior.
- **DataFrame mode coverage** expanded to Metadata Primitives, Transaction Primitives, TPC-Havoc,
  FlightData, and JoinOrder.
- **`--benchmark-option K=V` and `--iterations` CLI flags** added.

---

## At a glance table

| Area | What changed in v0.2.1 | Why it matters |
| --- | --- | --- |
| New platforms | Doris, CedarDB, StarRocks, SingleStore, QuestDB, Gluten+Velox | Broader MPP and analytics engine coverage |
| Vector Search benchmark | 6 kNN/ANN queries; recall@k + latency; 6 dialect variants | First BenchBox benchmark with a correctness metric alongside latency |
| FlightData benchmark | 20 analytical queries over BTS aviation data; DataFrame ready | New analytical workload with real-world data shape |
| NYC Taxi expansion | Green, FHV, HVFHV trip records via `taxi_types` option | Run NYC Taxi against a wider slice of the actual taxi fleet |
| Scale factor harmonization | 7 adjustable benchmarks target ~1 GB at SF=1 | Cross-benchmark size intuition holds at the same SF |
| ClickHouse split | `clickhouse-local`, `clickhouse-server`, `clickhouse-cloud` | Deployment mode no longer hidden behind one adapter |
| TPC-DS-OBT default format | Parquet by default; `--benchmark-option output_format=dat` opts out | Smaller output, better handling of wide sparse tables |
| DataFrame coverage | +5 benchmarks (Metadata/Transaction Primitives, TPC-Havoc, FlightData, JoinOrder) | DataFrame mode reaches more of the catalog |
| New CLI flags | `--benchmark-option K=V` (repeatable), `--iterations` | Benchmark-specific tuning and explicit power-test counts |
| SQL compatibility subsystem | `benchbox/sql_compat/` centralizes gating, variants, rewrites, schema, DDL | Adding/maintaining MPP adapters becomes mechanical, not bespoke |
| Unofficial TPC-DS scales | SF<1 supported via bundled patched dsdgen (non-comparable) | Fast iteration on TPC-DS without spec-scale data sizes |
| Other | HTTP TLS validation; pg_mooncake/pg_duckdb option surface; psycopg3 migration; pyarrow cap to <25 | Reliability and dependency hygiene |

---

## Section breakdown

### 1. Why this release looks different from v0.2.0 (~250 words)

This is the framing section. v0.2.0 was the Beta promotion: hardening, coverage threshold,
cloud reliability fixes. v0.2.1 is what becomes possible *after* the core path is reliable enough
to extend it.

- v0.2.0 made the core path reliable across cloud platforms.
- v0.2.1 adds 6 platforms, 2 benchmarks, a benchmark-data-size harmonization, and an architectural
  split of the ClickHouse adapter, all without regressing v0.2.0's coverage and reliability work.
- The SQL compatibility subsystem (`benchbox/sql_compat/`) is the quiet enabler. Six MPP adapters
  in one release was only achievable because gating, query variants, rewrites, and DDL emission
  were extracted into shared infrastructure rather than re-implemented per platform.

Connect to the rest of the post: the platform wave is the headline, but the underlying enabler
is the SQL compatibility subsystem, and the benchmark-side work (Vector Search, FlightData, NYC
Taxi expansion, scale factor harmonization) is what those new platforms have to run against.

### 2. Six new platform adapters (~400 words)

Per-platform, two-to-three-sentence treatment. Each entry covers what kind of engine, what
deployment model, and what dialect/loading characteristics BenchBox supports.

- **Apache Doris**: MPP analytics engine. Stream load for ingest, DDL injection for tuning, vector
  search dialect, and dialect coverage across TPC-DS, TPC-DI, ClickBench, NYC Taxi, and Write
  Primitives.
- **CedarDB**: PostgreSQL-wire RDBMS (formerly Umbra). OLAP-tuned defaults, `COPY` bulk loading.
  Wire-compatible with PostgreSQL clients.
- **StarRocks**: Columnar analytics engine. Stream load, Parquet handler, dialect coverage across
  9 benchmarks.
- **SingleStore**: Distributed SQL (formerly MemSQL). Columnstore DDL, `LOAD DATA LOCAL INFILE`,
  Helios and self-managed deployment support.
- **QuestDB**: Time-series database. Full dialect rewriter for CTE/EXISTS/mixed-predicate queries
  needed because QuestDB's SQL surface differs significantly from standard PG-style SQL.
- **Apache Gluten + Velox**: Spark acceleration via the Velox C++ vectorized engine, with
  transparent JVM fallback and columnar shuffle. Not a new database, a new execution path
  underneath Spark.

Then a paragraph framing: the pattern across these adapters is the important point, not a
registry-count victory lap. Each one needed a native bulk-load path, dialect-specific query
rewrites where standard SQL doesn't translate cleanly, and DDL injection for tuning settings the
benchmark needs.

### 3. New benchmarks: Vector Search and FlightData (~350 words)

#### Vector Search

**The metric story**: vector search is the first BenchBox benchmark where the headline metric
is a pair, not a single number. Each query reports both **recall@k** (correctness) and
**latency** (performance). You can't compare two engines at "the fastest run" without also
checking they returned the same answers.

- 6 kNN/ANN queries
- Dialect variants: DuckDB, pgvector, Snowflake, ClickHouse, StarRocks, Doris
- Useful for both exact-search engines (kNN) and ANN-index engines (HNSW, IVF) on the same
  workload

#### FlightData

- 20 analytical queries over US BTS on-time aviation data
- DataFrame mode supported out of the box
- Real-world data shape: high cardinality string columns (carrier, airport codes), date math,
  delay distributions, route-level aggregations
- Pairs naturally with the scale factor harmonization work: SF=1 maps to ~25.46M flights, ~1 GB

### 4. NYC Taxi expansion (~150 words)

NYC Taxi previously only ran against Yellow Taxi data. v0.2.1 adds:

- **Green Taxi**: outer-borough taxis launched in 2013
- **For-Hire Vehicle (FHV)**: traditional livery and limousine
- **High-Volume FHV (HVFHV)**: Uber, Lyft, and similar app-based dispatch

Selected via the new `--benchmark-option taxi_types=yellow,green` flag. Useful for testing how a
platform handles trip-record data with different schema shapes and volume profiles in one
benchmark run.

### 5. Scale factor harmonization (~250 words)

Short summary. Detailed treatment is in the dedicated post (#10).

- 7 benchmarks with adjustable scale factors now target roughly 1 GB of uncompressed CSV at SF=1:
  CoffeeShop, JoinOrder, AMPLab, H2ODB, TSBS DevOps, NYC Taxi, FlightData.
- Spec-locked benchmarks (TPC-H, TPC-DS, SSB, ClickBench, DataVault) are unchanged.
- This is a backwards-incompatible change for output sizes at a given SF: CoffeeShop SF=1 went
  from 78M order_lines to 13.26M. AMPLab grew. H2ODB grew 10x.
- Why it matters: before v0.2.1, `--scale 1` meant wildly different output sizes across
  benchmarks. Now, cross-benchmark intuition (cost, runtime, storage) holds at the same SF.
- Pointer to the deeper post: "we wrote up the design decision and per-benchmark numbers
  separately."

### 6. ClickHouse split into three platforms (~250 words)

`clickhouse` now has three first-class platform names:

- `--platform clickhouse-local` (embedded, `clickhouse-local` binary)
- `--platform clickhouse-server` (self-managed server)
- `--platform clickhouse-cloud` (managed cloud)

Driven by a standardized `deployment_mode` contract. Why this matters:

- Dialect quirks differ between local and server (e.g., temp table behavior, system table access).
- Connection handling differs (clickhouse-local has no network, server has wire protocol, cloud
  has TLS plus auth).
- Tuning DDL applicable on server is meaningless on local.

The single adapter previously encoded all three behaviors with branching. The split separates
them so each can evolve without compromising the others.

This is also the pattern that other multi-deployment platforms will follow. The
`deployment_mode` contract is reusable.

Migration nuance: bare `--platform clickhouse` still works during the deprecation window and maps
to `clickhouse-local` by default, while `deployment_mode=server` still resolves to
`clickhouse-server`. The post should tell readers to migrate to the explicit names anyway.

### 7. TPC-DS-OBT, DataFrame coverage, and CLI surface (~250 words)

TPC-DS-OBT (one big table variant) now writes Parquet by default. Previously it wrote `.dat`
text files like other TPC-DS variants.

Why parquet:

- Wide, sparse OBT tables compress dramatically better in columnar formats
- Output sizes drop substantially (give a representative number if available)
- Native loaders on most platforms handle parquet without a text-to-columnar conversion step

Backwards compatibility: pass `--benchmark-option output_format=dat` to keep the old behavior.

**DataFrame mode now covers 5 more benchmarks**: Metadata Primitives, Transaction Primitives,
TPC-Havoc, FlightData, JoinOrder. The DataFrame catalog is now substantially closer to the SQL
catalog.

**New CLI flags**:

- `--benchmark-option K=V` (repeatable). For benchmark-specific parameters that don't belong on
  the global CLI surface. Examples: `taxi_types=yellow,green` for NYC Taxi,
  `output_format=dat` for TPC-DS-OBT.
- `--iterations`. Power-test measurement count. Previously this was implicit; now it's explicit.

### 8. Stability and correctness follow-through (~300 words)

This is the tail section that should stay compressed. The goal is to show that the new surface
area shipped with follow-through, not to reproduce the changelog.

**New-adapter shake-out**:

- Bulk loading hardened (timeouts, type handling, retry behavior)
- SQL compatibility (dialect fixes for `tpcdi`, `tpcds_obt`, `vector_search`, ClickBench, NYC
  Taxi, primitives)
- Docker startup reliability
- ARM64 support
- Type handling edge cases

Call out Apache Doris and StarRocks by name here: this is the typical new-adapter shake-out
cycle, and both platforms got substantial attention before release rather than being shipped raw.

**ClickHouse correctness highlights**:

- TPC-DS power tests now report `FAILED` when no queries execute (previously passed silently)
- Dialect overrides for `tpcdi`, `coffeeshop`, `h2odb` Q9, `nyctaxi` EXTRACT, `tpchavoc` Q6,
  `read_primitives`
- Query error messages now surfaced in results (also extended to Redshift and Firebolt)

The "passed silently when no queries ran" fix is worth a sentence on its own: a benchmark tool
that reports success when nothing executed is doing something worse than reporting failure.

**One dense paragraph for the rest**:

- **QuestDB compatibility and loading**: query rewrites, `/imp` CSV loading with zstd and
  multi-chunk support, HTTPS support, table reuse stabilization.
- **Cross-adapter correctness**: CedarDB benchmark failures resolved; LakeSail local-mode startup
  and file scanning improved; Firebolt S3 staging and load errors hardened; Databend connection
  and cache behavior improved; pg_mooncake/pg_duckdb columnstore migration hardened.
- **psycopg3 migration**: pg-family adapters moved off psycopg2.
- **Dependency hygiene**: relaxed a DataFusion v53 ordering assertion; raised pyarrow cap to
  `<25.0.0`; restored benchmark timeout enforcement on macOS.
- **Unofficial TPC-DS scales**: SF<1 now works out of the box, backed by patched
  `dsdgen` binaries bundled with BenchBox. Runs are tagged `unofficial_subscale` and
  non-comparable to published TPC-DS results.
- **HTTP TLS certificate validation** for HTTP-based data loading.
- **Advanced pg_mooncake and pg_duckdb benchmarking options** exposed.
- **Extended compressed data generation**: TSBS, FlightData, and NYC Taxi generators now support
  BenchBox compression options and write compression metadata manifests.
- **DataVault**: SHA-256 hash-key support added to the SQL ETL path.
- **Firebolt Core**: Docker-based live smoke tests added.

Keep this section short in the final draft. If it starts reading like a long bug-fix inventory,
cut details and link the changelog.

### 9. Changed behavior to be aware of (~200 words)

- **`--platform clickhouse` is now deprecated shorthand**: bare `clickhouse` still resolves to
  `clickhouse-local` during the migration window, and legacy `deployment_mode=server` still
  resolves to `clickhouse-server`, but scripts should migrate to the explicit platform names.
- **TPC-DS-OBT default format**: defaults to parquet now. Pass
  `--benchmark-option output_format=dat` for the old `.dat` behavior.
- **Scale factor data sizes change**: 7 benchmarks (CoffeeShop, JoinOrder, AMPLab, H2ODB,
  TSBS DevOps, NYC Taxi, FlightData) produce different SF=1 data sizes than before. Existing
  cached datasets may need to be regenerated to match the new baselines (`--force datagen`).
- **Spec-locked benchmarks unchanged**: TPC-H, TPC-DS, SSB, ClickBench, DataVault produce the
  same output as before.
- **psycopg3 migration**: pg-family adapters now use psycopg3. If you pinned psycopg2 in your
  environment, that pin is no longer required.

### 10. Quick upgrade checks (~150 words)

Standard upgrade checks template:

1. Confirm version: `benchbox --version`
2. Smoke benchmark on DuckDB:
   `benchbox run --platform duckdb --benchmark tpch --scale 0.01 --phases power --non-interactive`
3. If you still script bare `--platform clickhouse`, migrate to `clickhouse-local`,
   `clickhouse-server`, or `clickhouse-cloud` and stop relying on the deprecated alias behavior
4. If you regenerate data nightly, expect new SF=1 sizes for the 7 affected benchmarks; force a
   regeneration with `--force datagen`
5. Try the new Vector Search benchmark on a supported platform to see the recall@k metric flow:
   `benchbox run --platform duckdb --benchmark vector_search --scale 0.01`

### 11. Bottom line (~150 words)

Tie the release together:

- v0.2.0 hardened the core path; v0.2.1 used that stability to expand the surface area
  meaningfully (6 platforms, 2 benchmarks, 1 schema-and-loader change for ClickHouse, 1
  benchmark-data harmonization).
- The release leans on the SQL compatibility subsystem to make the platform wave manageable.
  Without it, six adapters in one cycle would have meant six bespoke dialect implementations.
- Vector Search introduces a metric pattern (correctness alongside latency) that is likely to
  show up in more benchmarks over time.
- Scale factor harmonization is a quiet but user-visible change: cross-benchmark size intuition
  now holds at the same SF.

If you run into anything unexpected after upgrading, open an issue.

---

## Word count target

~1,700-1,900 words. Similar to the actual published v0.2.0 range, but tighter in the back half.
If it starts to read like a changelog, collapse the stability tail into one paragraph and link
the changelog instead of enumerating every fix.

---

## Post structure (release-post template)

```
# BenchBox v0.2.1: MPP wave, vector search, and harmonized scale factors

{one-sentence intro}

![{image placeholder}]

## TL;DR
## At a glance
## Why this release looks different from v0.2.0
## Six new platform adapters
## New benchmarks: Vector Search and FlightData
## NYC Taxi expansion
## Scale factor harmonization
## ClickHouse split into three platforms
## TPC-DS-OBT, DataFrame coverage, and CLI surface
## Stability and correctness follow-through
## Changed behavior to be aware of
## Quick upgrade checks
## Bottom line
## Reference
```

---

## Image placeholders (to generate before publishing)

- `vector_search_recall_latency.png`: scatter or pareto chart showing recall@k vs latency for
  the 6 vector search dialect variants
- `nyc_taxi_types.png`: stacked bar of trip counts across yellow/green/FHV/HVFHV
- `clickhouse_split_diagram.png`: the three-deployment-mode adapter split (optional)

---

## Narrative angle

This release has one overarching story: **scale comes from infrastructure, not heroics.**

v0.1.x built the catalog one adapter and one benchmark at a time. v0.2.0 hardened the core path.
v0.2.1 is the first release where adding six adapters in one cycle was a tractable amount of
work, because the SQL compatibility subsystem turned per-platform dialect work into a
configuration problem. The post should make that explicit without making it the headline:
readers care about the platforms and benchmarks they got, but the engineering story is the
infrastructure that made the platform wave possible.

The Vector Search and FlightData additions are the second narrative thread: BenchBox's
benchmark catalog is broadening beyond TPC-style analytics into vector search (with a
correctness metric) and real-world data shapes (BTS aviation). These are the kinds of
benchmarks the user community has been asking about.

Scale factor harmonization is the user-visible methodology change. It's intentionally
backwards-incompatible because the alternative (`SF=1 means whatever each benchmark wants`) was
making cross-benchmark reasoning impossible. The dedicated post (#10) covers the rationale in
depth; the release post just notes it and points there.

One structural rule for the draft: keep the tail compressed. The release should feel like a
coherent story about platform expansion, new benchmarks, and harmonized scale factors, not like a
tour through every changelog bullet.

---

## Reference

- Changelog entry: `CHANGELOG.md` (`[0.2.1] - 2026-04-22`)
- Companion post: `10-scale-factor-harmonization.md` (deep dive on the SF=1 decision)
- Previous release post: `08-v0-2-0-release-summary.md`

---

## References & Resources

- BenchBox CHANGELOG, v0.2.1 entry: `/Users/joe/Developer/BenchBox/CHANGELOG.md` (lines 10-112)
- SQL compatibility subsystem location: `benchbox/sql_compat/`
- Vector Search dialect variants: 6 (DuckDB, pgvector, Snowflake, ClickHouse, StarRocks, Doris)
- FlightData query count: 20
- ClickHouse split: `clickhouse-local`, `clickhouse-server`, `clickhouse-cloud` driven by
  `deployment_mode` contract; bare `clickhouse` remains a deprecated migration alias
- ClickHouse migration guide: `docs/platforms/clickhouse-migration.md`
- New platform count: 6 (Doris, CedarDB, StarRocks, SingleStore, QuestDB, Gluten+Velox)
- Affected scale-factor benchmarks: 7 (CoffeeShop, JoinOrder, AMPLab, H2ODB, TSBS DevOps,
  NYC Taxi, FlightData)
- Spec-locked benchmarks: TPC-H, TPC-DS, SSB, ClickBench, DataVault
