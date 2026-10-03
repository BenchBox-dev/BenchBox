Results API
===========

.. tags:: reference, python-api, validation

Benchmark results contain query records, timing summaries, validation outcomes,
and the context needed to compare runs. The in-memory dataclasses and exported
JSON use different layouts. Use ResultExporter to write and load the supported
JSON format; loading returns a dictionary rather than a BenchmarkResults object.

Quick Start
-----------

Run a local benchmark and export its result:

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter
    from benchbox.core.results.exporter import ResultExporter
    from benchbox.core.results.query_normalizer import normalize_query_results

    benchmark = TPCH(scale_factor=0.1)
    results = benchmark.run_with_platform(DuckDBAdapter())
    print(results.benchmark_name, results.platform)
    print(f"Total query time: {results.total_execution_time:.2f}s")
    print(f"Successful queries: {results.successful_queries}/{results.total_queries}")

    for query in normalize_query_results(results.query_results):
        print(query.query_id, query.execution_time_ms, query.status)

    exporter = ResultExporter(output_dir="benchmark_runs/results")
    exported_paths = exporter.export_result(results, formats=["json"])
    print(exported_paths["json"])

Core Classes
------------

BenchmarkResults
~~~~~~~~~~~~~~~~

.. py:class:: benchbox.core.results.models.BenchmarkResults

   Dataclass for an in-memory benchmark result. The constructor requires
   benchmark_name, platform, scale_factor, execution_id, timestamp,
   duration_seconds, total_queries, successful_queries, and failed_queries,
   in that order. The remaining fields are optional constructor arguments
   with the defaults listed below. Mutable defaults are allocated per instance.

   Query records remain dictionaries, rather than instances of a QueryResult
   class. Normalize their timing aliases before analysis. Top-level durations
   ending in ``_time`` use seconds unless the field explicitly names another
   unit; normalized query executions and schema-v2 query ``ms`` values use
   milliseconds.

.. py:property:: benchbox.core.results.models.BenchmarkResults.benchmark_id
   :type: str

   Return the explicit internal override when set, otherwise a nonempty string
   benchmark_id from execution_metadata. Without either override, lowercase
   benchmark_name, replace spaces and hyphens with underscores, and collapse
   repeated underscores.

Constructor fields
^^^^^^^^^^^^^^^^^^

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.benchmark_name
   :type: str

   Human-readable benchmark name. Required constructor argument.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.platform
   :type: str

   Platform name recorded for this run. Required constructor argument.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.scale_factor
   :type: float

   Dataset scale factor. Required constructor argument.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.execution_id
   :type: str

   Identifier for this execution. Required constructor argument.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.timestamp
   :type: datetime

   Run timestamp as a datetime object. Required constructor argument.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.duration_seconds
   :type: float

   Total run duration in seconds. Required constructor argument.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.total_queries
   :type: int

   Number of queries attempted. Required constructor argument.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.successful_queries
   :type: int

   Number of successful queries. Required constructor argument.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.failed_queries
   :type: int

   Number of failed queries. Required constructor argument.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.query_results
   :type: list[dict[str, Any]]

   Runner query records stored as dictionaries. Use query normalization before assuming timing aliases or units. Default: a new empty list for each instance.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.total_execution_time
   :type: float

   Total query execution time in seconds. Default: ``0.0``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.average_query_time
   :type: float

   Average query execution time in seconds. Default: ``0.0``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.data_loading_time
   :type: float

   Data loading duration in seconds. Default: ``0.0``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.schema_creation_time
   :type: float

   Schema creation duration in seconds. Default: ``0.0``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.total_rows_loaded
   :type: int

   Number of rows loaded. Default: ``0``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.data_size_mb
   :type: float

   Loaded data size in megabytes. Default: ``0.0``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.table_statistics
   :type: dict[str, int]

   Per-table statistics keyed by table name. Default: a new empty dictionary for each instance.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.data_generation_version
   :type: int | None

   Version of the data-generation algorithm; absent on older results. Compare compatible versions. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.data_generation_hash
   :type: str | None

   Fingerprint of the data-generation base constants; distinguishes input changes without a version bump. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.flightdata_source_provenance
   :type: dict[str, Any] | None

   Source provenance captured for FlightData datasets. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.per_query_timings
   :type: list[dict[str, Any]] | None

   Optional detailed timing dictionaries for query analysis and export. Default: a new empty list for each instance.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.execution_phases
   :type: ExecutionPhases | None

   Optional structured execution phases. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.query_definitions
   :type: dict[str, dict[str, QueryDefinition]] | None

   Query definitions grouped by string keys, with SQL and optional parameters. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.test_execution_type
   :type: str

   Execution mode label, such as standard, power, or throughput. Default: ``'standard'``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.power_at_size
   :type: float | None

   TPC power metric at the recorded scale. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.throughput_at_size
   :type: float | None

   TPC throughput metric at the recorded scale. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.qph_at_size
   :type: float | None

   Composite TPC queries-per-hour metric at scale: QphH for TPC-H or QphDS for TPC-DS. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.geometric_mean_execution_time
   :type: float | None

   Geometric mean query execution time in seconds. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.validation_status
   :type: str

   Result validation status. Default: ``'PASSED'``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.validation_details
   :type: dict[str, Any] | None

   Optional validation evidence and outcomes. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.execution_environment
   :type: NormalizedExecutionEnvironment | dict[str, Any] | None

   Normalized execution environment, or its dictionary representation. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.platform_deployment
   :type: PlatformDeploymentMetadata | dict[str, Any] | None

   Platform deployment metadata, or its dictionary representation. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.platform_cloud
   :type: PlatformCloudMetadata | dict[str, Any] | None

   Cloud platform metadata, or its dictionary representation. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.platform_compute
   :type: PlatformComputeMetadata | dict[str, Any] | None

   Compute metadata, or its dictionary representation. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.platform_storage
   :type: PlatformStorageMetadata | dict[str, Any] | None

   Storage metadata, or its dictionary representation. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.platform_raw_config
   :type: dict[str, Any] | None

   Captured platform configuration before export sanitization. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.platform_raw_metadata
   :type: dict[str, Any] | None

   Captured platform metadata before export sanitization. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.platform_info
   :type: dict[str, Any] | None

   Platform information captured for the run. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.platform_metadata
   :type: dict[str, Any] | None

   Additional platform metadata. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.tunings_applied
   :type: dict[str, Any] | None

   Recorded tuning configuration applied for the run. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.tuning_config_hash
   :type: str | None

   SHA-256 of the requested tuning configuration in canonical JSON. Identifies the requested template, not physical application. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.applied_tuning_ledger
   :type: dict[str, Any] | None

   Receipt produced by the execution path for ordered statements and dropped tuning requests; absent when no tuning ran. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.applied_ledger_hash
   :type: str | None

   SHA-256 of the ordered executed-statement list. Identifies physical application independently of the requested configuration hash. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.tuning_source_file
   :type: str | None

   Repository-relative tuning template path, or a basename and content hash for an external template; never a raw local filesystem path. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.tuning_source
   :type: str | None

   Tuning source label, such as auto_discovered, explicit_file, wizard, fallback, smart_defaults, or baseline. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.tuning_validation_status
   :type: str

   Validation status of the tuning configuration. Default: ``'not_validated'``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.tuning_metadata_saved
   :type: bool

   Whether tuning metadata was saved. Default: ``False``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.system_profile
   :type: dict[str, Any] | None

   Captured hardware and software context. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.database_name
   :type: str | None

   Database used by the run. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.anonymous_machine_id
   :type: str | None

   Machine pseudonym associated with the run. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.execution_metadata
   :type: dict[str, Any] | None

   Additional execution metadata; may supply an explicit benchmark_id. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.performance_characteristics
   :type: dict[str, Any]

   Additional performance characteristics. Default: a new empty dictionary for each instance.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.performance_summary
   :type: dict[str, Any]

   Additional performance summary values. Default: a new empty dictionary for each instance.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.cost_summary
   :type: dict[str, Any] | None

   Optional cost estimate, including total cost and phase or platform details. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.driver_package
   :type: str | None

   Python driver package name. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.driver_version_requested
   :type: str | None

   Requested driver version. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.driver_version_resolved
   :type: str | None

   Driver version selected by dependency resolution. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.driver_version_actual
   :type: str | None

   Observed installed driver version. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.driver_runtime_strategy
   :type: str | None

   Strategy used to resolve or isolate the driver runtime. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.driver_runtime_path
   :type: str | None

   Resolved driver runtime path. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.driver_runtime_python_executable
   :type: str | None

   Python executable used by the driver runtime. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.driver_auto_install
   :type: bool

   Whether automatic driver installation was enabled. Default: ``False``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.engine_version
   :type: str | None

   Observed engine or remote service version, independent of the Python driver version. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.engine_version_source
   :type: str | None

   Provenance of the engine version, such as sql_query, api, connection_metadata, or driver_coupled. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.output_filename
   :type: str | None

   Optional output filename override used by the exporter to choose its filename stem. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.resource_utilization
   :type: dict[str, Any] | None

   Captured resource utilization. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.summary_metrics
   :type: dict[str, Any]

   Additional summary metrics. Default: a new empty dictionary for each instance.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.query_subset
   :type: list[str] | None

   Optional selected query identifiers. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.concurrency_level
   :type: int | None

   Recorded concurrency level. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.benchmark_version
   :type: str | None

   Version of the benchmark implementation. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.query_plans_captured
   :type: int

   Number of captured query plans. Default: ``0``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.plan_capture_failures
   :type: int

   Number of query plan capture failures. Default: ``0``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.plan_capture_errors
   :type: list[dict[str, str]]

   Error records from query plan capture. Default: a new empty list for each instance.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.plan_comparison_summary
   :type: dict[str, Any] | None

   Cross-run or cross-platform plan comparison summary. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.total_plan_capture_time_ms
   :type: float

   Total plan capture duration in milliseconds. Default: ``0.0``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.avg_plan_capture_overhead_pct
   :type: float

   Average plan capture overhead as a percentage of query time. Default: ``0.0``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.max_plan_capture_time_ms
   :type: float

   Longest individual plan capture duration in milliseconds. Default: ``0.0``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.execution_context
   :type: dict[str, Any] | None

   CLI, MCP, or Python API parameters captured for reproducibility. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.native_comparison
   :type: NativeComparison | None

   Optional pg_duckdb versus native DuckDB timing comparison. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.compliance_class
   :type: str | None

   Methodology label, such as official, unofficial_nonstandard, or unofficial_subscale; not a certification by itself. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.dataset_version
   :type: str | None

   Version of the manifest-backed dataset. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.manifest_hash
   :type: str | None

   Dataset manifest identity hash. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.data_archive_hash
   :type: str | None

   Dataset archive identity hash. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.funding
   :type: str | None

   How the benchmark run was funded. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.BenchmarkResults.result_source
   :type: str | None

   Advisory producer label, such as internal, community, or vendor. Authoritative vendor trust is assigned downstream by maintainers. Default: ``None``.

