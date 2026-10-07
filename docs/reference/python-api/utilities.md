---
myst:
  enable_extensions:
    - attrs_block
---
<!-- markdownlint-disable MD024 -->

# Utility Functions API

```{tags} reference, python-api
```

Complete Python API reference for BenchBox utility functions.

## Overview

BenchBox provides utility functions for common tasks like SQL dialect translation. These utilities simplify cross-database benchmarking and platform-specific optimizations. This page covers dialect normalization and query translation; the other utility modules are listed in {doc}`utilities-index`.

**Available Utilities**:

- **Dialect Translation**: SQL dialect normalization and query translation

## Dialect Translation

```{important}
**Dialect Translation vs Platform Adapters**

BenchBox can translate queries to many SQL dialects via SQLGlot (PostgreSQL, MySQL, SQL Server, Oracle, etc.),
but **dialect translation does not mean platform adapters exist** for connecting to those databases.

**Currently supported platforms**: DuckDB, SQLite, PostgreSQL, TimescaleDB, ClickHouse, Databricks SQL, BigQuery, Redshift, Snowflake, Trino, Presto, Amazon Athena, Firebolt, Azure Synapse Analytics, Microsoft Fabric, and many more (see {doc}`/platforms/index`)

**Planned platforms**: MySQL, SQL Server, and others (see {doc}`/development/roadmap`)

The examples below demonstrate dialect translation capabilities - you can use translated queries with your own
database connections, but BenchBox's built-in platform adapters are limited to the supported platforms listed above.
```

### SQL Dialect Normalization

#### `benchbox.utils.dialect_utils.normalize_dialect_for_sqlglot`

<span id="benchbox.utils.dialect_utils.normalize_dialect_for_sqlglot"></span>

Returns the SQLGlot dialect name to use for a database name, mapping a few databases that SQLGlot lacks onto PostgreSQL.

**Import:** `from benchbox.utils.dialect_utils import normalize_dialect_for_sqlglot` · **Extras:** none

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `dialect` | `str` | required | The dialect or database name. Matching ignores case but not surrounding spaces. |

##### Returns

`str`: the lower-case form of `dialect`, except for these names, which return `"postgres"`:

| Name | Result |
| --- | --- |
| `netezza` | `postgres` |
| `greenplum` | `postgres` |
| `vertica` | `postgres` |
| `datafusion` | `postgres` |
| `ansi` | `postgres` |
| `standard` | `postgres` |

Every other name is returned lower-cased and unchanged. The function does not check that SQLGlot knows the result: `"postgresql"` and `"not_a_dialect"` pass through as given, and `None` or `""` returns `""`.

##### Raises

Nothing it raises itself. A value that is neither a string nor empty, such as `5`, raises `AttributeError`.

##### Example

```python
from benchbox.utils.dialect_utils import normalize_dialect_for_sqlglot

# Netezza maps to PostgreSQL
normalized = normalize_dialect_for_sqlglot("netezza")
assert normalized == "postgres"

# Supported dialects pass through unchanged
normalized = normalize_dialect_for_sqlglot("duckdb")
assert normalized == "duckdb"

# Case-insensitive
normalized = normalize_dialect_for_sqlglot("SNOWFLAKE")
assert normalized == "snowflake"

print(normalize_dialect_for_sqlglot("postgresql"))
print(repr(normalize_dialect_for_sqlglot(None)))
```

```text
postgresql
''
```

**Supported Dialects**:

SQLGlot 30.21.0 registers these dialect names, among others. The function passes them through unchanged:

- **Cloud**: athena, bigquery, databricks, redshift, snowflake
- **Open Source**: clickhouse, duckdb, mysql, postgres, sqlite
- **Enterprise**: oracle, teradata, tsql (SQL Server)
- **Big Data**: drill, druid, hive, presto, spark, spark2, trino
- **Other**: doris, dune, materialize, prql, risingwave, starrocks, tableau

BenchBox accepts any SQLGlot release from 25.6.0 up to, but not including, 31.0.0, so the registered names can differ with the release that is installed.

