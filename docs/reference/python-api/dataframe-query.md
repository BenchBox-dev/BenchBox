# DataFrame Query Registries

```{tags} reference, python-api, dataframe
```

DataFrame benchmark modules store callable implementations and query metadata in shared registries. Registration metadata is runtime data: descriptions, category codes, SQL equivalents, expected counts and platform exclusions remain part of the query surface rather than source documentation.

## Query and Registry Classes

### DataFrameQuery

#### `benchbox.core.dataframe.query.DataFrameQuery`

<span id="benchbox.core.dataframe.query.DataFrameQuery"></span>

```python
class DataFrameQuery:
    def __init__(self, query_id: str, query_name: str, description: str, categories: list[QueryCategory] = ..., pandas_impl: Callable[[DataFrameContext], Any] | None = None, expression_impl: Callable[[DataFrameContext], Any] | None = None, sql_equivalent: str | None = None, expected_row_count: int | None = None, scale_factor_dependent: bool = False, timeout_seconds: float | None = None, skip_platforms: list[str] = ...) -> None: ...
```

A mutable dataclass. The ellipses in the signature denote fresh-list factories: `categories` and `skip_platforms` each get a fresh empty list. `pandas_impl`, `expression_impl`, `sql_equivalent`, `expected_row_count` and `timeout_seconds` default to `None`. `scale_factor_dependent` defaults to `False`. Timeout metadata is in seconds. Construction rejects a false query ID, a false query name, or the absence of both implementations with `ValueError`. Other field values are not comprehensively validated.

**Import:** `from benchbox.core.dataframe.query import DataFrameQuery` · **Extras:** none

##### Implementation and category checks

`has_pandas_impl()`, `has_expression_impl()` and `has_sql_equivalent()` test whether their corresponding fields are non-`None`. `in_category(category)` checks membership in `categories`. `get_impl_for_family(family)` accepts case-insensitive `pandas` or `expression`, returns the callable or `None`, and raises `ValueError` for another family name.

##### Execution

`execute(ctx, family)` calls the selected implementation with `ctx` and returns its result unchanged. A missing implementation raises `ValueError`, and implementation exceptions propagate. This method does not enforce expected row counts, timeout metadata or platform exclusions.

##### Platform support

`supports_platform(platform)` first rejects a case-insensitive match in `skip_platforms`. Pandas, cuDF, Vaex and Dask require `pandas_impl`. Polars, PySpark, DataFusion and Spark require `expression_impl`. Unrecognized platform names return `False`.

##### Serialization

`to_dict()` returns the query ID, name and description, the category values, the implementation-presence flags, the SQL equivalent, the expected row count, the scale-factor dependence, the timeout and the platform exclusions. Callables are not serialized. The returned `skip_platforms` value is the original list.

### QueryRegistry

#### `benchbox.core.dataframe.query.QueryRegistry`

<span id="benchbox.core.dataframe.query.QueryRegistry"></span>

```python
class QueryRegistry:
    def __init__(self, benchmark: str, loader: Callable[[], Iterable[DataFrameQuery]] | None = None) -> None: ...
```

Stores queries by their exact ID string. `get(query_id)` returns the stored query or `None`. `get_or_raise(query_id)` raises `KeyError` when the ID is absent. `get_all_queries()` and `get_query_ids()` sort lexicographically by query ID; they do not interpret numeric portions of an ID. Queries are returned by reference, not copied. Iteration yields sorted IDs, and membership and length consult the registry contents.

**Import:** `from benchbox.core.dataframe.query import QueryRegistry` · **Extras:** none

##### Registration

`register(query)` rejects a duplicate ID with `ValueError`. `register_many(queries)` registers in input order and can leave earlier items registered when a later item fails. These operations trigger any configured lazy loader before adding the supplied queries.

##### Filtering

`get_queries_by_category(category)` uses category membership. `get_queries_for_platform(platform)` uses `supports_platform`. `get_queries_for_family(family)` selects non-`None` implementations for case-insensitive `pandas` or `expression` and raises `ValueError` for another family name. `list_queries(family=None, category=None)` applies both optional filters while preserving sorted query order.

##### Lazy loading

`set_loader(loader)` is allowed only before the registry is loaded or contains queries; otherwise it raises `RuntimeError`. With a loader, lookups and other content-dependent methods initialize it under a lock. Successful initialization runs once. Loader and duplicate-registration errors propagate. Partial registrations are not rolled back, and a failed load does not set the loaded flag.