ExecutionPhases
~~~~~~~~~~~~~~~

.. py:class:: benchbox.core.results.models.ExecutionPhases(setup: SetupPhase, power_test: PowerTestPhase | None = None, throughput_test: ThroughputTestPhase | None = None, maintenance_test: MaintenanceTestPhase | None = None, migration: MigrationPhase | None = None)

   Group detailed lifecycle phases for a run. ``setup`` is required; all other
   phases default to None. Setup's individual stages can themselves be absent.
   Phase fields named ``*_ms`` use milliseconds; ``PowerTestPhase.geometric_mean_time`` uses seconds.

.. py:attribute:: benchbox.core.results.models.ExecutionPhases.setup
   :type: SetupPhase

   Setup lifecycle stages. Required constructor argument.

.. py:attribute:: benchbox.core.results.models.ExecutionPhases.power_test
   :type: PowerTestPhase | None

   Optional power-test execution phase. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.ExecutionPhases.throughput_test
   :type: ThroughputTestPhase | None

   Optional throughput-test execution phase. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.ExecutionPhases.maintenance_test
   :type: MaintenanceTestPhase | None

   Optional maintenance-test execution phase. Default: ``None``.

.. py:attribute:: benchbox.core.results.models.ExecutionPhases.migration
   :type: MigrationPhase | None

   Optional pg_mooncake heap-to-columnstore migration phase. Default: ``None``.

Nested execution phase records
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All records below are mutable dataclasses except ``ThroughputOutstandingWork``,
which describes a dictionary. Required fields have no constructor default;
a nullable required field must still be supplied. List factories create
independent containers. Producers supply timestamp strings and status values;
these dataclasses do not enforce a timestamp format or status enum.

.. py:class:: benchbox.core.results.models.TableGenerationStats

   One table's generated row count, data size in bytes, output file path,
   and generation time in milliseconds. Optional failure fields retain
   attempted row and byte counts and producer-supplied error details.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``generation_time_ms``
        - ``int``
        - ``Required``
      * - ``status``
        - ``str``
        - ``Required``
      * - ``rows_generated``
        - ``int``
        - ``Required``
      * - ``data_size_bytes``
        - ``int``
        - ``Required``
      * - ``file_path``
        - ``str``
        - ``Required``
      * - ``error_type``
        - ``str | None``
        - ``None``
      * - ``error_message``
        - ``str | None``
        - ``None``
      * - ``rows_attempted``
        - ``int | None``
        - ``None``
      * - ``bytes_attempted``
        - ``int | None``
        - ``None``
      * - ``error_timestamp``
        - ``str | None``
        - ``None``

.. py:class:: benchbox.core.results.models.DataGenerationPhase

   Generation duration in milliseconds, table and row counts, and total
   data size in bytes. ``per_table_stats`` maps table names to generation records.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``duration_ms``
        - ``int``
        - ``Required``
      * - ``status``
        - ``str``
        - ``Required``
      * - ``tables_generated``
        - ``int``
        - ``Required``
      * - ``total_rows_generated``
        - ``int``
        - ``Required``
      * - ``total_data_size_bytes``
        - ``int``
        - ``Required``
      * - ``per_table_stats``
        - ``dict[str, TableGenerationStats]``
        - ``Required``

.. py:class:: benchbox.core.results.models.TableCreationStats

   One table's creation duration in milliseconds, applied constraint count,
   created index count, and optional producer-supplied failure details.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``creation_time_ms``
        - ``int``
        - ``Required``
      * - ``status``
        - ``str``
        - ``Required``
      * - ``constraints_applied``
        - ``int``
        - ``Required``
      * - ``indexes_created``
        - ``int``
        - ``Required``
      * - ``error_type``
        - ``str | None``
        - ``None``
      * - ``error_message``
        - ``str | None``
        - ``None``
      * - ``error_timestamp``
        - ``str | None``
        - ``None``

.. py:class:: benchbox.core.results.models.SchemaCreationPhase

   Schema-creation duration in milliseconds and table, constraint, and
   index counts. ``per_table_creation`` maps table names to creation records.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``duration_ms``
        - ``int``
        - ``Required``
      * - ``status``
        - ``str``
        - ``Required``
      * - ``tables_created``
        - ``int``
        - ``Required``
      * - ``constraints_applied``
        - ``int``
        - ``Required``
      * - ``indexes_created``
        - ``int``
        - ``Required``
      * - ``per_table_creation``
        - ``dict[str, TableCreationStats]``
        - ``Required``

.. py:class:: benchbox.core.results.models.TableLoadingStats

   One table's reported row count and loading duration in milliseconds.
   Optional failure fields retain processed and successful row counts and
   producer-supplied error details.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``rows``
        - ``int``
        - ``Required``
      * - ``load_time_ms``
        - ``int``
        - ``Required``
      * - ``status``
        - ``str``
        - ``Required``
      * - ``error_type``
        - ``str | None``
        - ``None``
      * - ``error_message``
        - ``str | None``
        - ``None``
      * - ``rows_processed``
        - ``int | None``
        - ``None``
      * - ``rows_successful``
        - ``int | None``
        - ``None``
      * - ``error_timestamp``
        - ``str | None``
        - ``None``

.. py:class:: benchbox.core.results.models.DataLoadingPhase

   Loading duration in milliseconds and loaded row and table counts.
   ``per_table_stats`` maps table names to loading records.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``duration_ms``
        - ``int``
        - ``Required``
      * - ``status``
        - ``str``
        - ``Required``
      * - ``total_rows_loaded``
        - ``int``
        - ``Required``
      * - ``tables_loaded``
        - ``int``
        - ``Required``
      * - ``per_table_stats``
        - ``dict[str, TableLoadingStats]``
        - ``Required``

.. py:class:: benchbox.core.results.models.ValidationPhase

   Setup validation duration in milliseconds, outcome text for row counts,
   schema and integrity checks, and optional additional validation details.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``duration_ms``
        - ``int``
        - ``Required``
      * - ``row_count_validation``
        - ``str``
        - ``Required``
      * - ``schema_validation``
        - ``str``
        - ``Required``
      * - ``data_integrity_checks``
        - ``str``
        - ``Required``
      * - ``validation_details``
        - ``dict[str, Any] | None``
        - ``None``

