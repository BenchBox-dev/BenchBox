Result Analysis API
===================

.. tags:: reference, python-api, validation

Complete Python API reference for BenchBox result analysis, export, and comparison utilities.

Overview
--------

BenchBox provides comprehensive result analysis utilities for benchmark execution data. These tools enable detailed performance analysis, result comparison, statistical analysis, and automated export in multiple formats.

**Key Features**:

- **Result Export**: Export benchmar results to JSON, CSV, and HTML formats
- **Result Comparison**: Compare results across runs to detect regressions
- **Timing Analysis**: Detailed query timing with statistical analysis
- **Anonymization**: Privacy-preserving result sharing with PII removal
- **Display Utilities**: Formatted output for benchmark results
- **Performance Tracking**: Trend analysis and outlier detection

Quick Start
-----------

Export and analyze benchmark results:

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter
    from benchbox.core.results.exporter import ResultExporter

    benchmark = TPCH(scale_factor=0.01)
    adapter = DuckDBAdapter()
    results = adapter.run_benchmark(benchmark)

    exporter = ResultExporter(output_dir="benchmark_results")
    exported_files = exporter.export_result(results, formats=["json", "csv", "html"])

    print(f"Results exported: {exported_files}")

API Reference
-------------

Result Exporter
~~~~~~~~~~~~~~~

.. py:class:: benchbox.core.results.exporter.ResultExporter(output_dir: str | Path | None=None, anonymize: bool=True, anonymization_config: AnonymizationConfig | None=None, console: Console | None=None, plan_history_dir: str | Path | None=None)

   Export and compare benchmark results using the maintained result schema. JSON,
   CSV and HTML are supported. Omitted output_dir uses the configured results
   directory; explicit local output directories are created. Anonymization defaults
   to True. With no explicit anonymization_config, soft-read BENCHBOX_MACHINE_ID_SALT
   through AnonymizationConfig.from_public_environ; an unset salt permits private
   or local exports. Public submission separately requires its public salt.

   :param output_dir: Optional local or supported cloud output directory.
   :param anonymize: Apply result anonymization; defaults to True.
   :param anonymization_config: Explicit policy, overriding the environment-derived default.
   :param console: Optional Rich console; otherwise create one.
   :param plan_history_dir: Optional plan-history directory, otherwise BENCHBOX_PLAN_HISTORY_DIR. When both are unset, plan history is not recorded.

.. py:method:: benchbox.core.results.exporter.ResultExporter.export_result(result: ResultLike, formats: list[str] | None=None) -> dict[str, Path]

   Export a BenchmarkResults object or supported result-like input. formats=None
   means ["json"]. Return a mapping from format names to output paths. Unknown
   formats or failed exports raise ResultExportError; earlier successful files may
   already have been written when another format fails. JSON validates the schema,
   converts datetime values and writes applicable tuning or plan companions.

   :param result: Result to export.
   :param formats: Requested formats: json, csv and/or html.
   :returns: Paths of successfully exported formats.
   :raises ResultExportError: An unknown format or an export failure.

.. py:method:: benchbox.core.results.exporter.ResultExporter.list_results() -> list[dict[str, Any]]

   List supported result-schema JSON files in the output directory, newest
   ISO-timestamp strings first. Skip companion and submission files and files
   that cannot be loaded. Each metadata entry contains file, version, benchmark,
   platform, scale_factor, execution_id, timestamp, duration in seconds, queries
   and status.

.. py:method:: benchbox.core.results.exporter.ResultExporter.show_results_summary() -> None

   Print a summary table for up to ten newest exported results, or an empty-directory message.

.. py:method:: benchbox.core.results.exporter.ResultExporter.load_result_from_file(filepath: Path) -> dict[str, Any] | None

   Parse a JSON file and return a wrapper with data, version, result_schema_version
   and filepath; return None on loading failure. Read the schema version from
   result_schema_version or version, falling back to unknown. This method does not
   reconstruct BenchmarkResults or validate the loaded schema.

.. py:method:: benchbox.core.results.exporter.ResultExporter.compare_results(baseline_path: Path, current_path: Path) -> dict[str, Any]

   Compare saved baseline and current results across supported schema layouts.
   Return performance_changes, per-query comparisons, summary and a
   generation_compatibility block with status, compatible, warning and stamped
   provenance. Loading failure returns an error dictionary. A positive performance
   change means the current duration increased; a negative change means it fell.
   Review generation compatibility before interpreting performance differences.

.. py:method:: benchbox.core.results.exporter.ResultExporter.export_comparison_report(comparison: dict[str, Any], output_path: PathLike | None=None) -> PathLike

   Write comparison results to an HTML report and return its path. Omitted
   output_path creates a timestamped comparison_report file in the output directory.
   Use the dictionary returned by compare_results, including compatibility warnings.


Export benchmark results to multiple formats with anonymization support.

**Constructor**:

**Parameters**:

- **output_dir** (str | Path | None): Output directory for exported files (default: "benchmark_runs/results")
- **anonymize** (bool): Whether to anonymize sensitive data (default: True)
- **anonymization_config** (AnonymizationConfig | None): Custom anonymization configuration
- **console** (Console | None): Rich console for output (creates default if None)

**Methods**:

.. method:: export_result(result, formats=None) -> dict[str, Path]

   Export benchmark result to specified formats.

   **Parameters**:

   - **result** (BenchmarkResults): Benchmark result object to export
   - **formats** (list[str] | None): Export formats (default: ["json"]). Options: "json", "csv", "html"

   **Returns**: dict - Mapping of format names to exported file paths

   **Example**:

   .. code-block:: python

       exporter = ResultExporter()
       files = exporter.export_result(results, formats=["json", "csv", "html"])

   The returned ``files`` mapping has one entry per format, keyed by format name, such as ``json``, ``csv`` and ``html``. Each value is the ``Path`` of the exported file, named like ``tpch_sf001_duckdb_20250112_120000.json``.

