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
# or
uv run -- python -m pytest -m fast
```

**Integration Tests** (~5 minutes, requires local databases):
```bash
make test-integration
# or
uv run -- python -m pytest -m "integration and not live_integration"
```

**E2E Tests** (validates complete CLI workflows):
```bash
# Dry-run mode, fast
uv run -- python -m pytest -m e2e_quick

# Full E2E with local platforms
uv run -- python -m pytest tests/e2e/ -v
```

**Full Suite** (requires all dependencies):
```bash
make test-all
# or
uv run -- python -m pytest
```

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

The suite contains **3576+ tests** organized into:
- **Unit tests** (`tests/unit/`): Fast component tests with no external dependencies
- **Integration tests** (`tests/integration/`): Database integration and component interaction
- **E2E tests** (`tests/e2e/`): Complete CLI workflow validation (125+ tests)
- **Example tests** (`tests/examples/`): Validate example scripts work correctly

## Platform Smoke Suite

Run all smoke checks:
```bash
make test-smoke
# or
uv run -- python -m pytest -m platform_smoke
```

Run specific platform smoke tests:
```bash
# Local adapters (DuckDB/SQLite)
uv run -- python -m pytest tests/integration/platforms/test_local_platforms_smoke.py

# Cloud adapters with stubbed clients
# Databricks
uv run -- python -m pytest tests/integration/platforms/test_databricks_smoke.py

# BigQuery
uv run -- python -m pytest tests/integration/platforms/test_bigquery_smoke.py

# Redshift
uv run -- python -m pytest tests/integration/platforms/test_redshift_smoke.py

# Snowflake
uv run -- python -m pytest tests/integration/platforms/test_snowflake_smoke.py
```

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
# Quick E2E (dry-run mode)
uv run -- python -m pytest -m e2e_quick

# Local platform tests (full execution)
uv run -- python -m pytest -m e2e_local

# All E2E tests
uv run -- python -m pytest tests/e2e/ -v
```

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
# Install cloud platform extras
uv pip install -e ".[bigquery,databricks,snowflake]"

# Run BigQuery tests
make test-live-bigquery
# or
uv run -- python -m pytest -m bigquery

# Run all tests including those requiring TPC binaries
uv run -- python -m pytest --run-optional
```

### Table-Format Integration Lane (Delta/Iceberg)

The presorted open table-format integration checks are tagged with
`requires_table_formats` and depend on `deltalake` and `pyiceberg`.

Use this command locally when validating those paths:

```bash
uv run -- python -m pytest -q tests/integration/core/data_organization/test_presorted_generation.py -m "requires_table_formats"
```

CI runs this marker in a dedicated required workflow job
`integration-table-formats` so dependency-gated tests are not silently skipped.

#### Rollout Checklist

Use this checklist when introducing or updating this lane:

1. Confirm `.github/workflows/test.yml` defines `integration-table-formats`.
2. Confirm marker registration exists in both `pytest.ini` and `pyproject.toml`.
3. Confirm marker-selected tests are collected and executable:
   `uv run -- python -m pytest --collect-only -q tests/integration/core/data_organization/test_presorted_generation.py -m "requires_table_formats"`
4. Update GitHub branch protection rules manually so `integration-table-formats`
   is a required status check for pull requests into `main`.

## Test Status

Current test suite status:
- ✅ **CLI Exporter Tests**: 30/30 passing (`tests/unit/cli/test_cli_output.py`)
- ✅ **Result Schema Tests**: `tests/unit/core/results/`
- ✅ **Test Collection**: 3576 tests collected with 0 errors
- ⚠️ **Full Suite**: Some tests skipped when optional dependencies unavailable

For questions or issues, see the troubleshooting section in `docs/development/adding-new-platforms.md`.