.. py:class:: benchbox.core.results.models.StatisticsGatheringPhase

   Optimizer-statistics duration in milliseconds. ``stats_mode`` is
   ``explicit`` for a measured ANALYZE build; ``auto-on-load`` and
   ``unsupported`` record a duration of 0.

   ``stats_lifecycle`` is ``reset`` when statistics were invalidated before
   the build, ``unsupported`` when a requested reset was unavailable, or
   ``persist`` for an explicit warm-statistics choice. None means that the
   control was unused. ``per_table_ms`` provides an opt-in per-table ANALYZE
   breakdown in milliseconds. Whole-database hooks, auto-on-load, and
   unsupported modes leave it None. Serialization omits it when None or empty.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``duration_ms``
        - ``int``
        - ``Required``
      * - ``status``
        - ``str``
        - ``Required``
      * - ``stats_mode``
        - ``str``
        - ``Required``
      * - ``tables_analyzed``
        - ``int``
        - ``0``
      * - ``error_message``
        - ``str | None``
        - ``None``
      * - ``stats_lifecycle``
        - ``str | None``
        - ``None``
      * - ``per_table_ms``
        - ``dict[str, int] | None``
        - ``None``

.. py:class:: benchbox.core.results.models.SetupPhase

   Optional stages grouped under ``ExecutionPhases.setup``. A missing stage
   is represented by None.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``data_generation``
        - ``DataGenerationPhase | None``
        - ``None``
      * - ``schema_creation``
        - ``SchemaCreationPhase | None``
        - ``None``
      * - ``data_loading``
        - ``DataLoadingPhase | None``
        - ``None``
      * - ``validation``
        - ``ValidationPhase | None``
        - ``None``
      * - ``statistics_gathering``
        - ``StatisticsGatheringPhase | None``
        - ``None``

.. py:class:: benchbox.core.results.models.PowerTestPhase

   Power-test timestamps, duration in milliseconds, and query records.
   ``geometric_mean_time`` uses seconds. ``power_at_size`` is the power
   metric supplied by the benchmark result producer.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``start_time``
        - ``str``
        - ``Required``
      * - ``end_time``
        - ``str``
        - ``Required``
      * - ``duration_ms``
        - ``int``
        - ``Required``
      * - ``query_executions``
        - ``list[QueryExecution]``
        - ``Required``
      * - ``geometric_mean_time``
        - ``float``
        - ``Required``
      * - ``power_at_size``
        - ``float``
        - ``Required``

.. py:class:: benchbox.core.results.models.ThroughputStream

   One throughput stream's identifier, timestamps, duration in milliseconds,
   query records, and success or failure outcome.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``stream_id``
        - ``int``
        - ``Required``
      * - ``start_time``
        - ``str``
        - ``Required``
      * - ``end_time``
        - ``str``
        - ``Required``
      * - ``duration_ms``
        - ``int``
        - ``Required``
      * - ``query_executions``
        - ``list[QueryExecution]``
        - ``Required``
      * - ``success``
        - ``bool``
        - ``True``
      * - ``error_message``
        - ``str | None``
        - ``None``

.. py:class:: benchbox.core.results.models.ThroughputOutstandingWork

   Dictionary shape for workers remaining after phase completion. Both
   keys are required: ``stream_ids`` identifies the workers, and
   ``cleanup_state`` records their producer-reported cleanup state.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``stream_ids``
        - ``list[int]``
        - ``Required key``
      * - ``cleanup_state``
        - ``str``
        - ``Required key``

.. py:class:: benchbox.core.results.models.ThroughputTestPhase

   Throughput timestamps, duration in milliseconds, configured stream count,
   stream records and executed-query count. ``throughput_at_size`` is a
   required argument that may be None when no metric is available.
   ``errors`` contains phase error messages; ``outstanding_work`` retains
   optional evidence about workers remaining after phase completion.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``start_time``
        - ``str``
        - ``Required``
      * - ``end_time``
        - ``str``
        - ``Required``
      * - ``duration_ms``
        - ``int``
        - ``Required``
      * - ``num_streams``
        - ``int``
        - ``Required``
      * - ``streams``
        - ``list[ThroughputStream]``
        - ``Required``
      * - ``total_queries_executed``
        - ``int``
        - ``Required``
      * - ``throughput_at_size``
        - ``float | None``
        - ``Required``
      * - ``success``
        - ``bool``
        - ``True``
      * - ``errors``
        - ``list[str]``
        - ``Fresh list``
      * - ``outstanding_work``
        - ``ThroughputOutstandingWork | None``
        - ``None``

.. py:class:: benchbox.core.results.models.MaintenanceOperation

   One maintenance operation's identifier, type, affected table, duration
   in milliseconds, affected-row count and outcome.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``operation``
        - ``str``
        - ``Required``
      * - ``operation_type``
        - ``str``
        - ``Required``
      * - ``table``
        - ``str``
        - ``Required``
      * - ``execution_time_ms``
        - ``int``
        - ``Required``
      * - ``rows_affected``
        - ``int``
        - ``Required``
      * - ``status``
        - ``str``
        - ``Required``
      * - ``error_message``
        - ``str | None``
        - ``None``

.. py:class:: benchbox.core.results.models.MaintenanceTestPhase

   Maintenance timestamps, duration in milliseconds, operation records
   and query execution records.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``start_time``
        - ``str``
        - ``Required``
      * - ``end_time``
        - ``str``
        - ``Required``
      * - ``duration_ms``
        - ``int``
        - ``Required``
      * - ``maintenance_operations``
        - ``list[MaintenanceOperation]``
        - ``Required``
      * - ``query_executions``
        - ``list[QueryExecution]``
        - ``Required``

.. py:class:: benchbox.core.results.models.MigrationTableStats

   One table's migration duration in milliseconds and storage sizes before
   and after migration, with their change, in bytes.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``duration_ms``
        - ``int``
        - ``Required``
      * - ``status``
        - ``str``
        - ``Required``
      * - ``storage_before_bytes``
        - ``int``
        - ``Required``
      * - ``storage_after_bytes``
        - ``int``
        - ``Required``
      * - ``storage_delta_bytes``
        - ``int``
        - ``Required``
      * - ``error_message``
        - ``str | None``
        - ``None``

.. py:class:: benchbox.core.results.models.MigrationPhase

   pg_mooncake heap-to-columnstore migration duration in milliseconds,
   migrated and failed table counts, and aggregate storage sizes and
   change in bytes. ``per_table_stats`` maps table names to migration records.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``duration_ms``
        - ``int``
        - ``Required``
      * - ``status``
        - ``str``
        - ``Required``
      * - ``tables_migrated``
        - ``int``
        - ``Required``
      * - ``tables_failed``
        - ``int``
        - ``Required``
      * - ``storage_before_bytes``
        - ``int``
        - ``Required``
      * - ``storage_after_bytes``
        - ``int``
        - ``Required``
      * - ``storage_delta_bytes``
        - ``int``
        - ``Required``
      * - ``per_table_stats``
        - ``dict[str, MigrationTableStats]``
        - ``Required``


Working with Results
--------------------

Saving and Loading JSON
~~~~~~~~~~~~~~~~~~~~~~~

ResultExporter supports JSON, CSV and HTML. JSON uses the maintained result
schema, validates the payload before writing, converts datetime values, and can
write companion tuning or plan files. Anonymization is enabled by default.
Export failures raise ResultExportError. See :doc:`result-analysis` for the
exporter and anonymization configuration.

.. code-block:: python

    from pathlib import Path
    from benchbox.core.results.exporter import ResultExporter

    exporter = ResultExporter(output_dir="benchmark_runs/results")
    paths = exporter.export_result(results, formats=["json", "csv", "html"])
    loaded = exporter.load_result_from_file(paths["json"])
    if loaded is None:
        raise ValueError("Could not load the exported result")
    payload = loaded["data"]
    print(loaded["result_schema_version"], loaded["filepath"])
    print(payload["summary"])
    for query in payload["queries"]:
        print(query["id"], query.get("ms"), query["status"])

``load_result_from_file(filepath: Path)`` returns data, version,
result_schema_version and filepath keys, or None when loading fails. It parses
JSON and reports a version; it does not reconstruct the dataclass or validate
that the file is a current result schema. Exported ``queries`` use compact keys
such as id, ms, iter, stream and run_type. Do not treat them as the in-memory
query dictionaries.