.. method:: list_results() -> list[dict[str, Any]]

   List all exported results in the output directory.

   **Returns**: list - Result metadata dictionaries sorted by timestamp (newest first)

   **Example**:

   .. code-block:: python

       exporter = ResultExporter(output_dir="results")
       results = exporter.list_results()
       for result in results:
           print(f"{result['benchmark']} @ {result['timestamp']}: {result['duration']:.2f}s")

.. method:: show_results_summary()

   Display a formatted summary of all exported results.

   **Example**:

   .. code-block:: python

       exporter = ResultExporter()
       exporter.show_results_summary()

   The output starts with an ``Exported Results (15 total)`` heading (the count depends on how many results exist) and the output directory, for example ``/path/to/results``. A Rich table follows with the benchmark, timestamp, duration, queries and status of each result.

.. method:: compare_results(baseline_path, current_path) -> dict[str, Any]

   Compare two benchmark results for performance changes.

   **Parameters**:

   - **baseline_path** (Path): Path to baseline result JSON file
   - **current_path** (Path): Path to current result JSON file

   **Returns**: dict - Comparison analysis with performance changes and query-level comparisons

   **Example**:

   .. code-block:: python

       comparison = exporter.compare_results(
           Path("baseline_results.json"),
           Path("current_results.json")
       )

       perf = comparison['performance_changes']['average_query_time']
       print(f"Average query time: {perf['change_percent']:.2f}% change")
       if perf['improved']:
           print("✅ Performance improved!")

.. method:: export_comparison_report(comparison, output_path=None) -> Path

   Export comparison analysis as HTML report.

   **Parameters**:

   - **comparison** (dict): Comparison results from compare_results()
   - **output_path** (Path | None): Output file path (auto-generated if None)

   **Returns**: Path - Path to exported HTML report

   **Example**:

   .. code-block:: python

       comparison = exporter.compare_results(baseline_path, current_path)
       report_path = exporter.export_comparison_report(comparison)
       print(f"Comparison report: {report_path}")

Timing Collector
~~~~~~~~~~~~~~~~

.. py:class:: benchbox.core.results.timing.TimingCollector(enable_detailed_timing: bool=True)

   Collect complete-query durations and optional detailed phases in seconds.
   enable_detailed_timing=False disables phase measurements, while complete query
   measurements still run. Completed records accumulate until cleared.

.. py:method:: benchbox.core.results.timing.TimingCollector.time_query(query_id: str, query_name: Optional[str]=None)

   Return a context manager yielding a mutable execution dictionary. Measure
   elapsed seconds, record the query's wall-clock start timestamp, and append a
   completed QueryTiming on exit. Exceptions derived from Exception mark the
   record ERROR, retain the error message and re-raise. Active execution state is
   removed after completion. Repeated or nested uses of a query ID have separate
   execution tokens.

.. py:method:: benchbox.core.results.timing.TimingCollector.time_phase(query_id: str, phase_name: str)

   Return a context manager yielding no value. With detailed timing enabled and
   an active query execution, record elapsed seconds under phase_name on exit,
   including exceptional exit. A repeated phase name replaces its earlier value.
   With detailed timing disabled or no active query, the context is a no-op.
   Standard parse, optimize, execute and fetch names populate corresponding fields.

.. py:method:: benchbox.core.results.timing.TimingCollector.record_metric(query_id: str, metric_name: str, value: Any)

   Store a metric on the active execution for query_id; no active execution is a
   no-op. Context-local execution is preferred, otherwise the latest active token
   for that query ID is used. Standard metrics include rows_returned,
   bytes_processed, tables_accessed, thread_id, connection_id, cpu_time,
   memory_peak, warning_count and platform_metrics.

.. py:method:: benchbox.core.results.timing.TimingCollector.get_completed_timings() -> list[QueryTiming]

   Return a shallow copy of the completed-record list; QueryTiming objects themselves remain shared.

.. py:method:: benchbox.core.results.timing.TimingCollector.clear_completed_timings()

   Clear the completed-record list without clearing active execution state.

.. py:method:: benchbox.core.results.timing.TimingCollector.get_timing_summary() -> dict[str, Any]

   Return {} with no completed records. With no successful records, return only
   total_queries and successful_queries=0. Otherwise return successful/failed
   counts and total, average, median, minimum, maximum and sample standard
   deviation of successful execution times in seconds. One successful observation
   has a zero standard deviation.


Collect detailed timing information during query execution.

**Constructor**:

**Parameters**:

- **enable_detailed_timing** (bool): Whether to collect phase-level timing breakdown

**Methods**:

.. method:: time_query(query_id, query_name=None)

   Context manager for timing a complete query execution.

   **Parameters**:

   - **query_id** (str): Unique query identifier
   - **query_name** (str | None): Human-readable query name

   **Yields**: dict - Timing data dictionary for collecting metrics during execution

   **Example**:

   .. code-block:: python

       from benchbox.core.results.timing import TimingCollector

       collector = TimingCollector()

       with collector.time_query("Q1", "Pricing Summary Report") as timing:
           result = connection.execute(query)

           timing["metrics"]["rows_returned"] = len(result)
           timing["metrics"]["bytes_processed"] = result.nbytes

       timings = collector.get_completed_timings()
       print(f"Query executed in {timings[0].execution_time:.3f}s")

   The ``time_query`` context manager captures the timing automatically. Inside it, execute the query and then record metrics such as ``rows_returned`` on ``timing["metrics"]``.

