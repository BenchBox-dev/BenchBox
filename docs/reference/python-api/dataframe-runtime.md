# DataFrame Contexts and Tuning

```{tags} reference, python-api, dataframe
```

Query implementations share table access and expression helpers through a context. Pandas-family queries use string column access and Series operations. Expression queries use platform expression objects. See {doc}`dataframe-query` for query metadata, execution and registry contracts, and {doc}`/platforms/dataframe` for family architecture. These interfaces do not imply that every native DataFrame implements every protocol operation, or that benchmark results are equivalent.

## Contexts

### DataFrameContext

#### `benchbox.core.dataframe.context.DataFrameContext`

<span id="benchbox.core.dataframe.context.DataFrameContext"></span>

A runtime-checkable protocol for table access, expression construction and platform/family identity.

**Import:** `from benchbox.core.dataframe.context import DataFrameContext` · **Extras:** none

##### Tables and expressions

`get_table(name)`, `list_tables()` and `table_exists(name)` expose registered tables. `col(name)` and `lit(value)` construct platform column references (strings in the Pandas family) and literal expressions. `element()` supplies a list-element expression where supported. Polars list evaluation uses `element()` rather than a named column reference inside `eval()`. `date_sub(column, days)` and `date_add(column, days)` adjust date expressions. `cast_date(column)` and `cast_string(column)` request native date or string conversion. Query code can use these helpers without importing a native DataFrame library.

##### Window functions

`window_rank`, `window_row_number` and `window_dense_rank` require `order_by: list[tuple[str, bool]]` and accept an optional `partition_by: list[str] | None = None`. The boolean is ascending order. Rank permits gaps after ties, dense rank has no gaps, and row number assigns sequential positions. `window_sum` and `window_avg` accept a column, optional partitions and optional ordering: unordered operations aggregate a partition, while ordering requests cumulative results. `window_count` additionally allows `column=None` for row counting. `window_min` and `window_max` accept a column and optional partitions. Native adapters determine concrete expression types and supported window behavior.

##### Frame operations and identity

`union_all(*dataframes)` concatenates rows, including duplicates. `rename_columns(df, mapping)` maps old names to new names. `scalar(df, column=None)` expects a one-row result and selects the named column, or the first column when omitted. `scalar_to_df(data)` constructs one row from a dict of column names to scalar values, which avoids platform imports in query implementations. `platform` and `family` identify the adapter and its `pandas` or `expression` family.

### DataFrameContextImpl

#### `benchbox.core.dataframe.context.DataFrameContextImpl`

<span id="benchbox.core.dataframe.context.DataFrameContextImpl"></span>

```python
class DataFrameContextImpl:
    def __init__(self, platform: str, family: str) -> None: ...
```

An abstract generic base with a fresh table registry. Identity strings are stored unchanged.

**Import:** `from benchbox.core.dataframe.context import DataFrameContextImpl` · **Extras:** none

##### Table registry

`register_table(name, df)` lowercases the name and replaces any previous registration with that key. Table values are stored and returned by reference. Retrieval, membership and removal are case-insensitive, and `list_tables()` returns sorted lowercase names. `unregister_table(name)` returns whether an entry was removed, and `clear_tables()` removes all entries. Missing retrieval raises `KeyError` and reports the sorted available names.

##### Extension points and helpers

Expression, date/cast, window, union, rename and scalar methods are abstract extension points. Their existing implicit-`None` method bodies carry no implementation guarantee. `element()` raises `NotImplementedError` by default. `to_date(value)` returns a date unchanged, extracts a datetime's date, or parses a string with `%Y-%m-%d`. Parsing errors propagate, and other types raise `TypeError`. `days(n)` returns `timedelta(days=n)`.

### _to_list

#### `benchbox.core.dataframe.compat._to_list`

<span id="benchbox.core.dataframe.compat._to_list"></span>

```python
def _to_list(values: Any) -> list: ...
```

Materializes an object that exposes `compute()` first, then uses `tolist()` if available, otherwise `list(values)`. This supports Dask membership filters, whose right-hand operand must be a materialized collection. Conversion errors propagate. This helper imports no SDK.

**Import:** `from benchbox.core.dataframe.compat import _to_list` · **Extras:** none