To inspect the JSON text directly:

.. code-block:: python

    import json

    with paths["json"].open(encoding="utf-8") as handle:
        payload = json.load(handle)
    print(json.dumps(payload, indent=2))

Analyzing Query Performance
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Normalize in-memory runner records before sorting or calculating statistics.
Keep successful measured executions separate from failures and warmups; preserve
stream and iteration identifiers when analyzing repeated runs.

.. code-block:: python

    import math
    import statistics
    from benchbox.core.results.query_normalizer import normalize_query_results

    queries = normalize_query_results(results.query_results)
    successful = [
        query for query in queries
        if query.status == "SUCCESS" and query.run_type != "warmup"
        and query.execution_time_ms is not None
    ]
    for query in sorted(successful, key=lambda query: query.execution_time_ms, reverse=True)[:5]:
        print(query.query_id, query.execution_time_ms)

    times_ms = [query.execution_time_ms for query in successful]
    if times_ms:
        print("Median milliseconds:", statistics.median(times_ms))
        print("Mean milliseconds:", statistics.mean(times_ms))
    if len(times_ms) > 1:
        print("Standard deviation:", statistics.stdev(times_ms))
    if times_ms and all(value > 0 for value in times_ms):
        geometric_mean_ms = math.exp(statistics.mean(math.log(value) for value in times_ms))
        print("Geometric mean milliseconds:", geometric_mean_ms)

This descriptive geometric mean is not an official TPC metric: official metrics
also depend on the benchmark's query set, scale, streams and measurement rules.
Use the recorded TPC metrics and validation evidence when evaluating compliance.

Export to DataFrame
~~~~~~~~~~~~~~~~~~~

For pandas analysis, build rows from the normalized records:

.. code-block:: python

    import pandas as pd

    frame = pd.DataFrame([
        {
            "query_id": query.query_id,
            "execution_time_ms": query.execution_time_ms,
            "status": query.status,
            "rows_returned": query.rows_returned,
            "stream_id": query.stream_id,
            "iteration": query.iteration,
        }
        for query in queries
    ])
    if not frame.empty:
        print(frame.groupby("status").size())
        print(frame["execution_time_ms"].describe())

Comparing Results and Detecting Regressions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use the exporter comparison API for saved results. It handles schema versions
and reports data-generation compatibility alongside performance changes.

.. code-block:: python

    from pathlib import Path

    comparison = exporter.compare_results(Path("baseline.json"), Path("current.json"))
    if "error" in comparison:
        raise ValueError(comparison["error"])
    print(comparison["generation_compatibility"])
    print(comparison["performance_changes"])
    report_path = exporter.export_comparison_report(comparison)
    print(report_path)

Compare compatible data-generation versions and hashes, scale factors, query
sets, platform configuration and hardware. Keep multiple measurements to assess
variance. A reported timing change is not enough to establish a regression when
those conditions differ. See :doc:`performance-monitoring` for historical
metrics and configurable regression thresholds.

Validation Results
------------------

Check validation before trusting timing results. validation_details can be None,
and its content depends on the executed validation checks.

.. code-block:: python

    print(results.validation_status)
    details = results.validation_details or {}
    for name, outcome in details.items():
        print(name, outcome)

For an independently known expected row count, compare normalized query records:

.. code-block:: python

    expected_counts = {"1": 4, "6": 1}
    mismatches = []
    for query in queries:
        expected = expected_counts.get(query.query_id)
        if expected is not None and query.status == "SUCCESS" and query.rows_returned != expected:
            mismatches.append((query.query_id, expected, query.rows_returned))
    print(mismatches)

These example counts assume the standard TPC-H query definitions and parameters;
use expectations appropriate to the actual benchmark and parameter set.

Execution Context and Phases
----------------------------

System and platform metadata are optional and vary by runner. Inspect the
captured dictionaries rather than assuming every provider supplies the same keys.

.. code-block:: python

    print(results.system_profile or {})
    print(results.platform_info or {})
    print(results.execution_context or {})
    phases = results.execution_phases
    if phases is not None:
        setup = phases.setup
        if setup.data_generation is not None:
            print("Data generation milliseconds:", setup.data_generation.duration_ms)
        if setup.schema_creation is not None:
            print("Schema creation milliseconds:", setup.schema_creation.duration_ms)
        if setup.data_loading is not None:
            print("Data loading milliseconds:", setup.data_loading.duration_ms)
        if phases.power_test is not None:
            print("Power-test geometric mean:", phases.power_test.geometric_mean_time)

Result Storage and Monitoring
-----------------------------

Use a dedicated output directory and keep stable baselines with their provenance.
Set results.output_filename to control an export's filename stem, then use the
paths returned by export_result; do not assume the output is always results.json.

.. code-block:: python

    results.output_filename = "tpch_sf1_duckdb_baseline.json"
    baseline_paths = exporter.export_result(results, formats=["json"])
    print(baseline_paths["json"])

Review validation, workload comparability and run variance before choosing alert
thresholds. Keep query, stream and iteration identities in historical analysis,
and investigate outliers before excluding measurements.

Cost Calculation and Result Enrichment
--------------------------------------

These APIs estimate costs from packaged prices and resource metadata. Query
and phase totals do not certify invoices or infrastructure idle costs. See
:doc:`../../development/adr/adr-billing-unit-tb-tib-contract` for billing units.

.. py:function:: benchbox.core.cost.calculator.validate_resource_usage(platform: str, resource_usage: dict[str, Any]) -> tuple[bool, list[str]]

   Lowercase the platform and check key presence against ``cost_specs.yaml``.
   Required keys and at-least-one groups must be present. Values are not
   checked for type or sign. Unexpected keys produce warnings without
   invalidating the input. Unknown platforms return ``True`` with a no-schema
   warning. The input is not changed.

