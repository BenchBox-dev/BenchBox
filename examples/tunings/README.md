# Tuning Configuration Guide

This directory contains pre-built tuning configuration files for all benchmark examples in BenchBox. These configurations demonstrate performance comparison between optimized and baseline configurations.

## Available Configurations

### DuckDB Configurations

#### TPC-H Benchmark
- `duckdb_tpch_tuned.yaml` - Maximum performance with all DuckDB-supported optimizations
- `duckdb_tpch_notuning.yaml` - Baseline performance with all optimizations disabled

#### TPC-DS Benchmark
- `duckdb_tpcds_tuned.yaml` - Maximum performance with partitioning on date columns and sorting
- `duckdb_tpcds_notuning.yaml` - Baseline performance for comparison

#### ClickBench Benchmark
- `duckdb_clickbench_tuned.yaml` - Optimized for web analytics workloads with date partitioning
- `duckdb_clickbench_notuning.yaml` - Unoptimized baseline

#### Star Schema Benchmark (SSB)
- `duckdb_ssb_tuned.yaml` - Star schema optimizations with fact table partitioning
- `duckdb_ssb_notuning.yaml` - Baseline configuration

#### AMPLab Big Data Benchmark
- `duckdb_amplab_tuned.yaml` - Optimized for big data queries with sorting on key columns
- `duckdb_amplab_notuning.yaml` - Baseline configuration

#### H2O.ai Database Benchmark
- `duckdb_h2odb_tuned.yaml` - Optimized for data science workloads
- `duckdb_h2odb_notuning.yaml` - Baseline configuration

#### Read Primitives Benchmark
- `duckdb_primitives_tuned.yaml` - Basic OLAP optimizations using TPC-H schema
- `duckdb_primitives_notuning.yaml` - Baseline configuration

#### Write Primitives Benchmark
- `duckdb_primitives_tuned.yaml` - Basic OLAP optimizations using TPC-H schema
- `duckdb_primitives_notuning.yaml` - Baseline configuration

#### Join Order Benchmark
- `duckdb_joinorder_tuned.yaml` - Optimized for complex join queries
- `duckdb_joinorder_notuning.yaml` - Baseline configuration

#### TPC-Havoc Benchmark
- `duckdb_tpchavoc_tuned.yaml` - Optimized for query optimizer stress testing
- `duckdb_tpchavoc_notuning.yaml` - Baseline configuration

### Databricks Configurations

#### TPC-H Benchmark
- `databricks_tpch_tuned.yaml` - Delta Lake optimizations with Z-ordering, auto-optimize, and bloom filters
- `databricks_tpch_notuning.yaml` - Baseline performance

#### TPC-DS Benchmark
- `databricks_tpcds_tuned.yaml` - Full Delta Lake optimizations for large-scale analytics
- `databricks_tpcds_notuning.yaml` - Baseline configuration

#### TPC-Havoc Benchmark
- `databricks_tpchavoc_tuned.yaml` - Delta Lake optimizations for optimizer stress testing
- `databricks_tpchavoc_notuning.yaml` - Baseline configuration

#### Star Schema Benchmark (SSB)
- `databricks_ssb_tuned.yaml` - Delta Lake star schema optimizations
- `databricks_ssb_notuning.yaml` - Baseline configuration

#### Primitives Benchmark
- `databricks_primitives_tuned.yaml` - Delta Lake basic OLAP optimizations
- `databricks_primitives_notuning.yaml` - Baseline configuration

## Usage

### Using with Example Scripts

All example scripts support loading tuning configurations via the `--tuning-config` parameter:

```bash
# Run with tuned configuration
python examples/duckdb_tpch.py --scale 0.01 --tuning-config examples/duckdb_tpch_tuned.yaml

# Run with no-tuning baseline
python examples/duckdb_tpch.py --scale 0.01 --tuning-config examples/duckdb_tpch_notuning.yaml

# Compare performance between configurations
python examples/duckdb_tpch.py --scale 0.01 --tuning-config examples/duckdb_tpch_tuned.yaml --save-results tuned_results.json
python examples/duckdb_tpch.py --scale 0.01 --tuning-config examples/duckdb_tpch_notuning.yaml --save-results baseline_results.json
```

### Using with CLI

The BenchBox CLI also supports tuning configurations:

