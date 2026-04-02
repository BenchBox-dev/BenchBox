(cli-datagen)=
# `datagen` - Data Generation

```{tags} reference, cli, data
```

Generate benchmark data files without running queries. This is a convenience wrapper for `benchbox run --phases generate`.

## Basic Syntax

```bash
benchbox datagen --benchmark <name> --scale <sf> [OPTIONS]
```

## Options

**Required:**
- `--benchmark TEXT`: Benchmark name (e.g., `tpch`, `tpcds`, `clickbench`)
- `--scale FLOAT`: Scale factor for data generation

**Optional:**
- `--output PATH`: Output directory for generated data
- `--format [parquet|csv|json]`: **Not yet implemented.** This option is accepted but has no effect. Data is generated as pipe-delimited `.tbl` flat files (compressed to `.tbl.zst` when compression is enabled, which is the default). To convert generated data to parquet or other formats, use `benchbox run` with `--table-format`.
- `--seed INT`: Random seed for reproducible data generation
- `--verbose, -v`: Enable verbose logging

## Usage Examples

```bash
# Generate TPC-H data at scale factor 0.1
benchbox datagen --benchmark tpch --scale 0.1 --output ./data/tpch_0.1

# Generate TPC-DS data with specific seed
benchbox datagen --benchmark tpcds --scale 1 --seed 42 --output ./data/tpcds_1

# Generate ClickBench data
benchbox datagen --benchmark clickbench --scale 1 --output ./data/clickbench

# Generate with verbose logging
benchbox datagen --benchmark tpch --scale 0.01 --output ./data --verbose
```

## Notes

- Internally invokes `benchbox run --phases generate` with a dummy platform. No database connection is needed.
- Generated data can be reused across multiple benchmark runs by pointing `--output` to a shared location, or by using `benchbox run --global-cache`.

## Related

- [run](run.md) - Run full benchmarks including data generation
