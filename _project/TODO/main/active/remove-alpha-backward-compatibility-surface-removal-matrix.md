# Removal Matrix (w1)

Total tracked entries: 89

## By Module Prefix
- `benchbox/base.py`: 1
- `benchbox/cli/commands`: 4
- `benchbox/cli/platform_hooks.py`: 1
- `benchbox/cli/types.py`: 1
- `benchbox/core/config.py`: 1
- `benchbox/core/dataframe`: 1
- `benchbox/core/datavault`: 3
- `benchbox/core/expected_results`: 2
- `benchbox/core/joinorder`: 1
- `benchbox/core/manifest`: 2
- `benchbox/core/platform_config.py`: 1
- `benchbox/core/platform_registry.py`: 1
- `benchbox/core/results`: 5
- `benchbox/core/tpc_compliance.py`: 7
- `benchbox/core/tpcdi`: 6
- `benchbox/core/tpcds`: 11
- `benchbox/core/tpch`: 3
- `benchbox/core/tpchavoc`: 1
- `benchbox/core/transaction_primitives`: 1
- `benchbox/core/tuning`: 10
- `benchbox/core/validation`: 2
- `benchbox/core/visualization`: 1
- `benchbox/core/write_primitives`: 1
- `benchbox/platforms/base`: 5
- `benchbox/platforms/clickhouse`: 3
- `benchbox/platforms/dataframe`: 1
- `benchbox/platforms/firebolt.py`: 1
- `benchbox/platforms/influxdb`: 1
- `benchbox/platforms/redshift.py`: 2
- `benchbox/platforms/sqlite.py`: 3
- `benchbox/utils/VERSION_MANAGEMENT.md`: 1
- `benchbox/utils/database_naming.py`: 2
- `benchbox/utils/datagen_manifest.py`: 1
- `benchbox/utils/dependencies.py`: 1
- `benchbox/utils/format_converters`: 1

## Entries
| Location | Current Status | Removal Action | Canonical Replacement/Outcome |
|---|---|---|---|
| `benchbox/base.py:232` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tpchavoc/queries.py:251` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/utils/database_naming.py:359` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/utils/database_naming.py:402` | deprecate | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/utils/dependencies.py:381` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/utils/VERSION_MANAGEMENT.md:106` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/utils/datagen_manifest.py:151` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/utils/format_converters/base.py:181` | deprecate | remove compatibility handling | use canonical API/behavior only |
| `benchbox/cli/types.py:1` | active | delete alias/re-export | use canonical API/behavior only |
| `benchbox/cli/commands/run.py:756` | deprecate | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/platforms/base/cloud_spark/session.py:128` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/platforms/base/cloud_spark/mixins.py:219` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/cli/commands/setup.py:333` | deprecate | remove compatibility handling | use canonical API/behavior only |
| `benchbox/cli/platform_hooks.py:162` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/platforms/redshift.py:107` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/platforms/redshift.py:377` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/cli/commands/shell.py:50` | deprecate | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/cli/commands/shell.py:90` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/platforms/firebolt.py:168` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/platforms/base/format_capabilities.py:223` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/platforms/clickhouse/metadata.py:53` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/platforms/influxdb/client.py:9` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/platforms/base/data_loading.py:290` | deprecate | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/platforms/base/data_loading.py:315` | deprecate | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/platforms/clickhouse/adapter.py:69` | active | delete alias/re-export | use canonical API/behavior only |
| `benchbox/platforms/clickhouse/adapter.py:129` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/platforms/sqlite.py:122` | deprecate | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/platforms/sqlite.py:145` | deprecate | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/platforms/sqlite.py:385` | deprecate | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/validation/__init__.py:21` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/validation/engines.py:56` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/config.py:3` | active | delete alias/re-export | use canonical API/behavior only |
| `benchbox/platforms/dataframe/unified_frame.py:2631` | active | delete alias/re-export | use canonical API/behavior only |
| `benchbox/core/dataframe/profiling.py:954` | deprecate | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/write_primitives/catalog/loader.py:188` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/joinorder/generator.py:128` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tpc_compliance.py:161` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/tpc_compliance.py:222` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tpc_compliance.py:491` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tpc_compliance.py:492` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tpc_compliance.py:493` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tpc_compliance.py:494` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tpc_compliance.py:498` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/platform_config.py:63` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/visualization/ascii/heatmap.py:48` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/manifest/models.py:54` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/manifest/models.py:55` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/platform_registry.py:101` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tpcds/throughput_test.py:78` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tpcds/benchmark/phases.py:7` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/tuning/interface.py:190` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tuning/interface.py:256` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tuning/interface.py:384` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tuning/interface.py:438` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tuning/interface.py:483` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tuning/interface.py:901` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tuning/interface.py:1101` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/tuning/interface.py:1286` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/tuning/interface.py:1296` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/tpcds/benchmark/results.py:41` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/tpcds/benchmark/results.py:56` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/tpcds/benchmark/results.py:69` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/tuning/generators/duckdb.py:142` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/tpch/generator.py:251` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tpch/generator.py:1056` | deprecate | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/tpch/official_benchmark.py:263` | active | delete alias/re-export | use canonical API/behavior only |
| `benchbox/core/transaction_primitives/catalog/loader.py:194` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/results/exporter.py:186` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/results/exporter.py:553` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/results/loader.py:7` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/results/loader.py:120` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/results/filenames.py:75` | deprecate | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/datavault/queries.py:429` | deprecate | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/datavault/queries.py:1008` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/datavault/queries.py:1051` | active | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/tpcds/generator/runner.py:48` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tpcds/power_test.py:56` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tpcds/power_test.py:127` | deprecate | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/tpcds/power_test.py:255` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tpcds/power_test.py:684` | deprecate | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/expected_results/tpcds_results.py:84` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/expected_results/tpcds_results.py:106` | active | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tpcds/dataframe_queries/rollup_helper.py:296` | deprecate | remove legacy branch/path | use canonical API/behavior only |
| `benchbox/core/tpcdi/etl/data_quality_monitor.py:60` | active | delete alias/re-export | use canonical API/behavior only |
| `benchbox/core/tpcdi/tools/data_cleaners.py:566` | deprecate | delete alias/re-export | use canonical API/behavior only |
| `benchbox/core/tpcdi/queries.py:56` | deprecate | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tpcdi/queries.py:271` | deprecate | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tpcdi/benchmark.py:112` | deprecate | remove compatibility handling | use canonical API/behavior only |
| `benchbox/core/tpcdi/benchmark.py:1616` | deprecate | delete alias/re-export | use canonical API/behavior only |