.. method:: time_phase(query_id, phase_name)

   Context manager for timing a specific execution phase.

   **Parameters**:

   - **query_id** (str): Query identifier
   - **phase_name** (str): Phase name (e.g., "parse", "optimize", "execute", "fetch")

   **Example**:

   .. code-block:: python

       with collector.time_query("Q1") as timing:
           with collector.time_phase("Q1", "parse"):
               parsed_query = parser.parse(query)

           with collector.time_phase("Q1", "optimize"):
               optimized_query = optimizer.optimize(parsed_query)

           with collector.time_phase("Q1", "execute"):
               result = executor.execute(optimized_query)

.. method:: get_completed_timings() -> list[QueryTiming]

   Get all completed query timings.

   **Returns**: list - List of QueryTiming objects

.. method:: get_timing_summary() -> dict[str, Any]

   Get statistical summary of all collected timings.

   **Returns**: dict - Summary statistics (total, average, median, min, max, stddev)

   **Example**:

   .. code-block:: python

       summary = collector.get_timing_summary()
       print(f"Total queries: {summary['total_queries']}")
       print(f"Average time: {summary['average_execution_time']:.3f}s")
       print(f"Median time: {summary['median_execution_time']:.3f}s")

Timing Analyzer
~~~~~~~~~~~~~~~

.. py:class:: benchbox.core.results.timing.TimingAnalyzer(timings: list[QueryTiming])

   Analyze a list of QueryTiming records. Statistical timing methods use records
   whose status is SUCCESS; status breakdown still includes every input record.
   The successful-record subset is selected during construction.

.. py:method:: benchbox.core.results.timing.TimingAnalyzer.get_basic_statistics() -> dict[str, Any]

   Return count, total_time, mean, median, min, max, stdev and variance for
   successful execution times in seconds. No successes yields {}; one observation
   has zero sample standard deviation and variance. Variance uses squared seconds.

.. py:method:: benchbox.core.results.timing.TimingAnalyzer.get_percentiles(percentiles: list[float] | None=None) -> dict[float, float]

   Return linearly interpolated execution-time percentiles in seconds. Omitted
   percentiles means [50, 75, 90, 95, 99]. Ignore requested values outside 0 to 100.
   No successful records yields {}; a singleton returns its one value.

.. py:method:: benchbox.core.results.timing.TimingAnalyzer.analyze_query_performance() -> dict[str, Any]

   Return basic_stats, percentiles, status_breakdown, timing_phases and
   throughput_metrics. Phase summaries use recorded successful phase timings;
   throughput summaries use successful records with a nonzero rows_per_second.

.. py:method:: benchbox.core.results.timing.TimingAnalyzer.identify_outliers(method: str='iqr', factor: float=1.5) -> list[QueryTiming]

   Return successful QueryTiming records outside the selected threshold. iqr uses
   quartiles and bounds Q1-factor*IQR and Q3+factor*IQR; the default factor is 1.5.
   zscore uses absolute deviation divided by sample standard deviation, strictly
   greater than factor; zero standard deviation returns no outliers. No successful
   records returns []. IQR requires at least two successful observations.

   :raises ValueError: An unknown method when successful records are present.
   :raises statistics.StatisticsError: IQR with only one successful observation.

.. py:method:: benchbox.core.results.timing.TimingAnalyzer.compare_query_performance(baseline_timings: list[QueryTiming]) -> dict[str, Any]

   Compare current and baseline successful timing statistics. Missing successes
   on either side returns an error dictionary. Mean, median, min and max changes
   are whole percentages: 15.0 means 15 percent slower, unlike the fractional
   thresholds in PerformanceHistory. Negative changes are improvements. Mean
   changes above 10 percent flag regression; above 25 is major and above 50 is
   critical. Changes below -10 percent flag improvement. Comparison is of aggregate
   statistics, without matching query identities.

   :raises ZeroDivisionError: A compared baseline mean, median, min or max is zero.


Analyze timing data to provide insights and statistics.

**Constructor**:

**Parameters**:

- **timings** (list[QueryTiming]): List of QueryTiming objects to analyze

**Methods**:

.. method:: get_basic_statistics() -> dict[str, Any]

   Get basic statistical measures for execution times.

   **Returns**: dict - Statistics (count, total_time, mean, median, min, max, stdev, variance)

   **Example**:

   .. code-block:: python

       from benchbox.core.results.timing import TimingAnalyzer

       analyzer = TimingAnalyzer(timings)
       stats = analyzer.get_basic_statistics()

       print(f"Mean execution time: {stats['mean']:.3f}s")
       print(f"Standard deviation: {stats['stdev']:.3f}s")

.. method:: get_percentiles(percentiles=None) -> dict[float, float]

   Calculate percentiles for execution times.

   **Parameters**:

   - **percentiles** (list[float] | None): Percentile values 0-100 (default: [50, 75, 90, 95, 99])

   **Returns**: dict - Mapping of percentile to execution time

   **Example**:

   .. code-block:: python

       percentiles = analyzer.get_percentiles([50, 90, 95, 99])
       print(f"P50: {percentiles[50]:.3f}s")
       print(f"P95: {percentiles[95]:.3f}s")
       print(f"P99: {percentiles[99]:.3f}s")

.. method:: analyze_query_performance() -> dict[str, Any]

   Comprehensive performance analysis of queries.

   **Returns**: dict - Analysis with basic stats, percentiles, status breakdown, timing phases, throughput metrics

   **Example**:

   .. code-block:: python

       analysis = analyzer.analyze_query_performance()

       print(f"Mean time: {analysis['basic_stats']['mean']:.3f}s")

       print(f"P95: {analysis['percentiles'][95]:.3f}s")

       print(f"Successful: {analysis['status_breakdown']['SUCCESS']}")
       print(f"Failed: {analysis['status_breakdown'].get('ERROR', 0)}")

       throughput = analysis.get('throughput_metrics', {})
       if throughput:
           print(f"Mean throughput: {throughput['mean_rows_per_second']:.0f} rows/s")

   The example prints the basic stats, the percentiles, the status breakdown and the throughput.

