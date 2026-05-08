<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Test Databases

This directory contains the generation script for small embedded DuckDB databases used for testing BenchBox functionality. The databases are created automatically during test execution and cleaned up afterwards.

## Database Files (Created Automatically)

- `basic_test.duckdb` - Simple tables for connection and basic SQL testing
- `tpch_test.duckdb` - Minimal TPC-H benchmark tables with sample data
- `tpcds_test.duckdb` - Minimal TPC-DS benchmark tables with sample data
- `ssb_test.duckdb` - Star Schema Benchmark tables with sample data
- `primitives_test.duckdb` - Tables for testing OLAP operations and window functions

## Database Characteristics

- **Size**: Each database is kept small (< 5MB) for fast test execution
- **Data**: Contains minimal but representative data for testing functionality
- **Schema**: Follows the standard benchmark schemas but with reduced data volume
- **Read-Only**: Test fixtures open databases in read-only mode to prevent contamination
- **Temporary**: Created before tests run and cleaned up after tests complete
- **Not Committed**: Database files are excluded from git via .gitignore

## Usage in Tests

These databases are accessed through fixtures defined in `tests/fixtures/database_fixtures.py`:

```python
def test_example(tpch_test_db):
    # Use the TPC-H test database
    result = tpch_test_db.execute("SELECT COUNT(*) FROM customer").fetchone()
    assert result[0] > 0
```

Available fixtures:
- `basic_test_db` - Connection to basic_test.duckdb
- `tpch_test_db` - Connection to tpch_test.duckdb
- `tpcds_test_db` - Connection to tpcds_test.duckdb
- `ssb_test_db` - Connection to ssb_test.duckdb
- `primitives_test_db` - Connection to primitives_test.duckdb

## Automatic Database Management

The test databases are managed automatically by the test framework:

1. **Creation**: Databases are created before test sessions start (via `pytest_sessionstart`)
2. **On-Demand**: If a database is missing during a test, it's created automatically
3. **Cleanup**: All databases are removed after test sessions complete (via `pytest_sessionfinish`)

### Manual Database Creation

If you need to create databases manually for debugging:

```bash
uv run -- python tests/databases/create_test_databases.py
```

This will recreate all database files with fresh data.

## Design Principles

1. **No Mocks**: These databases eliminate the need for database mocking in tests
2. **Realistic Data**: Provides actual SQL execution against real data
3. **Fast Tests**: Small size ensures quick test execution
4. **Deterministic**: Same data every time for consistent test results
5. **Isolated**: Each test gets a fresh connection to prevent interference

## Benefits

- **Reliability**: Tests execute against real databases, catching SQL errors
- **Performance**: Small databases load quickly while providing realistic execution
- **Maintainability**: No complex mock setup and teardown logic
- **Accuracy**: Tests verify actual database behavior rather than mock behavior
