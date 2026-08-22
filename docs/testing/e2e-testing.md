<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# End-to-End (E2E) Testing Guide

```{tags} contributor, guide, testing, e2e
```

This guide covers BenchBox's end-to-end test suite, which validates complete benchmark workflows through the CLI interface.

## Overview

The E2E test suite (`tests/e2e/`) validates that BenchBox works correctly as an integrated system. Unlike unit tests that test individual components or integration tests that test component interactions, E2E tests exercise the full CLI workflow from command invocation through result generation.

**Test Count**: 162 test functions across 6 test modules

## Test Structure

```
tests/e2e/
├── conftest.py                 # Fixtures and helpers
├── test_cli_options.py         # CLI option validation (31 tests)
├── test_error_handling.py      # Error handling coverage (31 tests)
├── test_result_validation.py   # Result schema validation (40 tests)
├── test_local_platforms.py     # Local platform tests (16 tests)
├── test_cloud_platforms.py     # Cloud platform dry-run tests (26 tests)
├── test_dataframe_platforms.py # DataFrame platform tests (18 tests)
└── utils/
    ├── platform_detection.py   # Platform availability detection
    └── result_validators.py    # Result JSON validation
```

## Quick Start

### Run All E2E Tests

```bash
# All E2E tests
uv run -- python -m pytest tests/e2e/ -v

# With parallel execution
uv run -- python -m pytest tests/e2e/ -n auto
```

### Run Quick E2E Tests (Dry-Run Mode)

```bash
# Quick tests using dry-run mode (no actual benchmark execution)
uv run -- python -m pytest -m e2e_quick
```

### Run Local Platform Tests

```bash
# Full execution against local databases
uv run -- python -m pytest -m e2e_local

# Specific platform
uv run -- python -m pytest tests/e2e/test_local_platforms.py -v
```

## Test Categories

### CLI Options Tests (`test_cli_options.py`)

Validates all CLI options work correctly:

| Option | Tests |
|--------|-------|
| `--benchmark` | TPC-H, TPC-DS, SSB, ClickBench selection |
| `--scale` | Scale factor validation (0.01, 0.1) |
| `--phases` | Phase selection (generate, load, warmup, power) |
| `--queries` | Query subset: single, multiple, case normalization |
| `--tuning` | Tuning modes (tuned, notuning, auto) |
| `--compression` | Compression formats (zstd, gzip, none) |
| `--validation` | Validation levels (disabled, loose) |
| `--seed` | Deterministic seeding (seed 42 reproducibility) |
| `--force` | Force modes (datagen, all) |

```bash
# Run CLI option tests
uv run -- python -m pytest tests/e2e/test_cli_options.py -v

# Test specific option
uv run -- python -m pytest tests/e2e/test_cli_options.py -k "scale" -v
```

### Error Handling Tests (`test_error_handling.py`)

Validates proper error messages and exit codes:

- Missing required parameters (`--platform`, `--benchmark`)
- Invalid platform/benchmark names
- Invalid scale factors (negative, zero; TPC-DS requires scale ≥ 1)
- Query format violations (max 100 queries, alphanumeric IDs only, SQL injection patterns)
- Invalid tuning, compression, and validation modes
- Platform option format validation (`key=value`)
- Dry-run directory edge cases (file instead of directory)
- Help and version commands (`--help`, `--help all`, `--help examples`, `--version`)

```bash
# Run error handling tests
uv run -- python -m pytest tests/e2e/test_error_handling.py -v
```

### Result Validation Tests (`test_result_validation.py`)

Validates benchmark result file structure and content:

- **Result structure**: Required fields, null handling, timestamp formats, negative durations, query count consistency
- **Query execution**: Valid/invalid query IDs, status values (SUCCESS, FAILED, ERROR, TIMEOUT, SKIPPED), execution times
- **Phase timing**: Duration constraints, zero-duration handling
- **Execution phases**: Setup (data_generation, data_loading), power_test, throughput_test validation
- **Validator reuse**: Multiple validation passes, error collection
- **File loading**: Valid JSON, nonexistent files, malformed JSON, end-to-end load-and-validate

```bash
# Run result validation tests
uv run -- python -m pytest tests/e2e/test_result_validation.py -v
```

### Local Platform Tests (`test_local_platforms.py`)

Full benchmark execution against local databases:

| Platform | Tests |
|----------|-------|
| DuckDB | Full TPC-H, query subsets, `--capture-plans`, SSB execution |
| SQLite | Full TPC-H, phase-limited execution (generate,load only) |
| DataFusion | Full TPC-H (skipped if unavailable) |
| ClickHouse (chDB) | Dry-run with local mode and platform options |
| Cross-platform | DuckDB vs SQLite result comparison (Q1) |

