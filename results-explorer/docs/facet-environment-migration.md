# Facet Environment Contract Migration

This audit maps the explorer facet data path from the pre-refactor cost/deployment
columns to the normalized schema v2.1 execution-environment contract emitted by
`results-complete-execution-environment-capture`.

## Current Data Path

The current explorer UI does not read result JSON directly. The static pipeline
flattens result bundles into `bench.results`, and the Preact app filters those
DuckDB columns:

- `results-explorer/src/lib/facetModel.ts` builds `WHERE` clauses over
  `bench.results`.
- `results-explorer/src/lib/queryFilters.ts` exposes the same column contract to
  the Query page.
- `results-explorer/src/lib/duckdbQueries.ts` selects cost/deployment columns
  from `bench.results` and joins them into benchmark/platform rows.

The fallback layer is upstream of the UI today:

- `benchbox.core.explorer_pipeline.transformer._normalized_cost()` reads
  `normalized_cost` or emits explicit `cost_status="unavailable"` for old
  bundles.
- `benchbox.core.cost.integration._extract_platform_config_from_results()`
  derives cost deployment metadata from `platform_info` / `configuration`
  fields when normalized environment metadata was not available.
- `benchbox.core.cost.calculator._deployment_metadata()` serializes that config
  as `normalized_cost.deployment`, which becomes the browser columns
  `cloud_provider`, `cloud_region`, `instance_type`, `warehouse_size`,
  `node_count`, `cluster_size`, `storage_format`, and `storage_tier`.

W2-W4 should move the explorer-facing columns to normalized environment fields
and remove the cost/deployment fallback dependency from the facet path.

## Field Migration Table

| Facet key | Current source and quirks | Normalized contract target | Value-domain shifts and notes |
| --- | --- | --- | --- |
| `deployment_class` | Derived in `facetModel.ts`, `Home.tsx`, `BenchmarkIndex.tsx`, and `PlatformIndex.tsx`: `cloud` when `cloud_provider IS NOT NULL`, `local` when `cost_status = 'not_applicable_local'`, `unavailable` when `cost_status = 'unavailable'`. This conflates runtime/deployment identity with cost availability. | Prefer `environment.platform_runtime.runtime_type` plus `platform.deployment.deployment_type` / `platform.deployment.endpoint_class`. Suggested derived browser column: `deployment_class`, computed as `cloud` for `managed_cloud` or `serverless`, `local` for `local_process`, `dataframe_process`, `docker_container`, or localhost `self_hosted`, and `unavailable` for `unknown`/unavailable metadata. | Product labels remain `cloud`, `local`, and `unavailable` for URL and chip stability. Docker-backed localhost should now classify from runtime/deployment evidence, not cost status. Remote self-hosted servers need an explicit decision in W2: either keep them out of `local` or add a non-visible internal value that maps to existing labels. |
| `cloud_provider` | Browser column from `normalized_cost.deployment.cloud_provider`, originally derived from adapter/cost config keys such as `cloud`, `cloud_provider`, Snowflake account metadata, BigQuery project config, Redshift/Athena AWS config, and Databricks cloud hints. Values may be lower-case (`aws`, `gcp`) or adapter-native. | `platform.cloud.provider`. | Normalize to canonical explorer labels in the label layer, not the model layer. Accepted canonical values from the result contract are lower-case or provider-native strings; W4 should keep visible labels user-stable (`AWS`, `GCP`, `Azure`) while preserving URL values. |
| `cloud_region` | Browser column from `normalized_cost.deployment.cloud_region`, filled from cost pricing region or platform config aliases (`region`, `location`, `cloud_region`). Missing values may be `NULL`, while pricing fallback may report `"unknown"`. | `platform.cloud.region` with fallback to `platform.cloud.location` when region is absent. Preserve `platform.cloud.region_collection_status` for coverage diagnostics, not for facet filtering. | Region aliases collapse into a single facet value. BigQuery locations such as `US` or `us-central1` should remain as emitted. Missing/permission-denied metadata should be `NULL` or `unavailable`, not a guessed default region. |
| `instance_or_warehouse` | `facetModel.ts` filters `COALESCE(instance_type, warehouse_size, cluster_size)`. Query page exposes `instance_type` and `warehouse_size` separately. Source values come from `normalized_cost.deployment` and ultimately adapter/cost config fields (`node_type`, `instance_type`, `warehouse_size`, `dwu_level`, `cluster_size_dbu_per_hour`, `cluster_size`). | Prefer `platform.compute.node_type`, then `platform.compute.warehouse_size`, then `platform.compute.warehouse`, then `platform.compute.cluster_id` / `cluster_name`, then service-specific fields such as `rpu` or `serverless_slots` when present. Suggested browser column: keep `instance_or_warehouse` as the unified filter column; derive from normalized compute fields in pipeline SQL/Python. | Preserve existing URL key `shape` and aliases `instance_type`, `warehouse_size`. Case should be preserved for warehouse sizes (`XSMALL`, `Medium`) unless W4 adds display-only mapping. Do not keep `COALESCE(instance_type, warehouse_size, cluster_size)` in frontend SQL after W3. |
| `storage_format` | Browser column from `normalized_cost.deployment.storage_format`; source can be adapter config (`storage_format`, `table_format`, external table format) or absent. It currently represents both data table format and staging/storage hints depending on adapter. | `platform.storage.table_format`, with optional display fallback to `platform.storage.staging_url_type` only when table format is unavailable and the product explicitly wants staging as storage format. | Contract uses `table_format` as the canonical field. Values like `parquet`, `delta`, `iceberg`, `native`, and platform-native table formats should remain lower-case/display-normalized in W4. |
| `cost_status` | Browser column from `normalized_cost.cost_status` with values `normalized`, `not_applicable_local`, and `unavailable`. It is also used as a proxy for local/unavailable deployment in several components. | Keep sourcing from `normalized_cost.cost_status`; it is a cost contract, not an environment contract. Stop using it to infer deployment when `platform.deployment` and `environment.platform_runtime` are available. | No URL or label change for the Cost Status facet. W2/W4 should only remove `cost_status` from deployment classification helpers. |

## Serializer And URL Compatibility

The shipped URL contract must stay stable:

| Facet key | Current URL key | Aliases to preserve |
| --- | --- | --- |
| `deployment_class` | `deployment` | `deployment_class` |
| `cloud_provider` | `cloud_provider` | None |
| `cloud_region` | `cloud_region` | None |
| `instance_or_warehouse` | `shape` | `instance_type`, `warehouse_size` |
| `storage_format` | `storage_format` | None |
| `cost_status` | `cost_status` | None |

W2 can change SQL column names and browser read-model columns, but
`readFacetParam()` and `writeFacetParam()` must keep this URL behavior.

## Downstream Work Notes

- W2 should introduce browser columns derived from the normalized contract
  before deleting old fallback expressions.
- W3 should remove frontend `COALESCE` / cost-status deployment inference from
  `facetModel.ts`, `queryFilters.ts`, and `duckdbQueries.ts`.
- W4 should own casing and display labels. The model layer should compare
  canonical values only.
- W5-W7 should verify that every fixture result facets through normalized
  `environment.*` / `platform.*` fields without falling back to
  `normalized_cost.deployment` for deployment, cloud, compute, or storage facets.