**Usage in Benchmarks**:

```python
from benchbox.tpch import TPCH
from benchbox.utils.dialect_utils import normalize_dialect_for_sqlglot

benchmark = TPCH(scale_factor=1.0)

# Translate query for Netezza (uses PostgreSQL dialect)
target_dialect = normalize_dialect_for_sqlglot("netezza")
query_netezza = benchmark.get_query(1, dialect=target_dialect)
```

### Query Translation

The `translate_query` method is available on all benchmark classes via `BaseBenchmark`.

**Method Signature**:

```python
def translate_query(
    self,
    query_id: Union[int, str],
    dialect: str
) -> str
```

**Parameters**:

- **query_id** (int|str): Query identifier. TPC-H and TPC-DS take an integer; ClickBench takes a string such as `"Q1"`, and SSB takes strings such as `"Q1.1"`.
- **dialect** (str): Target SQL dialect

**Returns**: Translated query string

**Raises**:

- **ValueError**: If query_id is out of range (TPC-H accepts 1 to 22)
- **ValueError**: If dialect is not supported by SQLGlot (for example `Unknown dialect 'nonsense_dialect'`)
- **TypeError**: If a TPC-H or TPC-DS query_id is not an integer

**Basic Translation**:

```python
from benchbox.tpch import TPCH

benchmark = TPCH(scale_factor=1.0)

# Translate TPC-H Query 1 to different dialects
q1_duckdb = benchmark.translate_query(1, "duckdb")
q1_postgres = benchmark.translate_query(1, "postgres")
q1_bigquery = benchmark.translate_query(1, "bigquery")
q1_snowflake = benchmark.translate_query(1, "snowflake")

print("DuckDB:")
print(q1_duckdb)
print("\nPostgreSQL:")
print(q1_postgres)
```

**Batch Translation**:

```python
from benchbox.tpch import TPCH

benchmark = TPCH(scale_factor=1.0)
target_dialect = "snowflake"

# Translate all queries
translated_queries = {}

for query_id in range(1, 23):  # TPC-H has 22 queries
    try:
        translated = benchmark.translate_query(query_id, target_dialect)
        translated_queries[f"Q{query_id}"] = translated
    except Exception as e:
        print(f"Failed to translate Q{query_id}: {e}")

print(f"Successfully translated {len(translated_queries)} queries to {target_dialect}")
```

```text
Successfully translated 22 queries to snowflake
```

**Cross-Platform Validation**:

```python
from benchbox.clickbench import ClickBench

benchmark = ClickBench(scale_factor=0.01)

# Test query translation across multiple platforms
dialects_to_test = ["duckdb", "postgres", "mysql", "bigquery", "snowflake"]
query_id = "Q1"

translation_results = {}

for dialect in dialects_to_test:
    try:
        translated = benchmark.translate_query(query_id, dialect)
        translation_results[dialect] = {
            "success": True,
            "query_length": len(translated),
            "query": translated[:100] + "..." if len(translated) > 100 else translated
        }
    except Exception as e:
        translation_results[dialect] = {
            "success": False,
            "error": str(e)
        }

# Print results
print("Translation Results:")
for dialect, result in translation_results.items():
    if result["success"]:
        print(f"  {dialect:15s}: SUCCESS ({result['query_length']} chars)")
    else:
        print(f"  {dialect:15s}: FAILED - {result['error']}")
```

```text
Translation Results:
  duckdb         : SUCCESS (27 chars)
  postgres       : SUCCESS (27 chars)
  mysql          : SUCCESS (27 chars)
  bigquery       : SUCCESS (27 chars)
  snowflake      : SUCCESS (27 chars)
```

## Execution Configuration

### `benchbox.utils.ExecutionConfigHelper`

<span id="benchbox.utils.ExecutionConfigHelper"></span>

Reads and changes the power-run and concurrent-query execution settings that are stored in a configuration provider, and applies named performance profiles to them.

**Import:** `from benchbox.utils import ExecutionConfigHelper` · **Extras:** none