.. py:class:: benchbox.core.cost.calculator.CostCalculator

   Construct without arguments. Cloud calculation keys are ``snowflake``,
   ``bigquery``, ``redshift``, ``databricks``, ``databricks-df``, ``athena``,
   ``synapse``, ``fabric_dw`` and ``firebolt``. Lookups lowercase names but
   do not resolve display aliases; other keys can be local or unsupported.

   .. py:method:: is_local_platform(platform: str) -> bool

      Test the local/self-hosted platform set. Zero cloud compute cost does
      not measure hardware, storage or operating costs.

   .. py:method:: calculate_query_cost(platform: str, resource_usage: dict[str, Any], platform_config: dict[str, Any], validate: bool = True) -> QueryCost | None

      Return an estimate in packaged ``CURRENCY``. Validation logs warnings
      but does not prevent calculation when invalid. Local platforms return
      zero. Unsupported platforms and exceptions inside a platform calculator
      return ``None`` after logging; earlier input/schema errors can propagate.
      Missing query costs are not evidence of free execution.

      Fallback pricing can produce an estimate marked by
      ``pricing_details["price_unavailable"]``. Normalized publication rejects
      that estimate. Snowflake uses metered warehouse ``credits_used`` when
      present; ``credits_used_cloud_services`` is not warehouse billing.
      Otherwise runtime and warehouse size can support an estimate. Runtime
      preference is numeric ``execution_time_ms``, ``execution_time_seconds``,
      then ``total_elapsed_time_ms``; millisecond values are divided by 1,000.
      Booleans are not runtime measurements. Estimates exclude idle periods
      and multicluster scaling and can overcount concurrent warehouse use.

      Byte-priced tables declare ``tebibyte`` (``1024**4`` bytes) or
      ``terabyte`` (``10**12`` bytes). Retain that distinction when providing
      byte counts; unit labels alone are insufficient.

      ``benchbox/core/cost/cost_specs.yaml`` defines presence-validation schemas.
      The calculators consume these inputs; defaults below apply to missing
      configuration keys and support estimates, not observed deployment proof:

      * Snowflake uses ``edition="standard"``, ``cloud="aws"`` and
        ``region="us-east-1"``. Runtime estimation uses a truthy per-query
        ``warehouse_size`` before configuration ``warehouse_size``.
      * BigQuery uses truthy ``bytes_billed`` before ``bytes_processed`` and
        ``location="us"``. List-rate estimation starts at byte zero; it does
        not model the monthly free tier.
      * Redshift needs ``execution_time_seconds`` and uses
        ``node_type="dc2.large"``, ``node_count=1`` and
        ``region="us-east-1"``. It estimates runtime-based query cost,
        excluding cluster idle time; total cluster spend needs full runtime.
      * Databricks uses metered ``dbu_consumed`` when non-``None``; otherwise
        ``execution_time_seconds`` and ``cluster_size_dbu_per_hour`` are both
        needed. Defaults are ``cloud="aws"``, ``tier="premium"`` and
        ``workload_type="all_purpose"``. This is DBU cost only and excludes
        underlying cloud compute charges.
      * Athena needs ``data_scanned_bytes`` and uses ``region="us-east-1"``;
        legacy adapter ``cost_usd`` is ignored.
      * Synapse lowercases ``mode`` and treats missing/falsy mode as
        ``"serverless"``. That mode needs ``bytes_processed``; all other
        mode values take the dedicated branch using ``execution_time_seconds``
        and ``dwu_level="dw100c"``. Both branches use ``region="eastus"``.
        Dedicated pricing is per selected pool-hour, not multiplied by DWUs.
      * Fabric uses non-``None`` ``cu_seconds``; otherwise it needs
        ``execution_time_seconds`` and resolves CU count from ``sku="f64"``.
        It uses ``region="eastus"`` and converts CU-seconds to CU-hours.
      * Firebolt uses non-``None`` ``fbu_consumed``; otherwise it needs
        ``execution_time_seconds`` and estimates consumption from hourly
        rate for ``node_type="m"`` and ``node_count=1``. With metered FBUs,
        missing node type is recorded as ``"unknown"`` instead.

   .. py:method:: calculate_phase_cost(phase_name: str, query_costs: list[QueryCost]) -> PhaseCost

      Sum compute costs, including concurrent queries. This is summed spend,
      not cost per hour of phase wall time. ``None`` placeholders are omitted
      from totals and stored costs; query count remains the input list length.
      Empty input produces zero and no individual costs. Duration and stream
      count are not inferred. Callers must use packaged currency consistently;
      no conversion or matching-currency validation is performed.

   .. py:method:: calculate_benchmark_cost(phase_costs: list[PhaseCost], platform_details: dict[str, Any] | None = None) -> BenchmarkCost

      Delegate to ``BenchmarkCost.from_phase_costs`` using packaged
      ``CURRENCY``. Phase amounts must use that currency. Storage is not
      automatically added to the compute total.

   .. py:method:: calculate_normalized_benchmark_cost(platform: str, benchmark_cost: BenchmarkCost, platform_config: dict[str, Any]) -> tuple[NormalizedCost, list[str]]

      Return a normalized record and availability warnings. Local platforms
      return explicit zero with ``not_applicable_local`` and no warnings.
      Cloud normalization needs computed phases, billing unit, cloud/region
      and applicable warehouse, cluster or node sizing. Defaulted metadata,
      fallback price markers, missing pricing provenance or pricing older
      than 90 days make the amount unavailable. Concurrent Snowflake phases
      containing runtime-estimated credits are also unavailable.

      Success converts the existing compute total through
      ``Decimal(str(total_cost))`` without recalculating queries. Scope is
      ``compute_only``. Warnings yield ``normalized_cost_usd=None`` while
      preserving deployment and model provenance.

.. py:function:: benchbox.core.cost.integration.validate_platform_config(platform: str, config: dict[str, Any]) -> tuple[bool, list[str]]

   Check packaged requirements after lowercasing the platform. Missing or
   ``None`` values warn. Dedicated Synapse additionally needs ``dwu_level``;
   Databricks needs ``workload_type`` or ``warehouse_type``. Unknown platforms
   return ``True`` without warnings. This checks presence, not types or
   price coverage, and does not change configuration.

.. py:function:: benchbox.core.cost.integration.canonical_cost_platform_key(results: BenchmarkResults) -> str

   Resolve ``platform_type``, ``platform_name``, ``name``, then ``platform``.
   For each key, inspect ``platform_info``, its ``configuration``, then that
   mapping's nested ``configuration``. Fall back to ``results.platform``;
   return an empty string when absent. Strip/lowercase tokens, remove display
   mode suffixes and normalize spaces/underscores before registry aliases.
   Canonical ``fabric_dw`` and ``clickhouse_cloud`` retain underscores.

.. py:function:: benchbox.core.cost.integration.add_cost_estimation_to_results(results: BenchmarkResults, platform_config: dict[str, Any] | None = None) -> BenchmarkResults

   Enrich and return the same object. Without platform identity it is
   unchanged. Otherwise calculate available query costs, phase/compute totals,
   optional storage estimates, warnings and ``cost_summary["normalized_cost"]``.
   Query dictionaries receive ``cost``; objects with that attribute receive
   its value. Fallback-priced query amounts are stored as ``None``.

   Explicit configuration overrides are used directly. Otherwise extract
   normalized facets and legacy metadata. Observed compute sizing may support
   publication; requested, inferred or defaulted values support estimates
   while marking normalized cost unavailable. Missing sizing fields merge
   across representations while retaining field provenance. Databricks
   configured ``cluster_size`` is not observed warehouse size. Override
   callers remain responsible for truthful metadata and ``_defaulted_fields``;
   overrides are not independently authenticated.

   Validation logs warnings and continues. Positive loaded-data size adds a
   separate storage estimate for at least one hour, without changing compute
   total or normalized scope. Exceptions inside enrichment are logged and
   return the same object; prior mutations are not rolled back. Identity
   resolution precedes this handler, so errors there can propagate.


Cost Records and Availability
-----------------------------

The records in ``benchbox.core.cost.models`` carry estimates and availability
metadata. Creating a query, phase or benchmark cost record does not validate
currency consistency or nonnegative amounts. Normalized costs enforce the
availability rules below.

.. py:class:: benchbox.core.cost.models.DeploymentMetadata

   Frozen deployment context. Every field defaults to ``None``:
   ``cloud_provider: str | None``, ``cloud_region: str | None``,
   ``instance_type: str | None``, ``warehouse_size: str | None``,
   ``node_count: int | None``, ``cluster_size: str | None``,
   ``storage_format: str | None`` and ``storage_tier: str | None``.
   The class stores supplied values without resolving deployment defaults.

   .. py:method:: to_dict() -> dict[str, str | int | None]

      Return all eight named fields, including those whose values are ``None``.

.. py:class:: benchbox.core.cost.models.NormalizedCost

   Frozen cost with required fields ``normalized_cost_usd: Decimal | None``,
   ``cost_model_version: str``, ``cost_model_source: str``,
   ``cost_scope: CostScope``, ``cost_status: CostStatus``,
   ``billing_unit: str`` and ``pricing_region: str``. The optional
   ``deployment: DeploymentMetadata`` gets a new empty context per instance.
   ``CostScope`` names ``"compute_only"`` and ``"compute_plus_storage"``;
   ``CostStatus`` names ``"normalized"``, ``"not_applicable_local"`` and
   ``"unavailable"``. These Literal annotations are not runtime enum checks.

   Non-``None`` amounts are converted through ``Decimal(str(value))``.
   Construction rejects a negative amount, a normalized status without an
   amount, a local-not-applicable status without explicit zero, and an
   unavailable status carrying any amount. Local zero is not comparable to
   normalized cloud spend.

   .. py:property:: cost_usd
      :type: Decimal | None

      Deprecated compatibility alias. Return the amount only when status is
      ``"normalized"`` and scope is ``"compute_only"``; otherwise return
      ``None``, including for storage-inclusive costs.

   .. py:method:: to_dict() -> dict[str, Any]

      Return every named field plus ``cost_usd``. Both amount fields serialize
      as decimal strings or ``None``; deployment serializes using ``to_dict``.
      Decimal precision is retained rather than converted to a binary float.

.. py:class:: benchbox.core.cost.models.QueryCost(compute_cost: float, currency: str = "USD", pricing_details: dict[str, Any] = ...)

   Store the compute amount in ``currency`` and platform pricing context.
   ``pricing_details`` defaults to a new empty dictionary per instance.

   .. py:method:: to_dict() -> dict[str, Any]

      Return ``compute_cost``, ``currency`` and ``pricing_details``. The pricing
      dictionary is reused, not deep-copied.

.. py:class:: benchbox.core.cost.models.PhaseCost(phase_name: str, total_cost: float, query_count: int, currency: str = "USD", query_costs: list[QueryCost] | None = None, wall_clock_duration_seconds: float | None = None, concurrent_streams: int | None = None)

   Store a phase total, query count and optional individual costs. The duration
   is in seconds; concurrent streams is a count. Supplying query costs does
   not recompute or check the supplied total.

   .. py:method:: to_dict() -> dict[str, Any]

      Always return ``phase_name``, ``total_cost``, ``query_count`` and
      ``currency``. Include each optional field only when non-``None``.
      Serialize query costs recursively. When duration is positive, also
      include ``effective_cost_per_hour = total_cost / (duration / 3600)``.
      Zero or negative duration is retained without that derived field.