## Operation Protocols and Query Categories

### DataFrameOps

#### `benchbox.core.dataframe.protocols.DataFrameOps`

<span id="benchbox.core.dataframe.protocols.DataFrameOps"></span>

A runtime-checkable generic structural protocol.

**Import:** `from benchbox.core.dataframe.protocols import DataFrameOps` · **Extras:** none

##### Chainable operations

`select(*columns)` projects columns. `filter(condition)` takes a boolean Series or string expression for the Pandas family, or an expression object for the expression family. `group_by(*columns)` returns `DataFrameGroupBy`. `join(other, on=None, left_on=None, right_on=None, how=JoinType.INNER)` supports shared or separate join keys. `sort(*columns, ascending=True)` accepts one boolean or an order sequence. `with_column(name, expr)` adds or replaces a column using a Series, a scalar or an expression. These operations return a chainable `DataFrameOps` type, as do `distinct()` and `limit(n)`.

##### Materialization and shape

`collect()` returns a native materialized result and may trigger lazy computation. `count()` returns the row count. `columns` returns the column names. `shape` is `(rows, columns)`. Count and shape may compute lazy data. The protocol defines signatures and intended roles, without implementing native semantics or runtime value validation.

### DataFrameGroupBy

#### `benchbox.core.dataframe.protocols.DataFrameGroupBy`

<span id="benchbox.core.dataframe.protocols.DataFrameGroupBy"></span>

A runtime-checkable generic grouped-operation protocol. `agg(*aggregations, **named_aggregations)` accommodates expression arguments, Pandas-style column/function mappings and named outputs. `sum(*columns)` and `mean(*columns)` target named columns, or numeric columns when omitted. `count()` counts group rows. `min(*columns)`, `max(*columns)` and `first(*columns)` return the corresponding grouped values. All methods return the `DataFrameOps` protocol type.

**Import:** `from benchbox.core.dataframe.protocols import DataFrameGroupBy` · **Extras:** none

### JoinType

#### `benchbox.core.dataframe.protocols.JoinType`

<span id="benchbox.core.dataframe.protocols.JoinType"></span>

Values are `inner`, `left`, `right`, `outer`, `cross`, `semi` and `anti`. `str(member)` returns its value. `from_string(value)` lowercases the input without stripping whitespace, and an unknown value raises `ValueError`.

**Import:** `from benchbox.core.dataframe.protocols import JoinType` · **Extras:** none

### AggregateFunction

#### `benchbox.core.dataframe.protocols.AggregateFunction`

<span id="benchbox.core.dataframe.protocols.AggregateFunction"></span>

Values are `sum`, `mean`, `avg`, `count`, `min`, `max`, `first`, `last`, `std`, `var`, `median` and `count_distinct`. `mean` and `avg` are distinct enum members that represent the same aggregation role; they are not Python enum aliases. String conversion and parsing follow the `JoinType` rules.

**Import:** `from benchbox.core.dataframe.protocols import AggregateFunction` · **Extras:** none

### SortOrder

#### `benchbox.core.dataframe.protocols.SortOrder`

<span id="benchbox.core.dataframe.protocols.SortOrder"></span>

Values are `asc` and `desc`. String conversion returns the value. `ascending` is true only for `ASC`.

**Import:** `from benchbox.core.dataframe.protocols import SortOrder` · **Extras:** none

### QueryCategory

#### `benchbox.core.dataframe.query.QueryCategory`

<span id="benchbox.core.dataframe.query.QueryCategory"></span>

Values are `scan`, `projection`, `filter`, `sort`, `aggregate`, `group_by`, `join`, `multi_join`, `subquery`, `window`, `analytical`, `tpch` and `tpcds`. These classify query workloads and benchmark families. `str(member)` returns the value.

**Import:** `from benchbox.core.dataframe.query import QueryCategory` · **Extras:** none

## Runtime Tuning Records

Runtime tuning configures adapter execution and memory. Physical write tuning configures output layout. A configuration describes requested settings, rather than proving that an adapter applied them. The `benchbox.core.dataframe` package re-exports its query/context, capability, validation, loader, profiling, maintenance and comparison APIs. Its `tuning` package re-exports the runtime, write, profile/default, loader and validation APIs described here and in their respective guides.

