# Installation & Environment Setup

```{tags} beginner, quickstart
```

BenchBox targets Python 3.10+ and ships as a single Python package. The recommended workflow uses [uv](https://docs.astral.sh/uv/) for fast installs, but the commands below include alternatives for `pip` and `pipx`.

## 1. Install BenchBox

```bash
# Recommended: uv (modern package management)
uv add benchbox

# Alternative (pip-compatible)
uv pip install benchbox

# Traditional pip (uses the active Python environment)
python -m pip install benchbox

# pipx for a dedicated CLI environment
pipx install benchbox
```

BenchBox installs a `benchbox` executable. If you use `uv`, prefer `uv run benchbox <command>` to ensure the project virtual environment is activated automatically.

(installation-extras)=
## 2. Pick Optional Extras

Extras keep the base install lean.

| Extra | Enables | Recommended (uv) | Alternative (pip-compatible) |
| --- | --- | --- | --- |
| `(none)` | SQLite only (core package, no DuckDB) | `uv add benchbox` | `uv pip install benchbox` |
| `[duckdb]` | DuckDB for local analytics | `uv add benchbox --extra duckdb` | `uv pip install "benchbox[duckdb]"` |
| `[cloudstorage]` | Cloud path helpers (S3, GCS, Azure) | `uv add benchbox --extra cloudstorage` | `uv pip install "benchbox[cloudstorage]"` |
| `[cloud]` | Databricks, BigQuery, Redshift, Snowflake connectors | `uv add benchbox --extra cloud` | `uv pip install "benchbox[cloud]"` |
| `[clickhouse]` | ClickHouse native driver | `uv add benchbox --extra clickhouse` | `uv pip install "benchbox[clickhouse]"` |
| `[databricks]` / `[bigquery]` / `[redshift]` / `[snowflake]` | Single-platform installs | `uv add benchbox --extra databricks` | `uv pip install "benchbox[databricks]"` |
| `[all]` | Everything listed above | `uv add benchbox --extra all` | `uv pip install "benchbox[all]"` |

### Cloud Spark Platforms

For managed Spark platforms, use provider-specific extras to install only the dependencies you need:

| Extra | Platforms | Dependencies |
| --- | --- | --- |
| `[cloud-spark-aws]` | AWS Glue, EMR Serverless, Athena Spark | boto3 |
| `[cloud-spark-gcp]` | Google Cloud Dataproc, Dataproc Serverless | google-cloud-dataproc, google-cloud-storage |
| `[cloud-spark-azure]` | Azure Synapse Analytics Spark, Fabric Spark | azure-identity, azure-storage-file-datalake, requests |
| `[cloud-spark-snowflake]` | Snowflake Snowpark | snowflake-snowpark-python, pyspark |
| `[cloud-spark-databricks]` | Databricks Connect | databricks-connect, databricks-sdk |
| `[cloud-spark]` | All cloud Spark platforms | All of the above |

```bash
# AWS users: Install only AWS Spark dependencies
uv add benchbox --extra cloud-spark-aws

# Multi-cloud: Install all cloud Spark dependencies
uv add benchbox --extra cloud-spark

# Combine with other extras
uv add benchbox --extra cloud-spark-aws --extra athena
```

### Combining Extras

```bash
# Recommended: Enable all cloud platforms and ClickHouse
uv add benchbox --extra cloud --extra clickhouse

# Alternative (pip-compatible)
uv pip install "benchbox[cloud,clickhouse]"
```

Re-run the installer at any time to add extras. For `pipx`, use `pipx inject benchbox "benchbox[cloud]"`.

## 3. Verify the CLI

```bash
uv run benchbox --version
```

The command prints the current BenchBox version and validates that `pyproject.toml`, `benchbox/__init__.py`, and doc version markers match.

## 4. Run Dependency Checks

`benchbox check-deps` inspects optional connectors and suggests install commands.

```bash
# Overview of all platforms
uv run benchbox check-deps

# Detailed matrix with extras guidance
uv run benchbox check-deps --matrix

# Focus on a single platform
uv run benchbox check-deps --platform snowflake --verbose
```

## 5. Create a Workspace (Optional)

BenchBox stores generated data and results under `benchmark_runs/` by default. Set a custom location with `--output PATH` when invoking `benchbox run`, or point to cloud storage such as `s3://` or `gs://` if the corresponding extras are installed.

For repeatable environments, initialise a project-level virtual environment with `uv venv .venv && source .venv/bin/activate` (or the Windows equivalent) before running the commands above.

## Next Steps

- Follow the [5-minute walkthrough](getting-started.md) for your first benchmark.
- Browse the [CLI quick reference](cli-quick-start.md) to learn the most-used commands.
- Keep [Troubleshooting](troubleshooting.md) handy for resolving dependency or connectivity issues.
