# Data Organization Strategies

This guide explains how to generate pre-organized benchmark datasets in BenchBox for
zone-map pruning, data-skipping, and clustering experiments.

## Overview

BenchBox can post-process generated TPC data and write organized outputs in:

- `parquet-sorted`
- `delta-sorted`
- `iceberg-sorted`

Organization is controlled by tuning config (sort/partition/cluster columns) or by
built-in defaults for `tpch` and `tpcds`.

## Quick Start

Run TPC-H with a sorted Parquet output:

```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.01 --presort parquet-sorted --non-interactive
```

Run TPC-H with Delta output:

```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.01 --presort delta-sorted --non-interactive
```

Run TPC-H with Iceberg output:

```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.01 --presort iceberg-sorted --non-interactive
```

## How Organization Is Applied

BenchBox preserves native TPC generation, then applies organization as a post-processing step:

1. Read generated TBL/DAT files.
2. Apply partition-aware sorting.
3. Optionally apply clustering (`z_order` or `hilbert`).
4. Write organized output in the requested table format.

If no tuning file provides explicit columns, default sorted keys are used:

- `tpch`: `lineitem.l_shipdate`
- `tpcds`: `store_sales.ss_sold_date_sk`

## Tuning Config Mapping

Unified tuning fields map to data organization as follows:

- `table_tunings.<table>.sorting` -> sort columns and order
- `table_tunings.<table>.partitioning` -> partition-aware sort prefix
- `table_tunings.<table>.clustering` -> cluster-by columns

## Notes

- Delta output requires `deltalake`.
- Iceberg output requires `pyiceberg`.
- When dependencies are missing, BenchBox reports a clear installation hint.