The following dataclasses are defined in `benchbox.core.dataframe.tuning.interface`. Each `to_dict()` returns all fields listed for that record. Each `from_dict(data)` reads those keys with constructor defaults when they are absent, ignores unrelated keys, and invokes constructor validation. The six runtime subconfigurations provide `is_default()`, which compares their listed defaults. Metadata has its own behavior, described below. Type annotations do not add general runtime type checking.

### ParallelismConfiguration

#### `benchbox.core.dataframe.tuning.interface.ParallelismConfiguration`

<span id="benchbox.core.dataframe.tuning.interface.ParallelismConfiguration"></span>

```python
class ParallelismConfiguration:
    def __init__(self, thread_count: int | None = None, worker_count: int | None = None, threads_per_worker: int | None = None) -> None: ...
```

Requested thread count, worker-process count and threads per worker. `None` leaves the setting to the platform. Each provided count must be at least 1, or construction raises `ValueError`. DataFusion maps thread count to target partitions. Dask uses worker and per-worker thread settings.

**Import:** `from benchbox.core.dataframe.tuning.interface import ParallelismConfiguration` · **Extras:** none

### MemoryConfiguration

#### `benchbox.core.dataframe.tuning.interface.MemoryConfiguration`

<span id="benchbox.core.dataframe.tuning.interface.MemoryConfiguration"></span>

```python
class MemoryConfiguration:
    def __init__(self, memory_limit: str | None = None, chunk_size: int | None = None, spill_to_disk: bool = False, spill_directory: str | None = None, rechunk_after_filter: bool = True) -> None: ...
```

Memory limit per worker, rows per streaming or batch chunk, spill request and directory, and the Polars rechunk preference. A provided chunk size must be at least 1. Memory limits accept a non-negative decimal number (digits with an optional fractional part, and optional whitespace) followed by a case-insensitive `B`, `KB`, `MB`, `GB`, `TB`, `KiB`, `MiB`, `GiB` or `TiB` suffix. An unsupported format raises `ValueError`. This validates syntax without measuring memory.

**Import:** `from benchbox.core.dataframe.tuning.interface import MemoryConfiguration` · **Extras:** none

### ExecutionConfiguration

#### `benchbox.core.dataframe.tuning.interface.ExecutionConfiguration`

<span id="benchbox.core.dataframe.tuning.interface.ExecutionConfiguration"></span>

```python
class ExecutionConfiguration:
    def __init__(self, streaming_mode: bool = False, engine_affinity: str | None = None, lazy_evaluation: bool = True, collect_timeout: int | None = None) -> None: ...
```

Streaming and lazy-evaluation requests and an optional preferred engine. `collect_timeout` is in seconds, and a provided value must be at least 1. Engine affinity is stored without enum validation. Platform consumers decide whether the settings apply.

**Import:** `from benchbox.core.dataframe.tuning.interface import ExecutionConfiguration` · **Extras:** none

### DataTypeConfiguration

#### `benchbox.core.dataframe.tuning.interface.DataTypeConfiguration`

<span id="benchbox.core.dataframe.tuning.interface.DataTypeConfiguration"></span>

```python
class DataTypeConfiguration:
    def __init__(self, dtype_backend: str = "numpy_nullable", enable_string_cache: bool = False, auto_categorize_strings: bool = False, categorical_threshold: float = 0.5) -> None: ...
```

The backend must be `numpy`, `numpy_nullable` or `pyarrow`. The categorical threshold must lie between 0 and 1 inclusive. It represents the unique-value to row ratio used for automatic string categorization. A backend or threshold violation raises `ValueError`. The string-cache and automatic-categorization requests are separate fields.

**Import:** `from benchbox.core.dataframe.tuning.interface import DataTypeConfiguration` · **Extras:** none

### IOConfiguration

#### `benchbox.core.dataframe.tuning.interface.IOConfiguration`

<span id="benchbox.core.dataframe.tuning.interface.IOConfiguration"></span>

```python
class IOConfiguration:
    def __init__(self, memory_pool: str = "default", memory_map: bool = False, pre_buffer: bool = True, row_group_size: int | None = None) -> None: ...
```

