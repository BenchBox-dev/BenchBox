# Your First Benchmark

```{tags} beginner, tutorial, tpc-h, duckdb
```

Run a complete TPC-H benchmark in under 5 minutes with zero configuration.

## What You'll Do

1. Install BenchBox
2. Run a TPC-H power test on DuckDB
3. View your results

## Step 1: Install BenchBox

Use uv (recommended) or pip:

```bash
uv add benchbox

pip install benchbox
```

## Step 2: Run the Benchmark

```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.01
```

This command:
- Generates TPC-H data at scale factor 0.01 (~10MB)
- Loads data into DuckDB (stored in a database file inside the run output directory)
- Executes all 22 TPC-H queries
- Reports timing and validation results

**Example output (your numbers will differ):**
```
Running TPC-H Power Test (Scale Factor: 0.01, Stream ID: 0)
Warm-up runs: 1, Measurement runs: 3
...
✅ TPC-H Power Test completed
  Queries executed: 22, Successful: 22
...
✅ Benchmark completed: PASSED
...
┌ TPC-H on DuckDB (SF 0.01) ────────┐
│ Queries:  22                       │
│ Best: Q6, Q11, Q17                 │
│ Worst: Q10, Q8, Q21                │
└────────────────────────────────────┘
```

## Step 3: View Results

The first command shows recent results. The second exports the last result to JSON for analysis.

```bash
benchbox results --limit 1

benchbox export --last --format json
```

## What Just Happened?

1. **Data Generation**: BenchBox used TPC-H's data generator to create realistic business data (customers, orders, line items)

2. **Schema Loading**: Tables were created in DuckDB and data was loaded

3. **Query Execution**: All 22 TPC-H queries ran sequentially (power test)

4. **Validation**: Results were compared against expected row counts

## Try Different Options

The first command uses a larger dataset, which takes longer and is more realistic. The second runs specific queries
only. The third previews without running (dry run).

```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.1

benchbox run --platform duckdb --benchmark tpch --queries Q1,Q6,Q17

benchbox run --dry-run ./preview --platform duckdb --benchmark tpch
```

## Next Steps

- [Understanding Results](understanding-results.md) - Learn what the metrics mean
- [Comparing Platforms](comparing-platforms.md) - Run on multiple databases
- [DataFrame Benchmarking](dataframe-quickstart.md) - Use Polars/Pandas APIs
