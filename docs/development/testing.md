# BenchBox Testing Guide

```{tags} contributor, guide, testing
```

This guide summarizes the testing infrastructure and provides guidance on running
different test tiers based on your development needs and available dependencies.

## Quick Start

The test suite is organized into tiers for different development workflows:

**Fast Unit Tests** (~30 seconds, no external dependencies):
```bash
make test-fast
uv run -- python -m pytest -m fast
```
Either command works. The `make` target wraps the pytest command.

**Integration Tests** (~5 minutes, requires local databases):
```bash
make test-integration
uv run -- python -m pytest -m "integration and not live_integration"
```

**E2E Tests** (validates complete CLI workflows):
```bash
uv run -- python -m pytest -m e2e_quick

uv run -- python -m pytest tests/e2e/ -v
```
The first command runs in dry-run mode and is fast. The second runs full E2E tests with local platforms.

**Full Suite** (requires all dependencies):
```bash
make test-all
uv run -- python -m pytest
```
Either command works.

## Pytest xdist Safety

BenchBox uses pytest-xdist for local development, but local worker counts are
not left fully unconstrained on macOS.

- BenchBox caps pytest-xdist to a safe worker count **before** xdist starts.
- On macOS, the current default cap is **2 workers**.
- If you request `-n 4` or `-n 8`, BenchBox may rewrite that request and print
  a warning explaining the effective cap.
- Use `BENCHBOX_MAX_XDIST_WORKERS` only for deliberate local experiments.

This is not an arbitrary slowdown. It prevents a proven machine-lockup mode
caused by worker oversubscription plus native-library thread pools.

See [Pytest xdist Safety](pytest-xdist-safety.md) for the root-cause analysis,
the validation matrix, and the checklist to follow when editing test
infrastructure.

## Test Organization

The suite is organized into:
- **Unit tests** (`tests/unit/`): Fast component tests with no external dependencies
- **Integration tests** (`tests/integration/`): Database integration and component interaction
- **E2E tests** (`tests/e2e/`): Complete CLI workflow validation (125+ tests)
- **Example tests** (`tests/examples/`): Validate example scripts work correctly

## Platform Smoke Suite

Run all smoke checks:
```bash
make test-smoke
uv run -- python -m pytest -m platform_smoke
```
Either command works.

Run specific platform smoke tests:
```bash
uv run -- python -m pytest tests/integration/platforms/test_local_platforms_smoke.py

uv run -- python -m pytest tests/integration/platforms/test_databricks_smoke.py

uv run -- python -m pytest tests/integration/platforms/test_bigquery_smoke.py

uv run -- python -m pytest tests/integration/platforms/test_redshift_smoke.py

uv run -- python -m pytest tests/integration/platforms/test_snowflake_smoke.py
```
The first command covers the local adapters (DuckDB and SQLite). The rest cover the cloud adapters with stubbed clients: Databricks, BigQuery, Redshift, and Snowflake, in that order.

Each test file installs lightweight client stubs automatically so you can run
the suite without provisioning real services. Failures generally indicate a
behavioral regression in the corresponding adapter.

## E2E Test Suite

The E2E test suite (`tests/e2e/`) provides comprehensive validation of CLI workflows:

| Test Module | Coverage |
|-------------|----------|
| `test_cli_options.py` | CLI option validation (--benchmark, --scale, --phases, etc.) |
| `test_error_handling.py` | Error messages and exit codes for invalid inputs |
| `test_result_validation.py` | Result file schema and content validation |
| `test_local_platforms.py` | Full execution on DuckDB, SQLite, DataFusion |
| `test_cloud_platforms.py` | Dry-run tests for Snowflake, BigQuery, etc. |
| `test_dataframe_platforms.py` | DataFrame platforms (Polars, Pandas, Dask) |

Run E2E tests:
```bash
uv run -- python -m pytest -m e2e_quick

uv run -- python -m pytest -m e2e_local

uv run -- python -m pytest tests/e2e/ -v
```
The commands run quick E2E tests (dry-run mode), local platform tests (full execution), and all E2E tests, in that order.

See [E2E Testing Guide](../testing/e2e-testing.md) for detailed documentation.

## CLI Dry-Run Coverage

The CLI tests exercise `benchbox run --dry-run` across all platforms.
Cloud platform dry-run tests use stubs and require no credentials:

```bash
uv run -- python -m pytest tests/e2e/test_cloud_platforms.py -v
```

The ClickHouse dry-run uses a temporary stub of the `chdb` package; no manual
installation is required for the smoke test.

## Optional Dependencies

Some tests require optional dependencies that are not installed by default. These tests
will be automatically skipped with clear messages when dependencies are unavailable.

### TPC Binary Dependencies

**TPC-H Queries**: Some tests require the `qgen` binary from TPC-H sources.
- **Location**: `benchbox/_sources/tpc-h/qgen/`
- **Installation**: Download from [tpc.org](http://tpc.org/tpc_documents_current_versions/current_specifications5.asp) and compile following `docs/development/tpc-compilation-guide.md`
- **Tests affected**: Query generation and validation tests

**TPC-DS Data Generation**: Some tests require `dsdgen` binary from TPC-DS sources.
- **Location**: `benchbox/_sources/tpc-ds/tools/`
- **Installation**: Download from [tpc.org](http://tpc.org/tpc_documents_current_versions/current_specifications5.asp) and compile
- **Tests affected**: Example tests that generate TPC-DS data (e.g., `test_duckdb_tpcds_power_runs`)

### Cloud Platform Dependencies

Tests for cloud platforms require their respective SDKs:
- **BigQuery**: `google-cloud-bigquery` package
- **Databricks**: `databricks-sql-connector` package
- **Snowflake**: `snowflake-connector-python` package
- **Redshift**: `redshift-connector` package
- **ClickHouse**: `clickhouse-driver` or `chdb` package

Cloud platform tests use stubbed clients for smoke tests but require real credentials for
full integration tests.

### Running Tests With Optional Dependencies

To run tests that require specific dependencies:

```bash
uv pip install -e ".[bigquery,databricks,snowflake]"

make test-live-bigquery
uv run -- python -m pytest -m bigquery

uv run -- python -m pytest --run-optional
```

The first command installs the cloud platform extras. The next two run the BigQuery tests, either through the `make` target or through pytest directly. The last runs all tests, including those that require TPC binaries.

### Table-Format Integration Lane (Delta/Iceberg)

The presorted open table-format integration checks are tagged with
`requires_table_formats` and depend on `deltalake` and `pyiceberg`.

Use this command locally when validating those paths:

```bash
uv run -- python -m pytest -q tests/integration/core/data_organization/test_presorted_generation.py -m "requires_table_formats"
```

CI runs this marker in a dedicated required workflow job
`integration-table-formats` so dependency-gated tests are not silently skipped.

## Troubleshooting

Some tests are skipped when optional dependencies are unavailable. For questions or issues, see the troubleshooting section in `docs/development/adding-new-platforms.md`.