Arrow allocator, memory-mapped read and prebuffer requests, and rows per Parquet row group. The pool must be `default`, `jemalloc`, `mimalloc` or `system`. A provided group size must be at least 1. Invalid values raise `ValueError`.

**Import:** `from benchbox.core.dataframe.tuning.interface import IOConfiguration` · **Extras:** none

### GPUConfiguration

#### `benchbox.core.dataframe.tuning.interface.GPUConfiguration`

<span id="benchbox.core.dataframe.tuning.interface.GPUConfiguration"></span>

```python
class GPUConfiguration:
    def __init__(self, enabled: bool = False, device_id: int = 0, spill_to_host: bool = True, pool_type: str = "default") -> None: ...
```

GPU request, zero-based device, host-spill request and RMM pool selection. Device IDs must be non-negative. Pools must be `default`, `managed`, `pool` or `cuda`. Violations raise `ValueError`. A valid record does not establish GPU availability.

**Import:** `from benchbox.core.dataframe.tuning.interface import GPUConfiguration` · **Extras:** none

### TuningMetadata

#### `benchbox.core.dataframe.tuning.interface.TuningMetadata`

<span id="benchbox.core.dataframe.tuning.interface.TuningMetadata"></span>

```python
class TuningMetadata:
    def __init__(self, version: str = "1.0", format: str = "dataframe_tuning", platform: str | None = None, description: str | None = None, created: str | None = None, generated_by: str | None = None) -> None: ...
```

Version and format, plus an optional target platform, description, creation-date text and generating-tool text. No date or version validation occurs. `to_dict()` always includes version and format, and includes the optional fields only when they are truthy. `from_dict()` supplies defaults for missing keys. This record has no `is_default()` method.

**Import:** `from benchbox.core.dataframe.tuning.interface import TuningMetadata` · **Extras:** none

### DataFrameTuningConfiguration

#### `benchbox.core.dataframe.tuning.interface.DataFrameTuningConfiguration`

<span id="benchbox.core.dataframe.tuning.interface.DataFrameTuningConfiguration"></span>

The fields `parallelism`, `memory`, `execution`, `data_types`, `io`, `gpu` and `write` each receive fresh default records. `metadata` defaults to `None`.

**Import:** `from benchbox.core.dataframe.tuning.interface import DataFrameTuningConfiguration` · **Extras:** none

##### Serialization

`to_dict()` includes only non-default sections, and truthy metadata under `_metadata`. `to_full_dict()` includes all seven sections, and metadata when present. Write serialization remains sparse in either form. `from_dict()` builds each section from its mapping, defaults absent sections, and creates metadata only if the `_metadata` key is present. Malformed section values and constructor validation errors propagate.

##### Defaults and summaries

`is_default()` ignores metadata. `get_enabled_settings()` returns the runtime tuning enum values selected by the settings table: non-`None` counts, memory limit, chunk size and engine affinity; enabled spill, streaming and string cache; disabled rechunk, lazy evaluation and prebuffer; a non-default backend or allocator; mapped reads; and a non-`None` row group size. The GPU device is enabled when `gpu.enabled` is set. Host-spill and pool changes count only when GPU is enabled. The method omits write options and does not enumerate every configurable field. `get_summary()` reports enum-value lists and a count, default/GPU/streaming/write flags, selected thread, worker and memory fields, and write type, name and compression summaries. Enum sets do not promise list order.

### DataFrameTuningType

#### `benchbox.core.dataframe.tuning.types.DataFrameTuningType`

<span id="benchbox.core.dataframe.tuning.types.DataFrameTuningType"></span>

A string-valued runtime-setting enum. `str(member)` returns its value. `from_string(value)` lowercases without stripping whitespace and raises `ValueError` for unknown values. Compatibility checks lowercase platform names and remove a trailing `-df`. Unknown platforms support no types. `get_platform_supported_types(platform)` returns a copy of its set, and `is_compatible_with_platform(platform)` tests membership. This policy matrix is separate from physical write capabilities.

**Import:** `from benchbox.core.dataframe.tuning.types import DataFrameTuningType` · **Extras:** none

##### Supported types by platform