`load_info()` returns lazy-load statistics. A registry without a loader does not accumulate load hits or misses, even when it contains manual entries.

### QueryRegistryLoadInfo

#### `benchbox.core.dataframe.query.QueryRegistryLoadInfo`

<span id="benchbox.core.dataframe.query.QueryRegistryLoadInfo"></span>

A named tuple with the integer fields `hits`, `misses`, `maxsize` and `currsize`. Hits count checks after a successful lazy load, and misses count load attempts. `maxsize` is 1, and `currsize` is 1 only after a successful lazy load.

**Import:** `from benchbox.core.dataframe.query import QueryRegistryLoadInfo` · **Extras:** none

## Benchmark Registry Helpers

The `registry` modules under `benchbox.core.<benchmark>.dataframe_queries` for AMPLab, ClickBench, CoffeeShop, DataVault, H2Odb, NYC Taxi, SSB, TPC-DS, TPC-H Skew and TSBS DevOps expose `get_<benchmark>_query(query_id)`, `list_<benchmark>_queries(family=None, category=None)` and `register_query(query)`. Their names use the module spelling, such as `get_tsbs_devops_query`. They delegate to the shared registry: retrieval can return `None`, filters and order follow the contract above, and duplicate registration raises `ValueError`. Importing their package installs the benchmark's registrations or loader. TPC-DS uses `configure_query_loader(loader)` to install its generated-metadata loader. Loader replacement follows the `set_loader` restrictions.

TPC-Havoc uses eager variant registration. Its `get_dataframe_queries()` returns the shared registry object, `list_query_ids()` returns sorted variant IDs, and `get_query(query_id)` raises `KeyError` for an unknown exact ID. IDs use `Q<query>v<variant>`. The registry imports the 22 query modules and registers their variant objects. This is not a live SQL-equivalence certification.

## TPC-Havoc Variant Factories

### load_variant_specs

#### `benchbox.core.tpchavoc.dataframe_queries.loader.load_variant_specs`

<span id="benchbox.core.tpchavoc.dataframe_queries.loader.load_variant_specs"></span>

```python
def load_variant_specs(module_file: str, namespace: dict[str, Any]) -> tuple[list[tuple[VariantImpl, VariantImpl]], list[str]]: ...
```

Reads UTF-8 YAML beside `module_file`, using its path with the suffix `.yaml`. For each entry in `variants`, it resolves the `expression_impl` and `pandas_impl` names from `namespace` and collects `description` in the same order. File, YAML, missing-key and namespace errors propagate. Empty input lacks the required `variants` key.

**Import:** `from benchbox.core.tpchavoc.dataframe_queries.loader import load_variant_specs` · **Extras:** none

### build_variants

#### `benchbox.core.tpchavoc.dataframe_queries.loader.build_variants`

<span id="benchbox.core.tpchavoc.dataframe_queries.loader.build_variants"></span>

```python
def build_variants(query_number: int, impl_pairs: Sequence[tuple[VariantImpl, VariantImpl]], descriptions: Sequence[str], categories: Sequence[QueryCategory], *, expected_row_count: int | None = None, scale_factor_dependent: bool = False, timeout_seconds: float | None = None, skip_platforms: Sequence[str] | None = None) -> list[DataFrameQuery]: ...
```

Enumerates the implementation pairs from 1, forming `Q<number>v<variant>` IDs and the corresponding query names. Each pair uses the description at the same index; too few descriptions raise `IndexError`. Categories are copied into each object. A truthy platform sequence is copied into a new list; otherwise the object gets an empty list. Row-count, scale-dependence and timeout metadata are forwarded unchanged. The caller supplies canonical metadata. This factory does not validate a query-number range, execute queries or certify equivalence.

**Import:** `from benchbox.core.tpchavoc.dataframe_queries.loader import build_variants` · **Extras:** none

### build_yaml_variants

#### `benchbox.core.tpchavoc.dataframe_queries.loader.build_yaml_variants`

<span id="benchbox.core.tpchavoc.dataframe_queries.loader.build_yaml_variants"></span>

```python
def build_yaml_variants(module_file: str, namespace: dict[str, Any], query_number: int, categories: Sequence[QueryCategory]) -> list[DataFrameQuery]: ...
```

