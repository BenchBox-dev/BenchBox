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

**TL;DR**: BenchBox v0.4.1 can benchmark Delta tables on ClickHouse and Iceberg tables on BigQuery and Redshift Spectrum, and it can create Hudi tables on Databricks. Result submissions now need every query and an official TPC-H run, and cost reports say "unavailable" instead of guessing. Python 3.11, pandas 3, and DuckDB 1.5 are now minimums, and Modin support is gone.

---

![BenchBox 0.4.1 lakehouse support matrix. Delta: BigQuery, Redshift Spectrum, Databricks, Snowflake, ClickHouse (new), DuckDB, DataFusion, Trino/Presto, Apache Spark, Athena Spark, and Onehouse Quanton. Iceberg: BigQuery (new), Redshift Spectrum (new), Snowflake, ClickHouse Cloud, DuckDB, DataFusion, Trino/Presto, Apache Spark, Athena Spark, and Onehouse Quanton. Hudi: Databricks (new), Apache Spark, and Onehouse Quanton. The Apache Spark column also covers EMR Serverless and Dataproc; the Athena Spark column also covers Synapse Spark and Fabric Spark.](../images/v041_lakehouse_matrix.png)

BenchBox v0.4.1 was released on **September 24, 2026**.

The headline change is lakehouse coverage. BenchBox can now benchmark Delta Lake and Apache Iceberg tables on three more engines and create Apache Hudi tables on Databricks, and external-table mode reaches four more Spark services. The matrix above shows where each format runs today, with the new pairings in orange.

The second change is stricter rules for published results. Submissions must be complete, official runs, and the Results Explorer gains views for comparing releases and previewing your own results before you submit them.

