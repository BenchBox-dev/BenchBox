Utility Functions API
=====================

.. tags:: reference, python-api

Complete Python API reference for BenchBox utility functions.

Overview
--------

BenchBox provides utility functions for common tasks like SQL dialect translation, configuration management, and data format handling. These utilities simplify cross-database benchmarking and platform-specific optimizations.

**Available Utilities**:

- **Dialect Translation**: SQL dialect normalization and query translation
- **Configuration Helpers**: Platform and benchmark configuration utilities
- **Data Format Utilities**: File format detection and handling

Dialect Translation
-------------------

.. important::
   **Dialect Translation vs Platform Adapters**

   BenchBox can translate queries to many SQL dialects via SQLGlot (PostgreSQL, MySQL, SQL Server, Oracle, etc.),
   but **dialect translation does not mean platform adapters exist** for connecting to those databases.

   **Currently supported platforms**: DuckDB, SQLite, PostgreSQL, TimescaleDB, ClickHouse, Databricks SQL, BigQuery, Redshift, Snowflake, Trino, Presto, Amazon Athena, Firebolt, Azure Synapse Analytics, Microsoft Fabric, and many more (see :doc:`/platforms/index`)

   **Planned platforms**: MySQL, SQL Server, and others (see :doc:`/development/roadmap`)

   The examples below demonstrate dialect translation capabilities - you can use translated queries with your own
   database connections, but BenchBox's built-in platform adapters are limited to the supported platforms listed above.

SQL Dialect Normalization
~~~~~~~~~~~~~~~~~~~~~~~~~

.. autofunction:: benchbox.utils.dialect_utils.normalize_dialect_for_sqlglot

**Purpose**: Normalize database dialect names for SQLGlot compatibility.

**Supported Dialects**:

SQLGlot natively supports these dialects:

- **Cloud**: athena, bigquery, databricks, redshift, snowflake
- **Open Source**: clickhouse, duckdb, mysql, postgres, sqlite
- **Enterprise**: oracle, teradata, tsql (SQL Server)
- **Big Data**: drill, druid, hive, presto, spark, spark2, trino
- **Other**: doris, dune, materialize, prql, risingwave, starrocks, tableau

**Dialect Mappings**:

.. code-block:: python

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

**Usage in Benchmarks**:

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.utils.dialect_utils import normalize_dialect_for_sqlglot

    benchmark = TPCH(scale_factor=1.0)

    # Translate query for Netezza (uses PostgreSQL dialect)
    target_dialect = normalize_dialect_for_sqlglot("netezza")
    query_netezza = benchmark.get_query(1, dialect=target_dialect)

Query Translation
~~~~~~~~~~~~~~~~~

The ``translate_query`` method is available on all benchmark classes via ``BaseBenchmark``.

**Method Signature**:

.. code-block:: python

    def translate_query(
        self,
        query_id: Union[int, str],
        dialect: str
    ) -> str

**Parameters**:

- **query_id** (int|str): Query identifier
- **dialect** (str): Target SQL dialect

**Returns**: Translated query string

**Raises**:

- **ValueError**: If query_id is invalid
- **ImportError**: If sqlglot is not installed
- **ValueError**: If dialect is not supported

**Basic Translation**:

.. code-block:: python

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

**Batch Translation**:

.. code-block:: python

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

**Cross-Platform Validation**:

.. code-block:: python

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

Usage Examples
--------------

Multi-Dialect Benchmark
~~~~~~~~~~~~~~~~~~~~~~~

Run benchmarks across multiple SQL dialects to test query compatibility:

.. code-block:: python

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

Automated Dialect Testing
~~~~~~~~~~~~~~~~~~~~~~~~~~

Validate SQL dialect translation quality:

.. code-block:: python

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

Custom Dialect Handling
~~~~~~~~~~~~~~~~~~~~~~~

Handle custom or proprietary database dialects:

.. code-block:: python

    from benchbox.tpcds import TPCDS
    from benchbox.utils.dialect_utils import normalize_dialect_for_sqlglot

    class CustomDialectHandler:
        """Handle custom database dialects with fallback strategies."""

        # Map custom dialects to closest SQLGlot-supported dialect
        CUSTOM_DIALECT_MAP = {
            "vertica": "postgres",      # Vertica uses PostgreSQL syntax
            "greenplum": "postgres",    # Greenplum is PostgreSQL-based
            "yellowbrick": "postgres",   # Yellowbrick uses PostgreSQL syntax
            "exasol": "postgres",       # ExaSol has PostgreSQL compatibility
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
            query_id: str,
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
        benchmark, "Q1", "vertica"
    )

    # Translate for Greenplum
    q2_greenplum = CustomDialectHandler.translate_for_custom_dialect(
        benchmark, "Q2", "greenplum"
    )

Best Practices
--------------

Dialect Translation
~~~~~~~~~~~~~~~~~~~

1. **Always validate translations**: Test translated queries on target platform before production use

   .. code-block:: python

       # Good: Validate translated query
       translated = benchmark.translate_query(1, "postgres")

       # Test on target platform
       try:
           result = postgres_conn.execute(translated)
           print("Translation validated successfully")
       except Exception as e:
           print(f"Translation needs adjustment: {e}")

2. **Use dialect normalization**: Normalize dialects before translation

   .. code-block:: python

       from benchbox.utils.dialect_utils import normalize_dialect_for_sqlglot

       # Normalize before use
       target_dialect = normalize_dialect_for_sqlglot(user_input_dialect)
       query = benchmark.translate_query(1, target_dialect)

3. **Handle translation failures gracefully**: Not all SQL features translate perfectly

   .. code-block:: python

       try:
           translated = benchmark.translate_query(query_id, dialect)
       except ValueError as e:
           print(f"Dialect not supported: {e}")
           # Fall back to compatible dialect
           translated = benchmark.translate_query(query_id, "postgres")

4. **Cache translated queries**: Translation can be expensive for large query sets

   .. code-block:: python

       from functools import lru_cache

       class CachedTranslator:
           @lru_cache(maxsize=1000)
           def translate_cached(self, benchmark_name, query_id, dialect):
               benchmark = self.get_benchmark(benchmark_name)
               return benchmark.translate_query(query_id, dialect)

5. **Document dialect limitations**: Track which features don't translate well

   .. code-block:: python

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

Common Issues
-------------

Unsupported Dialect
~~~~~~~~~~~~~~~~~~~

**Problem**: ValueError: Dialect 'xyz' not supported

**Solutions**:

.. code-block:: python

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

Translation Quality Issues
~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Translated query produces incorrect results or fails to execute

**Solutions**:

.. code-block:: python

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

See Also
--------

- :doc:`base` - Base benchmark interface
- :doc:`platforms/index` - Platform adapter documentation
- :doc:`benchmarks/index` - Benchmark API overview
- :doc:`/usage/configuration` - Configuration guide
- :doc:`/usage/troubleshooting` - Troubleshooting guide

External Resources
~~~~~~~~~~~~~~~~~~

- `SQLGlot Documentation <https://sqlglot.com/>`_ - SQL dialect translation library
- `SQLGlot Dialects <https://sqlglot.com/sqlglot/dialects.html>`_ - Supported SQL dialects
- `SQL Standards <https://www.iso.org/standard/63555.html>`_ - ISO SQL standards
