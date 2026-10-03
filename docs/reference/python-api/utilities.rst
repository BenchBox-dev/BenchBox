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

.. py:function:: benchbox.utils.dialect_utils.normalize_dialect_for_sqlglot(dialect: str) -> str

   Lowercase a dialect name and map BenchBox aliases to a SQLGlot dialect.
   netezza, greenplum, vertica, datafusion, ansi and standard map to postgres.
   Other names pass through after lowercasing. An empty input produces an empty
   string. Whitespace is not stripped.

   :param dialect: Dialect name to normalize.
   :returns: Lowercase name or its mapped equivalent.

   This function does not check whether SQLGlot accepts the returned name,
   translate a query, or establish that a BenchBox platform adapter exists.

   .. code-block:: python

      from benchbox.utils.dialect_utils import normalize_dialect_for_sqlglot

      assert normalize_dialect_for_sqlglot("NETEZZA") == "postgres"
      assert normalize_dialect_for_sqlglot("duckdb") == "duckdb"
      assert normalize_dialect_for_sqlglot("custom_db") == "custom_db"
      assert normalize_dialect_for_sqlglot("") == ""


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

.. py:method:: benchbox.base.BaseBenchmark.translate_query(query_id: Union[int, str], dialect: str) -> str
   :no-index:

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

Timing and UTC Boundaries
-------------------------

.. py:function:: benchbox.utils.clock.mono_time() -> float

   Return a ``perf_counter`` timestamp in seconds for elapsed calculations.
   Its origin is unspecified; it is not a UTC timestamp.

.. py:function:: benchbox.utils.clock.elapsed_seconds(start: float, end: float | None = None) -> float

   Subtract ``start`` from ``end``, sampling ``mono_time()`` when ``end`` is
   ``None``. Both supplied timestamps must use the same monotonic clock.
   Negative differences are returned unchanged.

.. py:function:: benchbox.utils.clock.utc_now() -> datetime

   Return the current timezone-aware UTC datetime for event metadata.

.. py:class:: benchbox.utils.clock.Stopwatch(start_mono: float, start_utc: datetime)

   Store a monotonic start timestamp and a UTC start boundary. Both constructor
   fields are required; direct construction does not sample either clock.

   .. py:classmethod:: start() -> Stopwatch

      Construct a new stopwatch by sampling the monotonic and UTC clocks.

   .. py:method:: elapsed_seconds() -> float

      Return seconds since ``start_mono`` using the monotonic clock.

   .. py:method:: elapsed_ms() -> float

      Return elapsed seconds multiplied by 1,000.

   .. py:method:: finish() -> tuple[datetime, float]

      Return the current UTC boundary and elapsed seconds. This method does
      not stop or freeze the stopwatch; later calls sample again.

.. py:function:: benchbox.utils.clock.measure_elapsed() -> Iterator[Stopwatch]

   Context manager yielding a newly started stopwatch. Exiting does not stop
   the stopwatch or store a finish value; call its elapsed methods or
   ``finish()`` when the desired boundary is reached. Exceptions in the
   context body propagate.

Cloud URL Components
--------------------

.. py:function:: benchbox.utils.cloud_urls.parse_cloud_url(url: str) -> tuple[str, str]

   Split a cloud URL into bucket and key prefix at the first slash after its
   scheme. For ``s3://bucket/path/`` the result is ``("bucket", "path/")``;
   for ``s3://bucket/`` it is ``("bucket", "")``. Remaining slashes,
   query-looking suffixes and percent escapes are preserved verbatim.

   This helper performs string splitting, not scheme, bucket or credential
   validation. The named schemes are ``s3``, ``gs`` and ``az``; other schemes
   are split with the same prefix-length rule. Pass a correctly formed URL.

.. py:function:: benchbox.utils.cloud_urls.parse_s3_url(s3_url: str) -> tuple[str, str]

   Delegate to ``parse_cloud_url`` without enforcing the S3 scheme.

.. py:function:: benchbox.utils.cloud_urls.parse_gcs_url(gcs_url: str) -> tuple[str, str]

   Delegate to ``parse_cloud_url`` without enforcing the GCS scheme.