- **DataFusion:** `thread_count` and `chunk_size`.
- **Polars:** thread and chunk settings, rechunk, streaming, engine and lazy settings, string cache, memory pool and row group settings.
- **Pandas:** chunk size, dtype backend, string cache, memory pool, mapped reads, prebuffer and row groups.
- **Dask:** workers, threads per worker, memory limit, chunk size, spill, lazy evaluation, backend, memory mapping and prebuffer.
- **cuDF:** string cache, GPU device, spill and pool, and row groups.

Arrow-backed allocators and categorical-string conversion are implementation paths, rather than promises of native APIs with identical names.

### get_all_platforms

#### `benchbox.core.dataframe.tuning.types.get_all_platforms`

<span id="benchbox.core.dataframe.tuning.types.get_all_platforms"></span>

```python
def get_all_platforms() -> list[str]: ...
```

Returns the matrix keys in insertion order: DataFusion, Polars, Pandas, Dask and cuDF, using lowercase slugs.

**Import:** `from benchbox.core.dataframe.tuning.types import get_all_platforms` · **Extras:** none

### create_profile_config

#### `benchbox.core.dataframe.tuning.profiles.create_profile_config`

<span id="benchbox.core.dataframe.tuning.profiles.create_profile_config"></span>

```python
def create_profile_config(platform: str, profile: str) -> DataFrameTuningConfiguration: ...
```

Constructs fresh default records. Names are compared exactly, without case or suffix normalization. DataFusion rejects profiles other than `default` or `optimized`. Other platforms leave unknown profiles at defaults.

**Import:** `from benchbox.core.dataframe.tuning.profiles import create_profile_config` · **Extras:** none

##### Profiles

- **`optimized`:** enables lazy evaluation. It selects Polars `in-memory` affinity, DataFusion thread count 4, Dask 4 workers with 2 threads, or cuDF GPU and pool mode.
- **`streaming`:** enables streaming and chunk size 100,000, with Polars streaming affinity.
- **`memory-constrained`:** enables streaming, chunk size 50,000 and disk spill. Dask adds a `2GB` memory limit.
- **`gpu`:** enables GPU and pool mode, even on a non-cuDF platform. Caller presentation handles mismatch warnings.

These are requested presets, not executed performance measurements.

`DATAFRAME_PLATFORMS` in `tuning.profiles` contains the five runtime-policy slugs. `DATAFRAME_CAPABILITY_ROWS` supplies CLI display rows from core so that presentation does not maintain a second policy table. The rows are descriptive metadata, distinct from the setting-compatibility and write-capability matrices.

## Physical Write Configuration

The following types are defined in `benchbox.core.dataframe.tuning.write_config`. Write options affect Parquet directory and file layout, sorting, grouping and encoding, which can affect compression and later scans. Consumers determine which options are applied. Configuration validation alone is not proof of the emitted layout.

### SortColumn

#### `benchbox.core.dataframe.tuning.write_config.SortColumn`

<span id="benchbox.core.dataframe.tuning.write_config.SortColumn"></span>

```python
class SortColumn:
    def __init__(self, name: str, order: SortOrder = "asc") -> None: ...
```

The name must be truthy and the order exactly `asc` or `desc`, otherwise construction raises `ValueError`. `to_dict()` returns the name and order. `from_dict()` requires the name and defaults a missing order to `asc`. `SortOrder` here is a literal type alias, separate from the operation-protocol enum above.

**Import:** `from benchbox.core.dataframe.tuning.write_config import SortColumn` · **Extras:** none

### PartitionColumn

#### `benchbox.core.dataframe.tuning.write_config.PartitionColumn`

<span id="benchbox.core.dataframe.tuning.write_config.PartitionColumn"></span>

```python
class PartitionColumn:
    def __init__(self, name: str, strategy: PartitionStrategy = PartitionStrategy.VALUE) -> None: ...
```

A truthy name is required. The strategy is not checked in direct construction, and `to_dict()` reads its `value`. `from_dict()` requires the name, defaults the strategy to `value`, converts string values through `PartitionStrategy` and passes non-string values through. Invalid strings raise `ValueError`.

**Import:** `from benchbox.core.dataframe.tuning.write_config import PartitionColumn` · **Extras:** none

### PartitionStrategy

#### `benchbox.core.dataframe.tuning.write_config.PartitionStrategy`

<span id="benchbox.core.dataframe.tuning.write_config.PartitionStrategy"></span>

