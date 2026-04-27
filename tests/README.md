<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# BenchBox Test Suite

This directory contains the comprehensive test suite for BenchBox, organized into multiple categories for efficient testing and development workflows.

**See also**: [`AGENTS.md`](../AGENTS.md) for the contributor/agent guide, and [`docs/development/`](../docs/development/) for architecture deep-dives.

## Test Structure

```
tests/
├── e2e/                      # End-to-end CLI workflow tests
├── fixtures/                 # Shared test fixtures
├── integration/              # Integration tests
├── performance/              # Performance tests
├── specialized/              # Specialized functionality tests
├── unit/                     # Unit tests
├── utilities/                # Test utilities and helpers
├── conftest.py              # Global pytest configuration
├── pytest.ini              # Enhanced pytest configuration
└── README.md               # This file
```

## Test Categories

### Unit Tests (`unit/`)
Fast, isolated tests that verify individual components:
- **benchmarks/**: Core benchmark functionality
- **core/**: Base classes and utilities
- **generators/**: Data generation components

**Characteristics:**
- Fast execution (< 1 second each)
- No external dependencies
- High isolation and predictability
- Extensive code coverage

### E2E Tests (`e2e/`)
End-to-end tests that validate complete CLI workflows:
- **test_cli_options.py**: CLI option validation (27 tests)
- **test_error_handling.py**: Error handling coverage (25 tests)
- **test_result_validation.py**: Result schema validation (28 tests)
- **test_local_platforms.py**: Local platform tests (14 tests)
- **test_cloud_platforms.py**: Cloud platform dry-run tests (15 tests)
- **test_dataframe_platforms.py**: DataFrame platform tests (16 tests)

**Characteristics:**
- Tests full CLI workflow from command to results
- Validates all platforms (local, cloud, DataFrame)
- Uses dry-run mode for cloud platforms (no credentials needed)
- Includes result file schema validation

**Markers:**
- `e2e`: All E2E tests
- `e2e_quick`: Quick dry-run tests
- `e2e_local`: Local platform tests (full execution)
- `e2e_cloud`: Cloud platform dry-run tests
- `e2e_dataframe`: DataFrame platform tests

### Integration Tests (`integration/`)
Tests that verify component interactions:
- Database connectivity and query execution
- End-to-end benchmark workflows
- Cross-component data flow

**Characteristics:**
- Moderate execution time (1-10 seconds)
- Real database connections
- File system operations
- Network access (when applicable)

### Performance Tests (`performance/`)
Tests focused on performance characteristics:
- Query execution benchmarks
- Data generation performance
- Memory usage analysis
- Scalability testing

**Characteristics:**
- Longer execution time (10+ seconds)
- Resource monitoring
- Statistical analysis
- Baseline comparisons

### Specialized Tests (`specialized/`)
Tests for advanced or specialized functionality:
- Advanced SQL features
- OLAP operations
- Complex benchmark workflows
- Edge cases and error conditions

**Characteristics:**
- Variable execution time
- Complex test scenarios
- Advanced feature validation
- Specialized tooling requirements

## Test Execution

### Quick Development Testing
```bash
# Run fast unit tests only
make test-fast
# or
uv run -- python -m pytest -m fast

# Run specific benchmark tests
uv run -- python -m pytest tests/unit/benchmarks/test_tpch_core.py

# Run with coverage (fast tests only - quick feedback)
make coverage-fast
# or full suite
make coverage-all
# or
uv run -- python -m pytest --cov=benchbox --cov-report=html
```

### E2E Testing
```bash
# Quick E2E tests (dry-run mode)
make test-e2e-quick
# or
uv run -- python -m pytest -m e2e_quick

# Local platform E2E tests (full execution)
uv run -- python -m pytest -m e2e_local

# All E2E tests
uv run -- python -m pytest tests/e2e/ -v

# Specific E2E test module
uv run -- python -m pytest tests/e2e/test_cli_options.py -v
```

### Comprehensive Testing
```bash
# Run all tests
make test-all
# or
uv run -- python -m pytest

# Run with parallel execution
make test-parallel
# or
uv run -- python -m pytest -n auto

# Run integration tests
make test-integration
# or
uv run -- python -m pytest -m "integration and not live_integration"

# Run performance tests
uv run -- python -m pytest tests/performance/ -m performance
```

### Using the Unified Test Runner
```bash
# Run optimized development tests
uv run -- python tests/utilities/unified_test_runner.py --strategy development

# Run CI-optimized tests
uv run -- python tests/utilities/unified_test_runner.py --strategy ci

# Run specific benchmarks with parallel execution
uv run -- python tests/utilities/unified_test_runner.py --benchmark tpch tpcds --parallel --workers 4

# Run with coverage reporting
uv run -- python tests/utilities/unified_test_runner.py --coverage --report

# Run benchmark validation
uv run -- python tests/utilities/benchmark_validator.py --benchmark all --quick-check
```

## Performance Profiling

### Basic Profiling
```bash
# Profile a test run
uv run -- python tests/utilities/performance_profiler.py python -m pytest tests/unit/

# Profile with detailed output
uv run -- python tests/utilities/performance_profiler.py --output performance_report.md python -m pytest tests/unit/

# Check for performance regressions
uv run -- python tests/utilities/performance_profiler.py --check-regressions python -m pytest tests/unit/
```

### Advanced Profiling
```bash
# Update performance baselines
uv run -- python tests/utilities/performance_profiler.py --update-baseline python -m pytest tests/unit/

# Profile specific test categories
uv run -- python tests/utilities/performance_profiler.py python -m pytest tests/integration/ -m "integration and not slow"
```

## Test Markers

Tests are organized using pytest markers for selective execution:

### Execution Characteristics
- `fast`: Quick tests suitable for development
- `slow`: Tests that take significant time
- `memory_intensive`: Tests using significant memory
- `cpu_intensive`: Tests using significant CPU
- `io_intensive`: Tests performing heavy I/O

### Test Categories
- `unit`: Unit tests
- `integration`: Integration tests
- `e2e`: End-to-end CLI tests
- `e2e_quick`: Quick E2E tests (dry-run mode)
- `e2e_local`: Local platform E2E tests
- `e2e_cloud`: Cloud platform E2E tests (dry-run)
- `e2e_dataframe`: DataFrame platform E2E tests
- `performance`: Performance tests
- `specialized`: Specialized functionality tests

### Database Support
- `sqlite`: Tests requiring SQLite
- `duckdb`: Tests using DuckDB
- `database`: Tests requiring database connections

### Benchmark Types
- `tpch`: TPC-H benchmark tests
- `tpcds`: TPC-DS benchmark tests
- `ssb`: Star Schema Benchmark tests
- `amplab`: AMPLab Big Data Benchmark tests
- `clickbench`: ClickBench tests
- `h2odb`: H2O Database benchmark tests
- `primitives`: Primitive operations tests

### Example Usage
```bash
# Run only fast unit tests
make test-dev
# or
uv run -- python -m pytest -m "unit and fast"

# Run integration tests excluding slow ones
make test-integration
# or
uv run -- python -m pytest -m "integration and not slow"

# Run TPC-H related tests
make test-tpch
# or
uv run -- python -m pytest -m tpch

# Run all tests except memory intensive ones
uv run -- python -m pytest -m "not memory_intensive"
```

## Parallel Run Mutual Exclusion (File Lock)

`tests/conftest.py` acquires a single inter-process file lock at
`~/.benchbox/test.lock` for the duration of each parallel test session. This
prevents two concurrent `pytest -n auto` runs from fighting for CPU, which
would otherwise double runtime and produce flaky timing assertions.

**Contract** (`tests/conftest.py:52-209`):

- Only the **xdist controller** process locks - workers do not. `pytest_configure`
  checks `hasattr(config, "workerinput")` to distinguish them.
- Lock is skipped when `numprocesses` is 0/None (no `-n auto`) or when
  `BENCHBOX_SKIP_TEST_LOCK=1` is set in the environment.
- Uses `fcntl.flock(LOCK_EX | LOCK_NB)` on POSIX, `msvcrt.locking` on Windows.
- On contention, the second run **fails fast** with a message identifying the
  holder (pid, start time, command) and three recovery options. See
  `tests/conftest.py:138-159`.
- The fd is held open for the whole session and released in `pytest_unconfigure`.

**When to bypass**: only for intentional concurrent debug runs. Set
`BENCHBOX_SKIP_TEST_LOCK=1` - but expect noisy timing results and CPU
contention. Do not bypass in CI.

### macOS-specific conftest branch (`tests/conftest.py:109-122`)

On macOS, xdist workers suppress `setproctitle` to avoid a
`launchservicesd` CPU storm:

> xdist calls setproctitle() twice per test (running/idle) via
> xdist.remote.worker_title(). At ~200 calls/second this triggers macOS
> launchservicesd to rebuild its process registry continuously,
> consuming 200%+ CPU and ~900 MB RSS - the actual root cause of
> the macOS beachball during parallel test runs.

The workaround walks the call stack to find the live xdist exec namespace
and replaces `worker_title` with a no-op. This is necessary because
`import xdist.remote` in an execnet `__channelexec__` namespace resolves
to a *different* module object than the one executing - so patching by
module import alone is a no-op.

This branch only fires when `sys.platform == "darwin"` and the process is
an xdist worker. Linux and Windows are unaffected.

## CI/CD Integration

### GitHub Actions Example
```yaml
name: Test Suite
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.10', '3.11', '3.12', '3.13']

    steps:
    - uses: actions/checkout@v3
    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}

    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -e .[dev]

    - name: Run fast tests
      run: |
        uv run -- python tests/utilities/unified_test_runner.py --strategy ci

    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
```

### Jenkins Pipeline Example
```groovy
pipeline {
    agent any

    stages {
        stage('Setup') {
            steps {
                sh 'python -m pip install --upgrade pip'
                sh 'pip install -e .[dev]'
            }
        }

        stage('Fast Tests') {
            steps {
                sh 'uv run -- python tests/utilities/unified_test_runner.py --strategy ci --parallel --workers 4 --output junit'
            }
            post {
                always {
                    junit 'test_results.xml'
                }
            }
        }

        stage('Integration Tests') {
            when {
                branch 'main'
            }
            steps {
                sh 'uv run -- python tests/utilities/unified_test_runner.py --mode integration --parallel --workers 2 --coverage'
            }
            post {
                always {
                    publishHTML([
                        allowMissing: false,
                        alwaysLinkToLastBuild: true,
                        keepAll: true,
                        reportDir: 'htmlcov',
                        reportFiles: 'index.html',
                        reportName: 'Coverage Report'
                    ])
                }
            }
        }
    }
}
```

## Test Configuration

### pytest.ini
The enhanced `pytest.ini` provides:
- Comprehensive marker definitions
- Parallel execution configuration
- Coverage reporting setup
- Performance optimization settings
- CI/CD friendly defaults

### conftest.py
Global test configuration including:
- Database fixtures
- Data generation helpers
- Performance monitoring setup
- Cleanup utilities

## Best Practices

### Writing Tests
1. **Use appropriate markers**: Mark tests with relevant categories and characteristics
2. **Keep tests focused**: Each test should verify one specific behavior
3. **Use fixtures**: Leverage shared fixtures for database connections and test data
4. **Handle resources**: Ensure proper cleanup of temporary files and connections
5. **Performance awareness**: Use performance markers for resource-intensive tests

### Test Organization
1. **Follow naming conventions**: Use descriptive test names with `test_` prefix
2. **Group related tests**: Organize tests by functionality and component
3. **Use clear assertions**: Make test failures easy to understand
4. **Document complex tests**: Add docstrings for complex test scenarios

### Performance Testing
1. **Establish baselines**: Use the performance profiler to set baseline metrics
2. **Monitor regressions**: Regularly check for performance regressions
3. **Profile selectively**: Only profile tests when needed to avoid overhead
4. **Optimize test execution**: Use caching and parallel execution for faster feedback

## Troubleshooting

### Common Issues

#### Slow Test Execution
```bash
# Profile test execution
uv run -- python tests/utilities/performance_profiler.py python -m pytest tests/unit/ -v

# Run only fast tests
make test-fast
# or
uv run -- python -m pytest -m fast

# Use parallel execution
make test-parallel
# or
uv run -- python -m pytest -n auto
```

#### Memory Issues
```bash
# Run memory-intensive tests separately
uv run -- python -m pytest -m "memory_intensive" --maxfail=1

# Monitor memory usage
uv run -- python tests/utilities/performance_profiler.py --output memory_report.md python -m pytest tests/unit/
```

#### Database Connection Issues
```bash
# Run database tests with verbose output
make test-integration
# or
uv run -- python -m pytest tests/integration/ -v -s

# Test database connectivity
uv run -- python -c "import duckdb; print(duckdb.connect().execute('SELECT 1').fetchone())"
```

### Test Cache Management
```bash
# Clear pytest cache
uv run -- python -m pytest --cache-clear

# Clear custom test cache
uv run -- python tests/utilities/unified_test_runner.py --help

# Run with dry-run to see commands
uv run -- python tests/utilities/unified_test_runner.py --dry-run
```

## Contributing

When adding new tests:

1. **Choose the right category**: Place tests in the appropriate directory
2. **Add proper markers**: Mark tests with relevant characteristics
3. **Update documentation**: Add test descriptions to this README
4. **Consider performance**: Mark resource-intensive tests appropriately
5. **Test your tests**: Ensure new tests pass in isolation and with the full suite

### Adding New Test Categories
1. Create subdirectory in appropriate category
2. Add `__init__.py` file
3. Update markers in `pytest.ini`
4. Add documentation to this README
5. Update test runner configuration if needed

## Performance Monitoring

The test suite includes comprehensive performance monitoring:

- **Execution time tracking**: Monitor test duration trends
- **Memory usage analysis**: Track memory consumption patterns
- **CPU utilization**: Monitor CPU usage during test execution
- **I/O monitoring**: Track file system operations
- **Regression detection**: Automatically detect performance regressions

Performance data is stored in `~/.benchbox/test_cache/` and can be analyzed using the performance profiler utility.

## Test Utilities

The test suite includes several unified utilities for efficient testing:

- `utilities/unified_test_runner.py`: Comprehensive test runner with multiple execution strategies
- `utilities/benchmark_validator.py`: Unified benchmark validation utility
- `utilities/performance_profiler.py`: Performance monitoring and profiling
- `utilities/test_helpers.py`: Common test helper functions
- `utilities/test_runner.py`: Enhanced test runner with caching capabilities

These utilities provide a modern, efficient approach to testing and validation.

**Note**: Minimal tests have been moved to the `specialized/` directory:
- `specialized/test_tpch_minimal.py`: Minimal tests for TPC-H that don't require data generation
- `specialized/test_tpcds_minimal.py`: Minimal tests for TPC-DS that don't require data generation

## Support

For issues with the test suite:
1. Check this README for common solutions
2. Review test output for specific error messages
3. Use the performance profiler to identify bottlenecks
4. Consult the main BenchBox documentation
5. Open an issue with detailed reproduction steps
