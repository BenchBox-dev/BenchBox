<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# BenchBox Test Suite

This directory contains the BenchBox test suite. Directories group tests by purpose;
pytest markers select the execution lanes.

**See also**: [`AGENTS.md`](../AGENTS.md) for the contributor/agent guide, and [`docs/development/`](../docs/development/) for architecture deep-dives.

## Test Structure

```
tests/
├── contracts/                # Shared contract fixtures
├── databases/                # Local test database helpers
├── docs/                     # Documentation checks and test plans
├── e2e/                      # End-to-end CLI workflow tests
├── examples/                 # Example usage checks
├── fixtures/                 # Shared test fixtures
├── integration/              # Integration tests
├── parity/                   # Parity fixtures and generators
├── performance/              # Performance tests
├── system/                   # Repository and CI system checks
├── uat/                      # User acceptance checks and support code
├── unit/                     # Unit tests
├── utilities/                # Test utilities and helpers
├── validation/               # Data and query validation checks
├── test_*.py                 # Root-level benchmark and runner tests
├── conftest.py              # Global pytest configuration
└── README.md               # This file
```

Pytest uses the root `pytest.ini` by default (fast local runs). CI-oriented
targets such as `make test-ci` and `make coverage-fast` explicitly select the
root `pytest-ci.ini` profile with `pytest -c pytest-ci.ini`.

## Test Categories