Display Formatting
------------------

.. py:function:: benchbox.utils.formatting.format_duration(seconds: float) -> str

   Format values below one second as milliseconds with one decimal; values
   from one to below sixty seconds as seconds with three decimals; values
   at or above sixty seconds as minutes with one decimal. No range check is
   performed. For example, ``0.123`` produces ``"123.0ms"`` and ``1.5``
   produces ``"1.500s"``.

.. py:function:: benchbox.utils.formatting.format_bytes(bytes_val: int | float) -> str

   Convert to float and divide repeatedly by 1,024, selecting B, KB, MB, GB
   or TB while the value is below the next boundary, then PB for larger
   values. The result always has two decimal places and a separating space.
   Despite the unit labels, the conversion uses binary factors.

.. py:function:: benchbox.utils.formatting.format_memory_usage(memory_mb: float) -> str

   Multiply the input by ``1024 * 1024`` and delegate to ``format_bytes``.
   Thus ``512.5`` produces ``"512.50 MB"``; the input unit is binary
   megabytes and output precision is two decimals.

.. py:function:: benchbox.utils.formatting.format_number(value: int | float, precision: int = 2) -> str

   Add comma thousands separators. Integer inputs retain integer formatting
   regardless of ``precision``; other numeric inputs use that many decimal
   places. Python formatting errors propagate.

SQL Identifier and Parenthesis Checks
-------------------------------------

.. py:function:: benchbox.utils.sql_identifier.is_valid_sql_identifier(identifier: str, *, max_length: int) -> bool

   Return false for empty or non-string inputs and for names exceeding the
   caller's required length cap. Otherwise test the ASCII pattern
   ``^[a-zA-Z_][a-zA-Z0-9_]*$`` with Python's regular-expression matcher.
   This helper does not reject reserved words, quote a name or infer an
   engine-specific length cap. Because ``$`` accepts a position before a
   final newline, callers must not interpret the pattern as a stronger
   full-string validation guarantee.

   BenchBox callers currently use caps of 63 for PostgreSQL, TimescaleDB,
   pg_duckdb, pg_mooncake and CedarDB; 127 for QuestDB; and 128 for Spark,
   LakeSail, Velox and the Hive metastore. These are project caller settings,
   not a universal statement about those engines.

.. py:function:: benchbox.utils.sql_parsing.find_matching_parenthesis(text: str, open_index: int) -> int

   Starting at the supplied opening-parenthesis index, track nested
   parentheses and return the corresponding closing index. Parentheses
   inside single-quoted text are ignored; doubled single quotes are
   recognized. Backslash escapes, comments and double-quoted identifiers
   are not parsed. A valid opening index is a caller precondition.

   :raises ValueError: The scan reaches the end without closing the group.

Data-Generation Provenance
--------------------------

.. py:data:: benchbox.utils.datagen_version.DATA_GENERATION_VERSION
   :type: int
   :value: 1

   Generation-logic version used in manifest stamps. Maintainers must bump
   this value when generator-code changes invalidate previously generated
   data. Specification-backed benchmarks must also register their influencing
   files in the benchmark specification mapping; otherwise specification
   edits cannot invalidate that benchmark's cached data.

.. py:function:: benchbox.utils.datagen_version.compute_base_constants_hash(benchmark: str | None = None) -> str

   Return a SHA-256 hex digest seeded by ``DATA_GENERATION_VERSION`` and
   extended with the raw bytes of registered specification files. Benchmark
   lookup lowercases the supplied name. Registered names are ``tpch``,
   ``tpch_skew`` and ``tsbs_devops``/``tsbs``; skewed TPC-H includes both the
   base TPC-H and skew specifications. Unknown names use only the version
   marker. Unreadable specification files are skipped, so this digest
   cannot certify their presence or detect unregistered specification edits.

.. py:function:: benchbox.utils.datagen_version.current_datagen_stamp(benchmark: str | None = None) -> dict[str, Any]

   Return ``data_generation_version`` and ``base_constants_hash`` for newly
   generated manifests. The current generation version is ``1``.