.. method:: identify_outliers(method="iqr", factor=1.5) -> list[QueryTiming]

   Identify timing outliers using statistical methods.

   **Parameters**:

   - **method** (str): Detection method - "iqr" (Interquartile Range) or "zscore" (Z-score)
   - **factor** (float): Outlier threshold factor (default: 1.5 for IQR, 3.0 for Z-score)

   **Returns**: list - QueryTiming objects identified as outliers

   **Example**:

   .. code-block:: python

       outliers_iqr = analyzer.identify_outliers(method="iqr", factor=1.5)

       outliers_zscore = analyzer.identify_outliers(method="zscore", factor=3.0)

   The IQR method is the default. The first call uses it with a factor of 1.5, and the second uses the Z-score method with a factor of 3.0.

       for outlier in outliers_iqr:
           print(f"Outlier: {outlier.query_id} - {outlier.execution_time:.3f}s")

.. method:: compare_query_performance(baseline_timings) -> dict[str, Any]

   Compare current timings against baseline timings.

   **Parameters**:

   - **baseline_timings** (list[QueryTiming]): Baseline timing data

   **Returns**: dict - Comparison analysis with performance changes and regression assessment

   **Example**:

   .. code-block:: python

       current_analyzer = TimingAnalyzer(current_timings)
       comparison = current_analyzer.compare_query_performance(baseline_timings)

       mean_change = comparison['performance_change']['mean']
       print(f"Mean time change: {mean_change['change_percent']:.2f}%")

       regression = comparison['regression_analysis']
       if regression['is_regression']:
           print(f"⚠️ Performance regression detected ({regression['severity']})")
       elif regression['is_improvement']:
           print("✅ Performance improved!")

   ``performance_change`` gives the overall performance change, and ``regression_analysis`` gives the regression assessment.

Query Timing
~~~~~~~~~~~~

.. py:class:: benchbox.core.results.timing.QueryTiming(query_id: str, query_name: Optional[str] = None, execution_sequence: int = 0, execution_time: float = 0.0, parse_time: Optional[float] = None, optimization_time: Optional[float] = None, execution_only_time: Optional[float] = None, fetch_time: Optional[float] = None, timing_breakdown: dict[str, float] = <factory>, rows_returned: int = 0, bytes_processed: Optional[int] = None, tables_accessed: list[str] = <factory>, timestamp: datetime = <factory>, thread_id: Optional[str] = None, connection_id: Optional[str] = None, rows_per_second: Optional[float] = None, bytes_per_second: Optional[float] = None, cpu_time: Optional[float] = None, memory_peak: Optional[int] = None, status: str = 'SUCCESS', error_message: Optional[str] = None, warning_count: int = 0, platform_metrics: dict[str, Any] = <factory>)

   Dataclass for one timing record. query_id is required; all other fields have
   the defaults shown below. Execution and phase timings use seconds. During
   construction, positive execution_time and rows_returned compute rows_per_second;
   positive execution_time with bytes_processed computes bytes_per_second.

.. py:method:: benchbox.core.results.timing.QueryTiming.to_dict() -> dict[str, Any]

   Return a serialization dictionary. The execution_time field becomes
   execution_time_seconds, timestamp becomes an ISO 8601 string, and phase timings
   remain seconds. This is a timing-analysis dictionary, not the compact schema-v2
   query-row layout.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.query_id
   :type: str

   Query identifier. Required constructor argument.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.query_name
   :type: Optional[str]

   Optional human-readable query name. Default: ``None``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.execution_sequence
   :type: int

   Execution sequence number. Default: ``0``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.execution_time
   :type: float

   Complete query duration in seconds. Default: ``0.0``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.parse_time
   :type: Optional[float]

   Optional parsing duration in seconds. Default: ``None``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.optimization_time
   :type: Optional[float]

   Optional optimization duration in seconds. Default: ``None``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.execution_only_time
   :type: Optional[float]

   Optional execution phase duration in seconds. Default: ``None``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.fetch_time
   :type: Optional[float]

   Optional result-fetch duration in seconds. Default: ``None``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.timing_breakdown
   :type: dict[str, float]

   Named phase durations in seconds. Default: a new empty dictionary per instance.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.rows_returned
   :type: int

   Number of returned rows. Default: ``0``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.bytes_processed
   :type: Optional[int]

   Optional processed byte count. Default: ``None``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.tables_accessed
   :type: list[str]

   Names of accessed tables. Default: a new empty list per instance.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.timestamp
   :type: datetime

   Query timestamp; TimingCollector records its UTC wall-clock start. Default: the local datetime when the instance is created.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.thread_id
   :type: Optional[str]

   Optional execution thread identifier. Default: ``None``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.connection_id
   :type: Optional[str]

   Optional connection identifier. Default: ``None``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.rows_per_second
   :type: Optional[float]

   Rows returned divided by positive execution time when calculated. Default: ``None``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.bytes_per_second
   :type: Optional[float]

   Bytes processed divided by positive execution time when calculated. Default: ``None``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.cpu_time
   :type: Optional[float]

   Optional CPU time in seconds. Default: ``None``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.memory_peak
   :type: Optional[int]

   Optional peak memory metric supplied by the producer; no unit conversion is performed. Default: ``None``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.status
   :type: str

   Query status, commonly SUCCESS, ERROR, TIMEOUT or CANCELLED. Default: ``'SUCCESS'``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.error_message
   :type: Optional[str]

   Optional execution failure message. Default: ``None``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.warning_count
   :type: int

   Number of recorded warnings. Default: ``0``.