### Unit Tests (`unit/`)
Tests of individual components:
- **benchmarks/**: Core benchmark functionality
- **core/**: Base classes and utilities
- **generators/**: Data generation components

Many are isolated and fast, but the directory does not itself guarantee a
runtime or absence of external dependencies. Select the `fast` marker for the
curated fast lane.

Unit tests derive checkout paths from `tests.utilities.paths.REPO_ROOT`, not
the caller's working directory. The early pytest plugin acquires the shared
test lock before creating a disposable HOME, so conftest imports and collection
cannot read the caller's BenchBox configuration. Each unit test then receives
a fresh HOME. Child pytest processes share only a verified ancestor's live
lock, including collection-only subprocesses.

The required state detector checks cwd, every environment key, and registered
raw quiet/config-provider globals after fixture teardown. It restores leaked
state and reports a teardown error without printing environment values. Use
`monkeypatch` or an owned context for intentional changes. Existing reset safety
nets defer to that final check rather than hiding leaks. Unit CLI invocations
own their quiet/provider state because CliRunner does not exit a real CLI
process. Patch wall clocks at the consuming module, not globally, so timeout
and watchdog clocks keep running.

### Skew Generator Reference Snapshots

The [skew-generator byte test](unit/core/tpch_skew/test_skew_generator_coverage.py)
compares streamed table output with SHA256 snapshots captured from the original
in-memory transformer at seed 42. These snapshots detect changes from that
implementation baseline; they do not independently establish the correctness of
the skew distribution. The original provenance statement records no separate
transformer version.

### E2E Tests (`e2e/`)
End-to-end tests that validate complete CLI workflows:
- CLI option validation
- Error handling coverage
- Result schema validation
- Local platform execution
- Cloud platform dry-run workflows
- DataFrame platform workflows

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
- Real database connections
- File system operations

Integration tests may use local services; live network tests use the
`live_integration` marker and are excluded from the default local lanes.

### Performance Tests (`performance/`)
Tests focused on performance characteristics:
- Query execution benchmarks
- Data generation performance
- Memory usage analysis
- Scalability testing

This directory includes resource monitoring, statistical analysis, and
baseline comparisons. Use the `fast`, `medium`, `slow`, `stress`, and
`resource_heavy` markers to select tests by execution cost rather than by
directory name.

## Test Execution

### Automated Gate Contract

The standard gates are intentionally split by the risk they are meant to catch:

- `make test-fast`: quick developer and develop-PR feedback for code-impacting
  changes. The matching selection in `.github/workflows/ci.yml` also collects
  coverage.
- `make test-correctness-gate`: bounded develop-PR real-result gate. It runs the
  DuckDB TPC-H matrix slice (SF=1, pinned reference qgen seed) through generate,
  load, and execute, then validates the emitted stream-0 results against the stored
  TPC-H answers with EXACT row-count checking **and** stored VALUE digests. The
  gated subset is the 18 TPC-H queries whose answer-set cardinalities are stable
  across dbgen builds; Q11/Q16/Q18/Q20 are excluded because their HAVING/threshold
  boundaries make the stored row count vary with the generated data. The subset is
  deliberately *discriminating* — it is not dominated by one-row queries and
  includes multiple high-cardinality answer-backed queries (e.g. Q9=175, Q2/Q21=100)
  — so a wrong join/filter/aggregate that still emits one row is caught. The subset
  shape is ratcheted in `tests/unit/test_standardized_test_commands.py`
  (`TestCorrectnessGateOracle`). What the gate proves and what it does not:
  - **Value + cardinality at SF=1/pinned-seed**: with `BENCHBOX_EMIT_RESULT_DIGEST=1`
    the runner emits an order-normalized digest of each stream-0 query's *full*
    result set (reusing `benchbox.core.tpchavoc.validation.calculate_checksum`, the
    same primitive the TPC-Havoc gates use), which the gate asserts against a stored
    reference digest (`benchbox/core/expected_results/reference_digests/tpch_value_digests_sf1.json`)
    in addition to the row count. So a wrong-but-same-cardinality answer — a perturbed
    Q1 aggregate, a swapped column, a changed rounding — turns the gate RED, not just
    a wrong row count. Sensitivity is proven in
    `tests/unit/test_correctness_gate_value_oracle.py`.
  - **Regression snapshot, NOT an independent oracle**: the reference digests were
    produced by running benchbox-on-DuckDB and frozen, so the value check detects
    *change* from that DuckDB-pinned baseline (a regression tripwire), not correctness
    against an external authority. A conceptual value bug present at *freeze time* is
    enshrined in the reference, not caught. Read a green `value+cardinality` cell as
    "unchanged from the frozen DuckDB answer", never "values proven correct". The
    reference is regenerated (never hand-copied) by `make correctness-gate-digests-regen`,
    which reruns the same gate config and writes the file idempotently. The independence
    gap and the deferred cross-engine upgrade are analyzed in
    `_project/analysis/value-digest-cross-engine-independence-decision.md`. Two further
    fidelity properties are pinned in `test_correctness_gate_value_oracle.py`: the
    sensitivity floor is **relative** (~1e-6 per cell via significant-figure rounding,
    uniform across column magnitude), and the digest is a **value+type** digest
    (DuckDB-pinned), which is why cross-engine reuse is deferred.
  - **Values are UNGUARDED above SF=1**: stored answers and digests exist only at
    SF=1 (the expected-results loader raises for other scales), so the value
    guarantee holds at SF=1 only. There is no expected-results value or cardinality
    oracle above SF=1.
  - **Strict arming (both axes)**: with `BENCHBOX_STRICT_EXPECTED_RESULTS=1`, every
    configured query *must* produce a non-SKIP row-count validation **and**, where a
    reference digest exists, an evaluated value digest, or the run fails. A missing
    digest disarms RED, never green. This is not gated on benchmark name or scale, so
    a future CI speedup that retargets the gate (a different benchmark, or SF<1 where
    no answers exist) cannot silently disarm either oracle.
  - **No-skip guard**: the Makefile target emits a JUnit report and fails unless
    exactly one node ran with zero skips. `pytest` exits 0 when a *selected* node
    SKIPs (e.g. duckdb unavailable, or the case dropped from the stable matrix),
    which would otherwise pass the gate without executing anything.
  - **Required CI job composition**: the `correctness-gate` job in
    `.github/workflows/ci.yml` runs more than this row-count+value gate. It also runs
    the value-level cross-surface and TPC-Havoc equivalence gates
    (`tpchavoc-equivalence-report`, `tpchavoc-dataframe-equivalence-report`, and the
    ssb/amplab/coffeeshop/clickbench/joinorder-synthetic cross-surface reports), so
    the required job proves value-level equivalence across several benchmarks, not
    only TPC-H row counts. This composition is ratcheted in
    `tests/unit/test_standardized_test_commands.py`.
- `make test-integration`: non-live, non-stress integration coverage for broader
  local and main/release validation.
- `make test-local-matrix`: opt-in stress matrix for the full local platform
  benchmark sweep.
- Release canary, live cloud, Docker, and UAT evidence remain separate release
  signals until their cost, credential, and flake policies are suitable for
  blocking routine PRs.

The `medium-test` job in `.github/workflows/ci.yml` runs `make test-medium`,
but only when the heavy tier is needed: code-routed runs where the event is
`merge_group` or the change touches soundness paths or packaging
(`scripts/heavy_tier_needed.py` reports `heavy-needed == 'true'`). Ordinary
code-change PRs skip it, so do not assume medium coverage ran on a routine PR.
Its marker selection excludes slow, stress, resource-heavy, and live
integration tests. Product-critical tests that need a different selection
belong in an explicit workflow or correctness gate.

### Quick Development Testing
```bash
# Run the curated fast lane
make test-fast
# or
uv run -- python -m pytest -m fast

# Run specific benchmark tests
uv run -- python -m pytest tests/unit/benchmarks/test_tpch_core.py

# Run with coverage (fast tests only - quick feedback)
make coverage-fast
# or routine coverage (excludes stress/resource-heavy/live tests)
make coverage-all
# or full tree including opt-in stress/resource-heavy/live tests (needs services + credentials)
make coverage-opt-in-all
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
uv run -- python -m pytest -m "integration and not live_integration and not stress"

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

The default is intentionally global across worktrees: ten retained worktrees
can otherwise start ten independent `pytest -n auto` runs and saturate a
developer workstation. For isolated debugging or sandboxed CI, set
`BENCHBOX_TEST_LOCK_DIR=/path/to/dir`; BenchBox will use
`$BENCHBOX_TEST_LOCK_DIR/test.lock` instead. `make test-unlock` honors the same
override.

**Contract** (`tests/conftest.py:52-216`):

- Only the **xdist controller** process locks - workers do not. `pytest_configure`
  checks `hasattr(config, "workerinput")` to distinguish them.
- Lock is skipped when `numprocesses` is 0/None (no `-n auto`) or when
  `BENCHBOX_SKIP_TEST_LOCK=1` is set in the environment.
- Lock path defaults to `~/.benchbox/test.lock`; `BENCHBOX_TEST_LOCK_DIR`
  changes only the directory, not the filename.
- Uses `fcntl.flock(LOCK_EX | LOCK_NB)` on POSIX, `msvcrt.locking` on Windows.
- On contention, the second local run waits up to 3600 seconds with holder
  information and periodic progress messages. Set
  `BENCHBOX_TEST_LOCK_WAIT_SECONDS=0` to fail immediately; CI does this.
  Ctrl-C cancels the wait without disturbing the holder.
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
        python-version: ['3.11', '3.12', '3.13', '3.14']

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

## Fixture Boundaries

The SDK reload tests in `unit/platforms/aws/test_emr_serverless_paths.py` and
`unit/platforms/gcp/test_dataproc_serverless_paths.py` check imports under
controlled `sys.modules` entries. Cleanup restores the previous entries and
reloads the adapter. Do not assert SDK availability after restoration: installed
boto3 and Google Cloud packages depend on the local environment.

`unit/tpcds/test_parameter_log.py` uses a shortened Q8 parameter-log fixture with
three ZIP entries. The upstream `query8.tpl` defines 400 ZIP values. The excerpt
checks parsing of repeated values; it does not cover all 400 values or establish
the order of a complete generated log.

## Test Utilities

The test suite includes several unified utilities for efficient testing:

- `utilities/unified_test_runner.py`: Comprehensive test runner with multiple execution strategies
- `utilities/benchmark_validator.py`: Unified benchmark validation utility
- `utilities/performance_profiler.py`: Performance monitoring and profiling
- `utilities/test_helpers.py`: Common test helper functions
- `utilities/test_runner.py`: Enhanced test runner with caching capabilities

These utilities provide a modern, efficient approach to testing and validation.

## Support

For issues with the test suite:
1. Check this README for common solutions
2. Review test output for specific error messages
3. Use the performance profiler to identify bottlenecks
4. Consult the main BenchBox documentation
5. Open an issue with detailed reproduction steps

## CPU identity test isolation

In [test_system_info.py](unit/utils/test_system_info.py), replace
`benchbox.utils.system_info._proc_cpuinfo_model` to control that fallback read.
Do not replace `builtins.open` for this purpose: psutil also reads `/proc` on
Linux, so a broad replacement can fail an unrelated psutil call while appearing
to work on macOS. Preserve separate hardware detection and fallback assertions.

## Regression fixtures and interpretation

Keep regression expectations independent of implementation constants. Names,
assertions, parameter data and recorded fixtures describe the checked behavior;
the notes below preserve constraints that matter when extending these tests.
Offline or mocked checks establish their asserted contracts, rather than live
service certification or complete SQL compliance.

### Isolation and ownership

- [Script fixtures](unit/scripts/conftest.py) make `scripts/` importable.
  Tests for the BenchBox adapter boundary load `_project/scripts` explicitly.
- [DataFrame memory fixtures](unit/platforms/dataframe/conftest.py) opt in to
  sufficient-memory injection. Keep them non-autouse so memory-policy tests
  still exercise actual capacity decisions and insufficient-memory behavior.
- [Q17 Spark tests](unit/core/tpch/test_q17_spark_execution.py) own a local Spark
  session and restore Java/PySpark environment changes with a monkeypatch
  context. Adapter fixtures detach the shared session instead of closing it;
  the module fixture stops it. LakeSail coverage here exercises its inherited
  expression client, not a Sail server.
- [CLI result tests](unit/cli/commands/test_results.py) reset the Rich console
  singleton, disable quiet mode and use a wide capture console. Preserve literal
  bracket-containing paths rather than interpreting them as Rich markup.
  [Export consistency tests](unit/cli/test_run_export_consistency.py) obtain the
  run submodule from `sys.modules` and patch its object: the package also exports
  a Click command named `run`, so attribute lookup can select the wrong target.
- [Monitoring tests](unit/monitoring/test_performance_monitoring.py) close the
  `mkstemp` descriptor before using its path. Cleanup tolerates a tracker-held
  Windows file; that tolerance is not an assertion that deletion succeeded.
- GPU [metrics](unit/experimental/gpu/test_metrics_error_capture.py) and
  [version detection](unit/experimental/gpu/test_capabilities_error_capture.py)
  inject failures without CUDA/NVML hardware. Version detection disables earlier
  branches to reach a malformed temporary version file through `CUDA_HOME`.
- [Offline adapter tests](unit/platforms/test_offline_adapter_missing_sdks.py)
  run actual inventory assertions in a fresh process with vendor SDK imports
  blocked. Keep the child assertion-enabled and its explicit optimization guard;
  remove inherited `PYTHONOPTIMIZE` before launching it. Startup and cold imports
  justify its medium tier, rather than treating it as a fast assertion-only test.
- [Soundness history tests](unit/test_soundness_review_history.py) use real
  fetches and trusted checker subprocesses, which exceed the fast-test budget.
  [Release artifact tests](unit/scripts/test_release_artifact_consumer.py) retain
  their medium marker; consumer tests also import this module. Reassess measured
  budgets and CI tier wiring before changing that selection.
- [Marker tests](unit/test_marker_strategy.py) cache the discovered test modules
  to avoid repeated tree scans. Collection may enforce quarantine and budgets,
  but must not rewrite speed markers. In [SQL compatibility tests](unit/core/sql_compat),
  name benchmark parameters `bmark`: pytest-benchmark owns the `benchmark` fixture,
  and shadowing it can fail collection.

### Data and SQL regression boundaries

- [NYC Taxi](unit/core/nyctaxi/test_source_contract.py) pins its TLC file set;
  [FlightData](unit/core/flightdata/test_source_contract.py) ends month windows at
  the pinned BTS month. New upstream data must not silently change a scale
  factor's dataset. These tests are offline. A ZIP without CSV follows the
  download-failure cleanup path, not an uncaught-error path.
- TPC-DS SQL depends on data scale: [bulk query retrieval](unit/tpcds/test_get_queries_scale.py),
  [benchmark fakes](unit/core/test_tpcds_benchmark_fakes.py) and the
  [equivalence reference builder](unit/core/equivalence/test_tpcds_gate_scale.py)
  preserve matching scales. Q9 and Q44 illustrate scale-dependent templates;
  the equivalence regression also names Q46 and Q68. The fake generator checks
  forwarding; it does not establish binary generation correctness.
- [TPC-H subsets](unit/core/tpch/test_power_test_query_subset.py) accept bare and
  Q-prefixed IDs because the CLI forwards selected query IDs verbatim.
  [TPC-DS identity tests](unit/scripts/test_tpcds_platform_identity.py) compare
  repeated same-seed manifests on one platform before interpreting cross-platform
  differences; unavailable binaries retain their explicit skip conditions.
- [TPC-H manifest tests](unit/core/tpch/test_tpch_manifest_row_counts.py) exercise
  discovery of all compressed shards even when passed one shard. Reuse describes
  existing bytes, not a new generator's compression flags.
  [Compressed Data Vault tests](unit/core/datavault/test_compressed_source_buffers.py)
  retain the two-shard, 512 MB reproduction with plain input as the row-identity
  reference. This fixture targets the compressed-stream seek failure observed
  with DuckDB 1.5.5; it is not a general memory-capacity guarantee.
- [TPC-DS-OBT comparisons](unit/core/tpcds_obt/test_tpcds_obt_dataframe_queries.py)
  compare values as well as shape, including empty-set zero results for
  Q10/Q15/Q16. [SSB tuning](unit/core/tuning/test_tpc_workload_profiles.py) excludes
  `LO_ORDERKEY`: LINEORDER is denormalized and has no ORDERS join. The
  [replication prototype](unit/core/joinorder_replicated/test_replication_prototype.py)
  keeps company-type lookup identities shared across replicas.
- [Firebolt DDL](unit/core/tuning/generators/test_firebolt_ddl.py) stores the full
  `PRIMARY INDEX` clause in `distribute_by`. [ClickHouse DDL](unit/core/tuning/generators/test_clickhouse_ddl.py)
  stores a bare partition-column list but wraps it at rendering as a single
  partition expression for both single and multiple columns.
- Query-plan tests use recorded fixtures without their live services. Preserve
  Firebolt nested-parenthesis details, Synapse's RETURN root and linear chain,
  Snowflake's real Result root over stray parentless nodes, and Fabric's dedicated
  SHOWPLAN_TEXT handling that excludes the initial statement row. ClickHouse
  column expansion and multi-word names are not relational joins or table names.
  Presto/Starburst/Athena wiring uses a fake DBAPI cursor with recorded EXPLAIN JSON,
  reusing the connection to inspect the last SQL.
- Light [DSDGen](validation/test_dsdgen_integration_light.py) and
  [DSQGen](validation/test_dsqgen_integration_light.py) tests require the actual
  platform binaries. DSDGen streams a small table and checks compressed output;
  DSQGen validates base-query generation without assuming every template set
  contains variants. [Plan comparison performance](performance/test_comparison_performance.py)
  measures ten comparisons of 200-node chains against a one-second budget.

### Producers, consumers and publication

- Public-export [environment fixtures](unit/core/results/test_environment_schema_compatibility.py)
  reject dropped identifier keys anywhere in serialized output.
  [Client-link wiring](unit/platforms/base/test_client_link_wiring.py) cannot break
  a successful run when collection fails, and records unavailable when neither
  region nor overhead exists. Keep link fields nested in result payloads;
  DataFrame engines collect the locality half without a SQL overhead probe.
- [Provenance bundles](unit/core/results/test_provenance_bundle.py) omit the
  optional block for absent/empty funding and source rather than emitting an empty
  dictionary. [Timing payloads](unit/core/results/test_schema_timing_contract.py)
  retain credential redaction, explicit producer tagging and the missing-run-type
  fallback. [Result status](unit/core/results/test_status.py) distinguishes
  unexecuted validation from executed failure: unvalidated results are non-clean
  for publication without necessarily failing the CLI. Its unvalidated set is
  the non-clean set minus CLI-failure statuses.
- [Databricks cache tests](unit/platforms/test_databricks_cache_control.py) keep
  session setup outside the first measured harness query. Concrete adapters
  explicitly declare plan-capture phase eligibility; registry wrappers read the
  currently rebound registry singleton. Adapter config helpers preserve plan
  options and skip `None` values. Redshift query errors and Firebolt load errors
  retain complete nonempty driver messages, with defensive empty-message handling.
- [Livy tests](unit/platforms/azure/test_livy_mixin.py) preserve statement timing
  and counts, wait delegation and abstract header/session hooks. Azure credential
  fixtures inject the credential class and refresh five minutes before expiry.
  GCS path tests retain ConfigurationError wording, empty bucket-only prefixes
  and trailing-slash normalization shared by Dataproc adapters.
- [Corpus digest tests](unit/scripts/publication/test_db_digest.py) compare
  canonical logical content rather than database file bytes: build timestamps
  and bounded floating-point noise are ignored, while content changes differ.
  Explorer ranking rejects unofficial compliance even with an eligible trust
  label. The read-model version expectation is an independent migration pin;
  update it with the compatibility matrix deliberately, not by copying a changed
  production constant.
- [Promotion fixtures](unit/scripts/publication/test_verify_corpus_promotion.py)
  isolate inventory/site failures by substituting privacy and bijection checks;
  they do not establish those checks independently. Candidate archive validation
  packages real files; linear Git fixture helpers return oldest-first commits,
  and parent-bound fixtures retain their manifest generation/digest relationship.
- Trusted mirror publication may allow partial validation while community
  submission may not; privacy and inventory still apply. Corpus workflows use
  trusted-base code, explicit permits and parity checks. Empty changed-corpus
  lists do not bypass a separately required manifest. Release tag finalization
  binds the verified merge commit and recovers a tag created before its push.
- Release-tree tests tolerate the intentional absence of development-only
  `_project` files. Code-owner ruleset tests assert that specific predicate, not
  a branch-wide approval count. The project-reference guard rejects new stale
  paths while retaining its protected historical baseline. Lock revision guards
  reject decreases while permitting unchanged or increased revisions.
- Explorer override fixtures traverse bundle and override companion publication
  together. Static receipt tests check presentation-file contracts, not browser
  rendering. Notebook content tests accept declared platform extras or explicit
  dependencies and require a core-runner reference; those textual checks do not
  prove notebook execution or installed extra contents.