.. py:function:: benchbox.utils.datagen_version.compute_datagen_identity_hash(benchmark: str | None, configuration: Mapping[str, Any] | None = None) -> str

   Hash a compact, key-sorted JSON object containing the version, base-constant
   hash and a shallow dictionary copy of the optional effective configuration.
   ``None`` and an empty configuration produce different identities.

   :raises TypeError: Configuration values cannot be encoded as JSON.

.. py:function:: benchbox.utils.datagen_version.manifest_datagen_is_current(manifest: Mapping[str, Any] | None, benchmark: str | None = None) -> bool

   Require a mapping with the current version and expected base-constant
   hash. An explicit benchmark takes precedence over ``manifest["benchmark"]``.
   No generated data files or effective-configuration identity are checked.

.. py:function:: benchbox.utils.datagen_version.describe_datagen_staleness(manifest: Mapping[str, Any] | None, benchmark: str | None = None) -> str | None

   Return ``None`` when the stamp is current. Otherwise return a reason for
   a missing/unreadable manifest, absent version stamp, different generation
   version or changed base constants. This function does not regenerate data.

Data Format Selection
---------------------

.. py:class:: benchbox.utils.format_selection.FormatSelector

   Stateless format selection and local availability inspection.

   .. py:staticmethod:: select_format(platform_name: str, available_formats: list[str], user_preference: str | None = None) -> str

      Return ``"tbl"`` immediately when no formats are available, even when
      a user preference was supplied. Otherwise a nonempty preference must
      be both available and supported, or ``ValueError`` is raised. Without
      a preference, delegate to the platform's preferred-format resolver.

   .. py:staticmethod:: get_fallback_chain(platform_name: str, available_formats: list[str]) -> list[str]

      Start with available, supported formats in platform preference order,
      then append every remaining available format once in input order.
      Those appended formats are not filtered for platform support, so the
      returned list does not certify that every attempt is supported.

   .. py:staticmethod:: detect_available_formats(data_dir: Path, table_name: str, manifest_data: dict[str, Any] | None = None) -> list[str]

      Prefer nonempty manifest format metadata: top-level ``formats`` followed
      by keys of ``tables[table_name]["formats"]``, deduplicated in encounter
      order. This path does not verify files exist. Otherwise inspect local
      table-name patterns for tbl/dat, CSV and Parquet files, then Delta's
      ``_delta_log`` directory and Iceberg layout. Return ``["tbl"]`` when
      nothing is detected. No cloud storage discovery is performed.


See Also
--------

- :doc:`base` - Base benchmark interface
- :doc:`platforms` - Platform adapter documentation
- :doc:`benchmarks/index` - Benchmark API overview
- :doc:`/usage/configuration` - Configuration guide
- :doc:`/usage/troubleshooting` - Troubleshooting guide

External Resources
~~~~~~~~~~~~~~~~~~

- `SQLGlot Documentation <https://sqlglot.com/>`_ - SQL dialect translation library
- `SQLGlot Dialects <https://sqlglot.com/sqlglot/dialects.html>`_ - Supported SQL dialects
- `SQL Standards <https://www.iso.org/standard/63555.html>`_ - ISO SQL standards

Dataset Names and Output Paths
------------------------------

These helpers construct names and paths. Except for ``ensure_directory``, they
neither create directories nor validate remote storage access. Names are
compatibility labels, not unique dataset identities.

Scale-label formatting and its precision/identity limits are documented in
:doc:`additional-utilities`.

.. py:function:: benchbox.utils.output_path.normalize_output_root(output_root: str | None, benchmark: str, scale: float) -> str | None

   Return a falsy root unchanged. Otherwise strip/lowercase the benchmark,
   construct its scale suffix, and strip trailing slashes from the root.
   Append the suffix only if the final slash-separated component does not
   already match it case-insensitively. Preserve an existing component's case.
   An empty benchmark uses only the scale suffix. Local paths and remote URIs
   follow the same string operation; no scheme or filesystem validation occurs.