All platforms also include dry-run artifact validation tests, plus parametrized tests for help commands and dry-run across platform/benchmark combinations.

```bash
# Run local platform tests
uv run -- python -m pytest tests/e2e/test_local_platforms.py -v

# Run DuckDB tests only
uv run -- python -m pytest tests/e2e/test_local_platforms.py -k duckdb -v
```

**Note**: Local platform tests execute actual benchmarks and may take several minutes.

### Cloud Platform Tests (`test_cloud_platforms.py`)

Dry-run tests for cloud platforms (no credentials required):

| Platform | Tests |
|----------|-------|
| Snowflake | Dry-run validation, artifact generation |
| BigQuery | Dry-run validation, artifact generation |
| Redshift | Dry-run validation, artifact generation |
| Athena | Dry-run validation, artifact generation |
| Databricks | Dry-run validation, artifact generation |
| Firebolt | Dry-run validation, artifact generation |
| Trino | Dry-run validation, artifact generation |
| Presto | Dry-run validation, artifact generation |
| ClickHouse (cloud) | Dry-run validation (server mode) |

Each platform class also has a `test_full_execution_with_credentials()` test gated behind the `live_integration` marker. Parametrized tests cover all platforms across multiple benchmark types (including TPC-DS with SF=1 constraint).

```bash
# Run cloud platform dry-run tests
uv run -- python -m pytest tests/e2e/test_cloud_platforms.py -v

# Run live integration tests (requires credentials)
uv run -- python -m pytest -m live_integration -v
```

### DataFrame Platform Tests (`test_dataframe_platforms.py`)

Tests for DataFrame-based platforms:

| Platform | Tests |
|----------|-------|
| Pandas | Full TPC-H, query subsets, dry-run |
| Polars | Full TPC-H, query subsets, dry-run |
| Dask | Full TPC-H, dry-run |
| PySpark | Full TPC-H (marked `slow`), dry-run |
| cuDF | Full TPC-H (requires NVIDIA GPU) |
| Modin | Full TPC-H execution |
| DataFusion (DF) | Full TPC-H execution |
| Cross-platform | Pandas vs Polars result comparison (Q1) |

```bash
# Run DataFrame platform tests
uv run -- python -m pytest tests/e2e/test_dataframe_platforms.py -v

# Skip slow tests (PySpark)
uv run -- python -m pytest tests/e2e/test_dataframe_platforms.py -m "not slow" -v
```

## Test Markers

E2E tests use several pytest markers for selective execution:

| Marker | Description |
|--------|-------------|
| `e2e` | All E2E tests |
| `e2e_quick` | Quick dry-run tests (no benchmark execution) |
| `e2e_local` | Local platform tests (full execution) |
| `e2e_cloud` | Cloud platform dry-run tests |
| `e2e_dataframe` | DataFrame platform tests |
| `slow` | Tests that take significant time (e.g., PySpark) |
| `live_integration` | Tests requiring real cloud credentials |
| `tpch` / `tpcds` / `ssb` / `clickbench` | Benchmark-specific tests |
| `duckdb` / `sqlite` | Platform-specific tests |

```bash
# Examples
uv run -- python -m pytest -m e2e_quick          # Quick tests only
uv run -- python -m pytest -m e2e_local          # Local platforms
uv run -- python -m pytest -m "e2e and not slow" # Fast E2E tests
uv run -- python -m pytest -m "e2e and tpch"     # TPC-H tests only
uv run -- python -m pytest -m live_integration   # Live cloud tests
```

## Fixtures

The E2E test suite provides fixtures in `conftest.py`:

### Directory Fixtures

```python
@pytest.fixture
def results_dir(tmp_path):
    """Temporary directory for benchmark results."""

@pytest.fixture
def dry_run_dir(tmp_path):
    """Temporary directory for dry-run output."""
```

### Platform Configuration Fixtures

```python
# Local platforms
@pytest.fixture
def duckdb_config():
    return {"platform": "duckdb", "benchmark": "tpch", "scale": "0.01"}

@pytest.fixture
def sqlite_config():
    return {"platform": "sqlite", "benchmark": "tpch", "scale": "0.01"}

@pytest.fixture
def datafusion_config():
    return {"platform": "datafusion", "benchmark": "tpch", "scale": "0.01"}

# DataFrame platforms
@pytest.fixture
def pandas_df_config():
    return {"platform": "pandas-df", "benchmark": "tpch", "scale": "0.01"}

@pytest.fixture
def polars_df_config():
    return {"platform": "polars-df", "benchmark": "tpch", "scale": "0.01"}

# Cloud platforms (dry-run)
@pytest.fixture
def snowflake_dry_run_config(dry_run_dir):
    return {"platform": "snowflake", "benchmark": "tpch", "dry_run": str(dry_run_dir)}
```

