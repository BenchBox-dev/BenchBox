# MCP platform-option contract

This matrix is the review boundary for `platform_options` on the MCP run and
durable-job surfaces. The value specs and the matrix in
`benchbox/mcp/schemas.py` must have identical platform and option keys. A
request is rejected when either record is missing, before an adapter is built
or a durable job is persisted.

The matrix is intentionally narrower than the CLI option registry. `consumer`
identifies the code path that must consume the normalized value; it is not
permission to expose the underlying adapter's full configuration surface.

| Platform | Option(s) | Consumer | Security class | Compatibility alias / rejected alternatives |
|---|---|---|---|---|
| ClickHouse | `deployment_mode` | `ClickHouseAdapter.from_config` | execution | Connection destinations and transport policy remain server-owned. |
| ClickHouse | `connection_profile` | `ClickHouseAdapter.from_config(port, secure)` resolved from `BENCHBOX_MCP_CLICKHOUSE_PROFILES` | connection | Reject caller-supplied `port`/`secure`, arbitrary destinations, and TLS downgrade. Only the profile name is accepted and persisted. |
| cuDF | `device_id`, `spill_to_host` | cuDF runtime and memory policy | device/resource | Reject device paths, scheduler endpoints, and package controls. |
| Dask | `memory_limit`, `n_workers`, `threads_per_worker` | LocalCluster resource envelope, bounded in aggregate by `load_dask_resource_envelope()` before adapter construction | resource | Per-field maxima are insufficient: worker count, `n_workers` x `threads_per_worker`, and `n_workers` x `memory_limit` are each capped by a server-owned budget. Reject scheduler endpoints and spill paths. |
| Dask | `use_distributed` | Dask execution-mode selector | execution | Reject external scheduler selection. |
| DataFusion | `batch_size`, `memory_limit`, `target_partitions` | DataFusion execution configuration | resource | Reject filesystem paths and unbounded worker controls. |
| DataFusion | `parquet_pushdown`, `repartition_joins` | DataFusion execution options | execution | Reject arbitrary SQL or datasource configuration. |
| DuckDB | `memory_limit`, `threads` | DuckDB adapter settings | resource | Public `threads` maps to adapter `thread_limit`; reject raw SQL settings. |
| Firebolt | `disable_result_cache`, `strict_validation` | Firebolt execution/validation options | execution | Reject credentials, account, database, and endpoint fields. |
| Databricks | `databricks_clustering_strategy`, `liquid_clustering_columns` | `PlatformOptimizationConfiguration` | layout | Reject raw connection settings and contradictory layout combinations. |
| Modin | `engine` | Modin dataframe backend selector | execution | Only reviewed `ray`/`dask`; reject unsupported backend names. |
| pandas | `dtype_backend` | pandas dataframe dtype backend | execution | Reject package installation and arbitrary dtype expressions. |
| Polars | `n_rows`, `rechunk` | Polars input and memory layout | resource | Reject filesystem paths and unbounded row counts. |
| Polars | `streaming` | Polars dataframe execution mode | execution | Reject arbitrary engine/plugin configuration. |
| Spark | `adaptive_enabled` | Spark adaptive execution setting | execution | Reject cluster, master, and filesystem controls. |
| SQLite | `check_same_thread` | SQLite connection safety setting | execution | Reject database paths and URI query controls. |
| SQLite | `timeout` | SQLite connection timeout | resource | Reject arbitrary connection strings. |
| Velox | `adaptive_enabled` | Velox execution options | execution | Reject unreviewed execution flags. |
| Velox | `deployment` | Velox local/remote deployment selector | connection | Only `local`/`remote`; reject implicit Docker or arbitrary endpoint routing. |
| Velox | `driver_memory`, `offheap_size`, `shuffle_partitions` | Velox resource envelope | resource | Reject paths, scheduler endpoints, and unbounded values. |

## Change protocol

Adding an option requires all of the following in one change:

1. Add a bounded value spec and a matching matrix entry.
2. Name the effective consumer and classify the security boundary.
3. Record aliases and rejected alternatives, if any.
4. Add a negative validation test and an effective-consumer test. Durable
   requests must prove that normalized options survive persistence and replay.
5. Update the public reference only after the focused tests and lint pass.

Removing an option is fail-closed: delete it from both records, add a
regression test for rejection, and document the compatibility impact. The
matrix must never be widened merely to mirror the CLI registry.
