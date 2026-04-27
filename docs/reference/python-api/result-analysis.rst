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

    # Run benchmark
    benchmark = TPCH(scale_factor=0.01)
    adapter = DuckDBAdapter()
    results = adapter.run_benchmark(benchmark)

    # Export results
    exporter = ResultExporter(output_dir="benchmark_results")
    exported_files = exporter.export_result(results, formats=["json", "csv", "html"])

    print(f"Results exported: {exported_files}")

API Reference
-------------

Result Exporter
~~~~~~~~~~~~~~~

.. autoclass:: benchbox.core.results.exporter.ResultExporter
   :members:

Export benchmark results to multiple formats with anonymization support.

**Constructor**:

.. code-block:: python

    ResultExporter(
        output_dir: str | Path | None = None,
        anonymize: bool = True,
        anonymization_config: AnonymizationConfig | None = None,
        console: Console | None = None
    )

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
       # {'json': Path('tpch_sf001_duckdb_20250112_120000.json'),
       #  'csv': Path('tpch_sf001_duckdb_20250112_120000.csv'),
       #  'html': Path('tpch_sf001_duckdb_20250112_120000.html')}

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
       # Output:
       # Exported Results (15 total)
       # Output directory: /path/to/results
       # [Rich table with benchmark, timestamp, duration, queries, status]

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

       # Check overall performance
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

.. autoclass:: benchbox.core.results.timing.TimingCollector
   :members:

Collect detailed timing information during query execution.

**Constructor**:

.. code-block:: python

    TimingCollector(enable_detailed_timing: bool = True)

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
           # Execute query
           result = connection.execute(query)

           # Record metrics
           timing["metrics"]["rows_returned"] = len(result)
           timing["metrics"]["bytes_processed"] = result.nbytes

       # Timing automatically captured
       timings = collector.get_completed_timings()
       print(f"Query executed in {timings[0].execution_time:.3f}s")

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

.. autoclass:: benchbox.core.results.timing.TimingAnalyzer
   :members:

Analyze timing data to provide insights and statistics.

**Constructor**:

.. code-block:: python

    TimingAnalyzer(timings: list[QueryTiming])

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

       # Basic stats
       print(f"Mean time: {analysis['basic_stats']['mean']:.3f}s")

       # Percentiles
       print(f"P95: {analysis['percentiles'][95]:.3f}s")

       # Status breakdown
       print(f"Successful: {analysis['status_breakdown']['SUCCESS']}")
       print(f"Failed: {analysis['status_breakdown'].get('ERROR', 0)}")

       # Throughput
       throughput = analysis.get('throughput_metrics', {})
       if throughput:
           print(f"Mean throughput: {throughput['mean_rows_per_second']:.0f} rows/s")

.. method:: identify_outliers(method="iqr", factor=1.5) -> list[QueryTiming]

   Identify timing outliers using statistical methods.

   **Parameters**:

   - **method** (str): Detection method - "iqr" (Interquartile Range) or "zscore" (Z-score)
   - **factor** (float): Outlier threshold factor (default: 1.5 for IQR, 3.0 for Z-score)

   **Returns**: list - QueryTiming objects identified as outliers

   **Example**:

   .. code-block:: python

       # IQR method (default)
       outliers_iqr = analyzer.identify_outliers(method="iqr", factor=1.5)

       # Z-score method
       outliers_zscore = analyzer.identify_outliers(method="zscore", factor=3.0)

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

       # Overall performance change
       mean_change = comparison['performance_change']['mean']
       print(f"Mean time change: {mean_change['change_percent']:.2f}%")

       # Regression assessment
       regression = comparison['regression_analysis']
       if regression['is_regression']:
           print(f"⚠️ Performance regression detected ({regression['severity']})")
       elif regression['is_improvement']:
           print("✅ Performance improved!")

Query Timing
~~~~~~~~~~~~

.. autoclass:: benchbox.core.results.timing.QueryTiming
   :members:

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

.. autoclass:: benchbox.core.results.anonymization.AnonymizationManager
   :members:

Manage anonymization of benchmark results for privacy-preserving sharing.

**Constructor**:

.. code-block:: python

    AnonymizationManager(config: AnonymizationConfig | None = None)

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
       # Output: machine_a1b2c3d4e5f6g7h8

