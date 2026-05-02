# Dependency Compatibility Matrix

```{tags} contributor, reference
```

BenchBox ships a single source of dependency metadata in `pyproject.toml`.
The resolved versions are captured in `uv.lock`, which is consumed by CI and
local development through `uv`. Dependency validation now happens via an
explicit check so changes cannot drift silently.

## Supported Python Versions

- Declared range: `>=3.9,<3.15`
- Solver markers (from `uv.lock`):
  - `python_full_version >= '3.14' and platform_python_implementation != 'PyPy'`
  - `python_full_version == '3.13.*' and platform_python_implementation != 'PyPy'`
  - `python_full_version >= '3.13' and platform_python_implementation == 'PyPy'`
  - `python_full_version == '3.12.*'`
  - `python_full_version == '3.11.*'`
  - `python_full_version == '3.10.*'`
  - `python_full_version < '3.10'`

These markers mirror the lock file resolution and offer early warning if a
future interpreter release needs bespoke packaging rules.

## Core Dependencies

| Package | Specifier |
| ------- | --------- |
| sqlglot | `>=20.0.0` |
| pytest-xdist | `>=3.8.0` |
| pytest-benchmark | `>=5.1.0` |
| pytest-cov | `>=6.2.1` |
| click | `>=8.0.0` |
| rich | `>=13.0.0` |
| psutil | `>=5.9.0` |
| pydantic | `>=2.0.0` |
| pyyaml | `>=6.0.0` |
| packaging | `>=24.0` |
| duckdb | `>=1.0.0,<1.4.0` |

DuckDB is capped below 1.4.0 across the development, `all`, `duckdb`, and
`explorer` dependency paths until the browser runtime moves beyond
`@duckdb/duckdb-wasm` 1.32.x. Newer native DuckDB writers can emit
`results.duckdb` snapshots that the current WASM reader fails to attach.

## Optional Extras

| Extra | Dependencies |
| ----- | ------------ |
| all | `clickhouse-driver>=0.2.0`, `databricks-sql-connector>=2.0.0`, `google-cloud-bigquery>=3.0.0`, `google-cloud-storage>=2.0.0`, `redshift-connector>=2.0.0`, `snowflake-connector-python>=3.0.0`, `boto3>=1.20.0`, `cloudpathlib>=0.15.0` |
| bigquery | `google-cloud-bigquery>=3.0.0`, `google-cloud-storage>=2.0.0`, `cloudpathlib>=0.15.0` |
| clickhouse | `clickhouse-driver>=0.2.0` |
| cloud | `databricks-sql-connector>=2.0.0`, `google-cloud-bigquery>=3.0.0`, `google-cloud-storage>=2.0.0`, `redshift-connector>=2.0.0`, `snowflake-connector-python>=3.0.0`, `boto3>=1.20.0`, `cloudpathlib>=0.15.0` |
| databricks | `databricks-sql-connector>=2.0.0`, `cloudpathlib>=0.15.0` |
| dev | `pytest>=8.0.0`, `pytest-cov>=4.1.0`, `pytest-benchmark>=4.0.0`, `pytest-xdist>=3.0.0`, `duckdb>=1.0.0,<1.4.0`, `tox>=4.13.0` |
| docs | `sphinx>=7.2.0`, `sphinx-rtd-theme>=2.0.0`, `myst-parser>=2.0.0` |
| redshift | `redshift-connector>=2.0.0`, `boto3>=1.20.0`, `cloudpathlib>=0.15.0` |
| snowflake | `snowflake-connector-python>=3.0.0`, `cloudpathlib>=0.15.0` |

## Running the Validation Command

Use the new `Makefile` target to validate dependencies and show the compatibility
matrix:

```bash
make dependency-check            # Validate lock vs. pyproject specs
make dependency-check ARGS=--matrix  # Also print compatibility summary
```

Under the hood this calls `python -m benchbox.utils.dependency_validation`,
which parses both files and fails fast if a declared dependency has no matching
locked version. Incorporate the command into feature branches whenever
dependencies change, and expect CI to run it automatically.
