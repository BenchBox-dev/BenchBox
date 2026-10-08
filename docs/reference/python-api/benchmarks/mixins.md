# Shared Benchmark Facade Mixins

```{tags} reference, python-api, benchmarks
```

These maintained contracts document the public methods that benchmark facades inherit. Concrete benchmark pages describe only their own behavior and link here instead of repeating the same inherited member list.

All four mixins are defined in the module `benchbox.core.benchmark_mixins`. The source is `benchbox/core/benchmark_mixins.py`.

## API Reference

### DataGenerationMixin

#### `benchbox.core.benchmark_mixins.DataGenerationMixin`

<span id="benchbox.core.benchmark_mixins.DataGenerationMixin"></span>

Shared table generation and loading flow. Consumers provide a table schema, a data generator, and the benchmark's CREATE TABLE SQL method.

**Import:** `from benchbox.core.benchmark_mixins import DataGenerationMixin` · **Extras:** none

##### `benchbox.core.benchmark_mixins.DataGenerationMixin.generate_data`

<span id="benchbox.core.benchmark_mixins.DataGenerationMixin.generate_data"></span>

```python
def generate_data(tables: Optional[list[str]] = None, output_format: str = "csv") -> dict[str, Any]: ...
```

Generates the selected tables, defaulting to every table in the schema, and returns the benchmark's table-to-path mapping. Only `csv` output is accepted; another format raises `ValueError`. Unknown table names also raise `ValueError`.

##### `benchbox.core.benchmark_mixins.DataGenerationMixin.load_data_to_database`

<span id="benchbox.core.benchmark_mixins.DataGenerationMixin.load_data_to_database"></span>

```python
def load_data_to_database(connection: Any, tables: Optional[list[str]] = None) -> None: ...
```

Creates the schema, loads the selected generated tables, and commits when the connection exposes `commit`. Calling this before data generation raises `ValueError`. Names that are absent from the generated mapping or the schema are skipped.

### QueryFacadeMixin

#### `benchbox.core.benchmark_mixins.QueryFacadeMixin`

<span id="benchbox.core.benchmark_mixins.QueryFacadeMixin"></span>

Delegates query listing and retrieval to a benchmark implementation while preserving optional parameters and keyword compatibility.

**Import:** `from benchbox.core.benchmark_mixins import QueryFacadeMixin` · **Extras:** none

##### `benchbox.core.benchmark_mixins.QueryFacadeMixin.get_queries`

<span id="benchbox.core.benchmark_mixins.QueryFacadeMixin.get_queries"></span>

```python
def get_queries(dialect: Optional[str] = None) -> dict[str, str]: ...
```

Returns the implementation's query mapping, optionally translated to the requested dialect.

##### `benchbox.core.benchmark_mixins.QueryFacadeMixin.get_query`

<span id="benchbox.core.benchmark_mixins.QueryFacadeMixin.get_query"></span>

```python
def get_query(query_id: Union[int, str], *, params: Optional[dict[str, Any]] = None, **kwargs: Any) -> str: ...
```

Returns one implementation query, forwarding `params` and additional keyword options when they are supplied.

### QueryCategoryFacadeMixin

#### `benchbox.core.benchmark_mixins.QueryCategoryFacadeMixin`

<span id="benchbox.core.benchmark_mixins.QueryCategoryFacadeMixin"></span>

Delegates category-oriented query accessors to the benchmark implementation.

**Import:** `from benchbox.core.benchmark_mixins import QueryCategoryFacadeMixin` · **Extras:** none

##### `benchbox.core.benchmark_mixins.QueryCategoryFacadeMixin.get_queries_by_category`

<span id="benchbox.core.benchmark_mixins.QueryCategoryFacadeMixin.get_queries_by_category"></span>

```python
def get_queries_by_category(category: str) -> dict[str, str]: ...
```

Returns the implementation's query mapping for one category.

##### `benchbox.core.benchmark_mixins.QueryCategoryFacadeMixin.get_query_categories`

<span id="benchbox.core.benchmark_mixins.QueryCategoryFacadeMixin.get_query_categories"></span>

```python
def get_query_categories() -> list[str]: ...
```

Returns the implementation's available query category names.

### OperationCategoryFacadeMixin

#### `benchbox.core.benchmark_mixins.OperationCategoryFacadeMixin`

<span id="benchbox.core.benchmark_mixins.OperationCategoryFacadeMixin"></span>

Delegates category-oriented operation accessors to the benchmark implementation.

**Import:** `from benchbox.core.benchmark_mixins import OperationCategoryFacadeMixin` · **Extras:** none

##### `benchbox.core.benchmark_mixins.OperationCategoryFacadeMixin.get_operations_by_category`

<span id="benchbox.core.benchmark_mixins.OperationCategoryFacadeMixin.get_operations_by_category"></span>

```python
def get_operations_by_category(category: str) -> dict[str, Any]: ...
```

Returns the implementation's operation mapping for one category.

##### `benchbox.core.benchmark_mixins.OperationCategoryFacadeMixin.get_operation_categories`

<span id="benchbox.core.benchmark_mixins.OperationCategoryFacadeMixin.get_operation_categories"></span>

```python
def get_operation_categories() -> list[str]: ...
```

Returns the implementation's available operation category names.