.. py:class:: benchbox.core.cost.models.BenchmarkCost(total_cost: float, currency: str = "USD", phase_costs: list[PhaseCost] = ..., platform_details: dict[str, Any] = ..., cost_model: str | None = None, warnings: list[str] = ..., storage_cost: float | None = None)

   Store a run total, phase breakdown and pricing context. The list and
   dictionary defaults create new containers per instance. ``storage_cost``
   is optional; setting it does not automatically change ``total_cost``.
   ``cost_model`` and ``warnings`` carry calculation limitations without
   themselves enforcing publication availability.

   .. py:method:: to_dict() -> dict[str, Any]

      Always return ``total_cost``, ``currency``, recursively serialized
      ``phase_costs`` and ``platform_details``. Include ``cost_model`` and
      ``warnings`` only when truthy; include ``storage_cost`` whenever it is
      non-``None``, including zero. Platform details and warnings are not
      deep-copied.

   .. py:classmethod:: from_phase_costs(phase_costs: list[PhaseCost], platform_details: dict[str, Any] | None = None, currency: str = "USD") -> BenchmarkCost

      Sum phase totals and retain the supplied phase list. A truthy platform
      details dictionary is reused; absent or empty input produces a new
      empty dictionary. This method does not validate matching phase currencies
      or add storage cost. Callers must supply phases whose currencies all
      match the requested ``currency``; this precondition is not checked.

.. py:function:: benchbox.core.cost.models.normalized_cost_allows_direct_total(normalized_cost: Mapping[str, Any] | None) -> bool

   Allow ``None`` for legacy results with no normalized block. Otherwise
   require a mapping whose status is ``"normalized"`` or
   ``"not_applicable_local"`` and whose ``normalized_cost_usd`` is non-``None``.
   This predicate checks availability, not numeric validity or comparability.

.. py:function:: benchbox.core.cost.models.cost_status_of(cost_summary: Mapping[str, Any] | None) -> str | None

   Return the string status from the nested ``normalized_cost`` mapping,
   or ``None`` when either mapping or the string status is absent. Unknown
   string values are returned unchanged.

.. py:function:: benchbox.core.cost.models.published_total_cost(cost_summary: Mapping[str, Any] | None) -> float | None

   Return ``None`` when the summary is not a mapping or its normalized block
   rejects a direct total. Otherwise return ``cost_summary.get("total_cost")``
   unchanged, including for legacy summaries. This helper does not convert
   or validate the stored numeric value.

.. py:function:: benchbox.core.cost.models.unavailable_cost_warning(warnings: list[str] | tuple[str, ...] | None) -> str | None

   Return the first string beginning with the exact, case-sensitive prefix
   ``"normalized cost unavailable"``, or ``None``. Non-string entries are
   ignored. TCO and optimizer consumers use this marker to reject unavailable
   object-level estimates.

Storage Cost Estimates
----------------------

.. py:function:: benchbox.core.cost.storage.estimate_storage_cost(platform: str, total_bytes: int, storage_duration_hours: float, region: str = "us-east-1") -> dict[str, Any]

   Estimate USD storage spend using the packaged storage price table. Platform
   lookup lowercases the name. Region lookup strips and lowercases the region
   before mapping it to a pricing tier. Missing platform prices use ``23.00``;
   a known platform with a missing tier uses its US tier, then ``23.00``.
   Those fallbacks are estimates and carry no availability status.

   The formula is ``(total_bytes / 1024**4) * price_per_tb_month *
   (storage_duration_hours / 730)``. ``storage_tb`` therefore uses a binary
   tebibyte divisor despite the TB label. Negative inputs are not rejected.
   Compression, replication, retention features, snapshots and backups are
   not separately modeled.

   :returns: ``storage_cost`` in USD, ``storage_tb``, ``price_per_tb_month``,
      ``duration_hours`` and the platform's packaged ``note`` or a default
      estimate note. This calculation does not modify a benchmark cost record.


See Also
--------

- :doc:`base` - Base benchmark interface
- :doc:`result-analysis` - Export, comparison and anonymization API
- :doc:`performance-monitoring` - Historical metrics and regression detection
- :doc:`/reference/result-formats` - Export formats
- :doc:`/guides/tpc/tpc-validation-guide` - TPC validation
- :doc:`/usage/examples` - Benchmark examples

Cloud Scan Price Resolution
---------------------------

These functions resolve the per-terabyte scanned-data rates used in cost estimates.
Prices come from the packaged pricing tables, so callers should use the returned
value rather than assume a fixed rate. Both return a ``PriceResolution`` with
``value``, ``table``, ``resolved_key``, ``fallback_used``, ``unit`` and ``reason``.

.. py:function:: benchbox.core.cost.pricing.resolve_athena_price_per_tb(region: str = "") -> PriceResolution

   Resolve the Athena scanned-data rate for an AWS region, using the
   ``athena_price_per_tb`` table. A listed region returns its own rate. An omitted
   or unlisted region returns the ``us-east-1`` rate and sets
   ``fallback_used=True``.

.. py:function:: benchbox.core.cost.pricing.resolve_synapse_serverless_price_per_tb(region: str = "") -> PriceResolution

   Resolve the Azure Synapse Serverless SQL Pool scanned-data rate for an Azure
   region, using the ``synapse_serverless_price_per_tb`` table. A listed region
   returns its own rate. An omitted or unlisted region returns the ``eastus`` rate
   and sets ``fallback_used=True``.

Region inputs are stripped and lowercased before lookup. ``resolved_key`` is a
one-element tuple containing the selected region, including the default region
on fallback. ``unit`` records the table's declared billing unit, or None when
unspecified. A fallback supplies a human-readable ``reason``; listed hits have
``reason=None``. Callers must inspect ``fallback_used`` to distinguish a listed price
from a default estimate.
Price and Quantity Resolution
-----------------------------

Pricing lookups use packaged tables rather than live vendor catalogs. Every
price and billing-quantity resolver returns ``PriceResolution``; consumers
must inspect fallback status before publishing amounts. A selected bucket
is a table policy, not independent proof of a location's current vendor rate.

The packaged compute estimates exclude enterprise/reserved/commitment discounts,
storage and network/data-transfer charges. In ``pricing_data.yaml``, each price
table must carry provenance keys ``source``, ``retrieved``,
``upstream_published``, ``method`` and ``verified_regions``; the latter is a
list. Each byte-priced table must also declare its billing unit. These schema
requirements preserve provenance and divisor checks, not price certification.

.. py:class:: benchbox.core.cost.pricing.PriceResolution(value: float | int | None, table: str, resolved_key: tuple[str, ...], fallback_used: bool, unit: str | None = None, reason: str | None = None)

   Frozen lookup record for both prices and quantities. ``value`` can be
   absent; ``resolved_key`` is a resolver-supplied lookup identity. Some
   fallbacks retain requested normalized labels rather than an existing table
   cell. Inspect ``fallback_used``, ``reason`` and ``table`` together; the key
   alone does not prove a stored cell supplied the amount. Scalar tables use
   an empty tuple. A designed priced bucket
   such as a table's ``other`` tier need not be marked fallback; a guessed
   default is marked. ``reason`` explains fallback and ``unit`` records an
   applicable billing unit. Construction does not validate these relationships.

.. py:function:: benchbox.core.cost.pricing.get_table_provenance(table: str) -> dict[str, Any] | None

   Return a shallow copy of dictionary provenance for the exact table name,
   or ``None`` when absent. Nested values are not deep-copied.

.. py:function:: benchbox.core.cost.pricing.get_table_unit(table: str) -> str | None

   Return a table's declared string unit or ``None``. Byte units distinguish
   ``tebibyte`` from ``terabyte``; absence does not infer either divisor.

.. py:function:: benchbox.core.cost.pricing.resolve_snowflake_credit_price(edition: str, cloud: str, region: str) -> PriceResolution

   Resolve ``snowflake_credit_prices`` by normalized edition/cloud and mapped
   region tier. Edition accepts hyphens/spaces as underscores. Missing cells
   use standard/aws/us pricing and mark fallback; if that cell is absent the
   implementation estimate is ``2.00``. A designed ``other`` tier
   is not fallback merely because the region mapped there.

