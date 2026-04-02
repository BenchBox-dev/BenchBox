# Databricks Liquid Clustering

BenchBox supports first-class Databricks clustering strategy control so you can run reproducible comparisons across:

- `liquid_clustering`
- `z_order`
- `none`

## Tuning Configuration

Use unified tuning `platform_optimizations`:

```yaml
platform_optimizations:
  databricks_clustering_strategy: liquid_clustering  # liquid_clustering | z_order | none
  liquid_clustering_enabled: true
  liquid_clustering_columns:
    - event_time
    - customer_id
```

The `z_ordering_enabled` configuration is also supported.

## Precedence Rules

BenchBox resolves Databricks strategy with explicit precedence:

1. `liquid_clustering_enabled` or non-empty `liquid_clustering_columns`
2. `databricks_clustering_strategy`
3. `z_ordering_enabled`

If both liquid clustering and Z-ORDER settings are supplied, liquid clustering wins.

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

## Switching from Z-ORDER to Liquid Clustering

- Keep existing Z-ORDER configs unchanged if you need strict historical comparability.
- Add `databricks_clustering_strategy: liquid_clustering` in a new config variant for A/B runs.
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
- `liquid_clustering_enabled`
- `liquid_clustering_columns_config`
- `liquid_clustering_operations`
- `z_order_operations`
