# Tuning Commands

```{tags} reference, cli, tuning
```

Commands for creating and managing tuning configurations for SQL and DataFrame platforms.

(cli-tuning-resolution)=
## How `--tuning` is resolved

`benchbox run --tuning VALUE` accepts the keywords `notuning`, `tuned`, `auto`,
or an explicit path to a YAML file. If `--tuning` is omitted it **defaults to
`notuning`** (baseline, all optimizations disabled).

Resolution happens in this order (see `benchbox/cli/tuning_resolver.py:resolve_tuning`):

0. **Default**: no `--tuning` given -> `notuning`.
1. **Keyword check, before any file lookup**: if the value is exactly
   `notuning`, `auto`, or `tuned` (case-insensitive), it is resolved as that
   keyword immediately - a local file or directory that happens to be named
   `tuned` or `auto` can never shadow the keyword's meaning.
   - `notuning` -> baseline: all constraints disabled.
   - `auto` -> smart-defaults mode (see the DataFrame-only caveat below).
2. **`tuned` keyword resolution** (`_resolve_tuned`):
   1. If `benchbox.yaml`'s `tuning.default_config_file` is set (overridable
      with the `BENCHBOX_TUNING_CONFIG` environment variable) and that file
      exists, it is used - this beats template auto-discovery.
   2. Otherwise, auto-discovery searches, in order:
      1. `$BENCHBOX_TUNING_PATH/<platform>/<benchmark>_tuned.yaml`, if
         `BENCHBOX_TUNING_PATH` is set.
      2. `examples/tunings/<platform>/<benchmark>_tuned.yaml`, resolved
         relative to the **current working directory**.
      3. `<platform>/<benchmark>_tuned.yaml`, also cwd-relative.
   3. If none of those exist, tuning falls back to a basic, untuned
      configuration and prints a warning; in an interactive terminal the user
      is also offered the tuning wizard.
3. **Explicit file path**: if the value is not one of the three keywords, it
   is checked as a path; if it exists, that file is loaded directly.
4. **Invalid value**: if it's not a keyword and the path doesn't exist,
   `benchbox run` raises an error (with a hint to run `benchbox tuning list`).

```{note}
Step 2.2 is **cwd-relative**. `--tuning tuned` only auto-discovers the
templates bundled in `examples/tunings/` when `benchbox` is run from a
checkout of this repository (or another directory with its own
`examples/tunings/`). If BenchBox is installed as a package and run from
elsewhere, auto-discovery falls through to the basic-config fallback unless
`BENCHBOX_TUNING_PATH` is set to a directory with the same
`<platform>/<benchmark>_tuned.yaml` layout.
```

```{warning}
`--tuning auto` prints a "smart defaults" message, but real system-profile
smart defaults (`benchbox/cli/tuning_runtime.py:resolve_dataframe_tuning_config`)
are implemented for **DataFrame platforms only** today. On SQL platforms,
`--tuning auto` proceeds with a basic, untuned configuration and
`benchbox run` prints an explicit warning saying so.
```

`BENCHBOX_TUNING_CONFIG` and `BENCHBOX_TUNING_PATH` are the only tuning-related
environment variables that affect resolution; see
[Configuration - Environment Variables](configuration.md#cli-env-vars).

(cli-tuning-init)=
## `tuning init` - Create Tuning Configuration

Generate sample unified tuning configurations for specific platforms.

### Options

- `--platform TEXT`: Target platform (required) - duckdb, databricks, snowflake, etc.
- `--output TEXT`: Output file path. Default depends on mode:
  - SQL mode: `<platform>_tuning.yaml` (e.g. `duckdb_tuning.yaml`)
  - DataFrame mode: `<platform>_<profile>_tuning.yaml` (e.g. `polars_optimized_tuning.yaml`)

### Usage Examples

```bash
# Create sample tuning for Databricks (writes databricks_tuning.yaml)
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

(cli-tuning-list)=
## `tuning list` - List Available Templates

List the tuning templates found under `examples/tunings/` (cwd-relative,
same as `--tuning tuned` auto-discovery step 2.2 above), optionally filtered
by platform and/or benchmark. Unlike `--tuning tuned`, `tuning list` does
**not** consult `BENCHBOX_TUNING_PATH`.

```bash
benchbox tuning list
benchbox tuning list --platform duckdb
benchbox tuning list --platform duckdb --benchmark tpch
benchbox tuning list --benchmark tpcds
```

### Options

- `--platform TEXT`: Filter to a specific platform (e.g. `duckdb`, `snowflake`)
- `--benchmark TEXT`: Filter to a specific benchmark (e.g. `tpch`, `tpcds`)

(cli-tuning-show)=
## `tuning show` - Show Resolved Tuning Configuration

Show what a given `--tuning` value would actually resolve to for a
platform/benchmark - useful for checking which file (if any) `--tuning tuned`
or `--tuning auto` would pick up before running a full benchmark.

```bash
benchbox tuning show tuned --platform duckdb --benchmark tpch
benchbox tuning show ./my-tuning.yaml
benchbox tuning show auto --platform polars
benchbox tuning show notuning
```

### Arguments and Options

- `TUNING_ARG` (positional, default: `tuned`): `tuned`, `notuning`, `auto`, or a file path
- `--platform TEXT`: Target platform, used for template discovery
- `--benchmark TEXT`: Target benchmark, used for template discovery

(cli-tuning-platforms)=
## `tuning platforms` - List Platform Tuning Capabilities

Show which SQL and DataFrame platforms support tuning and a summary of their
key tuning options; does not take any options.

```bash
benchbox tuning platforms
```

## Related

- [Run Command](run.md) - Using `--tuning` option during benchmark execution
- [DataFrame Platforms](../../platforms/dataframe.md) - DataFrame platform documentation