.. py:function:: benchbox.core.cost.pricing.resolve_bigquery_price_per_tb(location: str) -> PriceResolution

   Strip/lowercase the location. Multi-region labels, captured exact locations
   and recognized continental branches resolve to packaged cells. An exact
   non-``other`` cell takes precedence over continental branches. The unmatched
   ``other`` bucket is a guessed rate and marks fallback. The table's declared
   unit accompanies the result; despite this function's name, the packaged
   BigQuery byte divisor is a tebibyte.

.. py:function:: benchbox.core.cost.pricing.resolve_redshift_node_price(node_type: str, region: str) -> PriceResolution

   Strip/lowercase inputs and resolve ``redshift_node_prices``. A known node
   with no exact region uses its ``other`` bucket without marking fallback.
   An unknown node returns the packaged implementation's default node-hour
   estimate ``1.00`` with fallback marked. These results estimate USD per node-hour.

.. py:function:: benchbox.core.cost.pricing.resolve_databricks_dbu_price(cloud: str, tier: str, workload_type: str) -> PriceResolution

   Normalize inputs and resolve ``databricks_dbu_prices``. Workload hyphens
   and spaces become underscores; ``serverless_sql`` maps to ``sql_serverless``
   and ``sql_compute`` to ``sql_pro``. Missing cells use aws/premium/all_purpose
   with fallback marked; if that default cell is absent the implementation
   estimate is ``0.55``. The result is a DBU price, not a warehouse size rate.

.. py:function:: benchbox.core.cost.pricing.resolve_databricks_warehouse_dbu_per_hour(warehouse_size: str) -> PriceResolution

   Strip and case-match warehouse labels. Return quantity unit ``DBU/hour``;
   unknown sizes use a conservative ``2.0`` estimate and mark fallback so the
   amount cannot support normalized publication.

.. py:function:: benchbox.core.cost.pricing.resolve_snowflake_warehouse_credits_per_hour(warehouse_size: str) -> PriceResolution

   Normalize case and size-label separators. Return quantity unit
   ``credits/hour``; unknown labels use the Medium ``4.0`` estimate with
   fallback marked. The selected size spelling is retained in known keys.

.. py:function:: benchbox.core.cost.pricing.resolve_synapse_dedicated_price(dwu_level: str, region: str) -> PriceResolution

   Strip/lowercase the DWU level and map the region tier. A known level with
   no tier cell uses its US cell and marks fallback; an unknown level uses
   DW100c US pricing with fallback marked. Missing US default cells use the
   implementation estimate ``1.20``. The amount is the hourly price
   for the selected pool level, not a price to multiply by the DWU count.

.. py:function:: benchbox.core.cost.pricing.resolve_fabric_cu_price(region: str) -> PriceResolution

   Map the region to a packaged capacity-unit hourly price. A designed
   ``other`` tier is returned without fallback marking, including when used
   after no direct tier cell exists.

.. py:function:: benchbox.core.cost.pricing.resolve_fabric_sku_cu_count(sku: str) -> PriceResolution

   Strip/lowercase a SKU and return quantity unit ``CU``. Unknown SKUs use
   the F2 quantity ``2`` with fallback marked. This is a quantity, not a price.

.. py:function:: benchbox.core.cost.pricing.resolve_firebolt_fbu_rate(node_type: str) -> PriceResolution

   Strip/lowercase the node label and return quantity unit ``FBU/hour``.
   Unknown nodes use the packaged M rate and mark fallback.

.. py:function:: benchbox.core.cost.pricing.resolve_firebolt_fbu_price() -> PriceResolution

   Return the packaged scalar ``firebolt_fbu_price`` with an empty resolved
   key and no fallback. Its presence does not establish provenance freshness.

.. py:function:: benchbox.core.cost.pricing.get_pricing_age_days(table: str | None = None) -> int | None

   For a table, parse its provenance retrieval date and return calendar days
   since that date, using local ``date.today()``. Missing, unknown or malformed
   dates return ``None``. Without a table use the file-level validation date;
   absence also returns ``None``. Future dates yield negative ages.

.. py:function:: benchbox.core.cost.pricing.is_pricing_stale(threshold_days: int = 90) -> bool

   Test whether the file-level age is strictly greater than the threshold.
   Unknown file-level age returns ``False``; callers needing publication
   assurance must check each relevant table's provenance separately.

Cost Projections
----------------

These projections extrapolate supplied costs. They do not forecast vendor
prices, validate invoices or automatically include idle infrastructure costs.
Rates are fractions: ``0.1`` growth means 10%, and ``0.2`` discount means 20%.

.. py:class:: benchbox.core.cost.tco.GrowthModel

   Enum members ``NONE="none"``, ``LINEAR="linear"`` and
   ``COMPOUND="compound"`` select flat, additive or compounded usage growth.

.. py:class:: benchbox.core.cost.tco.DiscountType

   Enum members ``NONE="none"``, ``RESERVED="reserved"``,
   ``COMMITTED_USE="committed_use"``, ``ENTERPRISE="enterprise"`` and
   ``VOLUME="volume"`` label the discount configuration.

.. py:class:: benchbox.core.cost.tco.GrowthConfig(model: GrowthModel = GrowthModel.NONE, annual_rate: float = 0.0, data_growth_rate: float | None = None)

   Store rates without range validation. The separate data rate is metadata;
   the calculator's cost multiplier uses ``annual_rate``.

   .. py:method:: get_data_growth_rate() -> float

      Return the separate data rate or ``annual_rate`` when it is ``None``.

   .. py:method:: calculate_multiplier(year: int) -> float

      Year numbers are one-based. The first year, earlier values and no-growth
      mode return one. Later linear growth is additive and compound growth
      multiplicative from the first-year base. Unknown model values return one.

.. py:class:: benchbox.core.cost.tco.DiscountConfig(discount_type: DiscountType = DiscountType.NONE, discount_percent: float = 0.0, commitment_years: int = 1, effective_start_year: int = 1)

   Store the discount fraction and commitment metadata without range checks.
   ``commitment_years`` does not limit the years receiving a discount.

   .. py:method:: get_discount_multiplier(year: int) -> float

      Return one for no discount or before its start year; otherwise return
      ``1 - discount_percent``. The discount persists in later years.

.. py:class:: benchbox.core.cost.tco.BudgetThreshold(name: str, amount: float, period: str = "annual")

   Amount uses the projected currency. Period labels are ``monthly``,
   ``annual`` and ``total``; construction does not validate them.

   .. py:method:: is_exceeded(cost: float, period: str) -> bool

      Compare strictly greater than the threshold. Convert only monthly to
      annual or annual to monthly when labels differ; other mismatches are
      compared without conversion.

.. py:class:: benchbox.core.cost.tco.BudgetAlert(threshold: BudgetThreshold, actual_cost: float, year: int, period: str, message: str)

   Store the triggered threshold, projected amount, one-based year, period
   and message. The amount is a projection, despite the ``actual_cost`` name.

.. py:class:: benchbox.core.cost.tco.YearlyProjection(year: int, calendar_year: int, base_cost: float, growth_multiplier: float, discount_multiplier: float, projected_cost: float, cumulative_cost: float, monthly_cost: float)

   Store one-based and calendar years, monetary amounts and applied multipliers.

   .. py:method:: to_dict() -> dict[str, Any]

      Return all fields; round amounts to two decimals and multipliers to four.

.. py:class:: benchbox.core.cost.tco.TCOProjection(platform: str, base_annual_cost: float, currency: str = "USD", projection_years: int = 5, start_year: int = ..., growth_config: GrowthConfig = ..., discount_config: DiscountConfig = ..., yearly_projections: list[YearlyProjection] = ..., total_tco: float = 0.0, average_annual_cost: float = 0.0, budget_alerts: list[BudgetAlert] = ..., metadata: dict[str, Any] = ...)

   Default start year is the local current year. Configurations and containers
   get new defaults per instance. Construction does not derive totals.

   .. py:method:: to_dict() -> dict[str, Any]

      Serialize projections and enum values, round monetary summary fields to
      two decimals and retain metadata by reference. Discount serialization
      omits ``effective_start_year``. Alert serialization uses threshold name
      and amount and omits the alert/threshold period; it is not a lossless
      reconstruction of every constructor field.

