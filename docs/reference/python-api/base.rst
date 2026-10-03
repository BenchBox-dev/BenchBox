Base Benchmark API
==================

.. tags:: reference, python-api, contributor

The ``benchbox.base`` module provides the foundational abstract class that all benchmarks inherit from.

Overview
--------

Every benchmark in BenchBox extends :class:`BaseBenchmark`, which provides a standardized interface for:

- Data generation and schema setup
- Query execution and timing
- Platform adapter integration
- SQL dialect translation
- Results collection and formatting

This abstraction ensures consistent behavior across all benchmark implementations (TPC-H, TPC-DS, ClickBench, etc.).

Runtime Contract Notes
----------------------

The lifecycle runner expects loader-resolved benchmarks to provide a shared runtime contract:

- ``generate_data``
- ``get_queries`` / ``get_query``
- ``create_enhanced_benchmark_result``
- ``create_minimal_benchmark_result``
- ``validate_preflight`` / ``validate_manifest`` / ``validate_loaded_data``

Compatibility boundaries:

- Public benchmark implementations should inherit ``benchbox.base.BaseBenchmark``.
- ``benchbox.core.base_benchmark.BaseBenchmark`` remains temporarily for internal compatibility and delegates result
  construction through the same shared factory path.
- ``create_enhanced_benchmark_result()`` preserves compatibility with legacy kwargs such as
  ``table_statistics`` and ``data_loading_time`` while exporting canonical per-table load timing as
  ``table_statistics.<table>.load_time_ms`` when available.

Quick Example
-------------

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms import DuckDBAdapter

    # Create benchmark instance
    benchmark = TPCH(scale_factor=0.01)

    # Generate data files
    data_files = benchmark.generate_data()

    # Run with platform adapter
    adapter = DuckDBAdapter()
    results = benchmark.run_with_platform(adapter)

    print(f"Completed {results.successful_queries}/{results.total_queries} queries")
    print(f"Average query time: {results.average_query_time:.3f}s")

BaseBenchmark contract
----------------------

.. py:module:: benchbox.base