.. py:function:: benchbox.utils.path_utils.get_default_data_directory() -> Path

   Use a nonempty ``BENCHBOX_DATA_DIR`` verbatim as a ``Path``; otherwise use
   ``Path.cwd() / "data"``. This helper does not strip whitespace or expand ``~``.

.. py:function:: benchbox.utils.path_utils.find_work_tree_root(start: Path | None = None) -> Path | None

   Inspect the starting directory and its parents for an existing ``.git``
   entry, accepting both clone directories and linked-worktree files. Resolve
   an explicit start first; otherwise start at ``Path.cwd()``. Return ``None``
   when no entry exists. Discovery does not launch Git, so it also works without
   a Git executable during benchmark construction.

.. py:function:: benchbox.utils.path_utils.default_benchmark_runs_root(start: Path | None = None) -> Path

   Delegate to shared runtime path resolution: use ``benchmark_runs`` beside
   the enclosing Git worktree, or beneath the starting directory outside Git.
   A worktree is identified by an existing ``.git`` entry, not its directory type.

.. py:function:: benchbox.utils.path_utils.resolve_benchmark_runs_dir() -> Path

   Use a nonblank ``BENCHBOX_OUTPUT_DIR`` after trimming and expanding ``~``;
   otherwise use the shared worktree-sibling/default rule above. This is distinct
   from the ``BENCHBOX_DATA_DIR`` rule used by ``get_default_data_directory``.

.. py:function:: benchbox.utils.path_utils.get_benchmark_runs_datagen_path(benchmark_name: str, scale_factor: float, base_dir: str | Path | None = None) -> Path

   Append ``<benchmark>_<formatted scale>`` to an explicit datagen root, or to
   ``resolve_benchmark_runs_dir() / "datagen"``. An explicit root does not
   receive another ``datagen`` component and is not expanded or resolved.

.. py:function:: benchbox.utils.path_utils.get_benchmark_runs_databases_path(benchmark_name: str, scale_factor: float, base_dir: str | Path | None = None) -> Path

   Apply the same rule with ``databases`` as the default subdirectory. The
   supplied benchmark name is not sanitized by either helper.

.. py:function:: benchbox.utils.path_utils.get_benchmark_runs_dataframe_path(base_dir: str | Path | None = None) -> Path

   Return an explicit root as a ``Path``; otherwise return the shared
   ``datagen`` directory used by SQL generation. Do not append a dataset suffix.

.. py:function:: benchbox.utils.path_utils.get_results_path(benchmark_name: str, timestamp: str, base_dir: str | Path | None = None) -> Path

   Append ``results/<benchmark>_<timestamp>`` to an explicit root or the default
   data directory. This uses ``BENCHBOX_DATA_DIR``, not ``BENCHBOX_OUTPUT_DIR``;
   the benchmark and timestamp are not sanitized.

.. py:function:: benchbox.utils.path_utils.ensure_directory(path: str | Path) -> Path

   Create the directory and missing parents with ``exist_ok=True`` and return
   its ``Path``. Filesystem errors propagate; the returned path is not resolved.

Runtime Toggles and Output
--------------------------

.. py:function:: benchbox.utils.toggles.is_probe_requested(value: Any) -> bool

   Normalize an opt-out toggle: ``None`` means requested, booleans pass through,
   and numbers use their truth value. Strip/lowercase strings; ``0``, ``false``,
   ``no`` and ``off`` mean false, while ``1``, ``true``, ``yes`` and ``on`` mean
   true. Other strings, including empty strings, log a warning and return false
   rather than enable a potentially billable probe on ambiguous input. Other
   objects use ``bool(value)``. This helper decides intent; it executes no probe.

Quiet-aware output helpers provide a shared runtime channel. Use ``emit`` for
text or Rich renderables. Where Rich keyword arguments are needed, use
``quiet_console.print`` or inject ``quiet_console`` into display classes.

.. py:function:: benchbox.utils.printing.set_quiet(enabled: bool) -> None

   Set process-global quiet state to ``bool(enabled)``. Its initial value is
   false. This affects subsequent helper calls and proxy attribute lookups.