.. method:: anonymize_system_profile() -> dict[str, Any]

   Generate anonymized system profile information.

   **Returns**: dict - Anonymized system information (OS, architecture, CPU, memory)

   **Example**:

   .. code-block:: python

       profile = manager.anonymize_system_profile()
       print(f"OS: {profile['os_type']} {profile['os_release']}")
       print(f"Architecture: {profile['architecture']}")
       print(f"CPU count: {profile['cpu_count']}")
       print(f"Memory: {profile['memory_gb']} GB")
       print(f"Hostname: {profile['hostname']}")  # Anonymized: host_abc123de
       print(f"Username: {profile['username']}")  # Anonymized: user_def456gh

.. method:: sanitize_path(path) -> str

   Sanitize file paths by removing or anonymizing sensitive components.

   **Parameters**:

   - **path** (str): File path to sanitize

   **Returns**: str - Sanitized path

   **Example**:

   .. code-block:: python

       # Sensitive path
       original = "/home/john.doe/projects/benchbox/data/customer_data.csv"
       sanitized = manager.sanitize_path(original)
       print(sanitized)
       # Output: /home/dir_a1b2c3d4/projects/benchbox/data/dir_e5f6g7h8.csv

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
       # Output: "Contact [REDACTED] or call [REDACTED]"

.. method:: anonymize_query_metadata(query_metadata) -> dict[str, Any]

   Anonymize query execution metadata.

   **Parameters**:

   - **query_metadata** (dict): Original query metadata

   **Returns**: dict - Anonymized metadata

.. method:: validate_anonymization(original_data, anonymized_data) -> dict[str, Any]

   Validate that anonymization was successful.

   **Parameters**:

   - **original_data** (dict): Original data before anonymization
   - **anonymized_data** (dict): Data after anonymization

   **Returns**: dict - Validation results with warnings and errors

   **Example**:

   .. code-block:: python

       validation = manager.validate_anonymization(original, anonymized)
       if validation['is_valid']:
           print("✅ Anonymization successful")
       else:
           print("❌ Anonymization issues:")
           for error in validation['errors']:
               print(f"  - {error}")

Anonymization Config
~~~~~~~~~~~~~~~~~~~~

.. autoclass:: benchbox.core.results.anonymization.AnonymizationConfig
   :members:

Configuration for result anonymization.

**Attributes**:

- **include_machine_id** (bool): Include anonymous machine identifier (default: True)
- **machine_id_salt** (str | None): Custom salt for machine ID generation
- **anonymize_paths** (bool): Sanitize file paths (default: True)
- **allowed_path_prefixes** (list[str]): Paths to keep unchanged (default: ["/tmp", "/var/tmp"])
- **include_system_profile** (bool): Include system information (default: True)
- **anonymize_hostnames** (bool): Anonymize machine hostnames (default: True)
- **anonymize_usernames** (bool): Anonymize usernames (default: True)
- **pii_patterns** (list[str]): Regex patterns for PII detection
- **custom_sanitizers** (dict[str, str]): Custom regex replacements

**Example**:

.. code-block:: python

    from benchbox.core.results.anonymization import (
        AnonymizationConfig,
        AnonymizationManager
    )

    # Custom configuration
    config = AnonymizationConfig(
        anonymize_hostnames=True,
        anonymize_usernames=True,
        anonymize_paths=True,
        allowed_path_prefixes=["/tmp", "/var/tmp", "/opt/benchbox"],
        custom_sanitizers={
            r"customer_\d+": "customer_[REDACTED]",
            r"project_[a-z]+": "project_[REDACTED]"
        }
    )

    manager = AnonymizationManager(config)

Display Utilities
~~~~~~~~~~~~~~~~~