Loads the implementation pairs and descriptions with `load_variant_specs` and delegates to `build_variants` with its metadata defaults. File, resolution and construction errors propagate.

**Import:** `from benchbox.core.tpchavoc.dataframe_queries.loader import build_yaml_variants` · **Extras:** none

### make_variant_delegate

#### `benchbox.core.tpchavoc.dataframe_queries._delegating_variants.make_variant_delegate`

<span id="benchbox.core.tpchavoc.dataframe_queries._delegating_variants.make_variant_delegate"></span>

```python
def make_variant_delegate(impl: VariantImpl, *, name: str, module: str) -> VariantImpl: ...
```

Returns a wrapper that calls `impl(ctx)` and returns its value unchanged. The wrapper's `__name__` and `__qualname__` are set to `name`, and its `__module__` is set to `module`. Exceptions propagate. This does not transform results or assign a runtime docstring.

**Import:** `from benchbox.core.tpchavoc.dataframe_queries._delegating_variants import make_variant_delegate` · **Extras:** none

## CSV and Schema Loading Helpers

### dialect_preserves_empty_strings

#### `benchbox.core.dataframe.csv_dialect.dialect_preserves_empty_strings`

<span id="benchbox.core.dataframe.csv_dialect.dialect_preserves_empty_strings"></span>

```python
def dialect_preserves_empty_strings(null_marker: str | None) -> bool: ...
```

Returns `null_marker != ""`. An empty marker maps empty CSV fields to NULL. `None` disables that conversion, and a non-empty sentinel converts only that sentinel. DataFrame readers can restore empty text fields to match the SQL dialect when this predicate is true. The helper lives in core so that loading code can share this policy without importing a platform adapter.

**Import:** `from benchbox.core.dataframe.csv_dialect import dialect_preserves_empty_strings` · **Extras:** none

### iter_schema_columns

#### `benchbox.core.dataframe.schema_utils.iter_schema_columns`

<span id="benchbox.core.dataframe.schema_utils.iter_schema_columns"></span>

```python
def iter_schema_columns(table_schema: Any) -> list[Any]: ...
```

Normalizes a dict's `columns` mapping into column dicts in mapping order. Dict specifications are copied, and a missing `name` is filled from the key. Non-dict specifications become `{"type": spec}` with that name. A list or tuple is copied to a list. Unsupported dict column containers return an empty list. For object schemas, the `columns` attribute is copied to a list, or an empty list is returned when it is absent or `None`.

**Import:** `from benchbox.core.dataframe.schema_utils import iter_schema_columns` · **Extras:** none

### column_name

#### `benchbox.core.dataframe.schema_utils.column_name`

<span id="benchbox.core.dataframe.schema_utils.column_name"></span>

```python
def column_name(column: Any) -> str | None: ...
```

Reads `name` from a dict or object, or parses the first identifier of a DDL string. Truthy names become strings. Absent or false-valued names return `None`. DDL identifiers support double quotes, backticks and brackets, including doubled closing delimiters. Delimiters are removed because DataFrame column lookup uses the logical SQL name. An unterminated quoted identifier returns its remaining contents as the name and has no parsed type.

**Import:** `from benchbox.core.dataframe.schema_utils import column_name` · **Extras:** none

### column_sql_type

#### `benchbox.core.dataframe.schema_utils.column_sql_type`

<span id="benchbox.core.dataframe.schema_utils.column_sql_type"></span>

```python
def column_sql_type(column: Any, default: str = "VARCHAR") -> str: ...
```

For DDL strings, preserves parenthesized precision and scale and these multi-word types: `DOUBLE PRECISION`, `CHARACTER VARYING`, `BIT VARYING` and time or timestamp zone modifiers. The type stops before a column constraint or an unsupported continuation. An unbalanced parenthesis preserves the remaining text, because this helper does not validate DDL syntax. Missing types use `default`.

Dicts use a truthy `type` or `data_type`. Objects try `get_sql_type` and `sql_type` (calling callable attributes), then `data_type`. The result is the first string candidate, or a candidate's string `value` attribute. Otherwise the result is `default`. Errors from these attributes or calls propagate.

**Import:** `from benchbox.core.dataframe.schema_utils import column_sql_type` · **Extras:** none