```bash
# Run benchmark with tuning configuration
benchbox run --platform duckdb --benchmark tpch --scale 0.01 --tuning-config examples/duckdb_tpch_tuned.yaml

# Compare different configurations
benchbox run --platform duckdb --benchmark tpch --scale 0.01 --tuning-config examples/duckdb_tpch_notuning.yaml
```

### Environment Variable

You can also set a default tuning configuration using an environment variable:

```bash
export BENCHBOX_TUNING_CONFIG=examples/duckdb_tpch_tuned.yaml
python examples/duckdb_tpch.py --scale 0.01
```

## Configuration Structure

All tuning configurations follow the unified tuning format with these sections:

### Constraint Configuration
- `primary_keys` - Primary key constraint settings
- `foreign_keys` - Foreign key constraint settings
- `unique_constraints` - Unique constraint settings
- `check_constraints` - Check constraint settings

### Platform Optimizations
- `platform_optimizations` - Platform-specific features (Z-ordering, auto-optimize, bloom filters, etc.)

### Table-Level Tunings
- `table_tunings` - Per-table optimizations (partitioning, clustering, distribution, sorting)

### Metadata
- `_metadata` - Configuration metadata including database, benchmark, and type information

## TPC Logical Tuning Profile

TPC-H and TPC-DS tuned templates consume a shared logical profile in
`benchbox/core/tuning/profiles/tpc.yaml`. The profile records workload-level
candidate columns, query evidence, accepted baseline columns, and
low-evidence candidates that must stay excluded unless new evidence changes the
decision.

Platform templates map that logical profile into platform-native mechanisms:
Databricks uses partitioning plus clustering/distribution consumed by Delta
Z-ORDER or liquid clustering paths; DuckDB uses partitioning plus sorting and
sorted layout semantics. The physical mechanisms are different, so
`tuning_mode == "tuned"` means "same logical profile coverage where mapped",
not "identical storage features".

Run the checked-template profile gate with:

```bash
uv run -- python _project/scripts/tuning_profile_check.py --benchmarks tpch,tpcds --platforms databricks,duckdb --strict
```

See `docs/usage/tpc-tuning-profiles.md` for the profile schema, current
Databricks/DuckDB mapping matrix, result metadata fields, and comparison
caveats. Do not treat a benchmark-specific tuned template and a
basic-constraints fallback as equivalent tuned runs.

## Tuned vs No-Tuning Configurations

### Tuned Configurations
- Enable all appropriate constraints (primary keys, foreign keys, unique constraints, check constraints)
- Include table-level optimizations (partitioning on date columns, sorting on key columns)
- Enable platform-specific features (Databricks: Z-ordering, auto-optimize, bloom filters)
- Optimized for maximum query performance

### No-Tuning Configurations
- Disable all constraints for fastest data loading
- No table-level optimizations
- No platform-specific features enabled
- Provide baseline performance for comparison

## Performance Impact

Tuned configurations typically provide:
- **Query Performance**: 2-10x faster query execution for analytical workloads
- **Data Loading**: Slower initial loading due to constraint validation and optimization
- **Storage**: More efficient storage with partitioning and compression
- **Maintenance**: Better long-term performance with auto-optimization features

No-tuning configurations provide:
- **Data Loading**: Fastest possible data loading with no overhead
- **Query Performance**: Baseline performance without optimizations
- **Consistency**: Predictable performance for benchmarking baseline
- **Simplicity**: No complex optimization dependencies

## Best Practices

1. **Development and Testing**: Use no-tuning configurations for fast iteration
2. **Performance Evaluation**: Use tuned configurations for realistic production performance
3. **Benchmarking**: Compare both configurations to understand optimization impact
4. **Production**: Adapt tuned configurations to your specific workload requirements

## Customization

You can customize any configuration file by:

1. Copying an existing configuration
2. Modifying the tuning parameters for your workload
3. Validating the configuration with your benchmark
4. Saving the custom configuration for reuse

Example customization:
```yaml
# Custom TPC-H configuration with specific partitioning
table_tunings:
  LINEITEM:
    table_name: LINEITEM
    partitioning:
    - name: L_SHIPDATE
      type: DATE
      order: 1
    # Add custom sorting
    sorting:
    - name: L_ORDERKEY
      type: INTEGER
      order: 1
    - name: L_PARTKEY
      type: INTEGER
      order: 2
```

For more information about the unified tuning system, see the main BenchBox documentation.