.. py:attribute:: benchbox.core.results.timing.QueryTiming.platform_metrics
   :type: dict[str, Any]

   Producer-supplied platform metrics. Default: a new empty dictionary per instance.


Detailed timing information for a single query execution.

**Attributes**:

- **query_id** (str): Unique query identifier
- **query_name** (str | None): Human-readable query name
- **execution_sequence** (int): Execution order number
- **execution_time** (float): Total execution time in seconds
- **parse_time** (float | None): SQL parsing time
- **optimization_time** (float | None): Query optimization time
- **execution_only_time** (float | None): Pure execution time (excluding parse/fetch)
- **fetch_time** (float | None): Result fetching time
- **timing_breakdown** (dict): Detailed phase-by-phase timing
- **rows_returned** (int): Number of rows returned
- **bytes_processed** (int | None): Bytes processed during execution
- **tables_accessed** (list[str]): Tables accessed by query
- **timestamp** (datetime): Execution timestamp
- **rows_per_second** (float | None): Throughput metric
- **bytes_per_second** (float | None): Data processing rate
- **status** (str): Execution status (SUCCESS, ERROR, TIMEOUT, CANCELLED)
- **error_message** (str | None): Error message if failed
- **platform_metrics** (dict): Platform-specific performance metrics

**Example**:

.. code-block:: python

    from benchbox.core.results.timing import QueryTiming
    from datetime import datetime

    timing = QueryTiming(
        query_id="Q1",
        query_name="Pricing Summary Report",
        execution_time=1.234,
        parse_time=0.015,
        optimization_time=0.042,
        execution_only_time=1.150,
        fetch_time=0.027,
        rows_returned=4,
        bytes_processed=1024 * 1024,
        tables_accessed=["lineitem", "orders"],
        status="SUCCESS"
    )

    print(f"Query: {timing.query_id}")
    print(f"Total time: {timing.execution_time:.3f}s")
    print(f"Throughput: {timing.rows_per_second:.0f} rows/s")
    print(f"Data rate: {timing.bytes_per_second / 1024 / 1024:.2f} MB/s")

Anonymization Manager
~~~~~~~~~~~~~~~~~~~~~

.. py:class:: benchbox.core.results.anonymization.AnonymizationManager(config: Optional[AnonymizationConfig]=None)

   Anonymize result metadata and text using an AnonymizationConfig. With
   config=None, construct a default configuration. The manager caches its generated
   machine pseudonym for reuse.

.. py:method:: benchbox.core.results.anonymization.AnonymizationManager.get_anonymous_machine_id() -> str

   Return a cached machine_<16-hex-character> pseudonym. Prefer an OS machine ID,
   then a hardware fingerprint, and use a restricted-environment fallback when
   needed. Apply an optional configured salt before SHA-256 hashing. Fallback
   identity may vary between runs; no raw machine ID is returned.

.. py:method:: benchbox.core.results.anonymization.AnonymizationManager.anonymize_result_payload(payload: dict[str, Any]) -> dict[str, Any]

   Return a key-aware anonymized result mapping. Redact secret-like values and
   pseudonymize stable infrastructure identities so exports can be grouped without
   exposing account, endpoint, storage or container identifiers.

.. py:method:: benchbox.core.results.anonymization.AnonymizationManager.anonymize_tuning_payload(payload: dict[str, Any]) -> dict[str, Any]

   Anonymize a tuning companion while preserving normalized source provenance.
   Handle table/column identifiers that generic result walking cannot identify.
   Retain a validated repository-relative source reference; path-hash other
   source_file values from legacy or user-authored companions.

.. py:method:: benchbox.core.results.anonymization.AnonymizationManager.remove_pii(text: str) -> str

   Apply configured regular expressions case-insensitively to text, replacing
   PII-pattern matches with [REDACTED], then applying custom sanitizer replacements.
   Return empty text unchanged. This performs configured pattern matching, not an
   exhaustive guarantee that every sensitive value is detected.


Manage anonymization of benchmark results for privacy-preserving sharing.

**Constructor**:

**Parameters**:

- **config** (AnonymizationConfig | None): Anonymization configuration (uses defaults if None)

**Methods**:

.. method:: get_anonymous_machine_id() -> str

   Generate stable, anonymous machine identifier.

   **Returns**: str - Anonymous machine ID (e.g., "machine_a1b2c3d4e5f6g7h8")

   **Example**:

   .. code-block:: python

       from benchbox.core.results.anonymization import AnonymizationManager

       manager = AnonymizationManager()
       machine_id = manager.get_anonymous_machine_id()
       print(f"Anonymous ID: {machine_id}")

   The ID has the form ``machine_a1b2c3d4e5f6g7h8``.

.. method:: anonymize_result_payload(payload) -> dict[str, Any]

   Anonymize a whole result bundle payload. This is the entry point that
   replaced the former per-field helpers: path sanitizing, system-profile
   scrubbing, and query-metadata anonymization now happen inside this single
   pass rather than through separate public methods.

   **Parameters**:

   - **payload** (dict): Result bundle payload to anonymize

   **Returns**: dict - Anonymized payload, safe for publication

   **Example**:

   .. code-block:: python

       from benchbox.core.results.anonymization import AnonymizationManager

       manager = AnonymizationManager()
       public_payload = manager.anonymize_result_payload(raw_payload)