.. py:class:: benchbox.core.cost.tco.TCOCalculator

   Construct without arguments and with no budget thresholds.

   .. py:method:: add_budget_threshold(threshold: BudgetThreshold) -> None

      Append and retain the supplied threshold; repeated additions are allowed.

   .. py:method:: clear_budget_thresholds() -> None

      Remove every registered threshold.

   .. py:method:: calculate_tco(benchmark_cost: BenchmarkCost, annual_runs: int = 1, projection_years: int = 5, growth_config: GrowthConfig | None = None, discount_config: DiscountConfig | None = None, platform: str | None = None, start_year: int | None = None) -> TCOProjection

      Multiply per-run cost by annual runs and apply configured yearly growth
      and discounts. Preserve benchmark currency. Absent platform uses
      ``platform_details["platform"]`` or ``"unknown"``; absent or zero start
      year uses the local current year. Costs and rates are not range-checked.
      Supply a positive integer horizon: zero raises ``ZeroDivisionError``.
      Horizons are not restricted to the example values one, three and five.

      Each registered non-total threshold yields at most one alert, at its
      first exceeded year; total thresholds check the complete projected sum.
      A warning beginning ``"normalized cost unavailable"`` rejects the input
      with ``ValueError``. This gate checks the object warning marker, not a
      separate normalized result block. No cost regeneration occurs.

   .. py:method:: calculate_tco_from_annual_cost(annual_cost: float, platform: str, projection_years: int = 5, growth_config: GrowthConfig | None = None, discount_config: DiscountConfig | None = None, currency: str = "USD", start_year: int | None = None) -> TCOProjection

      Wrap the supplied annual amount as a benchmark cost and calculate with
      one annual run. Other projection and alert rules remain the same.

   .. py:method:: compare_platforms(projections: list[TCOProjection]) -> dict[str, Any]

      Return an error dictionary for empty input; otherwise rank ascending TCO
      and report savings against the largest total. Monetary values round to
      two decimals, savings percentages to one. Zero/negative largest totals
      produce zero savings percentages. Currency and horizon come from the
      cheapest projection without checking all inputs agree; callers must
      supply comparable currencies and horizons. No input ordering is changed.

.. py:function:: benchbox.core.cost.tco.create_standard_tco_scenarios(benchmark_cost: BenchmarkCost, annual_runs: int = 12) -> dict[str, TCOProjection]

   Return three five-year scenarios: conservative has no growth/discount;
   moderate has 10% compound growth and 15% reserved discount with three-year
   commitment metadata; aggressive has 25% compound growth and no discount.
   These are fixed assumptions, not recommendations or predicted vendor rates.

Optimization Records and Analysis
---------------------------------

Optimization estimates are rule outputs, not guaranteed savings. Recommendations
can overlap; the reported sum does not deduplicate competing changes.

.. py:class:: benchbox.core.cost.optimizer.OptimizationCategory

   Members ``PLATFORM_TIER="platform_tier"``, ``REGION="region"``,
   ``RESOURCE_SIZING="resource_sizing"``, ``PRICING_MODEL="pricing_model"``,
   ``QUERY="query"`` and ``DATA_MANAGEMENT="data_management"`` label opportunities.

.. py:class:: benchbox.core.cost.optimizer.ConfidenceLevel

   ``HIGH="high"`` labels pricing-based estimates, ``MEDIUM="medium"``
   typical patterns and ``LOW="low"`` rough estimates. These are labels,
   not statistical confidence intervals or independent price certification.

.. py:class:: benchbox.core.cost.optimizer.ImplementationEffort

   ``TRIVIAL="trivial"``, ``LOW="low"``, ``MEDIUM="medium"`` and
   ``HIGH="high"`` label rough minutes, hours, days and weeks of effort.

.. py:class:: benchbox.core.cost.optimizer.SavingsEstimate(amount: float, currency: str = "USD", period: str = "annual", confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM, range_low: float | None = None, range_high: float | None = None, percentage: float | None = None)

   Store estimated savings per period and optional monetary range/percentage.
   Construction does not validate ranges or convert currencies.

   .. py:method:: to_dict() -> dict[str, Any]

      Include amount, currency, period and confidence value. Include optional
      fields only when non-``None``; round amounts/ranges to two decimals and
      percentage to one.

.. py:class:: benchbox.core.cost.optimizer.ImplementationGuide(steps: list[str], prerequisites: list[str] = ..., risks: list[str] = ..., rollback: str | None = None, estimated_time: str | None = None)

   Store actions, requirements, risks and optional rollback/time guidance.
   Default prerequisite and risk lists are new per instance.

   .. py:method:: to_dict() -> dict[str, Any]

      Always include steps; include other fields only when truthy. Lists are
      reused, not deep-copied.

.. py:class:: benchbox.core.cost.optimizer.Recommendation(id: str, title: str, description: str, category: OptimizationCategory, savings: SavingsEstimate, effort: ImplementationEffort, guide: ImplementationGuide, priority: int = 50, platform: str | None = None, current_config: dict[str, Any] | None = None, recommended_config: dict[str, Any] | None = None, metadata: dict[str, Any] = ...)

   Store a recommendation and configurations. Higher priority sorts first;
   the nominal 1–100 score is not clamped. IDs are not checked for uniqueness.

   .. py:method:: to_dict() -> dict[str, Any]

      Serialize enum values, savings and guide. Optional platform/configuration
      and metadata fields appear only when truthy; configuration dictionaries
      and metadata are reused rather than deep-copied.

.. py:class:: benchbox.core.cost.optimizer.OptimizationReport(recommendations: list[Recommendation] = ..., total_potential_savings: float = 0.0, currency: str = "USD", platform: str | None = None, analysis_date: str = ..., benchmark_cost: BenchmarkCost | None = None, metadata: dict[str, Any] = ...)

   New containers are created per instance. Default analysis date is a local,
   timezone-naive ISO timestamp. Direct construction does not sort or sum.

   .. py:method:: to_dict() -> dict[str, Any]

      Serialize recommendations and count, round total savings to two decimals
      and include currency, platform, date and metadata. The original benchmark
      cost is omitted; metadata is reused.

   .. py:method:: get_by_category(category: OptimizationCategory) -> list[Recommendation]

      Return matching recommendations in existing order.

   .. py:method:: get_quick_wins(max_effort: ImplementationEffort = ImplementationEffort.LOW) -> list[Recommendation]

      Include effort levels through the supplied maximum and sort descending
      by savings amount. Invalid effort values raise ``ValueError``.

.. py:class:: benchbox.core.cost.optimizer.CostOptimizer

   Construct without arguments and register the built-in rules.

   .. py:method:: analyze(benchmark_cost: BenchmarkCost, platform_config: dict[str, Any] | None = None, annual_runs: int = 12) -> OptimizationReport

      ``annual_runs`` is expected benchmark executions per year; yearly
      estimates scale the supplied single-run cost by this count. Resolve
      ``platform_config["platform"]``, then
      ``benchmark_cost.platform_details["platform"]``, then ``"unknown"``.
      Supply actual deployment settings: built-in rules read these fields
      with rule-specific missing-key defaults:

      * Snowflake edition changes read ``edition`` (``""``),
        ``cloud`` (``"aws"``) and ``region`` (``"us-east-1"``);
        only enterprise/business-critical editions qualify. Region changes
        read ``region`` (``""``), ``cloud`` (``"aws"``) and
        ``edition`` (``"standard"``).
      * Databricks tier changes read ``tier`` (``""``), ``cloud``
        (``"aws"``) and ``workload_type`` (``"sql_warehouse"``);
        only enterprise/premium tiers qualify. Workload changes read
        ``workload_type`` (``""``), ``cloud`` (``"aws"``) and ``tier``
        (``"premium"``); only ``"all_purpose"`` qualifies.
      * BigQuery region changes read ``location`` (``""``). Data-scan
        estimation instead defaults ``location`` to ``"us"``. The latter
        reads bytes from ``benchmark_cost.platform_details["pricing_details"]``
        under ``"total_bytes_processed"``; missing/zero bytes are estimated
        from total cost and resolved price using 1024**4 bytes per billing TB.
      * Redshift region changes read ``region`` (``""``), ``node_type``
        (``"dc2.large"``) and ``node_count`` (1). Node migration reads
        ``node_type`` (``""``), ``region`` (``"us-east-1"``) and
        ``node_count`` (1); only ``ds2``-prefixed types qualify.

      Evaluate built-in rules. Sort recommendations by descending priority
      and sum their savings amounts without currency conversion or overlap
      adjustment. Preserve report currency from the benchmark; individual
      savings records retain their own currency labels.

      An unavailable-cost warning suppresses every rule and returns no
      recommendations. Fallback/absent pricing suppresses affected rules;
      ``metadata["suppressed_rules"]`` records rule and reason. Other rule
      exceptions are skipped without a suppression entry. Metadata also
      records annual runs, rules evaluated and recommendations generated.
      No platform configuration or benchmark cost is changed.