.. py:function:: benchbox.utils.printing.is_quiet() -> bool

   Return the current global quiet state.

.. py:function:: benchbox.utils.printing.get_console(quiet: bool | None = None, *, stderr: bool = False) -> Console

   With ``quiet=None`` use global state; an explicit boolean overrides it,
   so false can force visible output while global quiet is enabled. Lazily
   cache separate stdout/stderr consoles. Quiet calls share a sink console
   backed by an in-memory stream, independent of the requested channel.

.. py:function:: benchbox.utils.printing.get_quiet_console() -> Console

   Return that sink regardless of global quiet state, without changing it.

.. py:function:: benchbox.utils.printing.emit(msg: Any = "", *, quiet: bool | None = None, stderr: bool = False) -> None

   Use the same global/explicit quiet precedence. Quiet calls return without
   printing. Visible calls pass the single message/renderable to Rich's
   ``Console.print`` on the requested channel; an omitted message emits a blank
   line. The function does not expose Rich styling keyword arguments.

.. py:function:: benchbox.utils.printing.info(msg: str) -> None
.. py:function:: benchbox.utils.printing.warn(msg: str) -> None
.. py:function:: benchbox.utils.printing.debug(msg: str) -> None

   Delegate to ``emit`` on stdout under global quiet state. These helpers do
   not apply logging levels or a separate verbosity gate.

.. py:function:: benchbox.utils.printing.error(msg: str) -> None

   Delegate to ``emit`` on stderr under global quiet state.

.. py:function:: benchbox.utils.printing.silence_output(enabled: bool = True) -> Iterator[None]

   A context manager that temporarily replaces Python's ``sys.stdout`` and
   ``sys.stderr`` with in-memory streams and restores both in ``finally``.
   False is a no-op. This changes process-global stream bindings, not file
   descriptors or independently held output streams; it is not task-local
   isolation and does not change global quiet state.

.. py:class:: benchbox.utils.printing.QuietConsoleProxy

   Forward attribute lookups and context-manager calls to the currently
   selected quiet-aware console. ``quiet_console`` is the shared proxy instance;
   changing quiet state affects later lookups on it. Its representation reports
   ``quiet`` or ``verbose`` according to global state.

Verbosity Settings and Logging
------------------------------

.. py:class:: benchbox.utils.verbosity.VerbositySettings(level: int = 0, verbose_enabled: bool = False, very_verbose: bool = False, quiet: bool = False)

   Frozen settings with the defaults shown. Direct construction does not
   normalize inconsistent fields. The ``verbose`` property is
   ``verbose_enabled and not quiet``. ``to_config()`` returns ``verbose_level``,
   ``verbose_enabled``, ``very_verbose``, ``quiet`` and the computed ``verbose``.

   .. py:method:: from_flags(verbose: int | bool | None, quiet: bool | None) -> VerbositySettings
      :classmethod:

      Boolean true means level 2; false or unset means 0. Other values use
      ``int(verbose or 0)``. Clamp negative levels to 0; truthy quiet forces level
      0. Enable verbose at level 1 and very verbose at level 2, unless quiet.
      Conversion errors propagate.

   .. py:method:: from_mapping(data: Mapping[str, Any] | None) -> VerbositySettings
      :classmethod:

      Empty or absent input returns default settings. Read ``quiet`` by truth
      value and ``verbose_level`` before the fallback ``level``, then apply
      ``int(value or 0)``. Quiet forces level 0; negative levels are otherwise
      retained. Explicit ``verbose_enabled`` and ``very_verbose`` values use
      their truth value and override defaults derived from level and quiet.
      These fields can remain true with quiet; the ``verbose`` property and
      mixin logging methods still respect quiet. Conversion errors propagate.

   .. py:method:: default() -> VerbositySettings
      :classmethod:

      Return the default settings shown above.

.. py:function:: benchbox.utils.verbosity.compute_verbosity(verbose: int | bool | None, quiet: bool | None) -> VerbositySettings

   Delegate to ``VerbositySettings.from_flags``.