### extract_schema_columns

#### `benchbox.core.dataframe.schema_utils.extract_schema_columns`

<span id="benchbox.core.dataframe.schema_utils.extract_schema_columns"></span>

```python
def extract_schema_columns(schema: Any) -> dict[str, list[dict[str, str]]]: ...
```

Non-dict input returns an empty dict. Each table is normalized with the helpers above. Unnamed columns, and tables with no retained columns, are omitted. Table names are stored as lowercase strings, and column order follows the input. Lowercase name collisions overwrite an earlier table entry.

**Import:** `from benchbox.core.dataframe.schema_utils import extract_schema_columns` · **Extras:** none

### get_benchmark_schema_columns

#### `benchbox.core.dataframe.schema_utils.get_benchmark_schema_columns`

<span id="benchbox.core.dataframe.schema_utils.get_benchmark_schema_columns"></span>

```python
def get_benchmark_schema_columns(benchmark: Any) -> dict[str, list[dict[str, str]]]: ...
```

Normalizes `benchmark.get_schema()`. Returns an empty dict when the method is absent or when retrieval or normalization raises an exception.

**Import:** `from benchbox.core.dataframe.schema_utils import get_benchmark_schema_columns` · **Extras:** none

## Benchmark Query Resolution

### build_dataframe_query_filter

#### `benchbox.core.dataframe.query_resolution.build_dataframe_query_filter`

<span id="benchbox.core.dataframe.query_resolution.build_dataframe_query_filter"></span>

```python
def build_dataframe_query_filter(query_subset: Any) -> set[str] | None: ...
```

False-valued input means no filter and returns `None`. Otherwise each item's string representation is stripped and uppercased, and both its `Q`-prefixed and unprefixed forms are added. `build_dataframe_query_filter_from_config(config)` applies this rule to the optional `queries` attribute.

**Import:** `from benchbox.core.dataframe.query_resolution import build_dataframe_query_filter` · **Extras:** none

### benchmark_defines_dataframe_hook

#### `benchbox.core.dataframe.query_resolution.benchmark_defines_dataframe_hook`

<span id="benchbox.core.dataframe.query_resolution.benchmark_defines_dataframe_hook"></span>

```python
def benchmark_defines_dataframe_hook(benchmark: Any | None, hook_name: str) -> bool: ...
```

Recognizes a callable defined directly on the instance or its class, or an already configured mock child with a return value, side effect or wrapped callable. Inherited methods and unconfigured mock children do not suffice. `benchmark_provides_dataframe_queries(benchmark)` checks the `get_dataframe_queries` hook with this rule.

**Import:** `from benchbox.core.dataframe.query_resolution import benchmark_defines_dataframe_hook` · **Extras:** none

### get_dataframe_queries_for_benchmark

#### `benchbox.core.dataframe.query_resolution.get_dataframe_queries_for_benchmark`

<span id="benchbox.core.dataframe.query_resolution.get_dataframe_queries_for_benchmark"></span>

```python
def get_dataframe_queries_for_benchmark(benchmark_config: Any, benchmark_instance: Any | None, stream_id: int | None = None) -> list[Any]: ...
```

Normalizes the configuration's benchmark name. A missing `stream_id` uses its configured value, defaulting to zero. TPC-H, TPC-DS and ClickBench use their named resolvers before an instance hook is considered. Other benchmarks accept an explicit provider's list unchanged, or its `get_all_queries()` result. Unsupported containers log a warning and fall back to the registry.

**Import:** `from benchbox.core.dataframe.query_resolution import get_dataframe_queries_for_benchmark` · **Extras:** none

### registry_dataframe_queries

#### `benchbox.core.dataframe.query_resolution.registry_dataframe_queries`

<span id="benchbox.core.dataframe.query_resolution.registry_dataframe_queries"></span>

```python
def registry_dataframe_queries(benchmark_id: str) -> list[Any]: ...
```

Imports `benchbox.core.<benchmark_id>.dataframe_queries` and finds distinct `QueryRegistry` objects by identity. Aliases to one object are allowed. Multiple distinct registries raise `RuntimeError`. No registry, or a missing target module or parent package, yields an empty list. A missing dependency within an existing module propagates. The result is the registry's sorted query list, which triggers its lazy loader. Registry fallback prevents registered benchmark families from silently running zero queries merely because they lack an explicit instance provider.

