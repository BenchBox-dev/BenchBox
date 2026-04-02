# Tuning Commands

```{tags} reference, cli, tuning
```

Commands for creating and managing tuning configurations for SQL and DataFrame platforms.

(cli-tuning-init)=
## `tuning init` - Create Tuning Configuration

Generate sample unified tuning configurations for specific platforms.

### Options

- `--platform TEXT`: Target platform (required) - duckdb, databricks, snowflake, etc.
- `--output TEXT`: Output file path (default: tuning_config.yaml)

### Usage Examples

```bash
# Create sample tuning for Databricks
benchbox tuning init --platform databricks

# Create with custom output path
benchbox tuning init --platform snowflake \
  --output ./configs/snowflake-tuning.yaml
```

(cli-tuning-dataframe)=
## DataFrame Tuning via `tuning` Commands

The unified `tuning` command group handles both SQL and DataFrame platforms.
Use `--mode dataframe` (or let it auto-detect from the platform name).

### Create DataFrame Tuning Configuration

```bash
# Create sample Polars tuning config (auto-detects DataFrame mode)
benchbox tuning init --platform polars

# Create with smart defaults based on your system
benchbox tuning init --platform polars --smart-defaults

# Explicit DataFrame mode with profile
benchbox tuning init --platform pandas --mode dataframe --profile memory-constrained

# Custom output path
benchbox tuning init --platform dask --output ./configs/dask_tuning.yaml
```

**Options for DataFrame mode:**

- `--platform TEXT`: Target platform (`polars`, `pandas`, `dask`, `modin`, `cudf`)
- `--mode [sql|dataframe|auto]`: Tuning mode (default: auto)
- `--profile [default|optimized|streaming|memory-constrained|gpu]`: Configuration profile
- `--output TEXT`: Output file path
- `--smart-defaults`: Use auto-detected system-optimal settings

### Validate Configuration

```bash
benchbox tuning validate polars_tuning.yaml --platform polars
```

### Show Smart Defaults

```bash
benchbox tuning defaults --platform polars
```

## Configuration Categories

DataFrame tuning supports these configuration sections:

| Category | Settings | Description |
|----------|----------|-------------|
| `parallelism` | `thread_count`, `worker_count`, `threads_per_worker` | CPU resource allocation |
| `memory` | `memory_limit`, `chunk_size`, `spill_to_disk`, `rechunk_after_filter` | Memory management |
| `execution` | `streaming_mode`, `lazy_evaluation`, `engine_affinity` | Execution behavior |
| `data_types` | `dtype_backend`, `enable_string_cache`, `auto_categorize_strings` | Type handling |
| `io` | `memory_pool`, `memory_map`, `pre_buffer`, `row_group_size` | I/O optimization |
| `gpu` | `enabled`, `device_id`, `spill_to_host`, `pool_type` | GPU settings (cuDF) |
| `write` | `sort_by`, `partition_by`, `row_group_size`, `target_file_size_mb`, `repartition_count`, `compression`, `compression_level`, `dictionary_columns`, `skip_dictionary_columns`, `data_page_version` | Write-time physical layout and Parquet encoding |

For complete configuration reference, see [DataFrame Platforms - Tuning](../../platforms/dataframe.md#dataframe-tuning).

## Related

- [Run Command](run.md) - Using `--tuning` option during benchmark execution
- [DataFrame Platforms](../../platforms/dataframe.md) - DataFrame platform documentation
