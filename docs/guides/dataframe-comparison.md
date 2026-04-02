<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# DataFrame Cross-Platform Comparison

```{tags} intermediate, guide, dataframe-platform
```

## Comparing DataFrame Platforms

Use the unified `benchbox compare` command to compare results across DataFrame platforms:

```bash
# Run benchmarks for each platform
benchbox run --platform polars-df --benchmark tpch --scale 0.01 --output polars.json
benchbox run --platform pandas-df --benchmark tpch --scale 0.01 --output pandas.json

# Compare results
benchbox compare polars.json pandas.json
```

### SQL vs DataFrame Comparison

```bash
# Run SQL benchmark
benchbox run --platform duckdb --benchmark tpch --scale 0.01 --output duckdb.json

# Run DataFrame benchmark
benchbox run --platform polars-df --benchmark tpch --scale 0.01 --output polars.json

# Compare
benchbox compare duckdb.json polars.json
```

### Visualization

Generate charts from comparison results:

```bash
benchbox visualize polars.json pandas.json --chart-type performance_bar
```

## Platform Categories

| Category | Platforms | Use Case |
|----------|-----------|----------|
| **Single Node** | Polars, Pandas, DataFusion | In-memory analysis, medium datasets |
| **Distributed** | PySpark, Dask, Modin, LakeSail | Large datasets, cluster computing |
| **GPU Accelerated** | cuDF | CUDA-enabled GPU acceleration |

## Best Practices

1. **Start small**: Use `--scale 0.01` to verify before scaling up
2. **Same machine**: Run all platforms on the same hardware for fair comparison
3. **Multiple iterations**: Use power run iterations for statistical confidence
4. **Match your workload**: Test at scale factors representative of production data

## Related Documentation

- [DataFrame Quickstart](../tutorials/dataframe-quickstart.md) - Getting started with DataFrame benchmarking
- [DataFrame Benchmarking Guide](dataframe-migration.md) - Adopting DataFrame benchmarking
- [Visualization Guide](../visualization/chart-generation-guide.md) - Chart customization
