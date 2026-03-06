# Coverage Theater Triage

Triage of `*coverage*.py` and `*wave_remaining*.py` test files.

Methodology: Each file was read and assessed for whether it tests real behavior
(computed values, actual error paths) vs. mock theater (mock-verify-mock,
isinstance checks, constructor tautologies).

## DELETE (confirmed hollow — deleted in w3)

13 files deleted in commit cbae72e2c:

| File | Reason |
|------|--------|
| tests/unit/cli/presentation/test_system_presentation_coverage.py | 26 lines, 1 test, only checks string in mocked console.print |
| tests/unit/cli/commands/test_tuning_cmd_coverage.py | Only verifies CLI exit codes, no config validation |
| tests/unit/cli/commands/test_tuning_group_coverage.py | >60% mock setup, only exit code assertions |
| tests/unit/cli/commands/test_df_tuning_coverage.py | Heavy mock setup, only exit code and string checks |
| tests/unit/cli/commands/test_datagen_coverage.py | Only mocks and string output containment |
| tests/unit/cli/commands/test_run_official_coverage.py | Direct module.run mocking, only exit codes |
| tests/unit/cli/test_onboarding_coverage.py | All UI helpers mocked, only mock call count assertions |
| tests/unit/cli/test_system_coverage.py | Only string containment in mocked output |
| tests/unit/cli/test_output_coverage.py | Only mocked console output string checks |
| tests/unit/mcp/test_mcp_init_coverage.py | Only mock assertions and lazy-load attribute checks |
| tests/unit/platforms/test_motherduck_coverage.py | 100% MagicMock connections, assert mock is mock |
| tests/unit/platforms/test_azure_synapse_coverage.py | 28% mock, all connections mocked |
| tests/unit/core/test_dataframe_queries_stub_execution_wave_remaining.py | Only stub execution with dummy contexts |

## REWRITE (completed in w5 — deleted and replaced)

4 credential test files replaced with `test_credential_files.py` (35 real file-based tests):

| File | Reason |
|------|--------|
| tests/unit/platforms/credentials/test_snowflake_coverage.py | Mock-only credential validation; replaced with real YAML file tests |
| tests/unit/platforms/credentials/test_databricks_credentials_coverage.py | Mock-only; replaced with real file-based tests |
| tests/unit/platforms/credentials/test_bigquery_coverage.py | Mock-only; replaced with real JSON file loading tests |
| tests/unit/platforms/credentials/test_redshift_coverage.py | Mock-only; replaced with real env-var substitution tests |

## KEEP (has real value — 67 files remaining)

The w2 description pre-assessed 15 DELETE candidates, but detailed triage found
that 11 of those have genuine behavioral value. The following were explicitly
reviewed and kept:

### Originally listed as DELETE candidates in w2, kept after detailed review

| File | Tests | Why kept |
|------|-------|----------|
| tests/unit/platforms/test_clickhouse_cloud_coverage.py | 38 | Real URL parsing, S3/GCS staging dispatch, OAuth handling, data loading assertions |
| tests/unit/platforms/test_clickhouse_metadata_coverage.py | 8 | Platform metadata extraction, version detection with computed values |
| tests/unit/platforms/test_cudf_coverage.py | 4 | Connection wrapper behavior, GPU caching, memory limit parsing |
| tests/unit/platforms/test_timescaledb_coverage.py | 3 | TimescaleDB-specific paths: hypertable metadata, chunk counting, analyze failure handling |
| tests/unit/platforms/test_influxdb_adapter_coverage.py | 10 | Real CSV parsing with type conversion, InfluxDB loading logic |
| tests/unit/platforms/dataframe/test_modin_df_coverage.py | 4 | Behavioral contracts: column dropping, concatenation, groupby aggregation |
| tests/unit/platforms/dataframe/test_dask_df_coverage.py | 6 | State transitions, distributed setup, aggregation logic, error handling |
| tests/unit/platforms/dataframe/test_cudf_df_coverage.py | 5 | GPU initialization flow, column handling, memory calculations |
| tests/unit/platforms/dataframe/test_unified_frame_coverage.py | 10 | Mixed: AST extraction and post-op logic is real; some isinstance cascades are hollow |
| tests/unit/platforms/test_platform_adapters_coverage_wave_remaining.py | 107 | Mixed: line protocol escaping, data source resolution, file handling are real; ~30% is hollow |
| tests/unit/core/test_concurrency_joinorder_coverage_wave_remaining.py | 23 | Percentile calculation, zero-division edge cases, failure handling, CSV formatting |

### Notable KEEP files with strong behavioral value

- tests/unit/core/test_dataframe_queries_coverage_wave_remaining.py (real Polars queries)
- tests/unit/core/tpch/test_dataframe_queries_coverage.py (real pandas DataFrames)
- tests/unit/cli/test_run_command_coverage_wave_remaining.py (real validation rules)
- tests/unit/cli/test_config_coverage.py (real YAML parsing)
- tests/unit/cli/commands/test_compare_coverage.py (real comparison logic)
- tests/unit/cli/commands/test_shell_coverage.py (real discovery/filtering)

### Remaining files (not individually assessed)

~50 additional `*coverage*.py` and `*wave_remaining*.py` files across cli/,
core/, platforms/, and utils/ were kept as a group. Many contain a mix of
mock-heavy and real tests; they are not pure theater but could benefit from
strengthening. These are candidates for a future remediation wave.