The third is cost reporting that no longer guesses. When BenchBox lacks a price, size, or region, it now says the cost is unavailable. The release also raises several dependency floors, so check [Changed behavior to be aware of](#changed-behavior-to-be-aware-of) before you upgrade.

## At a glance

| Area | What changed in v0.4.1 | Why it matters |
| --- | --- | --- |
| Lakehouse tables | Delta on ClickHouse, Iceberg on BigQuery and Redshift Spectrum, Hudi table creation on Databricks | Benchmark the same table format on more engines |
| External tables | `--table-mode external` on Athena Spark, EMR Serverless, Dataproc Serverless, and Glue | Query staged files without loading them first |
| Result submissions | Official TPC-H only, every query required, warnings for implausible timings | Published results are complete runs |
| Cost reporting | Unknown prices, sizes, or regions report cost as unavailable | No invented dollar figures |
| Results Explorer | Browse by engine version, compare runs to a baseline, preview before submitting | Easier to see what changed between releases |
| Requirements | Python 3.11+, pandas 3, DuckDB 1.5-1.x, DataFusion 54+; Modin removed | Check your environment before upgrading |

## Lakehouse tables on more engines

Lakehouse table formats add a transaction log and table metadata on top of Parquet files, so several engines can read the same table. BenchBox already covered many of these pairings, mostly through Spark and the local query engines. v0.4.1 fills in four gaps on the warehouse and query-engine side.

ClickHouse now reads Delta tables natively through its `DeltaLake` table engine and `deltaLake` table functions, with no Parquet conversion step. Object-storage URLs use the engine, and local paths use `deltaLakeLocal` when the server has it registered. If a local server lacks native Delta reads, BenchBox falls back to exporting a Parquet snapshot. A remote table with no native reader fails with a clear error rather than a snapshot that cannot run.

BigQuery and Redshift Spectrum both gained Iceberg in external-table mode. BigQuery reads Iceberg directories as BigLake tables, so it needs a `biglake_connection` platform option. Spectrum reads Iceberg only through the AWS Glue Data Catalog, so BenchBox registers each uploaded table in Glue, replacing any earlier registration, and queries it through the external schema.

Databricks support for Hudi is narrower than the other three. Set `table_format=hudi` and BenchBox creates the schema with `USING HUDI` DDL and the record-key properties you pass. BenchBox's managed loader uses `COPY INTO`, which writes only Delta tables, so it stops with an error for Hudi. Load the data through a Hudi-aware Spark job first. Delta-only maintenance such as `OPTIMIZE` is recorded as skipped for these tables. So far the DDL is validated by unit tests only, not on a live workspace. Your Databricks runtime must already support Hudi, because BenchBox does not install the Hudi libraries.

External-table mode (`--table-mode external`) queries staged files without loading them into native tables. It now works on Athena Spark, EMR Serverless, Dataproc Serverless, and AWS Glue as well.

Pairings in the matrix differ in maturity. Some read through external tables rather than native ones, and DuckDB's Iceberg support is still experimental. Check the platform guide before you plan a comparison.

Table maintenance is now part of the workflow too. Delta and Hudi tables support optimize and vacuum, and Iceberg tables support vacuum. A load can leave many small files behind, so a benchmark taken after compaction measures a different table than one taken straight after loading.

## Stricter rules for published results

Earlier releases already rejected unofficial TPC-DS runs for submission. v0.4.1 applies the same rule to TPC-H. A submission must also include every query in the benchmark, so a partial run cannot sit next to complete ones in the corpus. BenchBox now warns when timings look implausible. The warning does not block a submission, but it flags the result for a person to review.

The [Results Explorer](https://benchbox.dev/results/) gained three views that help with release-to-release questions. You can browse results by engine version, compare several runs against one baseline, and preview your own results before you submit them.

## Cost reports without guesses

Earlier releases could fill a missing price, warehouse size, or region with an estimate. v0.4.1 reports the cost as unavailable instead. A blank field is less convenient, but nobody can mistake it for a measured number. Prices now come from vendor price lists, and Snowflake cost reflects run time and warehouse size.

Result files also record more context: the tuning you requested next to the tuning BenchBox applied, the client's cloud region, and each table's load time when the loader captures per-table timings.

## Other notable changes

`benchbox run --streams N` sets how many query streams a throughput test runs at once. BenchBox now waits for timed-out queries to stop before the next phase starts, and if the throughput phase fails, `benchbox run` leaves Throughput@Size out of the result.

NYC Taxi and FlightData now download a fixed set of files, so every run starts from the same source window. TPC-DS One Big Table has 17 DataFrame queries, up from 3. BenchBox can also read query plans from the DuckDB 2.0 preview, while stable DuckDB 1.x remains the default.

On the fix side, ClickBench, TPC-DS, TPC-DI, and FlightData now load and run on BigQuery, Snowflake, and Databricks, and TPC-Havoc queries that Spark rejected now run. DataFrame queries for Data Vault and FlightData return the same results as SQL, and results record the real CPU model.

## Changed behavior to be aware of

- **Python 3.11 or later is required.** Python 3.10 reaches end of life in October 2026. We plan to require Python 3.12 after Python 3.11 reaches end of life in October 2027.
- **DataFrame platforms need pandas 3.** With pandas 2, BenchBox reports `pandas-df` and Dask as unavailable. Dask also needs `dask[distributed]>=2025.1.0`.
- **Newer engine drivers.** DuckDB must be at least 1.5 and below 2.0, DataFusion 54 or later, and `databricks-connect` below 19.
- **Modin is no longer supported.** Use `pandas-df` or `dask-df` instead of the `modin` and `modin-df` platforms and extras.
- **`PowerRunExecutor` and `ConcurrentQueryExecutor` are removed.** See `docs/advanced/power-run-concurrent-queries.md` for replacements.
- **Unofficial or partial TPC-H runs can no longer be submitted.** Rerun the official workload with every query before submitting.

## Try it yourself

```bash
benchbox --version
```

Query a Delta table directly from DuckDB. Without `--table-mode external`, DuckDB loads the Delta data into its own tables instead:

```bash
uv add "benchbox[duckdb,table-formats]"
uv run -- benchbox run --platform duckdb --benchmark tpch --scale 0.01 \
  --table-mode external --table-format delta
```

Preview an Iceberg external-table run on BigQuery without executing any queries:

```bash
uv run -- benchbox run --platform bigquery --benchmark tpch --scale 0.01 --phases power \
  --table-mode external --table-format iceberg \
  --platform-option biglake_connection=YOUR_PROJECT.US.YOUR_CONNECTION \
  --dry-run ./preview
```

Run a throughput test with four concurrent streams:

```bash
uv run -- benchbox run --platform duckdb --benchmark tpch --scale 0.01 \
  --phases power,throughput --streams 4
```

Then browse results by engine version in the [Results Explorer](https://benchbox.dev/results/). If a pairing in the matrix does not behave as described, or you would like one we have not covered, [start a discussion](https://github.com/BenchBox-dev/BenchBox/discussions).

---

## References

- Changelog entry: `CHANGELOG.md` (`[0.4.1] - 2026-09-24`)
- Release tag: [v0.4.1](https://github.com/BenchBox-dev/BenchBox/releases/tag/v0.4.1)
- Table format guides: `docs/guides/table-formats/`
- Databricks Hudi options: `docs/platforms/databricks.md`
- `run` command reference: `docs/reference/cli/run.md`
