(driver-version-management)=
# Driver Version Management

```{tags} intermediate, guide, driver, versioning
```

When running benchmarks, BenchBox uses the Python database driver (e.g. `duckdb`,
`snowflake-connector-python`) that is installed in the current environment. This guide
explains how version selection works and how to reliably benchmark a specific driver
version, including dev builds and pre-release releases.

## How BenchBox Selects a Driver Version

BenchBox follows this order:

1. **Explicit pin**: If `--platform-option driver_version=X.Y.Z` is set, BenchBox
   validates that the requested version is installed. If `driver_auto_install=true` is
   also set, BenchBox installs it automatically via uv.
2. **Current environment**: If no version is requested, BenchBox uses whatever is
   installed in the current Python environment (detected via `importlib.metadata`).

The version that actually ran is always recorded in the result JSON under
`execution.driver_version_actual` and displayed in the CLI announcement line:

```
Running tpch on duckdb at scale 1.0 [driver 1.4.3]
```

## Why Your Manually-Installed Version May Not Be Respected

If you run BenchBox via `uv run -- benchbox run ...`, uv syncs your environment against
`uv.lock` **before Python starts**. Any version you installed manually with
`uv pip install "duckdb==1.5.0"` may be silently reverted to the lock-file-pinned
version (e.g. `1.4.3`).

The result JSON will still report the version that actually ran, but you may not notice
the revert until you inspect it.

## Reliable Patterns for Testing a Specific Version

### Pattern 1: driver_auto_install (recommended)

BenchBox manages the install for the duration of the run. The lock file is not modified.

```bash
benchbox run --platform duckdb --benchmark tpch \
  --platform-option driver_version=1.5.0 \
  --platform-option driver_auto_install=true
```

This works for any platform, not just DuckDB:

```bash
# Snowflake connector
benchbox run --platform snowflake --benchmark tpch \
  --platform-option driver_version=3.12.0 \
  --platform-option driver_auto_install=true \
  --output s3://my-bucket/results/

# Polars DataFrame engine
benchbox run --platform polars-df --benchmark tpch \
  --platform-option driver_version=1.36.1 \
  --platform-option driver_auto_install=true

# ClickHouse Cloud (clickhouse-connect HTTP driver)
benchbox run --platform clickhouse-cloud --benchmark tpch \
  --platform-option driver_version=0.10.0 \
  --platform-option driver_auto_install=true \
  --platform-option host=your-instance.clickhouse.cloud \
  --platform-option password=your-password
```

### Pattern 2: uv run --with (inline override)

Override the installed package for a single invocation without touching `uv.lock`:

```bash
uv run --with "duckdb==1.5.0" benchbox run --platform duckdb --benchmark tpch
```

### Pattern 3: Update the lock file

If you want every `uv run` to use a specific version permanently:

```bash
uv add "duckdb==1.5.0" --allow-prereleases
# Re-lock and run normally
benchbox run --platform duckdb --benchmark tpch
```

This mutates `uv.lock` and is appropriate when you want a stable, reproducible
environment rather than a one-off test.

## Verifying Which Version Actually Ran

The CLI output shows the driver version immediately:

```
Running tpch on duckdb at scale 1.0 [driver 1.5.0]
```

For scripts and CI pipelines, check the result JSON:

```bash
jq '.execution.driver_version_actual' result.json
# or
jq '.platform.client_version' result.json
```

Both fields record the version that ran. `driver_version_actual` reflects what
`importlib.metadata` reported from the live process; `client_version` is populated by
the platform adapter from the driver itself.

## See Also

- {ref}`cli-configuration` - `driver_version` and `driver_auto_install` option reference
- [DuckDB Platform Guide](../platforms/duckdb.md) - DuckDB-specific version testing notes
