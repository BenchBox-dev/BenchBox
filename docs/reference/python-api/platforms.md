<!-- markdownlint-disable MD024 -->

# Platform API Reference

```{tags} reference, python-api, sql-platform
```

This section documents the supported database adapters and their shared lifecycle.

```{toctree}
:maxdepth: 1

platforms/common
platforms/duckdb
platforms/datafusion
platforms/clickhouse
platforms/databricks
platforms/bigquery
platforms/snowflake
platforms/redshift
platforms/sqlite
platforms/polars
```

## `benchbox.platforms`

<span id="benchbox.platforms"></span>

The package that exports BenchBox's platform adapter classes, the DataFrame adapter classes, and the functions that create adapters and report which platforms are available. It is a package, not a callable.

**Import:** `import benchbox.platforms` or `from benchbox.platforms import DuckDBAdapter` · **Extras:** none to import the package; each adapter's own package needs its extra (`duckdb` for DuckDB, `polars` for Polars)

### Exports

`benchbox.platforms.__all__` lists 65 names:

| Group | Count | Names |
| --- | --- | --- |
| Base types | 3 | `PlatformAdapter`, `ConnectionConfig`, `BenchmarkResults` |
| SQL platform adapters | 33 | Classes named `<Platform>Adapter`, such as `DuckDBAdapter`, `SQLiteAdapter`, `DataFusionAdapter`, `PolarsAdapter`, `DatabricksAdapter`, `SnowflakeAdapter`, `BigQueryAdapter`, `RedshiftAdapter` and `ClickHouseAdapter` |
| DataFrame adapters | 7 | `PolarsDataFrameAdapter`, `PandasDataFrameAdapter`, `CuDFDataFrameAdapter`, `DaskDataFrameAdapter`, `DataFusionDataFrameAdapter`, `PySparkDataFrameAdapter`, `LakeSailDataFrameAdapter` |
| Availability flags | 6 | `POLARS_AVAILABLE`, `PANDAS_AVAILABLE`, `CUDF_AVAILABLE`, `DASK_AVAILABLE`, `DATAFUSION_DF_AVAILABLE`, `PYSPARK_AVAILABLE` (`bool`, `True` when the library imports) |
| Other | 16 | `DataFramePlatformChecker` and the functions below |

Importing the package does not import `duckdb`, `polars` or the cloud SDKs; an adapter's module loads when its class is first accessed. Accessing a name that is not exported raises `AttributeError`.

### Functions

| Function | Returns |
| --- | --- |
| `get_platform_adapter(platform_name: str, **config)` | A configured adapter. The name is case-insensitive and aliases such as `sqlite3` are resolved; the keyword arguments go to the adapter's `from_config`. |
| `get_adapter(platform: str, mode=None, deployment=None, **config)` | An adapter for the platform in `"sql"` or `"dataframe"` mode. `get_adapter("polars")` returns a `PolarsDataFrameAdapter`. |
| `get_dataframe_adapter(platform_name: str, **config)` | A DataFrame adapter, selected by a name such as `"polars-df"`. |
| `list_available_platforms()` | `dict[str, bool]`: for each registered platform, whether its libraries are installed. |
| `list_available_dataframe_platforms()` | `dict[str, bool]`: the same for the DataFrame platforms (`polars-df`, `pandas-df`, `cudf-df`, `dask-df`, `datafusion-df`, `pyspark-df`, `lakesail-df`). |
| `get_platform_requirements(platform_name: str)` | `str`: the install command for a SQL platform, `"Unknown requirements"` for an unknown name. |
| `get_dataframe_requirements(platform_name: str)` | `str`: the same for a DataFrame platform, `"Unknown DataFrame platform"` for an unknown name. |
| `check_platform_connectivity(platform_name: str, **config)` | `bool`: `True` when an adapter for the platform connects, `False` otherwise, including for an unknown name. |
| `is_dataframe_platform(platform_name: str)` | `bool`: `True` for DataFrame platform names such as `"polars-df"`, `False` for `"polars"`, `"duckdb"` and unknown names. |
| `is_dataframe_mode(platform: str, mode=None)` | `bool`: whether the platform runs in DataFrame mode. With `mode=None` it is `True` for `"polars"` and `False` for `"databricks"`; `mode="dataframe"` makes `"databricks"` `True`. |
| `get_available_modes(platform: str)` | `list[str]`: the modes the platform supports (`['sql']` for DuckDB, `['sql', 'dataframe']` for Databricks, `['dataframe']` for Polars). |
| `get_available_deployments(platform: str)` and `get_default_deployment(platform: str)` | The deployment names of a platform (`['local']` for DuckDB, `['local', 'server']` for ClickHouse) and its default (`'local'` for DuckDB). |
| `diagnose_optional_adapter_imports(platform_names=None)` | `dict` that maps each platform name to a diagnostic record with `status`, `available`, `error_type` and `error_message`. |
| `get_lazy_adapter_diagnostics()` | `dict` of the diagnostics recorded when an adapter or flag failed to load; empty when nothing failed. |

### Raises

- `get_platform_adapter` raises `ValueError` for a platform that is not registered (`Unsupported platform: x. Available: ...`), and `RuntimeError` when the platform's driver package is not installed (for Snowflake without its connector: `Driver package 'snowflake-connector-python' is not installed...`). An adapter's own configuration errors, such as SQLite without a database path, are raised from its `from_config`.
- `get_dataframe_adapter` raises `ValueError` for a name that is not a DataFrame platform (`Unknown DataFrame platform: polars`); use `polars-df`.

### Example

```python
import benchbox.platforms as platforms
from benchbox.platforms import DuckDBAdapter, get_platform_adapter, list_available_platforms

print(len(platforms.__all__), platforms.DuckDBAdapter is DuckDBAdapter)
adapter = get_platform_adapter("DuckDB", database_path=":memory:")
print(type(adapter).__name__, adapter.database_path)

availability = list_available_platforms()
print(availability["duckdb"], platforms.is_dataframe_platform("polars-df"), platforms.get_available_modes("databricks"))

try:
    get_platform_adapter("not_a_platform")
except ValueError as exc:
    print(str(exc).split(". Available")[0])
```

Output on 0.4.1 with `duckdb` 1.5.6:

```text
65 True
DuckDBAdapter :memory:
True True ['sql', 'dataframe']
Unsupported platform: not_a_platform
```

### Compatibility

Each adapter is also importable from its own module, and both paths give the same object: `benchbox.platforms.duckdb.DuckDBAdapter` is `benchbox.platforms.DuckDBAdapter`. Per-adapter pages: {doc}`platforms/duckdb`, {doc}`platforms/polars` and the others in the list above.