.. method:: anonymize_tuning_payload(payload) -> dict[str, Any]

   Anonymize a tuning companion payload using the same pseudonym domain as
   :meth:`anonymize_result_payload`, so a bundle and its sidecars stay
   mutually consistent.

   **Parameters**:

   - **payload** (dict): Tuning companion payload

   **Returns**: dict - Anonymized payload

.. method:: remove_pii(text) -> str

   Remove personally identifiable information from text.

   **Parameters**:

   - **text** (str): Text to clean

   **Returns**: str - Text with PII removed or replaced with [REDACTED]

   **Example**:

   .. code-block:: python

       text = "Contact john@example.com or call 192.168.1.1"
       cleaned = manager.remove_pii(text)
       print(cleaned)

   The output is ``Contact [REDACTED] or call [REDACTED]``.

.. note::

   **Migrating from the pre-consolidation API.** ``anonymize_system_profile()``,
   ``sanitize_path()``, ``anonymize_query_metadata()``, and
   ``validate_anonymization()`` were removed. Call
   :meth:`anonymize_result_payload` on the whole payload instead - it applies
   all of those transforms in one pass. To confirm a payload is publishable,
   use :func:`benchbox.core.results.anonymization.find_public_path_leaks`,
   which returns the offending field paths and replaces the old
   ``validate_anonymization`` check.

Anonymization Config
~~~~~~~~~~~~~~~~~~~~

.. py:class:: benchbox.core.results.anonymization.AnonymizationConfig(machine_id_salt: Optional[str] = None, pii_patterns: list[str] = <factory>, custom_sanitizers: dict[str, str] = <factory>)

   Dataclass of anonymization settings. machine_id_salt defaults to None;
   pii_patterns has fresh IPv4/email/SSN-like patterns per instance, and
   custom_sanitizers defaults to a fresh empty mapping.

.. py:classmethod:: benchbox.core.results.anonymization.AnonymizationConfig.from_public_environ(*, environ: Optional[dict[str, str]]=None, require_salt: bool=False) -> 'AnonymizationConfig'

   Construct a configuration from BENCHBOX_MACHINE_ID_SALT in the supplied
   mapping, or the process environment when environ=None. require_salt=True raises
   MissingPublicPseudonymSaltError when salt is unset; False permits empty salt
   for private/local use. Whitespace-only values are treated as unset.

.. py:attribute:: benchbox.core.results.anonymization.AnonymizationConfig.machine_id_salt
   :type: Optional[str]

   Optional salt for machine pseudonyms. Default: ``None``.

.. py:attribute:: benchbox.core.results.anonymization.AnonymizationConfig.pii_patterns
   :type: list[str]

   Regular expressions to redact from text. Default: fresh configured IPv4/email/SSN-like regex patterns per instance.

.. py:attribute:: benchbox.core.results.anonymization.AnonymizationConfig.custom_sanitizers
   :type: dict[str, str]

   Regular expressions mapped to custom replacement strings. Default: a new empty dictionary per instance.


Configuration for result anonymization.

**Attributes**:

- **machine_id_salt** (str | None): Salt for machine-ID pseudonyms (default: ``None``).
  With the default, pseudonyms are deterministic across installations - set a
  salt when you need cross-installation correlation resistance.
- **pii_patterns** (list[str]): Regex patterns for PII detection (defaults cover
  IPv4 addresses, email addresses, and US SSN-shaped strings)
- **custom_sanitizers** (dict[str, str]): Custom regex replacements (default: ``{}``)

.. note::

   ``include_machine_id``, ``anonymize_paths``, ``allowed_path_prefixes``,
   ``include_system_profile``, ``anonymize_hostnames``, and
   ``anonymize_usernames`` were removed. Path, hostname, and username handling
   is no longer optional - it always applies - so passing any of these now
   raises ``TypeError``. Drop them from existing configs.

**Example**:

.. code-block:: python

    from benchbox.core.results.anonymization import (
        AnonymizationConfig,
        AnonymizationManager
    )

    config = AnonymizationConfig(
        machine_id_salt="your-org-salt",
        custom_sanitizers={
            r"customer_\d+": "customer_[REDACTED]",
            r"project_[a-z]+": "project_[REDACTED]"
        }
    )

    manager = AnonymizationManager(config)

Display Utilities
~~~~~~~~~~~~~~~~~

Benchmark listings use descriptions from the benchmark registry. Custom
classes passed to ``display_benchmark_list()`` can supply a ``description``
string attribute; otherwise the listing shows ``No description available``.
Class docstrings do not provide listing descriptions. Custom callers that
previously used a class docstring should move their short description to this
attribute.

.. py:function:: benchbox.core.results.display.display_results(result_data: dict[str, Any], verbosity: int=0) -> None

   Print a flat result-summary dictionary. Read benchmark, scale_factor,
   platform and success; optionally display query counts and successful execution
   times. With verbosity > 0 and total_duration present, print total/setup
   seconds. Additional verbosity levels do not select another output format.
   This input is not the exported nested schema-v2 payload.


Display benchmark results in standardized format.

**Parameters**:

- **result_data** (dict): Benchmark result dictionary
- **verbosity** (int): Verbosity level (0=minimal, 1=detailed, 2=verbose)

**Example**:

.. code-block:: python

    from benchbox.core.results.display import display_results

    result_data = {
        "benchmark": "tpch",
        "scale_factor": 0.01,
        "platform": "duckdb",
        "success": True,
        "total_queries": 22,
        "successful_queries": 22,
        "total_execution_time": 12.345,
        "average_query_time": 0.561
    }

    display_results(result_data, verbosity=1)

The output lists the benchmark (``TPCH``), the scale factor (0.01), the platform (``duckdb``), the benchmark status (``PASSED``), the query count (``22/22 successful``), the query execution time (``12.35s``), the average query time (``0.56s``) and a final completion line.

