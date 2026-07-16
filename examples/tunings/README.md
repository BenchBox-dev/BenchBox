# Tuning Configuration Examples

This directory contains example tuning configuration YAML files consumed by
`benchbox run --tuning`. They demonstrate a "tuned" configuration (constraints,
partitioning/sorting, platform-specific optimizations) against a baseline
"notuning" configuration for the same platform/benchmark pair.

## File layout

SQL platforms follow `examples/tunings/<platform>/<benchmark>_tuned.yaml` (and
a matching `<benchmark>_notuning.yaml`):

- `duckdb/` - `tpch`, `tpcds`, `clickbench`, `ssb`, `amplab`, `h2odb`,
  `read_primitives`, `joinorder`, `tpchavoc`
- `databricks/` - `tpch`, `tpcds`, `ssb`, `read_primitives`, `tpchavoc`, plus
  `tpch_liquid_tuned.yaml` / `tpcds_liquid_tuned.yaml` (Liquid Clustering AUTO
  variants of the same logical profile, alongside the legacy Z-ORDER
  `tpch_tuned.yaml` / `tpcds_tuned.yaml`)

DataFrame platforms live under `dataframe/` with a flat
`<platform>_<profile>.yaml` naming (e.g. `polars_optimized.yaml`,
`dask_memory_constrained.yaml`, `cudf_default.yaml`). These are **not**
auto-discovered (see below) - pass the path to `--tuning` explicitly.

## Using with the CLI

The `benchbox run` flag is `--tuning` (there is no `--tuning-config` flag).
It accepts one of the keywords `tuned`, `notuning`, `auto`, or an explicit
path to a YAML file; it defaults to `notuning` when omitted.

```bash
# Auto-discover the platform/benchmark tuned template (the primary UX)
benchbox run --platform duckdb --benchmark tpch --tuning tuned

# Explicit baseline (no tuning)
benchbox run --platform duckdb --benchmark tpch --tuning notuning

# Point directly at a file
benchbox run --platform duckdb --benchmark tpch \
  --tuning examples/tunings/duckdb/tpch_tuned.yaml

# DataFrame platform - these files must be referenced explicitly
benchbox run --platform polars --benchmark tpch --mode dataframe \
  --tuning examples/tunings/dataframe/polars_optimized.yaml
```

`examples/unified_runner.py` is a lighter-weight alternative to the `benchbox`
CLI for scripting/automation; it accepts the same `--tuning` values but
**defaults to `tuned`** (the main CLI defaults to `notuning`):

```bash
python examples/unified_runner.py --platform duckdb --benchmark tpch --scale 0.1 --tuning notuning
```

See `examples/features/tuning_comparison.py` for a runnable walkthrough of
comparing baseline vs. tuned performance.

## Auto-discovery (`--tuning tuned`)

`--tuning tuned` is the primary day-to-day UX: you don't reference a path,
BenchBox finds the matching template for you. The full resolution order
(covering every `--tuning` value, not just `tuned`) is documented in
[docs/reference/cli/tuning.md](../../docs/reference/cli/tuning.md); the part
relevant to these templates is:

1. `benchbox.yaml`'s `tuning.default_config_file` (overridable with the
   `BENCHBOX_TUNING_CONFIG` environment variable), if set and the file exists.
2. `$BENCHBOX_TUNING_PATH/<platform>/<benchmark>_tuned.yaml`, if
   `BENCHBOX_TUNING_PATH` is set.
3. `examples/tunings/<platform>/<benchmark>_tuned.yaml`, resolved relative to
   the current working directory.
4. `<platform>/<benchmark>_tuned.yaml`, also resolved relative to cwd.
5. If none of the above exist, the run falls back to a basic, untuned
   configuration and prints a warning (an interactive terminal is also
   offered the tuning wizard).

Step 3 is **cwd-relative**, so `--tuning tuned` only auto-discovers the
templates in this directory when `benchbox` is run from a checkout of this
repository (or another directory that contains its own `examples/tunings/`).
If BenchBox is installed as a package and run elsewhere, set
`BENCHBOX_TUNING_PATH` to a directory with the same
`<platform>/<benchmark>_tuned.yaml` layout - see the next section.

## Custom tuning directory - `BENCHBOX_TUNING_PATH`

Point `--tuning tuned` at a different template collection without relying on
the working directory:

```bash
# Directory must use the same <platform>/<benchmark>_tuned.yaml layout
export BENCHBOX_TUNING_PATH=/path/to/my-tunings
benchbox run --platform duckdb --benchmark tpch --tuning tuned
```

## Default file via `benchbox.yaml` / `BENCHBOX_TUNING_CONFIG`

Set a default file that `--tuning tuned` uses before falling back to
auto-discovery:

```yaml
# benchbox.yaml
tuning:
  default_config_file: ./tuning/my_tuning.yaml
```

or override it at runtime without editing the file:

```bash
export BENCHBOX_TUNING_CONFIG=./tuning/my_tuning.yaml
benchbox run --platform duckdb --benchmark tpch --tuning tuned
```

## Inspecting templates

```bash
# List everything available under examples/tunings/
benchbox tuning list

# Filter by platform and/or benchmark
benchbox tuning list --platform duckdb --benchmark tpch

# Show what --tuning would actually resolve to (including which file, if any)
benchbox tuning show tuned --platform duckdb --benchmark tpch
```

## Configuration structure

All tuning configurations follow the unified tuning format with these
sections:

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
Databricks keeps the existing `*_tuned.yaml` files as legacy Z-ORDER renderings
and adds `*_liquid_tuned.yaml` files for Liquid Clustering AUTO. DuckDB uses
partitioning plus sorting and sorted layout semantics. The physical mechanisms
are different, so `tuning_mode == "tuned"` means "same logical profile coverage
where mapped", not "identical storage features".

Databricks Liquid templates set `physical_rendering_id:
databricks_liquid_auto`, keep ZORDER disabled, and avoid per-table partitioning
or distribution fields. The listed table columns are logical workload intent;
with `CLUSTER BY AUTO`, Databricks chooses effective Liquid keys asynchronously.

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
- Enable platform-specific features (Databricks: Z-ordering/Liquid Clustering, auto-optimize, bloom filters)

### No-Tuning Configurations
- Disable all constraints for fastest data loading
- No table-level optimizations
- No platform-specific features enabled
- Provide baseline performance for comparison

Actual performance impact varies by platform, benchmark, and data volume; run
both configurations yourself with `benchbox run --tuning tuned` /
`--tuning notuning` and compare results rather than relying on a fixed
multiplier.

## Best Practices

1. **Development and Testing**: Use `--tuning notuning` for fast iteration
2. **Performance Evaluation**: Use `--tuning tuned` for realistic production performance
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

For the full `--tuning` precedence order and the `tuning` command group
(`init`, `validate`, `defaults`, `list`, `show`, `platforms`), see
[docs/reference/cli/tuning.md](../../docs/reference/cli/tuning.md).
