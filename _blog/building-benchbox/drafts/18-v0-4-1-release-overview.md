---
blogpost: true
status: draft
date: September 29, 2026
author: Joe Harris
series: building-benchbox
post_number: 18
type: release-notes
tags: benchbox, release, lakehouse, delta, iceberg, hudi, results-explorer, cost
meta_description: "BenchBox v0.4.1 adds four lakehouse table pairings, stricter result submissions, cost reporting without guesses, and requires Python 3.11 and pandas 3."
---
# BenchBox v0.4.1: more lakehouse pairings, stricter results

**TL;DR**: BenchBox v0.4.1 can benchmark four more lakehouse table pairings: Delta on ClickHouse, Iceberg on BigQuery and Redshift Spectrum, and Hudi on Databricks. Result submissions now need every query and an official TPC-H run, and cost estimates say "unavailable" instead of guessing. Before you upgrade: Python 3.11, pandas 3, and DuckDB 1.5 are now minimums, and Modin support is gone.

---

![BenchBox 0.4.1 support matrix for lakehouse tables. Rows are Delta, Iceberg, and Hudi. Columns are grouped into cloud warehouses (BigQuery, Redshift Spectrum, Databricks, Snowflake, ClickHouse Cloud), query engines (ClickHouse, DuckDB, DataFusion, Trino/Presto), and Spark (Apache Spark, Athena Spark, Onehouse Quanton). Four cells are marked new in 0.4.1: Delta on ClickHouse, Iceberg on BigQuery, Iceberg on Redshift Spectrum, and Hudi on Databricks.](../images/v041_lakehouse_matrix.png)

BenchBox v0.4.1 was released on **September 24, 2026**.