.. py:class:: BaseBenchmark(scale_factor: float = 1.0, output_dir: Union[str, pathlib.Path, NoneType] = None, **kwargs: Any)

   Abstract base class for BenchBox benchmark implementations. ``scale_factor`` must be positive; values of one or
   greater must be whole numbers. If ``output_dir`` is omitted, BenchBox resolves a benchmark-specific data-generation
   directory. ``verbose`` and ``quiet`` in ``kwargs`` configure verbosity; other keyword arguments become instance
   attributes for benchmark-specific configuration.

   .. py:attribute:: benchmark_name

      Human-readable benchmark name used in result metadata. Concrete benchmarks provide it through their name or
      implementation object.

   .. py:attribute:: scale_factor

      Instance data scale factor selected at construction. It is not a class attribute or callable API.

   .. py:attribute:: output_dir

      Resolved local or cloud-backed output-directory handler. Assigning it forwards the value to a wrapped
      implementation when present.

   .. py:attribute:: api_surface

      Class metadata identifying this benchmark API as ``"beta-public"``.

   .. py:attribute:: run_with_platform_api_surface

      Class metadata identifying :meth:`run_with_platform` as ``"beta-public"``.

   .. py:attribute:: DATA_SOURCE_BENCHMARK

      Optional lower-case identifier of the benchmark whose generated data this class reuses. Set it when the runner
      must resolve shared data before construction; leave it ``None`` when the benchmark generates its own data.

   .. py:attribute:: SKIP_DATA_LOADING

      Class flag for benchmarks whose queries require schema objects but no generated data files. Its default is
      ``False``.

   .. py:attribute:: tables

      Mapping from table names to generated-data paths. Wrapper instances delegate the mapping to their implementation.

   .. py:attribute:: csv_delimiter

      Optional CSV delimiter supplied by the benchmark implementation for platform data loading.

   .. py:attribute:: csv_null_marker

      Optional CSV null marker supplied by the benchmark implementation for platform data loading.

   .. py:method:: cleanup() -> None

      Compatibility lifecycle hook. The public base performs no cleanup itself, while older implementations may call it
      after releasing their resources.

   .. py:method:: get_csv_loading_config(table_name: str) -> Optional[list[str]]

      Return platform-specific CSV loading options for ``table_name`` when a wrapped implementation supplies them;
      otherwise return ``None``.

   .. py:method:: generate_data() -> list[Union[str, Path]]

      Required override. Generate the benchmark's data artifacts and return their paths. Concrete implementations
      choose the file layout and formats.

   .. py:method:: get_queries() -> dict[str, str]

      Required override. Return the benchmark query catalog as query-ID-to-SQL mapping.

   .. py:method:: get_query(query_id: Union[int, str], *, params: Optional[dict[str, Any]] = None) -> str

      Required override. Return one query with supported parameter values resolved. An invalid query ID raises
      ``ValueError``; individual benchmark pages specify whether parameters are supported.

   .. py:method:: setup_database(connection: DatabaseConnection) -> None

      Generate data when it has not already been generated, then call the benchmark's loading hook for ``connection``.
      Exceptions from generation or loading propagate to the caller.

   .. py:method:: run_query(query_id: Union[int, str], connection: DatabaseConnection, params: Optional[dict[str, Any]] = None, fetch_results: bool = False) -> dict[str, Any]

      Execute one query and return its ID, elapsed seconds, SQL text, result rows when requested, and row count. Query
      lookup and database execution errors propagate.

   .. py:method:: run_benchmark(connection: DatabaseConnection, query_ids: Optional[list[Union[int, str]]] = None, fetch_results: bool = False, setup_database: bool = True) -> dict[str, Any]

      Run the selected queries, or every query when ``query_ids`` is omitted. With ``setup_database=True``, it sets up
      the database first. The returned mapping contains timing summaries, setup time, counts of successful and failed
      queries, and one result entry per attempted query; individual query failures are captured in those entries.

   .. py:method:: run_with_platform(platform_adapter: SQLBenchmarkExecutor, **run_config: Any) -> BenchmarkResults

      Standard platform-execution entry point. It sets ``benchmark_type`` to the benchmark default when absent and
      delegates connection management, loading, and execution to the supplied SQL platform adapter. ``run_config`` can
      include a query subset, categories, connection configuration, and a benchmark-type override.

      .. code-block:: python

         from benchbox.tpcds import TPCDS
         from benchbox.platforms.duckdb import DuckDBAdapter

         benchmark = TPCDS(scale_factor=1)
         results = benchmark.run_with_platform(
             DuckDBAdapter(), query_subset=["q1", "q2", "q3"]
         )

   .. py:method:: translate_query(query_id: Union[int, str], dialect: str) -> str

      Return one query translated to ``dialect``. Translation support and SQL compatibility limits are benchmark- and
      dialect-specific.

      Dialect translation does not imply that an execution adapter exists for the target database. See
      :doc:`/platforms/index` for supported platform adapters.

   .. py:method:: create_enhanced_benchmark_result(platform: str, query_results: list[dict[str, Any]], execution_metadata: Optional[dict[str, Any]] = None, phases: Optional[dict[str, dict[str, Any]]] = None, resource_utilization: Optional[dict[str, Any]] = None, performance_characteristics: Optional[dict[str, Any]] = None, duration_seconds: Optional[float] = None, **kwargs: Any) -> BenchmarkResults

      Build the canonical ``BenchmarkResults`` payload. Wrapper benchmarks delegate to their implementation when it
      supplies this method; otherwise the shared result factory combines the supplied execution and resource metadata.

   .. py:method:: create_minimal_benchmark_result(*, validation_status: str, validation_details: Optional[dict[str, Any]] = None, duration_seconds: float = 0.0, platform: str = "unknown", execution_metadata: Optional[dict[str, Any]] = None, system_profile: Optional[dict[str, Any]] = None, phases: Optional[dict[str, dict[str, Any]]] = None, **overrides: Any) -> BenchmarkResults

      Build a minimal result for validation failures or interrupted execution. It contains no query results and records
      ``validation_status`` plus optional validation details and caller overrides.

   .. py:method:: validate_preflight(*, output_dir: Optional[Union[str, Path]] = None, benchmark_name: Optional[str] = None) -> ValidationResult

      Resolve the data directory and run preflight validation for the effective benchmark identifier and scale factor.
      A missing output directory raises ``RuntimeError``.

   .. py:method:: validate_manifest(*, manifest_path: Optional[Union[str, Path]] = None, benchmark_name: Optional[str] = None) -> ValidationResult

      Validate the supplied manifest, or ``_datagen_manifest.json`` under the resolved output directory. If no manifest
      path can be derived, it returns an invalid validation result with a manifest-path error.

   .. py:method:: validate_loaded_data(connection: Any, *, benchmark_name: Optional[str] = None) -> ValidationResult

      Validate the post-load database state for ``connection`` using the effective benchmark identifier and scale factor.

   .. py:method:: format_results(benchmark_result: dict[str, Any]) -> str

      Format a result mapping from :meth:`run_benchmark` as a human-readable summary of query counts and timings.

   .. py:method:: get_data_source_benchmark() -> Optional[str]

      Return the canonical source benchmark for shared generated data, or ``None`` when the benchmark generates its own
      data. Implementations can declare ``DATA_SOURCE_BENCHMARK`` or override this method.

Best Practices
--------------

1. **Always use platform adapters** - Call :meth:`run_with_platform` instead of direct :meth:`run_benchmark` for production use. Platform adapters provide optimized data loading and query execution.

2. **Handle scale factors carefully** - Scale factors ≥1 must be integers. Use 0.1, 0.01, etc. for small-scale testing.

3. **Check data generation** - Call :meth:`generate_data` explicitly if you need to inspect or manipulate data files before loading.

4. **Use query subsets for debugging** - Pass ``query_subset=["q1"]`` to test single queries during development.

5. **Use SQL translation** - Call :meth:`translate_query` to adapt queries to platform-specific dialects when needed.

See Also
--------

- :doc:`/usage/getting-started` - Getting started guide with complete examples
- :doc:`/platforms/platform-selection-guide` - Platform adapter documentation
- :doc:`/benchmarks/index` - Available benchmark implementations
- :doc:`/reference/api-reference` - High-level API overview
