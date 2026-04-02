"""TPC Metrics Calculation Engine

This module implements the official TPC metrics calculation engine that computes
standard TPC metrics according to the official TPC specifications.

Key metrics implemented:
- Power@Size: 3600 × Scale_Factor / geometric_mean(query_times)
- Throughput@Size: Num_Streams × 3600 × Scale_Factor / Throughput_Test_Time
- QphH@Size: sqrt(Power@Size × Throughput@Size) [TPC-H]
- QphDS@Size: sqrt(Power@Size × Throughput@Size) [TPC-DS]

Classes:
- TPCMetricsCalculator: Main metrics calculation engine
- PowerMetrics: Power@Size calculation and validation
- ThroughputMetrics: Throughput@Size calculation and validation
- CompositeMetrics: QphH@Size and QphDS@Size calculations
- MetricsValidator: Validation of metric calculations
- QueryResult: Container for individual query execution results
- StatisticalAnalyzer: Statistical analysis of test results
- MetricsReporter: Formatting and reporting of results

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import math
import statistics
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class BenchmarkType(Enum):
    """Enumeration of supported TPC benchmark types."""

    TPCH = "TPC-H"
    TPCDS = "TPC-DS"
    TPCDI = "TPC-DI"


@dataclass
class QueryResult:
    """Container for individual test execution results."""

    query_name: str
    execution_time: float  # in seconds
    success: bool
    error_message: Optional[str] = None
    stream_id: Optional[int] = None

    def __post_init__(self) -> None:
        if self.execution_time < 0:
            raise ValueError("Execution time cannot be negative")
        if not self.success and self.error_message is None:
            raise ValueError("Failed tests must have an error message")


@dataclass
class PowerTestResults:
    """Container for power test results."""

    scale_factor: float
    test_results: list[QueryResult]
    total_time: float  # Total power test time in seconds
    benchmark_type: BenchmarkType

    def __post_init__(self) -> None:
        if self.scale_factor <= 0:
            raise ValueError("Scale factor must be positive")
        if self.total_time <= 0:
            raise ValueError("Total time must be positive")
        if not self.test_results:
            raise ValueError("Test results cannot be empty")


@dataclass
class ThroughputTestResults:
    """Container for throughput test results."""

    scale_factor: float
    test_results: list[QueryResult]
    total_time: float  # Total throughput test time in seconds
    num_streams: int
    benchmark_type: BenchmarkType

    def __post_init__(self) -> None:
        if self.scale_factor <= 0:
            raise ValueError("Scale factor must be positive")
        if self.total_time <= 0:
            raise ValueError("Total time must be positive")
        if self.num_streams <= 0:
            raise ValueError("Number of streams must be positive")
        if not self.test_results:
            raise ValueError("Test results cannot be empty")


@dataclass
class MetricsResult:
    """Container for calculated metrics."""

    power_at_size: Optional[float] = None
    throughput_at_size: Optional[float] = None
    composite_metric: Optional[float] = None
    scale_factor: Optional[float] = None
    benchmark_type: Optional[BenchmarkType] = None
    validation_errors: list[str] = field(default_factory=list)


# Range validation rules for power test results: (attribute, min, max, label)
_POWER_TEST_VALIDATION_RULES: list[tuple[str, float, float, str]] = [
    ("scale_factor", 0.01, 100000.0, "Scale factor"),
    ("total_time", 0.001, 86400.0, "Total time"),
]


class MetricsValidator:
    """Validates TPC metric calculations and test results."""

    # TPC specification bounds and requirements
    MIN_SCALE_FACTOR = 0.01
    MAX_SCALE_FACTOR = 100000.0
    MIN_EXECUTION_TIME = 0.001  # 1ms minimum
    MAX_EXECUTION_TIME = 86400.0  # 24 hours maximum

    @staticmethod
    def validate_power_test_results(results: PowerTestResults) -> list[str]:
        """Validate power test results according to TPC specifications."""
        errors = []

        # Scale factor and total time range validation
        for attr, min_val, max_val, label in _POWER_TEST_VALIDATION_RULES:
            value = getattr(results, attr)
            if value < min_val:
                errors.append(f"{label} {value} is below minimum {min_val}")
            if value > max_val:
                errors.append(f"{label} {value} exceeds maximum {max_val}")

        # Test completeness validation
        failed_tests = [r for r in results.test_results if not r.success]
        if failed_tests:
            errors.append(f"Power test has {len(failed_tests)} failed queries: {[r.query_name for r in failed_tests]}")

        # Query execution time validation
        for result in results.test_results:
            if result.execution_time < MetricsValidator.MIN_EXECUTION_TIME:
                errors.append(f"Query {result.query_name} execution time {result.execution_time} is too low")
            if result.execution_time > MetricsValidator.MAX_EXECUTION_TIME:
                errors.append(f"Query {result.query_name} execution time {result.execution_time} is too high")

        # Benchmark-specific validation
        if results.benchmark_type == BenchmarkType.TPCH:
            if len(results.test_results) != 22:
                errors.append(f"TPC-H power test should have 22 queries, got {len(results.test_results)}")
        elif results.benchmark_type == BenchmarkType.TPCDS and len(results.test_results) != 99:
            errors.append(f"TPC-DS power test should have 99 queries, got {len(results.test_results)}")

        return errors

    @staticmethod
    def validate_throughput_test_results(results: ThroughputTestResults) -> list[str]:
        """Validate throughput test results according to TPC specifications."""
        errors = []

        # Scale factor validation
        if results.scale_factor < MetricsValidator.MIN_SCALE_FACTOR:
            errors.append(f"Scale factor {results.scale_factor} is below minimum {MetricsValidator.MIN_SCALE_FACTOR}")

        if results.scale_factor > MetricsValidator.MAX_SCALE_FACTOR:
            errors.append(f"Scale factor {results.scale_factor} exceeds maximum {MetricsValidator.MAX_SCALE_FACTOR}")

        # Time validation
        if results.total_time < MetricsValidator.MIN_EXECUTION_TIME:
            errors.append(f"Total time {results.total_time} is below minimum {MetricsValidator.MIN_EXECUTION_TIME}")

        if results.total_time > MetricsValidator.MAX_EXECUTION_TIME:
            errors.append(f"Total time {results.total_time} exceeds maximum {MetricsValidator.MAX_EXECUTION_TIME}")

        # Stream validation
        if results.num_streams < 1:
            errors.append(f"Number of streams {results.num_streams} must be at least 1")

        if results.num_streams > 1000:
            errors.append(f"Number of streams {results.num_streams} exceeds reasonable maximum of 1000")

        # Test completeness validation
        failed_tests = [r for r in results.test_results if not r.success]
        if failed_tests:
            errors.append(
                f"Throughput test has {len(failed_tests)} failed queries: {[r.query_name for r in failed_tests]}"
            )

        # Query execution time validation
        for result in results.test_results:
            if result.execution_time < MetricsValidator.MIN_EXECUTION_TIME:
                errors.append(f"Query {result.query_name} execution time {result.execution_time} is too low")
            if result.execution_time > MetricsValidator.MAX_EXECUTION_TIME:
                errors.append(f"Query {result.query_name} execution time {result.execution_time} is too high")

        # Stream distribution validation
        stream_ids = [r.stream_id for r in results.test_results if r.stream_id is not None]
        if stream_ids:
            unique_streams = set(stream_ids)
            if len(unique_streams) != results.num_streams:
                errors.append(
                    f"Stream IDs don't match num_streams: expected {results.num_streams}, found {len(unique_streams)}"
                )

        return errors

    @staticmethod
    def validate_metrics_result(result: MetricsResult) -> list[str]:
        """Validate calculated metrics result."""
        errors = []

        if result.power_at_size is not None:
            if result.power_at_size <= 0:
                errors.append(f"Power@Size {result.power_at_size} must be positive")
            if result.power_at_size > 1e12:  # Sanity check
                errors.append(f"Power@Size {result.power_at_size} is unreasonably high")

        if result.throughput_at_size is not None:
            if result.throughput_at_size <= 0:
                errors.append(f"Throughput@Size {result.throughput_at_size} must be positive")
            if result.throughput_at_size > 1e12:  # Sanity check
                errors.append(f"Throughput@Size {result.throughput_at_size} is unreasonably high")

        if result.composite_metric is not None:
            if result.composite_metric <= 0:
                errors.append(f"Composite metric {result.composite_metric} must be positive")
            if result.composite_metric > 1e12:  # Sanity check
                errors.append(f"Composite metric {result.composite_metric} is unreasonably high")

        return errors


class PowerMetrics:
    """Calculates Power@Size metrics according to TPC specifications."""

    @staticmethod
    def calculate_power_at_size(results: PowerTestResults) -> tuple[float, list[str]]:
        """
        Calculate Power@Size metric.

        Formula: Power@Size = 3600 × Scale_Factor / geometric_mean(query_times)

        Args:
            results: PowerTestResults containing test execution data

        Returns:
            Tuple of (power_at_size, validation_errors)
        """
        # Validate input
        validation_errors = MetricsValidator.validate_power_test_results(results)
        if validation_errors:
            return 0.0, validation_errors

        exec_times = [r.execution_time for r in results.test_results if r.success and r.execution_time > 0]
        if not exec_times:
            validation_errors.append("No valid query execution times for Power@Size calculation")
            return 0.0, validation_errors

        geometric_mean = statistics.geometric_mean(exec_times)
        power_at_size = (3600.0 * results.scale_factor) / geometric_mean

        # Additional validation on result
        if power_at_size <= 0:
            validation_errors.append(f"Calculated Power@Size {power_at_size} is not positive")

        return power_at_size, validation_errors

    @staticmethod
    def calculate_geometric_mean_time(
        results: PowerTestResults,
    ) -> tuple[float, list[str]]:
        """
        Calculate geometric mean of individual query execution times.

        This is used for additional analysis and validation.

        Args:
            results: PowerTestResults containing test execution data

        Returns:
            Tuple of (geometric_mean_time, validation_errors)
        """
        validation_errors = []

        # Extract successful query times
        successful_results = [r for r in results.test_results if r.success]

        if not successful_results:
            validation_errors.append("No successful queries found for geometric mean calculation")
            return 0.0, validation_errors

        execution_times = [r.execution_time for r in successful_results]

        # Check for zero or negative times
        if any(t <= 0 for t in execution_times):
            validation_errors.append("Cannot calculate geometric mean with zero or negative execution times")
            return 0.0, validation_errors

        # Calculate geometric mean
        try:
            geometric_mean = statistics.geometric_mean(execution_times)
        except statistics.StatisticsError as e:
            validation_errors.append(f"Error calculating geometric mean: {e}")
            return 0.0, validation_errors

        return geometric_mean, validation_errors


class ThroughputMetrics:
    """Calculates Throughput@Size metrics according to TPC specifications."""

    @staticmethod
    def calculate_throughput_at_size(
        results: ThroughputTestResults,
    ) -> tuple[float, list[str]]:
        """
        Calculate Throughput@Size metric.

        Formula: Throughput@Size = Num_Streams × 3600 × Scale_Factor / Throughput_Test_Time

        Args:
            results: ThroughputTestResults containing test execution data

        Returns:
            Tuple of (throughput_at_size, validation_errors)
        """
        # Validate input
        validation_errors = MetricsValidator.validate_throughput_test_results(results)
        if validation_errors:
            return 0.0, validation_errors

        # Calculate Throughput@Size
        throughput_at_size = (results.num_streams * 3600.0 * results.scale_factor) / results.total_time

        # Additional validation on result
        if throughput_at_size <= 0:
            validation_errors.append(f"Calculated Throughput@Size {throughput_at_size} is not positive")

        return throughput_at_size, validation_errors

    @staticmethod
    def calculate_stream_efficiency(
        results: ThroughputTestResults,
    ) -> tuple[dict[int, float], list[str]]:
        """
        Calculate efficiency metrics per stream.

        Returns execution rate (queries per second) for each stream.

        Args:
            results: ThroughputTestResults containing test execution data

        Returns:
            Tuple of (stream_efficiency_dict, validation_errors)
        """
        validation_errors = []
        stream_efficiency = {}

        # Group results by stream
        stream_results = {}
        for result in results.test_results:
            if result.stream_id is not None:
                if result.stream_id not in stream_results:
                    stream_results[result.stream_id] = []
                stream_results[result.stream_id].append(result)

        # Calculate efficiency for each stream
        for stream_id, stream_queries in stream_results.items():
            successful_queries = [r for r in stream_queries if r.success]

            if not successful_queries:
                validation_errors.append(f"Stream {stream_id} has no successful queries")
                continue

            total_stream_time = sum(r.execution_time for r in successful_queries)
            queries_per_second = len(successful_queries) / total_stream_time if total_stream_time > 0 else 0

            stream_efficiency[stream_id] = queries_per_second

        return stream_efficiency, validation_errors


class CompositeMetrics:
    """Calculates composite TPC metrics (QphH@Size, QphDS@Size)."""

    @staticmethod
    def calculate_qphh_at_size(power_at_size: float, throughput_at_size: float) -> tuple[float, list[str]]:
        """
        Calculate QphH@Size metric for TPC-H.

        Formula: QphH@Size = sqrt(Power@Size × Throughput@Size)

        Args:
            power_at_size: Power@Size metric value
            throughput_at_size: Throughput@Size metric value

        Returns:
            Tuple of (qphh_at_size, validation_errors)
        """
        validation_errors = []

        # Validate inputs
        if power_at_size <= 0:
            validation_errors.append(f"Power@Size {power_at_size} must be positive")

        if throughput_at_size <= 0:
            validation_errors.append(f"Throughput@Size {throughput_at_size} must be positive")

        if validation_errors:
            return 0.0, validation_errors

        # Calculate QphH@Size
        qphh_at_size = math.sqrt(power_at_size * throughput_at_size)

        return qphh_at_size, validation_errors

    @staticmethod
    def calculate_qphds_at_size(power_at_size: float, throughput_at_size: float) -> tuple[float, list[str]]:
        """
        Calculate QphDS@Size metric for TPC-DS.

        Formula: QphDS@Size = sqrt(Power@Size × Throughput@Size)

        Args:
            power_at_size: Power@Size metric value
            throughput_at_size: Throughput@Size metric value

        Returns:
            Tuple of (qphds_at_size, validation_errors)
        """
        validation_errors = []

        # Validate inputs
        if power_at_size <= 0:
            validation_errors.append(f"Power@Size {power_at_size} must be positive")

        if throughput_at_size <= 0:
            validation_errors.append(f"Throughput@Size {throughput_at_size} must be positive")

        if validation_errors:
            return 0.0, validation_errors

        # Calculate QphDS@Size
        qphds_at_size = math.sqrt(power_at_size * throughput_at_size)

        return qphds_at_size, validation_errors


class StatisticalAnalyzer:
    """Provides statistical analysis utilities for TPC test results."""

    @staticmethod
    def calculate_execution_statistics(results: list[QueryResult]) -> dict[str, float]:
        """
        Calculate statistical measures for query execution times.

        Args:
            results: List of QueryResult objects

        Returns:
            Dictionary containing statistical measures
        """
        successful_results = [r for r in results if r.success]

        if not successful_results:
            return {
                "count": 0,
                "mean": 0.0,
                "median": 0.0,
                "std_dev": 0.0,
                "min": 0.0,
                "max": 0.0,
                "geometric_mean": 0.0,
                "coefficient_of_variation": 0.0,
            }

        execution_times = [r.execution_time for r in successful_results]

        stats = {
            "count": len(execution_times),
            "mean": statistics.mean(execution_times),
            "median": statistics.median(execution_times),
            "min": min(execution_times),
            "max": max(execution_times),
        }

        # Standard deviation
        if len(execution_times) > 1:
            stats["std_dev"] = statistics.stdev(execution_times)
        else:
            stats["std_dev"] = 0.0

        # Geometric mean
        if all(t > 0 for t in execution_times):
            stats["geometric_mean"] = statistics.geometric_mean(execution_times)
        else:
            stats["geometric_mean"] = 0.0

        # Coefficient of variation
        if stats["mean"] > 0:
            stats["coefficient_of_variation"] = stats["std_dev"] / stats["mean"]
        else:
            stats["coefficient_of_variation"] = 0.0

        return stats

    @staticmethod
    def detect_outliers(results: list[QueryResult], threshold: float = 2.0) -> list[QueryResult]:
        """
        Detect outlier query execution times using z-score method.

        Args:
            results: List of QueryResult objects
            threshold: Z-score threshold for outlier detection

        Returns:
            List of QueryResult objects identified as outliers
        """
        successful_results = [r for r in results if r.success]

        if len(successful_results) < 3:
            return []  # Need at least 3 points for meaningful outlier detection

        execution_times = [r.execution_time for r in successful_results]
        mean_time = statistics.mean(execution_times)

        if len(execution_times) > 1:
            std_dev = statistics.stdev(execution_times)
        else:
            return []

        if std_dev == 0:
            return []  # No variation, no outliers

        outliers = []
        for result in successful_results:
            z_score = abs(result.execution_time - mean_time) / std_dev
            if z_score > threshold:
                outliers.append(result)

        return outliers

    @staticmethod
    def calculate_confidence_interval(
        results: list[QueryResult], confidence_level: float = 0.95
    ) -> tuple[float, float]:
        """
        Calculate confidence interval for mean execution time.

        Args:
            results: List of QueryResult objects
            confidence_level: Confidence level (default: 0.95 for 95% CI)

        Returns:
            Tuple of (lower_bound, upper_bound)
        """
        successful_results = [r for r in results if r.success]

        if len(successful_results) < 2:
            return (0.0, 0.0)

        execution_times = [r.execution_time for r in successful_results]
        mean_time = statistics.mean(execution_times)
        std_dev = statistics.stdev(execution_times)
        n = len(execution_times)

        # For large samples, use normal distribution approximation
        # For small samples, this is an approximation (should use t-distribution)
        if confidence_level == 0.95:
            z_score = 1.96
        elif confidence_level == 0.99:
            z_score = 2.576
        else:
            # Approximate z-score for arbitrary confidence level
            z_score = 1.96  # Default to 95% if not standard

        margin_of_error = z_score * (std_dev / math.sqrt(n))

        return (mean_time - margin_of_error, mean_time + margin_of_error)


class MetricsReporter:
    """Formats and reports TPC metrics results."""

    @staticmethod
    def format_metrics_report(result: MetricsResult, _include_details: bool = True) -> str:
        """
        Format a comprehensive metrics report.

        Args:
            result: MetricsResult containing calculated metrics
            include_details: Whether to include detailed information

        Returns:
            Formatted string report
        """
        report_lines = []

        # Header
        benchmark_name = result.benchmark_type.value if result.benchmark_type else "Unknown"
        report_lines.append(f"TPC {benchmark_name} Metrics Report")
        report_lines.append("=" * 50)

        # Scale factor
        if result.scale_factor is not None:
            report_lines.append(f"Scale Factor: {result.scale_factor}")

        # Primary metrics
        if result.power_at_size is not None:
            report_lines.append(f"Power@Size: {result.power_at_size:,.2f}")

        if result.throughput_at_size is not None:
            report_lines.append(f"Throughput@Size: {result.throughput_at_size:,.2f}")

        if result.composite_metric is not None:
            metric_name = "QphH@Size" if result.benchmark_type == BenchmarkType.TPCH else "QphDS@Size"
            report_lines.append(f"{metric_name}: {result.composite_metric:,.2f}")

        # Validation errors
        if result.validation_errors:
            report_lines.append("")
            report_lines.append("Validation Errors:")
            for error in result.validation_errors:
                report_lines.append(f"  - {error}")

        return "\n".join(report_lines)

    @staticmethod
    def format_statistical_report(stats: dict[str, float]) -> str:
        """
        Format a statistical analysis report.

        Args:
            stats: Dictionary of statistical measures

        Returns:
            Formatted string report
        """
        report_lines = []

        report_lines.append("Statistical Analysis")
        report_lines.append("-" * 30)
        report_lines.append(f"Query Count: {stats['count']}")
        report_lines.append(f"Mean Time: {stats['mean']:.4f}s")
        report_lines.append(f"Median Time: {stats['median']:.4f}s")
        report_lines.append(f"Std Deviation: {stats['std_dev']:.4f}s")
        report_lines.append(f"Min Time: {stats['min']:.4f}s")
        report_lines.append(f"Max Time: {stats['max']:.4f}s")
        report_lines.append(f"Geometric Mean: {stats['geometric_mean']:.4f}s")
        report_lines.append(f"Coefficient of Variation: {stats['coefficient_of_variation']:.4f}")

        return "\n".join(report_lines)


class TPCMetricsCalculator:
    """Main TPC metrics calculation engine."""

    def __init__(self) -> None:
        self.validator = MetricsValidator()
        self.power_metrics = PowerMetrics()
        self.throughput_metrics = ThroughputMetrics()
        self.composite_metrics = CompositeMetrics()
        self.statistical_analyzer = StatisticalAnalyzer()
        self.reporter = MetricsReporter()

    def calculate_full_metrics(
        self, power_results: PowerTestResults, throughput_results: ThroughputTestResults
    ) -> MetricsResult:
        """
        Calculate complete TPC metrics from power and throughput test results.

        Args:
            power_results: Results from power test execution
            throughput_results: Results from throughput test execution

        Returns:
            MetricsResult containing all calculated metrics
        """
        result = MetricsResult()
        all_errors = []

        # Validate benchmark type consistency
        if power_results.benchmark_type != throughput_results.benchmark_type:
            all_errors.append(
                f"Benchmark type mismatch: power={power_results.benchmark_type}, throughput={throughput_results.benchmark_type}"
            )

        # Validate scale factor consistency
        if power_results.scale_factor != throughput_results.scale_factor:
            all_errors.append(
                f"Scale factor mismatch: power={power_results.scale_factor}, throughput={throughput_results.scale_factor}"
            )

        # Calculate Power@Size
        power_at_size, power_errors = self.power_metrics.calculate_power_at_size(power_results)
        all_errors.extend(power_errors)

        # Calculate Throughput@Size
        throughput_at_size, throughput_errors = self.throughput_metrics.calculate_throughput_at_size(throughput_results)
        all_errors.extend(throughput_errors)

        # Calculate composite metric
        composite_metric = 0.0
        if not power_errors and not throughput_errors:
            if power_results.benchmark_type == BenchmarkType.TPCH:
                composite_metric, composite_errors = self.composite_metrics.calculate_qphh_at_size(
                    power_at_size, throughput_at_size
                )
            elif power_results.benchmark_type == BenchmarkType.TPCDS:
                composite_metric, composite_errors = self.composite_metrics.calculate_qphds_at_size(
                    power_at_size, throughput_at_size
                )
            else:
                composite_errors = [f"Unsupported benchmark type: {power_results.benchmark_type}"]

            all_errors.extend(composite_errors)

        # Populate result
        result.power_at_size = power_at_size if not power_errors else None
        result.throughput_at_size = throughput_at_size if not throughput_errors else None
        result.composite_metric = composite_metric if not all_errors else None
        result.scale_factor = power_results.scale_factor
        result.benchmark_type = power_results.benchmark_type
        result.validation_errors = all_errors

        # Final validation
        final_errors = self.validator.validate_metrics_result(result)
        result.validation_errors.extend(final_errors)

        return result

    def calculate_power_only_metrics(self, power_results: PowerTestResults) -> MetricsResult:
        """
        Calculate power-only metrics when throughput test is not available.

        Args:
            power_results: Results from power test execution

        Returns:
            MetricsResult containing power metrics only
        """
        result = MetricsResult()

        # Calculate Power@Size
        power_at_size, power_errors = self.power_metrics.calculate_power_at_size(power_results)

        # Populate result
        result.power_at_size = power_at_size if not power_errors else None
        result.scale_factor = power_results.scale_factor
        result.benchmark_type = power_results.benchmark_type
        result.validation_errors = power_errors

        # Final validation
        final_errors = self.validator.validate_metrics_result(result)
        result.validation_errors.extend(final_errors)

        return result

    def calculate_throughput_only_metrics(self, throughput_results: ThroughputTestResults) -> MetricsResult:
        """
        Calculate throughput-only metrics when power test is not available.

        Args:
            throughput_results: Results from throughput test execution

        Returns:
            MetricsResult containing throughput metrics only
        """
        result = MetricsResult()

        # Calculate Throughput@Size
        throughput_at_size, throughput_errors = self.throughput_metrics.calculate_throughput_at_size(throughput_results)

        # Populate result
        result.throughput_at_size = throughput_at_size if not throughput_errors else None
        result.scale_factor = throughput_results.scale_factor
        result.benchmark_type = throughput_results.benchmark_type
        result.validation_errors = throughput_errors

        # Final validation
        final_errors = self.validator.validate_metrics_result(result)
        result.validation_errors.extend(final_errors)

        return result

    def analyze_test_results(self, results: list[QueryResult]) -> dict[str, Any]:
        """
        Perform comprehensive statistical analysis of test results.

        Args:
            results: List of QueryResult objects

        Returns:
            Dictionary containing statistical analysis results
        """
        analysis = {}

        # Basic statistics
        analysis["statistics"] = self.statistical_analyzer.calculate_execution_statistics(results)

        # Outlier detection
        analysis["outliers"] = self.statistical_analyzer.detect_outliers(results)

        # Confidence interval
        analysis["confidence_interval_95"] = self.statistical_analyzer.calculate_confidence_interval(results, 0.95)

        # Success rate
        successful_count = len([r for r in results if r.success])
        analysis["success_rate"] = successful_count / len(results) if results else 0.0

        # Failed queries
        failed_queries = [r for r in results if not r.success]
        analysis["failed_queries"] = [{"query": r.query_name, "error": r.error_message} for r in failed_queries]

        return analysis

    def generate_detailed_report(
        self,
        power_results: Optional[PowerTestResults] = None,
        throughput_results: Optional[ThroughputTestResults] = None,
        include_statistical_analysis: bool = True,
    ) -> str:
        """
        Generate a comprehensive TPC metrics report.

        Args:
            power_results: Optional power test results
            throughput_results: Optional throughput test results
            include_statistical_analysis: Whether to include statistical analysis

        Returns:
            Formatted comprehensive report string
        """
        report_sections = []

        # Calculate metrics
        if power_results and throughput_results:
            metrics_result = self.calculate_full_metrics(power_results, throughput_results)
        elif power_results:
            metrics_result = self.calculate_power_only_metrics(power_results)
        elif throughput_results:
            metrics_result = self.calculate_throughput_only_metrics(throughput_results)
        else:
            return "No test results provided for metrics calculation."

        # Main metrics report
        report_sections.append(self.reporter.format_metrics_report(metrics_result))

        # Statistical analysis
        if include_statistical_analysis:
            if power_results:
                report_sections.append("\nPower Test Statistical Analysis:")
                power_analysis = self.analyze_test_results(power_results.test_results)
                report_sections.append(self.reporter.format_statistical_report(power_analysis["statistics"]))

                if power_analysis["outliers"]:
                    report_sections.append(f"\nPower Test Outliers ({len(power_analysis['outliers'])} found):")
                    for outlier in power_analysis["outliers"][:5]:  # Show first 5
                        report_sections.append(f"  - {outlier.query_name}: {outlier.execution_time:.4f}s")

            if throughput_results:
                report_sections.append("\nThroughput Test Statistical Analysis:")
                throughput_analysis = self.analyze_test_results(throughput_results.test_results)
                report_sections.append(self.reporter.format_statistical_report(throughput_analysis["statistics"]))

                if throughput_analysis["outliers"]:
                    report_sections.append(
                        f"\nThroughput Test Outliers ({len(throughput_analysis['outliers'])} found):"
                    )
                    for outlier in throughput_analysis["outliers"][:5]:  # Show first 5
                        report_sections.append(f"  - {outlier.query_name}: {outlier.execution_time:.4f}s")

        return "\n".join(report_sections)
