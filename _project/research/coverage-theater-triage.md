# Coverage Theater Triage

Triage of 84 `*coverage*.py` and `*wave_remaining*.py` test files.

Methodology: Each file was read and assessed for whether it tests real behavior
(computed values, actual error paths) vs. mock theater (mock-verify-mock,
isinstance checks, constructor tautologies).

## DELETE (confirmed hollow)

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

## KEEP (has real value)

All remaining files in `*coverage*.py` and `*wave_remaining*.py` that were not
listed above. Many contain a mix of mock-heavy and real tests; they are not pure
theater but could benefit from strengthening. Keeping them avoids regression risk.

Notable KEEP files with genuine value:
- tests/unit/core/test_dataframe_queries_coverage_wave_remaining.py (real Polars queries)
- tests/unit/core/tpch/test_dataframe_queries_coverage.py (real pandas DataFrames)
- tests/unit/cli/test_run_command_coverage_wave_remaining.py (real validation rules)
- tests/unit/cli/test_config_coverage.py (real YAML parsing)
- tests/unit/cli/commands/test_compare_coverage.py (real comparison logic)
- tests/unit/cli/commands/test_shell_coverage.py (real discovery/filtering)

## REWRITE (deferred)

Credential test files - cover critical paths but are currently mock-heavy:
- tests/unit/platforms/credentials/test_snowflake_coverage.py
- tests/unit/platforms/credentials/test_databricks_credentials_coverage.py
- tests/unit/platforms/credentials/test_bigquery_coverage.py
- tests/unit/platforms/credentials/test_redshift_coverage.py

These are tracked in TODO w5 (write file-based credential tests).