Values are `value` (direct Hive-style value directories), and `date_year`, `date_month` and `date_day` (date-extraction directory strategies).

**Import:** `from benchbox.core.dataframe.tuning.write_config import PartitionStrategy` · **Extras:** none

### DataFrameWriteTuningType

#### `benchbox.core.dataframe.tuning.write_config.DataFrameWriteTuningType`

<span id="benchbox.core.dataframe.tuning.write_config.DataFrameWriteTuningType"></span>

Values are `partition_by`, `sort_by`, `row_group_size`, `repartition`, `compression`, `dictionary_encoding` and `data_page_version`. They classify non-default write settings.

**Import:** `from benchbox.core.dataframe.tuning.write_config import DataFrameWriteTuningType` · **Extras:** none

### DataFrameWriteConfiguration

#### `benchbox.core.dataframe.tuning.write_config.DataFrameWriteConfiguration`

<span id="benchbox.core.dataframe.tuning.write_config.DataFrameWriteConfiguration"></span>

`partition_by` and `sort_by` are fresh empty lists of column records. `row_group_size` (rows), `target_file_size_mb` (target megabytes), `repartition_count` and `compression_level` default to `None`. `compression` defaults to `zstd`. `dictionary_columns` and `skip_dictionary_columns` each receive a fresh empty list. `data_page_version` defaults to `None`. Row group size has no fixed one-million-row default in this record.

**Import:** `from benchbox.core.dataframe.tuning.write_config import DataFrameWriteConfiguration` · **Extras:** none

##### Allowed values and validation

Compression codecs are annotated as `none`, `snappy`, `gzip`, `zstd`, `lz4` or `brotli`. Data page versions are annotated as `1.0` or `2.0`. These annotations do not independently validate arbitrary direct-constructor values.

Provided row-group, file-size and repartition values must be at least 1. Compression levels are bounded for zstd (1 to 22), gzip (1 to 9), brotli (0 to 11) and lz4 (0 to 16). Codecs without level support log a warning, and the field remains stored. Other violations raise `ValueError`. Dictionary selection requests control the encoding of low- and high-cardinality columns. Page versions describe Parquet serialization choices rather than an adapter support guarantee.

##### Serialization and enabled types

`to_dict()` includes non-default fields, serializes column records, and returns the original dictionary-column lists when they are included. `from_dict()` accepts partition names as strings or mappings. Sort entries may be strings, mappings or already constructed objects. It builds new partition and sort lists, passes supplied dictionary-column lists through, and uses field defaults when keys are absent. Errors from malformed entries propagate. `is_default()` checks the listed defaults. `get_enabled_types()` reports partition and sort settings, row groups, repartition, compression changes or explicit levels, dictionary selection and page-version changes. Target file size has no corresponding enabled-type enum entry.

### get_platform_write_capabilities

#### `benchbox.core.dataframe.tuning.write_config.get_platform_write_capabilities`

<span id="benchbox.core.dataframe.tuning.write_config.get_platform_write_capabilities"></span>

```python
def get_platform_write_capabilities(platform: str) -> dict[str, bool]: ...
```

Lowercases the name without stripping a `-df` suffix. Known platforms return their shared matrix dict by reference. Unknown names return a fresh basic capability dict. All five known platforms support row groups, compression and dictionary encoding in this policy. Dask and PySpark support partitioning and repartitioning. Dask does not declare sorting, while the other four do.

**Import:** `from benchbox.core.dataframe.tuning.write_config import get_platform_write_capabilities` · **Extras:** none

### validate_write_config_for_platform

#### `benchbox.core.dataframe.tuning.write_config.validate_write_config_for_platform`

<span id="benchbox.core.dataframe.tuning.write_config.validate_write_config_for_platform"></span>

```python
def validate_write_config_for_platform(config: DataFrameWriteConfiguration, platform: str) -> list[str]: ...
```

Returns warnings for requested unsupported partitioning, sorting or repartitioning. It does not mutate the configuration, reject it, or validate every write field. In particular, a capability warning does not itself ensure that a downstream writer ignores the option.

**Import:** `from benchbox.core.dataframe.tuning.write_config import validate_write_config_for_platform` · **Extras:** none