.. autofunction:: benchbox.core.results.display.display_results

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
    # Output:
    # Benchmark: TPCH
    # Scale Factor: 0.01
    # Platform: duckdb
    # Benchmark Status: PASSED
    # Queries: 22/22 successful
    # Query Execution Time: 12.35s
    # Average Query Time: 0.56s
    # ✅ TPCH benchmark completed!

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

    # Run baseline benchmark
    print("Running baseline benchmark...")
    benchmark = TPCH(scale_factor=0.01)
    adapter = DuckDBAdapter()
    baseline_results = adapter.run_benchmark(benchmark)

    # Export baseline
    exporter = ResultExporter(output_dir="results", anonymize=True)
    baseline_files = exporter.export_result(
        baseline_results,
        formats=["json", "csv", "html"]
    )
    baseline_json = baseline_files["json"]

    # Run current benchmark (after code changes)
    print("\nRunning current benchmark...")
    current_results = adapter.run_benchmark(benchmark)

    # Export current
    current_files = exporter.export_result(
        current_results,
        formats=["json", "csv", "html"]
    )
    current_json = current_files["json"]

    # Compare results
    print("\nComparing results...")
    comparison = exporter.compare_results(baseline_json, current_json)

    # Analyze comparison
    perf_changes = comparison["performance_changes"]
    for metric, change in perf_changes.items():
        print(f"\n{metric.replace('_', ' ').title()}:")
        print(f"  Baseline: {change['baseline']:.3f}s")
        print(f"  Current: {change['current']:.3f}s")
        print(f"  Change: {change['change_percent']:+.2f}%")
        print(f"  Status: {'✅ Improved' if change['improved'] else '❌ Regressed'}")

    # Export comparison report
    report_path = exporter.export_comparison_report(comparison)
    print(f"\nComparison report: {report_path}")

    # Summary
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

    # Create timing collector
    collector = TimingCollector(enable_detailed_timing=True)

    # Execute queries with timing
    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    queries = {
        "Q1": "SELECT COUNT(*) FROM lineitem",
        "Q2": "SELECT l_orderkey, COUNT(*) FROM lineitem GROUP BY l_orderkey LIMIT 10",
        "Q3": "SELECT AVG(l_quantity) FROM lineitem"
    }

    for query_id, sql in queries.items():
        with collector.time_query(query_id, f"Query {query_id}") as timing:
            # Phase 1: Parse
            with collector.time_phase(query_id, "parse"):
                # Simulated parse phase
                pass

            # Phase 2: Execute
            with collector.time_phase(query_id, "execute"):
                result = conn.execute(sql).fetchall()

            # Record metrics
            collector.record_metric(query_id, "rows_returned", len(result))
            collector.record_metric(query_id, "tables_accessed", ["lineitem"])

    # Analyze timings
    timings = collector.get_completed_timings()
    analyzer = TimingAnalyzer(timings)

    # Basic statistics
    stats = analyzer.get_basic_statistics()
    print("Basic Statistics:")
    print(f"  Total queries: {stats['count']}")
    print(f"  Mean time: {stats['mean']:.3f}s")
    print(f"  Median time: {stats['median']:.3f}s")
    print(f"  Std dev: {stats['stdev']:.3f}s")

    # Percentiles
    percentiles = analyzer.get_percentiles([50, 90, 95, 99])
    print("\nPercentiles:")
    for p, value in percentiles.items():
        print(f"  P{int(p)}: {value:.3f}s")

    # Performance analysis
    analysis = analyzer.analyze_query_performance()
    print("\nTiming Phases:")
    for phase, phase_stats in analysis["timing_phases"].items():
        print(f"  {phase}: {phase_stats['mean']:.3f}s avg")

    # Identify outliers
    outliers = analyzer.identify_outliers(method="iqr", factor=1.5)
    if outliers:
        print("\nOutliers detected:")
        for outlier in outliers:
            print(f"  {outlier.query_id}: {outlier.execution_time:.3f}s")

Privacy-Preserving Result Export
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Export results with full anonymization:

.. code-block:: python

    from benchbox.core.results.exporter import ResultExporter
    from benchbox.core.results.anonymization import (
        AnonymizationConfig,
        AnonymizationManager
    )

    # Configure strict anonymization
    anon_config = AnonymizationConfig(
        include_machine_id=True,
        anonymize_paths=True,
        anonymize_hostnames=True,
        anonymize_usernames=True,
        allowed_path_prefixes=["/tmp"],
        custom_sanitizers={
            r"company_name": "[COMPANY]",
            r"project_\w+": "[PROJECT]"
        }
    )

    # Create exporter with anonymization
    exporter = ResultExporter(
        output_dir="public_results",
        anonymize=True,
        anonymization_config=anon_config
    )

    # Export with anonymization
    files = exporter.export_result(results, formats=["json", "html"])

    # Verify anonymization
    manager = AnonymizationManager(anon_config)
    import json

    with open(files["json"]) as f:
        anonymized_data = json.load(f)

    validation = manager.validate_anonymization(
        original_data=results.__dict__,
        anonymized_data=anonymized_data
    )

    if validation["is_valid"]:
        print("✅ Results safely anonymized for public sharing")
        print(f"Checks performed: {len(validation['checks_performed'])}")
    else:
        print("⚠️ Anonymization warnings:")
        for warning in validation["warnings"]:
            print(f"  - {warning}")

Regression Detection
~~~~~~~~~~~~~~~~~~~~

Automated regression detection across benchmark runs:

