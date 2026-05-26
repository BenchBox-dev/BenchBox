# Databricks Liquid Clustering

BenchBox supports first-class Databricks clustering strategy control so you can run reproducible comparisons across:

- `liquid_clustering`
- `liquid_clustering_auto`
- `z_order`
- `none`

## Tuning Configuration

Use unified tuning `platform_optimizations`:

```yaml
platform_optimizations:
  databricks_clustering_strategy: liquid_clustering  # liquid_clustering | liquid_clustering_auto | z_order | none
  liquid_clustering_enabled: true
  liquid_clustering_columns:
    - event_time
    - customer_id
```

The `z_ordering_enabled` configuration is also supported.

## Precedence Rules

BenchBox resolves Databricks strategy with explicit precedence:

1. `databricks_clustering_strategy`
2. `liquid_clustering_enabled` or non-empty `liquid_clustering_columns`
3. `z_ordering_enabled`

If both Liquid Clustering and Z-ORDER settings are supplied, BenchBox raises a validation error instead of silently choosing one.

## CLI Overrides

You can override the strategy at runtime via `--platform-option`.

```bash
benchbox run \
  --platform databricks \
  --benchmark tpch \
  --scale 1 \
  --tuning ./databricks-tuning.yaml \
  --platform-option databricks_clustering_strategy=liquid_clustering \
  --platform-option liquid_clustering_columns=event_time,customer_id
```

Use `liquid_clustering_auto` for Databricks automatic Liquid Clustering, where Databricks chooses keys from workload history:

```bash
benchbox run \
  --platform databricks \
  --benchmark tpch \
  --scale 1 \
  --tuning examples/tunings/databricks/tpch_liquid_tuned.yaml \
  --platform-option databricks_clustering_strategy=liquid_clustering_auto
```

## Switching from Z-ORDER to Liquid Clustering

- Keep existing Z-ORDER configs unchanged if you need strict historical comparability.
- Add `databricks_clustering_strategy: liquid_clustering` in a new config variant for A/B runs.
- Add `databricks_clustering_strategy: liquid_clustering_auto` when you want Databricks to select keys automatically.
- Pin explicit `liquid_clustering_columns` to avoid accidental drift between runs.

## A/B Comparison With Z-ORDER

1. Z-ORDER run:

```bash
benchbox run --platform databricks --benchmark tpch --scale 1 --tuning ./databricks-zorder.yaml
```

2. Liquid clustering run:

```bash
benchbox run --platform databricks --benchmark tpch --scale 1 --tuning ./databricks-liquid.yaml
```

3. Compare outputs:

```bash
benchbox compare <zorder.json> <liquid.json>
```

## Result Metadata

Databricks platform metadata includes:

- `databricks_clustering_strategy`
- `requested_databricks_clustering_strategy`
- `resolved_databricks_clustering_strategy`
- `applied_layout_operations`
- `skipped_layout_operations`