Usage Examples
--------------

Complete Result Analysis Workflow
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Full workflow from benchmark execution to comparison:

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter
    from benchbox.core.results.exporter import ResultExporter
    from benchbox.core.results.timing import TimingAnalyzer
    from pathlib import Path

    print("Running baseline benchmark...")
    benchmark = TPCH(scale_factor=0.01)
    adapter = DuckDBAdapter()
    baseline_results = adapter.run_benchmark(benchmark)

    exporter = ResultExporter(output_dir="results", anonymize=True)
    baseline_files = exporter.export_result(
        baseline_results,
        formats=["json", "csv", "html"]
    )
    baseline_json = baseline_files["json"]

    print("\nRunning current benchmark...")
    current_results = adapter.run_benchmark(benchmark)

    current_files = exporter.export_result(
        current_results,
        formats=["json", "csv", "html"]
    )
    current_json = current_files["json"]

    print("\nComparing results...")
    comparison = exporter.compare_results(baseline_json, current_json)

    perf_changes = comparison["performance_changes"]
    for metric, change in perf_changes.items():
        print(f"\n{metric.replace('_', ' ').title()}:")
        print(f"  Baseline: {change['baseline']:.3f}s")
        print(f"  Current: {change['current']:.3f}s")
        print(f"  Change: {change['change_percent']:+.2f}%")
        print(f"  Status: {'✅ Improved' if change['improved'] else '❌ Regressed'}")

    report_path = exporter.export_comparison_report(comparison)
    print(f"\nComparison report: {report_path}")

    summary = comparison.get("summary", {})
    print(f"\n{'='*60}")
    print(f"Overall Assessment: {summary.get('overall_assessment', 'unknown')}")
    print(f"Queries compared: {summary.get('total_queries_compared', 0)}")
    print(f"Improved: {summary.get('improved_queries', 0)}")
    print(f"Regressed: {summary.get('regressed_queries', 0)}")
    print(f"{'='*60}")

Detailed Timing Analysis
~~~~~~~~~~~~~~~~~~~~~~~~~

Collect and analyze detailed query timing:

.. code-block:: python

    from benchbox.core.results.timing import (
        TimingCollector,
        TimingAnalyzer
    )
    from benchbox.platforms.duckdb import DuckDBAdapter

    collector = TimingCollector(enable_detailed_timing=True)

    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    queries = {
        "Q1": "SELECT COUNT(*) FROM lineitem",
        "Q2": "SELECT l_orderkey, COUNT(*) FROM lineitem GROUP BY l_orderkey LIMIT 10",
        "Q3": "SELECT AVG(l_quantity) FROM lineitem"
    }

    for query_id, sql in queries.items():
        with collector.time_query(query_id, f"Query {query_id}") as timing:
            with collector.time_phase(query_id, "parse"):
                pass

            with collector.time_phase(query_id, "execute"):
                result = conn.execute(sql).fetchall()

            collector.record_metric(query_id, "rows_returned", len(result))
            collector.record_metric(query_id, "tables_accessed", ["lineitem"])

    timings = collector.get_completed_timings()
    analyzer = TimingAnalyzer(timings)

    stats = analyzer.get_basic_statistics()
    print("Basic Statistics:")
    print(f"  Total queries: {stats['count']}")
    print(f"  Mean time: {stats['mean']:.3f}s")
    print(f"  Median time: {stats['median']:.3f}s")
    print(f"  Std dev: {stats['stdev']:.3f}s")

    percentiles = analyzer.get_percentiles([50, 90, 95, 99])
    print("\nPercentiles:")
    for p, value in percentiles.items():
        print(f"  P{int(p)}: {value:.3f}s")

    analysis = analyzer.analyze_query_performance()
    print("\nTiming Phases:")
    for phase, phase_stats in analysis["timing_phases"].items():
        print(f"  {phase}: {phase_stats['mean']:.3f}s avg")

    outliers = analyzer.identify_outliers(method="iqr", factor=1.5)
    if outliers:
        print("\nOutliers detected:")
        for outlier in outliers:
            print(f"  {outlier.query_id}: {outlier.execution_time:.3f}s")

The example creates a timing collector and executes queries with timing. Each query has a ``parse`` phase (a simulated placeholder) and an ``execute`` phase, and a ``rows_returned`` metric is recorded. It then analyzes the timings: basic statistics, percentiles, performance analysis and outliers.

Privacy-Preserving Result Export
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Export results with full anonymization:

.. code-block:: python

    from benchbox.core.results.exporter import ResultExporter
    from benchbox.core.results.anonymization import (
        AnonymizationConfig,
        AnonymizationManager
    )

    anon_config = AnonymizationConfig(
        machine_id_salt="your-org-salt",
        custom_sanitizers={
            r"company_name": "[COMPANY]",
            r"project_\w+": "[PROJECT]"
        }
    )

    exporter = ResultExporter(
        output_dir="public_results",
        anonymize=True,
        anonymization_config=anon_config
    )

    files = exporter.export_result(results, formats=["json", "html"])

    import json

    from benchbox.core.results.anonymization import find_public_path_leaks

    with open(files["json"]) as f:
        anonymized_data = json.load(f)

    leaks = find_public_path_leaks(anonymized_data)

    if not leaks:
        print("✅ No public-path leaks found - safe to share paths publicly")
        print("   (path check only - confirm PII sanitizers above separately)")
    else:
        print("⚠️ Anonymization warnings:")
        for path in leaks:
            print(f"  - {path}")

Path, hostname and username handling always applies (see the note above), so the configuration sets only the remaining options. The example then creates an exporter with anonymization, exports the results, and verifies that the exported payload carries no public-path leaks.

Regression Detection
~~~~~~~~~~~~~~~~~~~~