.. code-block:: python

    from benchbox.core.results.exporter import ResultExporter
    from pathlib import Path

    def check_for_regressions(baseline_file: Path, current_file: Path) -> bool:
        """Check for performance regressions."""
        exporter = ResultExporter()
        comparison = exporter.compare_results(baseline_file, current_file)

        if "error" in comparison:
            print(f"❌ Comparison failed: {comparison['error']}")
            return False

        # Check overall performance
        perf_changes = comparison.get("performance_changes", {})
        mean_change = perf_changes.get("average_query_time", {})

        if not mean_change:
            print("⚠️ No performance data available")
            return True

        change_pct = mean_change["change_percent"]

        # Regression threshold: >10% slower
        if change_pct > 10:
            print(f"❌ REGRESSION DETECTED: {change_pct:+.2f}% slower")

            # Show regressed queries
            query_comparisons = comparison.get("query_comparisons", [])
            regressed = [
                q for q in query_comparisons
                if not q["improved"] and q["change_percent"] > 10
            ]

            print(f"\nRegressed queries ({len(regressed)}):")
            for q in regressed[:5]:  # Show top 5
                print(f"  {q['query_id']}: {q['change_percent']:+.2f}%")

            return False

        elif change_pct < -10:
            print(f"✅ IMPROVEMENT: {abs(change_pct):.2f}% faster")
            return True

        else:
            print(f"✓ No significant change: {change_pct:+.2f}%")
            return True

    # Usage in CI/CD
    baseline = Path("baseline/tpch_sf001_duckdb.json")
    current = Path("current/tpch_sf001_duckdb.json")

    is_passing = check_for_regressions(baseline, current)
    exit(0 if is_passing else 1)

Best Practices
--------------

1. **Always Export Results**

   Export results for future comparison and analysis:

   .. code-block:: python

       from benchbox.core.results.exporter import ResultExporter

       # Export after every benchmark run
       exporter = ResultExporter(output_dir="results")
       exporter.export_result(results, formats=["json", "csv"])

2. **Enable Anonymization for Shared Results**

   Use anonymization when sharing results publicly:

   .. code-block:: python

       # For public sharing
       public_exporter = ResultExporter(anonymize=True)

       # For internal use
       internal_exporter = ResultExporter(anonymize=False)

3. **Track Baselines for Regression Detection**

   Maintain baseline results for each major configuration:

   .. code-block:: python

       # Save baseline
       baseline_exporter = ResultExporter(output_dir="baselines")
       baseline_exporter.export_result(results, formats=["json"])

       # Compare against baseline regularly
       comparison = exporter.compare_results(baseline_path, current_path)

4. **Use Detailed Timing for Optimization**

   Collect detailed timing to identify optimization opportunities:

   .. code-block:: python

       # Enable detailed timing
       collector = TimingCollector(enable_detailed_timing=True)

       # Analyze timing phases
       analyzer = TimingAnalyzer(timings)
       analysis = analyzer.analyze_query_performance()

       # Identify bottlenecks
       for phase, stats in analysis["timing_phases"].items():
           if stats["mean"] > 1.0:  # Phases taking >1s
               print(f"Bottleneck: {phase} taking {stats['mean']:.2f}s")

5. **Monitor for Outliers**

   Identify and investigate timing outliers:

   .. code-block:: python

       analyzer = TimingAnalyzer(timings)
       outliers = analyzer.identify_outliers(method="iqr", factor=1.5)

       if outliers:
           print("Investigating outliers:")
           for outlier in outliers:
               print(f"  {outlier.query_id}: {outlier.execution_time:.3f}s")
               # Investigate cause...

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

    # Enable detailed timing
    collector = TimingCollector(enable_detailed_timing=True)

    # Ensure timing phases are recorded
    with collector.time_query("Q1") as timing:
        with collector.time_phase("Q1", "execute"):
            # Execute query
            pass

Anonymization Validation Failures
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: PII detected in anonymized results

**Solution**:

.. code-block:: python

    # Add custom sanitizers
    config = AnonymizationConfig(
        custom_sanitizers={
            r"your_pattern": "[REDACTED]"
        }
    )

    manager = AnonymizationManager(config)
    validation = manager.validate_anonymization(original, anonymized)

    for warning in validation["warnings"]:
        print(f"Address: {warning}")

See Also
--------

- :doc:`results` - Result models and data structures
- :doc:`/usage/examples` - Usage examples
- :doc:`/usage/troubleshooting` - Troubleshooting guide
- :doc:`utilities` - Other utility functions
- :doc:`/testing` - Testing and validation

External Resources
~~~~~~~~~~~~~~~~~~

- `Rich Console Documentation <https://rich.readthedocs.io/>`_ - Terminal formatting
- `Python Statistics Module <https://docs.python.org/3/library/statistics.html>`_ - Statistical functions
- `JSON Schema <https://json-schema.org/>`_ - Result schema validation