.. py:class:: benchbox.utils.verbosity.VerbosityMixin

   Consumers set ``logger`` to a ``logging.Logger`` before a logging method
   reaches it. Reading an unset logger raises ``AttributeError``; assigning
   another type raises ``TypeError``. Verbosity fields initially use level 0
   and false flags. ``apply_verbosity(settings)`` copies the four settings fields
   and updates the legacy ``verbose`` attribute from the computed property.
   ``verbosity_settings`` returns a snapshot of the current four fields.

   Logging methods return without logging when ``quiet`` is true. They emit
   through Python logging, so logger levels and handlers also control visibility.
   ``log_verbose(message)`` uses INFO when ``verbose_enabled``;
   ``log_very_verbose(message)`` uses DEBUG when ``very_verbose``.
   ``log_notice(message)`` uses INFO without a verbosity requirement.

   ``log_operation_start(operation, details="")`` uses DEBUG with details when
   very verbose; otherwise it uses INFO when verbose is enabled.
   ``log_operation_complete(operation, duration=None, details="")`` uses DEBUG
   when very verbose, including supplied details; otherwise it uses INFO when
   verbose is enabled and omits details. Supplied durations appear in seconds
   with two decimal places.

   ``log_debug_info(context="Debug")`` requires very verbose and logs version,
   Python and platform information at DEBUG. Version-report failures fall back
   to basic version information or an unavailable message.
   ``log_error_with_debug_info(error, context="Error")`` logs at ERROR and adds
   debug context and the current exception traceback when very verbose.
   ``log_version_warning()`` checks version consistency and logs inconsistencies
   at WARNING, adding source details at DEBUG when very verbose. Failures in
   this version check are suppressed.

.. py:function:: benchbox.utils.verbosity.create_debug_logger(name: str, verbose_level: int = 0, quiet: bool = False) -> logging.Logger

   Get the named Python logger and set its level: ERROR for quiet, DEBUG for
   level 2 or higher, INFO for level 1, and WARNING otherwise. This changes the
   shared named logger; it does not add handlers. At level 2 or higher, also
   check version consistency and log a warning if inconsistent, including when
   quiet was requested. The logger's ERROR level normally filters that warning
   in quiet mode. Version-check failures are suppressed.

.. py:function:: benchbox.utils.verbosity.log_debug_context(logger: logging.Logger, context: dict[str, Any], title: str = "Debug Context") -> None

   Log the title and each key/value at DEBUG. No separate verbosity or quiet
   state is consulted.

.. py:function:: benchbox.utils.verbosity.log_import_debug(logger: logging.Logger, module_name: str, error: Exception | None = None) -> None

   Log import success or failure at DEBUG. A truthy error selects failure output
   and available version/Python context; version-report failures are suppressed.
   No separate verbosity or quiet state is consulted.

Configuration Providers and Execution Settings
----------------------------------------------

.. py:class:: benchbox.utils.config_interface.ConfigInterface

   Abstract provider interface with ``get(key, default=None)`` and
   ``set(key, value)``. Providers may supply richer behavior than the built-in
   in-memory implementation.

.. py:class:: benchbox.utils.config_interface.SimpleConfigProvider(defaults: dict | None = None)

   Shallow-copy supplied values and fill absent keys with built-in defaults;
   supplied values, including ``None``, take precedence. Keys are flat dotted
   strings, not nested-path lookups. ``get`` returns a caller default for an
   absent key; ``set`` and ``update(config_dict)`` store values without validation
   or persistence.

   Built-in ``execution.power_run`` defaults are ``iterations=4``,
   ``warm_up_iterations=0``, ``timeout_per_iteration_minutes=60`` and
   ``concurrent_streams=1``. ``execution.throughput_test`` defaults are
   ``duration_minutes=60``, ``concurrent_streams=4`` and ``warm_up_minutes=5``.
   Other execution defaults are ``timeout_minutes=120``, ``memory_limit_gb=8``
   and ``enable_profiling=False``.

