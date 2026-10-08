# Understanding Benchmark Results

```{tags} beginner, tutorial, validation
```

Learn how to interpret BenchBox output and what the metrics mean.

## Result Overview

After running a benchmark, BenchBox produces:
- **Console summary** - Quick overview of timing and validation
- **JSON results** - Detailed metrics for each query
- **Manifest files** - Data generation metadata

## Viewing Results

```bash
benchbox results --limit 1

benchbox export --last --format json --output-dir ./results
```

## Key Metrics

### Power Test Timing

| Metric | Description |
|--------|-------------|
| `total_time` | End-to-end benchmark duration |
| `data_generation_time` | Time to generate TPC data |
| `load_time` | Time to load data into tables |
| `query_time` | Total query execution time |

### Per-Query Metrics

Each query result includes:

```json
{
  "query_id": "Q1",
  "execution_time_ms": 156.4,
  "rows_returned": 4,
  "status": "SUCCESS",
  "validation": {
    "expected_rows": 4,
    "actual_rows": 4,
    "status": "PASS"
  }
}
```

| Field | Meaning |
|-------|---------|
| `execution_time_ms` | Query runtime in milliseconds |
| `rows_returned` | Number of result rows |
| `status` | SUCCESS, FAILED, or TIMEOUT |
| `validation.status` | PASS if row count matches expected |

## Understanding Validation

BenchBox validates query correctness by comparing row counts:

| Status | Meaning | Action |
|--------|---------|--------|
| `PASS` | Row count matches expected | No action needed |
| `FAIL` | Row count differs from expected | Check query translation |
| `SKIP` | No expected value available | Normal for some queries |

## TPC Metrics

For TPC-H/TPC-DS, BenchBox calculates Power@Size and Throughput@Size:

```
Power@Size      = (SF × 3600) / geometric_mean(query times, final iteration)
Throughput@Size = (Q × SF × 3600) / T_throughput
```

Where:
- `SF` = Scale Factor (0.01, 0.1, 1, 10, etc.)
- `Q` = queries scored in the throughput test: 22 × streams for TPC-H, 99 × streams for TPC-DS
- `T_throughput` = wall-clock duration of the throughput test, from the first stream's first query to the last stream's last query (connection setup is excluded)

**Higher is better.** Compare these metrics only at the same scale factor.

BenchBox does not export the composite QphH@Size (TPC-H) or QphDS@Size (TPC-DS). It does not run the TPC-H refresh functions inside the power and throughput tests, and the TPC-DS composite needs the data maintenance and load times. A result with a failed query or a failed throughput phase carries no Throughput@Size.

### Price/Performance

Not calculated by BenchBox (requires cost data), but you can derive it:

```
Price/Performance = (Platform Cost) / Throughput@Size
```

## Comparing Results

```bash
benchbox run --platform duckdb --benchmark tpch --output duckdb.json
benchbox run --platform sqlite --benchmark tpch --output sqlite.json

benchbox compare duckdb.json sqlite.json
```

The comparison shows:
- Per-query timing differences
- Relative speedup/slowdown
- Validation status alignment

## Result File Locations

BenchBox stores results in:

```
benchmark_runs/
├── results/                    # JSON result files
│   ├── tpch_duckdb_sf0.01_*.json
│   └── tpch_sqlite_sf0.01_*.json
├── datagen/                    # Generated data
│   └── tpch_sf0.01/
│       ├── lineitem.csv
│       ├── orders.csv
│       └── ...
└── manifests/                  # Data generation metadata
    └── tpch_sf0.01_manifest.json
```

## Interpreting Slow Queries

If a query is unexpectedly slow:

1. **Check scale factor** - Larger data takes longer
2. **Review query plan** - Use platform's EXPLAIN
3. **Compare baselines** - Run on DuckDB for reference
4. **Check validation** - Ensure correct results

```bash
benchbox run --dry-run ./analysis --platform duckdb --benchmark tpch
```

This exports the query SQL to `./analysis/queries/`.

## Next Steps

- [Comparing Platforms](comparing-platforms.md) - Run on multiple databases
- [Result Export Documentation](../reference/result-formats.md) - Full JSON schema
- [Performance Guide](../performance/dataframe-optimization.md) - Optimization tips
