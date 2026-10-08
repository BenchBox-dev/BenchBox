<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Testing Documentation

```{tags} contributor, testing
```

Documentation for testing BenchBox functionality, including live integration tests.

## Test Documentation

- [Pytest xdist Safety](../development/pytest-xdist-safety.md) - Why BenchBox caps local xdist workers and how to validate changes
- [Test tiers and duration budgets](../development/test-tier-policy.md) - Measured T1/T2/T3 policy and quarantine markers
- [Docker Integration Tests](docker-integration-tests.md) - Running real tests against database engines in Docker containers (free, no credentials)
- [Live Integration Tests](live-integration-tests.md) - Running integration tests against live cloud database platforms

## Test Categories

### Unit Tests
Fast, isolated tests for individual components without external dependencies.

```bash
make test-unit
uv run -- python -m pytest -m unit
```

The two commands are alternatives.

### Integration Tests
Tests that verify interaction between components, may use embedded databases.

```bash
make test-integration
uv run -- python -m pytest -m "integration and not live_integration"
```

The two commands are alternatives.

### E2E Tests
End-to-end tests that validate complete benchmark workflows through the CLI.

```bash
uv run -- python -m pytest -m e2e_quick

uv run -- python -m pytest -m e2e_local

uv run -- python -m pytest tests/e2e/
```

The `e2e_quick` marker runs quick E2E tests in dry-run mode, `e2e_local` runs local platform E2E tests with full execution, and the last command runs all E2E tests.

E2E tests cover:
- CLI option validation (`--benchmark`, `--scale`, `--phases`, `--queries`, etc.)
- Error handling for invalid parameters
- Result file validation and schema compliance
- Local platforms (DuckDB, SQLite, DataFusion)
- Cloud platforms (dry-run mode for Snowflake, BigQuery, etc.)
- DataFrame platforms (Polars, Pandas, Dask)

See [E2E Testing Guide](e2e-testing.md) for detailed information.

### Docker Integration Tests
Tests that execute real queries against database engines running in Docker containers.
No cloud credentials needed: just Docker.

```bash
make test-docker-clickhouse

make test-docker-all
```

The first command tests a single platform and the second tests all Docker platforms.

See [Docker Integration Tests](docker-integration-tests.md) for platform list and setup.

### Live Integration Tests (Cloud)
Tests that require live database credentials and cloud platforms.

```bash
make test-live
uv run -- python -m pytest -m live_integration
```

The two commands are alternatives.

See [Live Integration Tests](live-integration-tests.md) for detailed setup instructions.

## Related Documentation

- [Development Guide](../development/development.md) - Development environment setup
- [Testing Guide](../development/testing.md) - Test organization and strategies
- [Pytest xdist Safety](../development/pytest-xdist-safety.md) - xdist root cause, cap behavior, and validation checklist
- [CI/CD Integration](../advanced/ci-cd-integration.md) - Automated testing workflows

```{toctree}
:maxdepth: 1
:caption: Testing Guides
:hidden:

e2e-testing
docker-integration-tests
live-integration-tests
```