.. py:function:: benchbox.utils.config_interface.set_config_provider(provider: ConfigInterface | None) -> None

   Register a process-wide provider. Higher layers supply their user
   configuration through this interface, keeping utils independent of CLI
   imports. ``None`` clears the registration.

.. py:function:: benchbox.utils.config_interface.get_config_provider() -> ConfigInterface
.. py:function:: benchbox.utils.config_interface.get_default_config_provider() -> ConfigInterface

   ``get_config_provider`` returns the registered object when present; otherwise
   it calls ``get_default_config_provider``, which creates a new built-in
   provider each time. This fallback supports library and MCP consumers without
   CLI startup. Mutations of an unregistered fallback do not persist across
   subsequent calls.

.. py:class:: benchbox.utils.config_helpers.PowerRunSettings
.. py:class:: benchbox.utils.config_helpers.ConcurrentQueriesSettings

   Mutable dataclasses requiring every field at direct construction.
   ``from_config_manager(manager)`` reads each field from its matching dotted
   execution prefix; ``apply_to_config_manager(manager)`` writes those fields
   through ``set``. ``to_dict()`` returns field names and their current values.
   These operations do not coerce or validate values.

   ``PowerRunSettings`` uses ``execution.power_run`` with fallback values
   ``iterations=4``, ``warm_up_iterations=0``,
   ``timeout_per_iteration_minutes=60``, ``fail_fast=False`` and
   ``collect_metrics=True``. ``ConcurrentQueriesSettings`` uses
   ``execution.concurrent_queries`` with ``enabled=False``, ``max_concurrent=2``,
   ``query_timeout_seconds=300``, ``stream_timeout_seconds=3600``,
   ``retry_failed_queries=True`` and ``max_retries=3``.

.. py:class:: benchbox.utils.config_helpers.ExecutionConfigHelper(config_manager: Any | None = None)

   Capture the supplied manager, or obtain the registered/default provider at
   construction. Later registrations do not replace that captured object.
   The power-run and concurrent-query getters/readers and update methods use
   the two settings classes above.

   ``enable_power_run_iterations(iterations=3, warm_up_iterations=1)`` updates
   those counts; ``enable_concurrent_queries(max_concurrent=2)`` sets enabled
   and concurrency, and ``disable_concurrent_queries()`` clears enabled. Other
   settings remain as read from the manager.

   ``optimize_for_system(cpu_cores, memory_gb)`` sets concurrency to
   ``min(8, max(2, cpu_cores // 4))``. Below 8 GB it uses power/query/stream
   timeouts of 120 minutes, 600 seconds and 7200 seconds; above 16 GB it uses
   45 minutes, 180 seconds and 1800 seconds. At 8 through 16 GB those timeouts
   remain unchanged. It does not enable concurrent queries or run benchmarks.

   ``create_performance_profile(profile_name)`` accepts ``quick``, ``standard``,
   ``thorough`` or ``stress`` and returns ``name``, ``power_run`` and
   ``concurrent_queries`` dictionaries without changing the manager. Unknown
   names raise ``ValueError``. ``apply_performance_profile`` writes both settings
   groups from the selected profile.

   ``save_config()`` and ``validate_execution_config()`` delegate to the
   manager's ``save_config`` and ``validate_config`` methods. These methods are
   absent from ``SimpleConfigProvider`` and ``ConfigInterface``; callers need a
   provider implementing them. Exceptions propagate.

   ``get_execution_summary()`` returns ``power_run``, ``concurrent_queries`` and
   ``general`` groups. Power-run enabled means more than one iteration or any
   warm-up; its duration estimate is total iterations times per-iteration
   timeout. Concurrent duration converts stream timeout to minutes. General
   fallbacks are ``max_workers=4``, ``memory_limit_gb=0`` and
   ``parallel_queries=False``; provider-supplied values take precedence.

.. py:function:: benchbox.utils.config_helpers.create_sample_execution_config(output_path: str | Path) -> None

   Write a sample YAML configuration to the path in UTF-8, overwriting an
   existing file. Parent directories are not created. The sample contains
   execution settings and profile descriptions; it does not register a provider
   or apply settings. YAML import, conversion and filesystem errors propagate.
