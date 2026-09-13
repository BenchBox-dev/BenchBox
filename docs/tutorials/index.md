# Tutorials

```{tags} beginner, tutorial
```

Step-by-step tutorials for common BenchBox tasks. Each tutorial takes 5-15 minutes.

## Getting Started

| Tutorial | Time | Description |
|----------|------|-------------|
| [Your First Benchmark](first-benchmark.md) | 5 min | Run TPC-H on DuckDB with zero configuration |
| [Understanding Results](understanding-results.md) | 10 min | Interpret benchmark output and metrics |
| [Comparing Platforms](comparing-platforms.md) | 10 min | Run the same benchmark on multiple databases |
| [DataFrame Benchmarking](dataframe-quickstart.md) | 10 min | Use Polars/Pandas instead of SQL |

## Prerequisites

- BenchBox installed (`pip install benchbox` or `uv add benchbox`)
- Python 3.11+
- No database servers required (DuckDB is embedded)

## Related Resources

- [CLI Quick Reference](../usage/cli-quick-start.md) - Command reference
- [Examples Directory](../usage/examples-directory.md) - Runnable Python scripts
- [Platform Guides](../platforms/index.md) - Platform-specific setup

```{toctree}
:maxdepth: 1

first-benchmark
understanding-results
comparing-platforms
dataframe-quickstart
```