Automated regression detection across benchmark runs:

.. code-block:: python

    from benchbox.core.results.exporter import ResultExporter
    from pathlib import Path

    def check_for_regressions(baseline_file: Path, current_file: Path) -> bool:
        exporter = ResultExporter()
        comparison = exporter.compare_results(baseline_file, current_file)

        if "error" in comparison:
            print(f"❌ Comparison failed: {comparison['error']}")
            return False

        perf_changes = comparison.get("performance_changes", {})
        mean_change = perf_changes.get("average_query_time", {})

        if not mean_change:
            print("⚠️ No performance data available")
            return True

        change_pct = mean_change["change_percent"]

        if change_pct > 10:
            print(f"❌ REGRESSION DETECTED: {change_pct:+.2f}% slower")

            query_comparisons = comparison.get("query_comparisons", [])
            regressed = [
                q for q in query_comparisons
                if not q["improved"] and q["change_percent"] > 10
            ]

            print(f"\nRegressed queries ({len(regressed)}):")
            for q in regressed[:5]:
                print(f"  {q['query_id']}: {q['change_percent']:+.2f}%")

            return False

        elif change_pct < -10:
            print(f"✅ IMPROVEMENT: {abs(change_pct):.2f}% faster")
            return True

        else:
            print(f"✓ No significant change: {change_pct:+.2f}%")
            return True

    baseline = Path("baseline/tpch_sf001_duckdb.json")
    current = Path("current/tpch_sf001_duckdb.json")

    is_passing = check_for_regressions(baseline, current)
    exit(0 if is_passing else 1)

The function treats a mean query time more than 10% slower as a regression and lists up to the top 5 regressed queries. The last lines show the usage in CI/CD.

Best Practices
--------------

1. **Always Export Results**

   Export results for future comparison and analysis:

   .. code-block:: python

       from benchbox.core.results.exporter import ResultExporter

       exporter = ResultExporter(output_dir="results")
       exporter.export_result(results, formats=["json", "csv"])

   Export after every benchmark run.

2. **Enable Anonymization for Shared Results**

   Use anonymization when sharing results publicly:

   .. code-block:: python

       public_exporter = ResultExporter(anonymize=True)

       internal_exporter = ResultExporter(anonymize=False)

   Use the anonymizing exporter for public sharing and the other for internal use.

3. **Track Baselines for Regression Detection**

   Maintain baseline results for each major configuration:

   .. code-block:: python

       baseline_exporter = ResultExporter(output_dir="baselines")
       baseline_exporter.export_result(results, formats=["json"])

       comparison = exporter.compare_results(baseline_path, current_path)

   The first lines save the baseline. The last line compares against the baseline regularly.

4. **Use Detailed Timing for Optimization**

   Collect detailed timing to identify optimization opportunities:

   .. code-block:: python

       collector = TimingCollector(enable_detailed_timing=True)

       analyzer = TimingAnalyzer(timings)
       analysis = analyzer.analyze_query_performance()

       for phase, stats in analysis["timing_phases"].items():
           if stats["mean"] > 1.0:
               print(f"Bottleneck: {phase} taking {stats['mean']:.2f}s")

   The example treats phases that take more than 1 second as bottlenecks.

5. **Monitor for Outliers**

   Identify and investigate timing outliers:

   .. code-block:: python

       analyzer = TimingAnalyzer(timings)
       outliers = analyzer.identify_outliers(method="iqr", factor=1.5)

       if outliers:
           print("Investigating outliers:")
           for outlier in outliers:
               print(f"  {outlier.query_id}: {outlier.execution_time:.3f}s")

   Investigate the cause of each outlier.

Common Issues
-------------

Comparison Schema Mismatch
~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Cannot compare results with different schema versions

**Solution**:

.. code-block:: python

    comparison = exporter.compare_results(baseline_path, current_path)

    if "error" in comparison:
        print(f"Comparison error: {comparison['error']}")
        if "schema_version" in comparison.get("error", ""):
            print("Re-export both results with current schema version")

Missing Timing Data
~~~~~~~~~~~~~~~~~~~

**Problem**: No detailed timing information available

**Solution**:

.. code-block:: python

    collector = TimingCollector(enable_detailed_timing=True)

    with collector.time_query("Q1") as timing:
        with collector.time_phase("Q1", "execute"):
            pass

Anonymization Validation Failures
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: PII detected in anonymized results

**Solution**:

.. code-block:: python

    from benchbox.core.results.anonymization import (
        AnonymizationConfig,
        AnonymizationManager,
        find_public_path_leaks,
    )

    config = AnonymizationConfig(
        custom_sanitizers={
            r"your_pattern": "[REDACTED]"
        }
    )

    manager = AnonymizationManager(config)

    payload_under_test = {"working_dir": "/home/alice/project", "rows": 100}
    anonymized = manager.anonymize_result_payload(payload_under_test)

    for path in find_public_path_leaks(anonymized):
        print(f"Address: {path}")

The first part adds custom sanitizers. The last part re-anonymizes the payload under test with the stricter configuration and reports any remaining leaks.

See Also
--------

- :doc:`results` - Result models and data structures
- :doc:`/usage/examples` - Usage examples
- :doc:`/usage/troubleshooting` - Troubleshooting guide
- :doc:`utilities` - Other utility functions
- :doc:`/testing/index` - Testing and validation

External Resources
~~~~~~~~~~~~~~~~~~

- `Rich Console Documentation <https://rich.readthedocs.io/>`_ - Terminal formatting
- `Python Statistics Module <https://docs.python.org/3/library/statistics.html>`_ - Statistical functions
- `JSON Schema <https://json-schema.org/>`_ - Result schema validation