**Import:** `from benchbox.core.dataframe.query_resolution import registry_dataframe_queries` · **Extras:** none

### Stream-specific helpers

The stream-specific helpers preserve these ordering boundaries:

- `get_tpch_dataframe_queries(stream_id)` selects the permutation matrix row modulo its length, logs missing query IDs and omits those entries.
- `resolve_tpcds_query_manager(instance)` checks the instance, then its `_impl` wrapper. Without a manager, `get_tpcds_legacy_queries(ids, stream_id)` warns and generates legacy ordering using seed `42 + stream_id`.
- `get_tpcds_dataframe_queries(config, instance, stream_id)` gathers numeric base IDs, creates one standard stream over query range 1 through 99 with that seed, and resolves variants. `tpcds_dataframe_variant_fallback` defaults to true and is interpreted with `bool`.
- `resolve_tpcds_stream_queries(queries, allow_variant_fallback)` logs and skips missing base queries, resolves variant IDs with lower, upper and capitalized suffix spellings, and retains stream order. With fallback enabled, a missing variant uses a dataclass copy of the base implementation with the variant ID; this does not certify SQL parity. With fallback disabled, missing variants raise `RuntimeError` after collection.
- `get_clickbench_dataframe_queries(config, instance, stream_id)` returns the registry's sorted list. Its configuration, instance and stream arguments do not alter the order.

## DataFrame Row-count Evidence

### DataFrameQueryValidationSummary

#### `benchbox.core.dataframe.query_validation.DataFrameQueryValidationSummary`

<span id="benchbox.core.dataframe.query_validation.DataFrameQueryValidationSummary"></span>

```python
class DataFrameQueryValidationSummary:
    def __init__(self, status: str, details: dict[str, Any]) -> None: ...
```

A frozen dataclass that holds a run-level status and a mutable evidence dict.

**Import:** `from benchbox.core.dataframe.query_validation import DataFrameQueryValidationSummary` · **Extras:** none

### validate_dataframe_query_results

#### `benchbox.core.dataframe.query_validation.validate_dataframe_query_results`

<span id="benchbox.core.dataframe.query_validation.validate_dataframe_query_results"></span>

```python
def validate_dataframe_query_results(query_results: list[dict[str, Any]], *, benchmark_name: str, scale_factor: float, validation_mode: str | None = None, seed: int | None = None) -> DataFrameQueryValidationSummary: ...
```

Mutates successful measurement rows with `row_count_validation` evidence, then returns aggregate counts and status. Absent run types mean measurement. Run types other than measurement are excluded from oracle evidence. Execution failures and selected non-warmup skips affect the aggregate status. A false-valued mode defaults to `exact`. Mode and benchmark names are normalized.

**Import:** `from benchbox.core.dataframe.query_validation import validate_dataframe_query_results` · **Extras:** none

##### Supported evidence

Only TPC-H at scale factor 1, with an absent seed or the reference seed, can produce supported expected-row-count evidence. TPC-DS lacks seed-aligned counts for this path, so its successful rows receive skipped evidence. Other benchmarks have no registered provider and return `NOT_RUN`, or `PARTIAL` when execution failed. Disabled validation uses the same two statuses. Unsupported modes mark successful rows skipped and yield `UNCERTAIN` when evidence was unavailable, or `PARTIAL` when execution failed.

##### Row checks

DataFrame `stream_id` denotes a repeated measurement here, whereas the oracle uses it to select distinct answer streams. It is deliberately omitted from the oracle call. A valid actual count is a non-negative integer, excluding booleans. An invalid count clears `rows_returned` and marks the row failed. An oracle mismatch also marks the row failed. Skipped results retain their execution status. Oracle initialization or query errors produce error evidence rather than a fabricated candidate-result mismatch. Messages are truncated to 500 characters, including an ellipsis.

##### Aggregate status

The aggregate status is chosen in this order of precedence:

1. `FAILED` for a candidate mismatch or an invalid count.
2. `PARTIAL` for execution failures.
3. `UNCERTAIN` for skips or oracle errors.
4. `PASSED` when every successful measurement was checked.
5. `NOT_RUN` otherwise.

Initialization failure uses the unavailable-evidence status instead. Row-count agreement alone does not validate result contents or certify benchmark compliance.