This is a point release, but it touches more of a typical run than the version number suggests. Three changes stand out. More warehouses and engines can read open table formats. Published results have stricter rules. Cost reports stop filling gaps with estimates. The release also raises dependency floors, so read [Before you upgrade](#before-you-upgrade) first.

## At a glance

| Area | What changed in v0.4.1 | Why it matters |
| --- | --- | --- |
| Lakehouse tables | Delta on ClickHouse, Iceberg on BigQuery and Redshift Spectrum, Hudi on Databricks | Benchmark the same table format on more engines |
| External tables | `--table-mode external` on Athena Spark, EMR Serverless, Dataproc Serverless, and Glue | Query staged files without loading them first |
| Table maintenance | Optimize and vacuum for Delta and Hudi, vacuum for Iceberg | Measure a table after compaction, not only after the first load |
| Result submissions | Official TPC-H only; every query required; warnings for implausible timings | Published results are complete runs |
| Cost reporting | Unknown prices, sizes, or regions report cost as unavailable | No invented dollar figures |
| Results Explorer | Browse by engine version, compare runs to a baseline, preview before submitting | Easier to see what changed between releases |
| Throughput | `benchbox run --streams N`; timed-out queries finish before the next phase | Control concurrency and keep phases separate |
| Requirements | Python 3.11+, pandas 3, DuckDB 1.5-1.x, DataFusion 54+; Modin removed | Check your environment before upgrading |

## Lakehouse tables on more engines

Lakehouse table formats such as Delta Lake, Apache Iceberg, and Apache Hudi add a transaction log and table metadata on top of Parquet files. The same table can then be read by several engines. BenchBox already covered many of these pairings, mostly through Spark and the local query engines. v0.4.1 adds four more, shown in orange in the matrix above:

- **Delta on ClickHouse.** ClickHouse reads Delta tables natively through its `DeltaLake` table engine and `deltaLake` table functions. Object-storage URLs use the engine. Local paths use `deltaLakeLocal` when the server has it registered. If a local server lacks native Delta reads, BenchBox falls back to exporting a Parquet snapshot. Remote tables with no native reader fail with a clear error instead.
- **Iceberg on BigQuery.** BigQuery external mode now accepts Iceberg table directories as well as Parquet and Delta. It reads them as BigLake tables, so it needs a `biglake_connection` platform option.
- **Iceberg on Redshift Spectrum.** Spectrum reads Iceberg only through the AWS Glue Data Catalog. BenchBox registers the uploaded table in Glue, replacing any earlier registration, and queries it through the external schema.
- **Hudi on Databricks.** Set `table_format=hudi` and BenchBox creates tables with `USING HUDI` and the record-key properties you pass. So far this pairing is validated by unit tests only, not on a live workspace. Your Databricks runtime must already support Hudi, and BenchBox does not install the Hudi libraries.

External-table mode (`--table-mode external`), which queries staged files without loading them into native tables, now also works on Athena Spark, EMR Serverless, Dataproc Serverless, and AWS Glue.

The matrix separates support from maturity. Some pairings read through external tables rather than native ones. DuckDB's Iceberg support is still experimental. The Apache Spark column also covers Dataproc Serverless. Before you plan a comparison, check the platform guide for the pairing you need.

Table maintenance is now part of the workflow. Delta and Hudi tables support optimize and vacuum, and Iceberg tables support vacuum. Small files left behind by a load change scan performance, so a benchmark after compaction measures a different table than one taken straight after loading.

## Stricter rules for published results

Earlier releases already rejected unofficial TPC-DS runs for submission. v0.4.1 applies the same rule to TPC-H. A submission must now include every query in the benchmark, so a partial run cannot appear next to complete ones. BenchBox also warns when timings look implausible. The warning does not block the submission. It flags the result for a person to review.

The Results Explorer at [benchbox.dev/results/](https://benchbox.dev/results/) gained three views that help with release-to-release questions. You can browse results by engine version, compare several runs against one baseline, and preview your own results before you submit them.

## Cost reports without guesses

When BenchBox does not know a price, a warehouse size, or a region, it now reports the cost as unavailable. Earlier releases could fill that gap with an estimate. A blank field is less convenient, but it cannot be mistaken for a measured number. Prices now come from vendor price lists. Snowflake cost uses run time and warehouse size.

Result files also record more context. They store the tuning you requested next to the tuning BenchBox applied, the client's cloud region, and each table's load time when the loader captures per-table timings.

## Other notable changes

- **Throughput concurrency.** `benchbox run --streams N` sets how many query streams a throughput test runs at once. BenchBox now waits for timed-out queries to stop before starting the next phase. If the throughput phase fails, `benchbox run` leaves Throughput@Size out of the result.
- **Repeatable downloaded datasets.** NYC Taxi and FlightData download a fixed set of files, so every run starts from the same source window.
- **More DataFrame queries.** TPC-DS One Big Table has 17 DataFrame queries, up from 3.
- **DuckDB 2.0 preview.** BenchBox can read query plans from the DuckDB 2.0 preview. Stable DuckDB 1.x remains the default.
- **Cloud fixes.** ClickBench, TPC-DS, TPC-DI, and FlightData now load and run on BigQuery, Snowflake, and Databricks. Several Spark issues are fixed, including TPC-Havoc queries that Spark rejected.
- **Correctness fixes.** DataFrame queries for Data Vault and FlightData now return the same results as SQL, and results record the real CPU model. Command-line benchmark options are no longer dropped, and result export works on Windows.

## Before you upgrade

| Previous use | v0.4.1 action |
| --- | --- |
| Python 3.10 | Upgrade to Python 3.11 or later |
| pandas 2 with `pandas-df` or `dask-df` | Upgrade to pandas 3 and `dask[distributed]>=2025.1.0`; with pandas 2, both platforms report unavailable |
| DuckDB below 1.5 | Use DuckDB 1.5 or later, below 2.0 |
| DataFusion below 54 | Use DataFusion 54 or later |
| `databricks-connect` 19 | Pin `databricks-connect` below 19 |
| `--platform modin` or `modin-df` | Use `pandas-df` or `dask-df` |
| `PowerRunExecutor` or `ConcurrentQueryExecutor` | See `docs/advanced/power-run-concurrent-queries.md` for replacements |
| Submitting a non-official or partial TPC-H run | Run the official TPC-H workload with every query |

Python 3.10 reaches end of life in October 2026. We plan to require Python 3.12 after Python 3.11 reaches end of life in October 2027.

## Try it yourself

After upgrading to v0.4.1:

1. Confirm the installed version:

```bash
benchbox --version
```

2. Run a smoke benchmark with a Delta table on DuckDB:

```bash
uv add "benchbox[duckdb,table-formats]"
uv run -- benchbox run --platform duckdb --benchmark tpch --scale 0.01 \
  --table-format delta
```

3. Preview an Iceberg external-table run on BigQuery without running any queries:

```bash
uv run -- benchbox run --platform bigquery --benchmark tpch --scale 0.01 \
  --table-mode external --table-format iceberg \
  --platform-option biglake_connection=<project.region.connection> \
  --dry-run ./preview
```

4. Run a throughput test with four concurrent streams:

```bash
uv run -- benchbox run --platform duckdb --benchmark tpch --scale 0.01 \
  --phases power,throughput --streams 4
```

5. Browse results by engine version at [benchbox.dev/results/](https://benchbox.dev/results/).

If a pairing in the matrix does not behave as described, or you would like one we have not covered, [start a discussion](https://github.com/BenchBox-dev/BenchBox/discussions).

---

## References

- Changelog entry: `CHANGELOG.md` (`[0.4.1] - 2026-09-24`)
- Release tag: [v0.4.1](https://github.com/BenchBox-dev/BenchBox/releases/tag/v0.4.1)
- Table format guides: `docs/guides/table-formats/`
- Databricks Hudi options: `docs/platforms/databricks.md`
- `run` command reference: `docs/reference/cli/run.md`
