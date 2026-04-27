<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Flight Data Benchmark

```{tags} intermediate, concept, flightdata, real-world-benchmark
```

> **CLI name:** `flightdata` - use `benchbox run --benchmark flightdata`

The Flight Data benchmark uses US Bureau of Transportation Statistics (BTS)
On-Time Performance data to exercise real-world aviation analytics - delays,
routes, carriers, and temporal patterns - across 20 OLAP queries.

## Overview

| Property            | Value                                             |
| ------------------- | ------------------------------------------------- |
| **Total Queries**   | 20                                                |
| **Categories**      | 5 (on-time, delay, routes, temporal, carriers)    |
| **Data Source**     | BTS TranStats (downloader included)               |
| **Schema**          | Flight records with carrier, airport, and delay fields |
| **Scale**           | SF=0.01 (1 month sample) → SF≥10 (full corpus)   |

## Query Categories

| Category  | Queries | Focus                                              |
| --------- | ------: | -------------------------------------------------- |
| ontime    |       5 | On-time performance rates and trends              |
| delay     |       4 | Delay causes and attribution                       |
| routes    |       4 | Route performance and connectivity                 |
| temporal  |       4 | Day-of-week, month, and hour-of-day patterns      |
| carriers  |       3 | Carrier comparison and ranking                     |

## Scale Factors

| Scale | Approx. Flights | Approx. Size | Notes                                |
| ----: | --------------: | -----------: | ------------------------------------ |
|  0.01 |          ~600 K |        ~10 MB | 1-month BTS / dev sample             |
|   0.1 |          ~2.4 M |       ~100 MB | ~4 months of BTS data                |
|   1.0 |          ~24 M  |        ~1 GB  | ~41 months (~3.4 years)              |
| ≥10.0 |          Full   |       ~10 GB+ | Approaches full historical corpus    |

## Usage

```bash
# Default scale (SF=1.0, ~24M flights, ~1 GB)
benchbox run --platform duckdb --benchmark flightdata --scale 1.0

# Quick dev sample
benchbox run --platform duckdb --benchmark flightdata --scale 0.01

# Pin the most recent year included (default is LAST_AVAILABLE_YEAR)
benchbox run --platform duckdb --benchmark flightdata --scale 1.0 \
  --benchmark-option end_year=2024

# Reproducible runs via seed
benchbox run --platform duckdb --benchmark flightdata --scale 1.0 \
  --benchmark-option seed=42
```

## Benchmark Options

| Option             | Default                | Description                                 |
| ------------------ | ---------------------- | ------------------------------------------- |
| `end_year`         | `LAST_AVAILABLE_YEAR`  | Most recent year to include (works back)    |
| `seed`             | `None`                 | Random seed for reproducibility             |
| `force_regenerate` | `False`                | Force data regeneration                     |

## Data Generation

BenchBox downloads BTS On-Time Performance extracts via the bundled downloader.
The initial pull can be large for SF ≥ 1 - use the `generate` phase in isolation
to pre-stage data:

```bash
benchbox datagen --benchmark flightdata --scale 1.0
```

## Platform Support

Any SQL platform supported by BenchBox can run Flight Data. It is a useful
real-world complement to TPC-H and NYC Taxi for temporal / categorical workloads
and is supported on DataFrame platforms (Polars, Pandas, etc.) via the bundled
DataFrame query definitions.

## See Also

- [NYC Taxi](nyctaxi.md) - companion real-world benchmark with geospatial focus
- [TSBS DevOps](tsbs-devops.md) - time-series workload alternative
- [BTS TranStats](https://www.transtats.bts.gov/ontime/) - upstream data source