{#execution-config-helper-parameters}

#### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `config_manager` | object with `get(key, default)` and `set(key, value)` or `None` | `None` | The provider that holds the settings. `None` uses the process-wide provider, or a new in-memory provider with the defaults below when none has been registered. Each helper created that way has its own settings. |

{#execution-config-helper-returns}

#### Returns

An `ExecutionConfigHelper` with the provider in `config_manager`. Its methods return these values.

| Method | Returns |
| --- | --- |
| `get_power_run_settings()` | A `PowerRunSettings` dataclass with `iterations` (default 4), `warm_up_iterations` (0), `timeout_per_iteration_minutes` (60), `fail_fast` (`False`) and `collect_metrics` (`True`). |
| `get_concurrent_queries_settings()` | A `ConcurrentQueriesSettings` dataclass with `enabled` (`False`), `max_concurrent` (2), `query_timeout_seconds` (300), `stream_timeout_seconds` (`None`, not set), `retry_failed_queries` (`True`), `max_retries` (3) and `cancel_on_timeout` (`False`). |
| `update_power_run_settings(settings)` and `update_concurrent_queries_settings(settings)` | `None`. Write every field of the settings object to the provider, except a `stream_timeout_seconds` of `None`, which is left unwritten so the benchmark default applies. |
| `enable_power_run_iterations(iterations: int = 3, warm_up_iterations: int = 1)` | `None`. Sets the two counts. |
| `enable_concurrent_queries(max_concurrent: int = 2)` | `None`. Sets `enabled` to `True` and `max_concurrent`. |
| `disable_concurrent_queries()` | `None`. Sets `enabled` to `False`. |
| `optimize_for_system(cpu_cores: int, memory_gb: float)` | `None`. Sets `max_concurrent` to `cpu_cores // 4`, at least 2 and at most 8. Below 8 GB it sets the iteration timeout to 120 minutes and the query timeout to 600 seconds; above 16 GB, to 45 minutes and 180 seconds. From 8 to 16 GB the timeouts stay as they are. It never writes a stream timeout. |
| `create_performance_profile(profile_name: str)` | `dict` with `name`, `power_run` and `concurrent_queries`, without changing any setting. The profiles are `quick`, `standard`, `thorough` and `stress`, see below. |
| `apply_performance_profile(profile_name: str)` | `None`. Writes the profile's settings to the provider. Profiles do not set a stream timeout. |
| `get_execution_summary()` | `dict` with `power_run` (`enabled`, `total_iterations`, `estimated_duration_minutes`, `settings`), `concurrent_queries` (`enabled`, `max_streams`, `estimated_stream_duration_minutes`, which is `None` when no stream timeout is set or it is 0, and `settings`) and `general` (`max_workers`, `memory_limit_gb`, `parallel_queries`). |
| `save_config()` and `validate_execution_config()` | Call `save_config()` and `validate_config()` on the provider and return what `validate_config()` returns. |

Performance profiles:

| Profile | Iterations | Warm-up | Iteration timeout (min) | Concurrent queries | Max concurrent |
| --- | --- | --- | --- | --- | --- |
| `quick` | 1 | 0 | 30 | off | 2 |
| `standard` | 3 | 1 | 60 | on | 2 |
| `thorough` | 5 | 2 | 120 | on | 4 |
| `stress` | 10 | 3 | 180 | on | 8 |

{#execution-config-helper-raises}

#### Raises

- `create_performance_profile` and `apply_performance_profile`: `ValueError` for an unknown profile (`Unknown performance profile: fast. Available: ['quick', 'standard', 'thorough', 'stress']`).
- `save_config` and `validate_execution_config`: `AttributeError` when the provider has no `save_config` or `validate_config` method, which is the case for the default in-memory provider.

{#execution-config-helper-example}

#### Example

```python
from benchbox.utils import ExecutionConfigHelper

helper = ExecutionConfigHelper()
print(helper.get_power_run_settings().iterations, helper.get_concurrent_queries_settings().enabled)

helper.apply_performance_profile("thorough")
print(helper.get_power_run_settings().to_dict())

helper.optimize_for_system(cpu_cores=16, memory_gb=32)
print(helper.get_power_run_settings().timeout_per_iteration_minutes, helper.get_concurrent_queries_settings().max_concurrent)

summary = helper.get_execution_summary()
print(summary["power_run"]["total_iterations"], summary["general"])

try:
    helper.create_performance_profile("fast")
except ValueError as exc:
    print(exc)

try:
    helper.save_config()
except AttributeError as exc:
    print(exc)
```

Output on 0.4.1:

```text
4 False
{'iterations': 5, 'warm_up_iterations': 2, 'timeout_per_iteration_minutes': 120, 'fail_fast': False, 'collect_metrics': True}
45 4
7 {'max_workers': 4, 'memory_limit_gb': 8, 'parallel_queries': False}
Unknown performance profile: fast. Available: ['quick', 'standard', 'thorough', 'stress']
'SimpleConfigProvider' object has no attribute 'save_config'
```

{#execution-config-helper-compatibility}

#### Compatibility

`PowerRunSettings` and `ConcurrentQueriesSettings` are importable from `benchbox.utils` and `benchbox.utils.config_helpers`. A helper created without a provider does not share settings with other helpers: changes stay in that helper's own provider.

## Usage Examples

### Multi-Dialect Benchmark

Run benchmarks across multiple SQL dialects to test query compatibility. The example needs the DuckDB package (`pip install duckdb`).

```python
from benchbox.ssb import SSB
from benchbox.platforms.duckdb import DuckDBAdapter
import time

benchmark = SSB(scale_factor=0.01)
benchmark.generate_data()

adapter = DuckDBAdapter()
conn = adapter.create_connection()
adapter.create_schema(benchmark, conn)
adapter.load_data(benchmark, conn, benchmark.output_dir)

# Test query translation for different target databases
target_dialects = ["postgres", "mysql", "bigquery"]
query_ids = ["Q1.1", "Q1.2", "Q1.3"]

dialect_results = {}

for dialect in target_dialects:
    print(f"\nTesting {dialect} translations:")
    dialect_results[dialect] = []

    for query_id in query_ids:
        try:
            # Translate query
            translated_query = benchmark.translate_query(query_id, dialect)

            # Test if valid SQL (may not execute on DuckDB)
            result = {
                "query_id": query_id,
                "translated": True,
                "length": len(translated_query)
            }

            print(f"  {query_id}: Translated ({len(translated_query)} chars)")

        except Exception as e:
            result = {
                "query_id": query_id,
                "translated": False,
                "error": str(e)
            }
            print(f"  {query_id}: Failed - {e}")

        dialect_results[dialect].append(result)

# Summary
print("\nTranslation Summary:")
for dialect, results in dialect_results.items():
    success_count = sum(1 for r in results if r["translated"])
    print(f"  {dialect}: {success_count}/{len(results)} successful")
```

```text
  ✅ Loaded 300 rows into customer from 1 shard(s)
  ✅ Loaded 2,557 rows into date from 1 shard(s)
  ✅ Loaded 60,000 rows into lineorder from 1 shard(s)
  ✅ Loaded 2,000 rows into part from 1 shard(s)
  ✅ Loaded 20 rows into supplier from 1 shard(s)

Testing postgres translations:
  Q1.1: Translated (196 chars)
  Q1.2: Translated (219 chars)
  Q1.3: Translated (235 chars)

Testing mysql translations:
  Q1.1: Translated (196 chars)
  Q1.2: Translated (219 chars)
  Q1.3: Translated (235 chars)

Testing bigquery translations:
  Q1.1: Translated (196 chars)
  Q1.2: Translated (219 chars)
  Q1.3: Translated (235 chars)

Translation Summary:
  postgres: 3/3 successful
  mysql: 3/3 successful
  bigquery: 3/3 successful
```

### Automated Dialect Testing

Validate SQL dialect translation quality:

```python
from benchbox.tpch import TPCH
from benchbox.utils.dialect_utils import normalize_dialect_for_sqlglot

class DialectValidator:
    def __init__(self, benchmark):
        self.benchmark = benchmark

    def validate_dialect_support(self, dialect: str) -> dict:
        """Validate if a dialect is supported and working."""
        normalized = normalize_dialect_for_sqlglot(dialect)

        results = {
            "dialect": dialect,
            "normalized": normalized,
            "supported": True,
            "translated_queries": 0,
            "failed_queries": 0,
            "errors": []
        }

        # Test translation for sample queries
        sample_queries = list(range(1, 6))  # Test first 5 queries

        for query_id in sample_queries:
            try:
                translated = self.benchmark.translate_query(query_id, normalized)
                results["translated_queries"] += 1
            except Exception as e:
                results["failed_queries"] += 1
                results["errors"].append({
                    "query_id": query_id,
                    "error": str(e)
                })

        results["supported"] = results["failed_queries"] == 0

        return results

# Usage
benchmark = TPCH(scale_factor=0.01)
validator = DialectValidator(benchmark)

# Validate multiple dialects
dialects_to_validate = [
    "duckdb", "postgres", "mysql", "bigquery",
    "snowflake", "redshift", "clickhouse", "netezza"
]

print("Dialect Validation Results:")
print("=" * 70)

for dialect in dialects_to_validate:
    result = validator.validate_dialect_support(dialect)

    status = "✓ SUPPORTED" if result["supported"] else "✗ ISSUES"
    print(f"\n{dialect.upper()} → {result['normalized']}: {status}")
    print(f"  Translated: {result['translated_queries']}/{result['translated_queries'] + result['failed_queries']}")

    if result["errors"]:
        print(f"  Errors:")
        for error in result["errors"][:3]:  # Show first 3 errors
            print(f"    Q{error['query_id']}: {error['error'][:60]}...")
```

The last block of the output, where `netezza` is normalized to `postgres`:

```text
NETEZZA → postgres: ✓ SUPPORTED
  Translated: 5/5
```

### Custom Dialect Handling

Handle custom or proprietary database dialects:

```python
from benchbox.tpcds import TPCDS
from benchbox.utils.dialect_utils import normalize_dialect_for_sqlglot

class CustomDialectHandler:
    """Handle custom database dialects with fallback strategies."""

    # Map custom dialects to closest SQLGlot-supported dialect.
    # Exasol ships its own sqlglot dialect: the identity entry keeps
    # the generic fallback branch below from defaulting it to postgres.
    CUSTOM_DIALECT_MAP = {
        "exasol": "exasol",         # Native sqlglot dialect, no fallback
        "vertica": "postgres",      # Vertica uses PostgreSQL syntax
        "greenplum": "postgres",    # Greenplum is PostgreSQL-based
        "yellowbrick": "postgres",   # Yellowbrick uses PostgreSQL syntax
        "monetdb": "postgres",      # MonetDB has PostgreSQL compatibility
    }

    @classmethod
    def get_fallback_dialect(cls, dialect: str) -> str:
        """Get fallback dialect for custom databases."""
        # First try official normalization
        normalized = normalize_dialect_for_sqlglot(dialect)

        # Then check custom mappings
        if normalized == dialect.lower():  # No official mapping found
            return cls.CUSTOM_DIALECT_MAP.get(dialect.lower(), "postgres")

        return normalized

    @classmethod
    def translate_for_custom_dialect(
        cls,
        benchmark,
        query_id: int,
        target_dialect: str
    ) -> str:
        """Translate query for custom dialect with fallback."""
        fallback_dialect = cls.get_fallback_dialect(target_dialect)

        print(f"Translating {query_id} for {target_dialect} "
              f"(using {fallback_dialect} dialect)")

        return benchmark.translate_query(query_id, fallback_dialect)

# Usage
benchmark = TPCDS(scale_factor=0.1)

# Translate for Vertica
q1_vertica = CustomDialectHandler.translate_for_custom_dialect(
    benchmark, 1, "vertica"
)

# Translate for Greenplum
q2_greenplum = CustomDialectHandler.translate_for_custom_dialect(
    benchmark, 2, "greenplum"
)
```

```text
Translating 1 for vertica (using postgres dialect)
Translating 2 for greenplum (using postgres dialect)
```

TPC-DS query IDs are integers, so the example passes `1` and `2`; a string such as `"Q1"` raises `TypeError`.

## Best Practices

### Dialect Translation

1. **Always validate translations**: Test translated queries on target platform before production use

   ```python
   # Good: Validate translated query
   translated = benchmark.translate_query(1, "postgres")

   # Test on target platform
   try:
       result = postgres_conn.execute(translated)
       print("Translation validated successfully")
   except Exception as e:
       print(f"Translation needs adjustment: {e}")
   ```

2. **Use dialect normalization**: Normalize dialects before translation

   ```python
   from benchbox.utils.dialect_utils import normalize_dialect_for_sqlglot

   # Normalize before use
   target_dialect = normalize_dialect_for_sqlglot(user_input_dialect)
   query = benchmark.translate_query(1, target_dialect)
   ```

3. **Handle translation failures gracefully**: Not all SQL features translate perfectly

   ```python
   try:
       translated = benchmark.translate_query(query_id, dialect)
   except ValueError as e:
       print(f"Dialect not supported: {e}")
       # Fall back to compatible dialect
       translated = benchmark.translate_query(query_id, "postgres")
   ```

4. **Cache translated queries**: Translation can be expensive for large query sets

   ```python
   from functools import lru_cache

   class CachedTranslator:
       @lru_cache(maxsize=1000)
       def translate_cached(self, benchmark_name, query_id, dialect):
           benchmark = self.get_benchmark(benchmark_name)
           return benchmark.translate_query(query_id, dialect)
   ```

5. **Document dialect limitations**: Track which features don't translate well

   ```python
   DIALECT_LIMITATIONS = {
       "mysql": [
           "No support for FULL OUTER JOIN",
           "Limited window function support in older versions"
       ],
       "sqlite": [
           "No RIGHT JOIN or FULL OUTER JOIN",
           "Limited date/time function support"
       ]
   }
   ```

## Common Issues

### Unsupported Dialect

**Problem**: `ValueError: Error translating to dialect 'xyz': Unknown dialect 'xyz'.`

**Solutions**:

```python
from benchbox.utils.dialect_utils import normalize_dialect_for_sqlglot

# 1. Check if dialect needs normalization
normalized = normalize_dialect_for_sqlglot("netezza")  # Returns "postgres"

# 2. Use fallback dialect
try:
    query = benchmark.translate_query(1, "custom_db")
except ValueError:
    # Fall back to PostgreSQL (most compatible)
    query = benchmark.translate_query(1, "postgres")

# 3. Check SQLGlot documentation for supported dialects
# https://sqlglot.com/sqlglot/dialects.html
```

### Translation Quality Issues

**Problem**: Translated query produces incorrect results or fails to execute

**Solutions**:

```python
# 1. Compare original and translated queries
original = benchmark.get_query(1)
translated = benchmark.translate_query(1, "bigquery")

print("Original:")
print(original)
print("\nTranslated:")
print(translated)

# 2. Test with smaller dataset first
small_benchmark = TPCH(scale_factor=0.01)
translated = small_benchmark.translate_query(1, "bigquery")
# Test execution...

# 3. Manual adjustments for platform-specific features
if "bigquery" in target_dialect:
    # BigQuery-specific adjustments
    translated = translated.replace("::DATE", "")
```

## See Also

- {doc}`base` - Base benchmark interface
- {doc}`platforms` - Platform adapter documentation
- {doc}`benchmarks/index` - Benchmark API overview
- {doc}`/usage/configuration` - Configuration guide
- {doc}`/usage/troubleshooting` - Troubleshooting guide

### External Resources

- [SQLGlot Documentation](https://sqlglot.com/) - SQL dialect translation library
- [SQLGlot Dialects](https://sqlglot.com/sqlglot/dialects.html) - Supported SQL dialects
- [SQL Standards](https://www.iso.org/standard/63555.html) - ISO SQL standards