### Helper Functions

```python
def build_cli_args(config, extra_args=None):
    """Build CLI arguments from config dictionary."""

def run_benchmark(config, extra_args=None, env=None, timeout=600):
    """Run a benchmark with configuration."""

def find_result_files(directory, pattern="*.json"):
    """Find result files in directory."""

def find_latest_result(directory, pattern="*.json"):
    """Find the most recent result file."""
```

## Writing E2E Tests

### Basic Test Pattern

```python
import pytest
from tests.e2e.conftest import build_cli_args, run_benchmark

def test_basic_benchmark(duckdb_config, results_dir):
    """Test basic benchmark execution."""
    config = {**duckdb_config, "output": str(results_dir)}

    result = run_benchmark(config)

    assert result.returncode == 0
    assert "Benchmark completed" in result.stdout
```

### Testing Error Conditions

```python
def test_invalid_scale_factor():
    """Test that invalid scale factors produce clear errors."""
    config = {"platform": "duckdb", "benchmark": "tpcds", "scale": "0.1"}

    result = run_benchmark(config)

    assert result.returncode != 0
    assert "scale factor" in result.stderr.lower()
```

### Testing Result Files

```python
import json
from tests.e2e.conftest import find_result_files

def test_result_file_schema(duckdb_config, results_dir):
    """Test that result files match expected schema."""
    config = {**duckdb_config, "output": str(results_dir)}
    run_benchmark(config)

    result_files = find_result_files(results_dir / "results")
    assert len(result_files) > 0

    with open(result_files[0]) as f:
        data = json.load(f)

    assert "platform" in data
    assert "benchmark" in data
    assert "successful_queries" in data
```

## CI/CD Integration

### GitHub Actions

```yaml
jobs:
  e2e-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: uv sync --group dev

      - name: Run E2E quick tests
        run: uv run -- python -m pytest -m e2e_quick -v

      - name: Run E2E local tests
        run: uv run -- python -m pytest -m e2e_local -v
        timeout-minutes: 15
```

### Makefile Targets

```makefile
test-e2e-quick:
	uv run -- python -m pytest -m e2e_quick -v

test-e2e-local:
	uv run -- python -m pytest -m e2e_local -v

test-e2e-all:
	uv run -- python -m pytest tests/e2e/ -v
```

## Platform Availability Gating

Tests use decorators from `tests/e2e/utils/platform_detection.py` to skip gracefully when dependencies or credentials are unavailable:

```python
from tests.e2e.utils.platform_detection import requires_platform, requires_gpu

@requires_platform("datafusion")
def test_datafusion_execution():
    """Skipped if datafusion not importable."""

@requires_gpu()
def test_cudf_execution():
    """Skipped if no NVIDIA GPU/CUDA available."""
```

Available decorators:

| Decorator | Checks |
|-----------|--------|
| `@requires_platform(name)` | Platform module is importable |
| `@requires_dataframe(name)` | DataFrame platform available |
| `@requires_gpu()` | NVIDIA GPU and CUDA present |
| `@requires_cloud_credentials(name)` | Required env vars set (e.g., `SNOWFLAKE_ACCOUNT`) |

## Troubleshooting

### Tests Timing Out

E2E tests have a 10-minute timeout by default. For slower systems:

```bash
# Increase timeout
uv run -- python -m pytest tests/e2e/ --timeout=900
```

### ClickHouse Tests Without Dependencies

The test suite includes automatic stub generation for ClickHouse dependencies:

```python
@pytest.fixture
def clickhouse_stub_dir(tmp_path):
    """Create minimal chDB and clickhouse_driver stubs."""
    # Stubs are created automatically for dry-run tests
```

### Debugging Test Failures

```bash
# Run with verbose output
uv run -- python -m pytest tests/e2e/test_cli_options.py -v -s

# Run single test with debugging
uv run -- python -m pytest tests/e2e/test_cli_options.py::test_benchmark_selection -v -s --tb=long
```

### Result File Inspection

```bash
# Find generated result files
find /tmp -name "*.json" -path "*/benchmark_results/*" 2>/dev/null

# Validate JSON schema
python -c "import json; json.load(open('result.json'))"
```

## Related Documentation

- [Testing Index](index.md) - Overview of all test categories
- [Live Integration Tests](live-integration-tests.md) - Tests requiring cloud credentials
- [Development Testing Guide](../development/testing.md) - General testing guidance
- [CI/CD Integration](../advanced/ci-cd-integration.md) - Automated workflows
