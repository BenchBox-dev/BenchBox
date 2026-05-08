<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Unified Test Runner

The unified test runner consolidates functionality from the individual test runners (`run_tpch_tests.py`, `run_tpcds_tests.py`, `run_coverage.py`) into a single comprehensive tool.

## Features

- **Benchmark Support**: All BenchBox benchmarks (TPCH, TPCDS, TPCDI, SSB, AmpLab, ClickBench, H2ODB, Merge, Primitives, TPCHavoc)
- **Test Modes**: Unit, Integration, Performance, Specialized tests
- **Database Support**: DuckDB and SQLite testing
- **Coverage Integration**: Built-in coverage reporting
- **Parallel Execution**: Multi-worker test execution
- **Execution Strategies**: Development, CI, and Integration optimized modes
- **Comprehensive Reporting**: Detailed test reports with metrics

## Usage

### Using Makefile Commands (Recommended)

```bash
# Use convenient Makefile targets for common scenarios
make test                # Run default test suite (fast tests)
make test-all           # Run all tests
make test-unit          # Run unit tests only
make test-integration   # Run integration tests only
make test-tpch          # Run TPC-H tests only
make coverage           # Run tests with coverage
```

### Basic Usage with Unified Test Runner

```bash
# Run all unit tests
uv run -- python tests/utilities/unified_test_runner.py --mode unit

# Run TPCH tests with coverage
uv run -- python tests/utilities/unified_test_runner.py --benchmark tpch --coverage

# Run integration tests in parallel
uv run -- python tests/utilities/unified_test_runner.py --mode integration --parallel --workers 4
```

### Direct pytest Usage

```bash
# Run tests directly with pytest and markers
uv run -- python -m pytest -m unit                    # Unit tests only
uv run -- python -m pytest -m "tpch and fast"          # Fast TPC-H tests
uv run -- python -m pytest -m "integration and duckdb" # DuckDB integration tests
uv run -- python -m pytest --cov=benchbox             # Tests with coverage
```

### Advanced Marker Combinations

```bash
# Run specific benchmarks with speed filtering
uv run -- python -m pytest -m "tpch and fast and not slow"

# Database-specific testing
uv run -- python -m pytest -m "duckdb and unit"
uv run -- python -m pytest -m "sqlite and integration"

# Feature-specific testing
uv run -- python -m pytest -m "olap or advanced_sql"
```

## Execution Strategies

### Development Strategy (`--strategy development`)
- Optimized for fast feedback during development
- Runs unit tests first
- Stops on first failure if `--fail-fast` is used
- Focuses on quick validation

### CI Strategy (`--strategy ci`)
- Optimized for continuous integration
- Runs fast tests first, then slow tests
- Comprehensive coverage
- Parallel execution optimized

### Integration Strategy (`--strategy integration`)
- Focuses on DuckDB integration testing
- Emphasis on database connectivity and query execution
- Useful for validating database-specific functionality

## Command Line Options

### Test Selection
- `--benchmark`: Choose benchmarks (tpch, tpcds, primitives, etc.)
- `--mode`: Choose test modes (unit, integration, performance, specialized)
- `--duckdb/--sqlite`: Database selection
- `--markers`: Include tests with specific markers
- `--exclude-markers`: Exclude tests with specific markers

### Execution Control
- `--parallel`: Enable parallel execution
- `--workers`: Number of parallel workers
- `--fail-fast`: Stop on first failure
- `--timeout`: Set test timeout
- `--verbose`: Verbose output

### Coverage Options
- `--coverage`: Enable coverage reporting
- `--min-coverage`: Minimum coverage threshold
- `--output`: Output format (term, json, junit)
- `--output-location`: Custom output location

### Reporting
- `--report`: Generate detailed report
- `--report-file`: Custom report filename
- `--collect-only`: Collect tests without running
- `--dry-run`: Show commands without execution

## Examples

### Quick Development Testing
```bash
# Fast unit tests for active development
make test-fast
# or
uv run -- python -m pytest -m fast

# Test specific benchmark during development
make test-tpch
# or
uv run -- python -m pytest -m tpch

# Unit tests with verbose output
uv run -- python -m pytest -m unit -v
```

### CI/CD Pipeline
```bash
# Comprehensive CI testing
make test-ci
# or
uv run -- python -m pytest -c pytest-ci.ini -m "not (slow or flaky or local_only)"

# Run tests with coverage for CI
make coverage-report
# or
uv run -- python -m pytest --cov=benchbox --cov-report=xml --junit-xml=test-results.xml

# Parallel testing for CI
make test-parallel
# or
uv run -- python -m pytest -n auto -m "not (slow or flaky)"
```

### Integration Validation
```bash
# DuckDB integration testing
make test-duckdb
# or
uv run -- python -m pytest -m duckdb

# Full integration test suite
make test-integration
# or
uv run -- python -m pytest -m "integration and not live_integration"

# Integration with coverage
uv run -- python -m pytest -m integration --cov=benchbox
```

### Performance Testing
```bash
# Run performance tests only
uv run -- python -m pytest -m performance

# Fast performance tests
uv run -- python -m pytest -m "performance and fast"
```

## Migration from Individual Runners

### From `run_tpch_tests.py`
```bash
# Old way
python tests/run_tpch_tests.py

# New way
make test-tpch
# or
uv run -- python -m pytest -m tpch
```

### From `run_tpcds_tests.py`
```bash
# Old way
python tests/run_tpcds_tests.py minimal

# New way
make test-tpcds
# or
uv run -- python -m pytest -m "tpcds and fast"
```

### From `run_coverage.py`
```bash
# Old way
python tests/run_coverage.py --report html

# New way
make coverage-html
# or
uv run -- python -m pytest --cov=benchbox --cov-report=html
```

## Error Handling

The unified test runner provides comprehensive error handling:

- **Timeout Protection**: Tests that exceed timeout limits are terminated gracefully
- **Parallel Execution Safety**: Worker failures don't crash the entire test suite
- **Coverage Integration**: Coverage failures are reported but don't stop test execution
- **Database Connectivity**: Database connection issues are handled gracefully
- **Detailed Logging**: All errors are logged with context and suggestions

## Output Formats

- **Terminal** (default): Human-readable output with colors and progress
- **JSON**: Machine-readable format for CI/CD integration
- **JUnit XML**: Compatible with most CI systems and IDEs
- **Detailed Reports**: Markdown reports with comprehensive metrics

## Integration with pytest

The unified test runner leverages pytest's powerful features:

- **Markers**: Use pytest markers for test categorization
- **Fixtures**: Full compatibility with existing pytest fixtures
- **Plugins**: Support for pytest plugins like pytest-xdist, pytest-cov
- **Configuration**: Respects pytest.ini and pyproject.toml configurations

## Best Practices

1. **Use appropriate strategies** for different contexts (development vs CI)
2. **Leverage parallel execution** for faster feedback
3. **Set coverage thresholds** to maintain code quality
4. **Use markers** to organize and filter tests effectively
5. **Generate reports** for tracking test trends and coverage
6. **Configure timeouts** to prevent hanging tests
7. **Use database-specific flags** when testing specific integrations
