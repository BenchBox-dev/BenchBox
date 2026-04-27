"""TPC-H benchmark reporting and validation module.

This module provides comprehensive reporting capabilities for TPC-H benchmark results,
including detailed analysis, validation against TPC-H specification requirements,
and generation of certification-ready reports.

The reporting system supports:
- Detailed performance analysis and metrics
- TPC-H specification compliance validation
- Certification-ready report generation
- Performance trend analysis
- Result comparison and regression detection
- Audit trail generation

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import csv
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from benchbox.core.tpch.official_benchmark import TPCHOfficialBenchmarkResult


@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics for TPC-H benchmark."""

    qphh_at_size: float
    power_at_size: float
    throughput_at_size: float
    total_execution_time: float
    average_query_time: float
    median_query_time: float
    query_time_std_dev: float
    throughput_efficiency: float
    power_efficiency: float
    scale_factor: float

    def __post_init__(self) -> None:
        """Calculate derived metrics."""
        if self.qphh_at_size > 0:
            self.throughput_efficiency = self.throughput_at_size / self.qphh_at_size
            self.power_efficiency = self.power_at_size / self.qphh_at_size


@dataclass
class ValidationResult:
    """TPC-H specification validation result."""

    compliant: bool
    certification_ready: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class ComparisonResult:
    """Result comparison between benchmark runs."""

    baseline_qphh: float
    current_qphh: float
    performance_change: float
    relative_change: float
    significant_change: bool
    query_level_changes: dict[int, float] = field(default_factory=dict)


class TPCHReportGenerator:
    """Comprehensive TPC-H benchmark report generator.

    This class provides detailed reporting capabilities for TPC-H benchmark results,
    including performance analysis, validation, and certification-ready reports.
    """

    def __init__(self, output_dir: Optional[Union[str, Path]] = None) -> None:
        """Initialize the report generator.

        Args:
            output_dir: Directory for generated reports
        """
        self.output_dir = Path(output_dir) if output_dir else Path.cwd()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_detailed_report(
        self,
        result: TPCHOfficialBenchmarkResult,
        report_title: str = "TPC-H Benchmark Report",
        include_detailed_analysis: bool = True,
        include_certification_info: bool = True,
    ) -> Path:
        """Generate a comprehensive TPC-H benchmark report.

        Args:
            result: QphH benchmark result
            report_title: Title for the report
            include_detailed_analysis: Include detailed performance analysis
            include_certification_info: Include certification information

        Returns:
            Path to generated report file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = self.output_dir / f"tpch_comprehensive_report_{timestamp}.html"

        # Calculate performance metrics
        metrics = self._calculate_performance_metrics(result)

        # Perform validation
        validation = self._validate_result(result)

        # Generate HTML report
        html_content = self._generate_html_report(
            result,
            metrics,
            validation,
            report_title,
            include_detailed_analysis,
            include_certification_info,
        )

        with open(report_file, "w", encoding="utf-8") as f:
            f.write(html_content)

        return report_file

    def generate_certification_report(self, result: TPCHOfficialBenchmarkResult) -> Path:
        """Generate a certification-ready TPC-H report.

        Args:
            result: QphH benchmark result

        Returns:
            Path to generated certification report
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = self.output_dir / f"tpch_certification_report_{timestamp}.txt"

        validation = self._validate_result(result)
        metrics = self._calculate_performance_metrics(result)

        with open(report_file, "w", encoding="utf-8") as f:
            f.write("TPC-H BENCHMARK CERTIFICATION REPORT\n")
            f.write("=" * 60 + "\n\n")

            # Executive Summary
            f.write("EXECUTIVE SUMMARY\n")
            f.write("-" * 20 + "\n")
            f.write(f"QphH@Size: {result.qphh_at_size:.2f}\n")
            f.write(f"Scale Factor: {result.scale_factor}\n")
            f.write(f"Certification Ready: {'YES' if validation.certification_ready else 'NO'}\n")
            f.write(f"Specification Compliant: {'YES' if validation.compliant else 'NO'}\n\n")

            # Test Results
            f.write("TEST RESULTS\n")
            f.write("-" * 15 + "\n")
            f.write("Power Test:\n")
            f.write(f"  Execution Time: {result.power_test.total_time:.2f} seconds\n")
            f.write(f"  Power@Size: {result.power_test.power_at_size:.2f}\n")
            f.write(f"  Success: {'YES' if result.power_test.success else 'NO'}\n\n")

            f.write("Throughput Test:\n")
            f.write(f"  Execution Time: {result.throughput_test.total_time:.2f} seconds\n")
            f.write(f"  Throughput@Size: {result.throughput_test.throughput_at_size:.2f}\n")
            f.write(f"  Number of Streams: {result.throughput_test.num_streams}\n")
            f.write(f"  Success: {'YES' if result.throughput_test.success else 'NO'}\n\n")

            # Detailed Metrics
            f.write("DETAILED METRICS\n")
            f.write("-" * 18 + "\n")
            f.write(f"Average Query Time: {metrics.average_query_time:.3f} seconds\n")
            f.write(f"Median Query Time: {metrics.median_query_time:.3f} seconds\n")
            f.write(f"Query Time Std Dev: {metrics.query_time_std_dev:.3f} seconds\n")
            f.write(f"Total Execution Time: {metrics.total_execution_time:.2f} seconds\n\n")

            # Validation Results
            f.write("VALIDATION RESULTS\n")
            f.write("-" * 20 + "\n")
            if validation.issues:
                f.write("Issues Found:\n")
                for issue in validation.issues:
                    f.write(f"  - {issue}\n")
                f.write("\n")

            if validation.warnings:
                f.write("Warnings:\n")
                for warning in validation.warnings:
                    f.write(f"  - {warning}\n")
                f.write("\n")

            if validation.recommendations:
                f.write("Recommendations:\n")
                for rec in validation.recommendations:
                    f.write(f"  - {rec}\n")
                f.write("\n")

            # Query-Level Details
            f.write("QUERY-LEVEL PERFORMANCE\n")
            f.write("-" * 25 + "\n")
            f.write("Query ID | Execution Time (s) | Relative Performance\n")
            f.write("-" * 55 + "\n")

            for query_id, query_time in sorted(result.power_test.query_times.items()):
                relative_perf = query_time / metrics.average_query_time
                f.write(f"{query_id:8} | {query_time:16.3f} | {relative_perf:16.2f}\n")

            # Certification Statement
            f.write("\nCERTIFICATION STATEMENT\n")
            f.write("-" * 25 + "\n")
            if validation.certification_ready:
                f.write("This benchmark result meets TPC-H specification requirements\n")
                f.write("and is ready for certification submission.\n")
            else:
                f.write("This benchmark result does NOT meet all TPC-H specification\n")
                f.write("requirements and is NOT ready for certification.\n")
                f.write("Please address the issues listed above.\n")

        return report_file

    def generate_performance_csv(self, result: TPCHOfficialBenchmarkResult) -> Path:
        """Generate CSV file with detailed performance data.

        Args:
            result: QphH benchmark result

        Returns:
            Path to generated CSV file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_file = self.output_dir / f"tpch_performance_data_{timestamp}.csv"

        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            # Write header
            writer.writerow(
                [
                    "Query_ID",
                    "Execution_Time_Seconds",
                    "Relative_Performance",
                    "Query_Type",
                    "Complexity_Score",
                ]
            )

            # Calculate average for relative performance
            avg_time = statistics.mean(result.power_test.query_times.values())

            # Write query data
            for query_id, query_time in sorted(result.power_test.query_times.items()):
                relative_perf = query_time / avg_time
                query_type = self._classify_query_type(query_id)
                complexity = self._calculate_query_complexity(query_id)

                writer.writerow([query_id, query_time, relative_perf, query_type, complexity])

            # Write summary data
            writer.writerow([])
            writer.writerow(["SUMMARY"])
            writer.writerow(["Metric", "Value"])
            writer.writerow(["QphH@Size", result.qphh_at_size])
            writer.writerow(["Power@Size", result.power_test.power_at_size])
            writer.writerow(["Throughput@Size", result.throughput_test.throughput_at_size])
            writer.writerow(["Scale_Factor", result.scale_factor])
            writer.writerow(["Total_Time", result.total_benchmark_time])

        return csv_file

    def compare_results(
        self,
        baseline_result: TPCHOfficialBenchmarkResult,
        current_result: TPCHOfficialBenchmarkResult,
        significance_threshold: float = 0.05,
    ) -> ComparisonResult:
        """Compare two benchmark results for performance changes.

        Args:
            baseline_result: Baseline benchmark result
            current_result: Current benchmark result
            significance_threshold: Threshold for significant change detection

        Returns:
            ComparisonResult with detailed comparison analysis
        """
        # Calculate overall performance change
        baseline_qphh = baseline_result.qphh_at_size
        current_qphh = current_result.qphh_at_size

        if baseline_qphh > 0:
            performance_change = current_qphh - baseline_qphh
            relative_change = performance_change / baseline_qphh
            significant_change = abs(relative_change) > significance_threshold
        else:
            performance_change = 0.0
            relative_change = 0.0
            significant_change = False

        # Calculate query-level changes
        query_changes = {}
        for query_id in range(1, 23):
            baseline_time = baseline_result.power_test.query_times.get(query_id, 0)
            current_time = current_result.power_test.query_times.get(query_id, 0)

            if baseline_time > 0:
                change = (current_time - baseline_time) / baseline_time
                query_changes[query_id] = change

        return ComparisonResult(
            baseline_qphh=baseline_qphh,
            current_qphh=current_qphh,
            performance_change=performance_change,
            relative_change=relative_change,
            significant_change=significant_change,
            query_level_changes=query_changes,
        )

    def generate_comparison_report(
        self,
        baseline_result: TPCHOfficialBenchmarkResult,
        current_result: TPCHOfficialBenchmarkResult,
        report_title: str = "TPC-H Performance Comparison",
    ) -> Path:
        """Generate a comparison report between two benchmark results.

        Args:
            baseline_result: Baseline benchmark result
            current_result: Current benchmark result
            report_title: Title for the comparison report

        Returns:
            Path to generated comparison report
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = self.output_dir / f"tpch_comparison_report_{timestamp}.html"

        comparison = self.compare_results(baseline_result, current_result)

        # Generate HTML comparison report
        html_content = self._generate_comparison_html(baseline_result, current_result, comparison, report_title)

        with open(report_file, "w", encoding="utf-8") as f:
            f.write(html_content)

        return report_file

    def _calculate_performance_metrics(self, result: TPCHOfficialBenchmarkResult) -> PerformanceMetrics:
        """Calculate comprehensive performance metrics."""
        query_times = list(result.power_test.query_times.values())

        if not query_times:
            # Return default metrics if no query times available
            return PerformanceMetrics(
                qphh_at_size=result.qphh_at_size,
                power_at_size=result.power_test.power_at_size,
                throughput_at_size=result.throughput_test.throughput_at_size,
                total_execution_time=result.total_benchmark_time,
                average_query_time=0.0,
                median_query_time=0.0,
                query_time_std_dev=0.0,
                throughput_efficiency=0.0,
                power_efficiency=0.0,
                scale_factor=result.scale_factor,
            )

        avg_query_time = statistics.mean(query_times)
        median_query_time = statistics.median(query_times)
        std_dev = statistics.stdev(query_times) if len(query_times) > 1 else 0.0

        return PerformanceMetrics(
            qphh_at_size=result.qphh_at_size,
            power_at_size=result.power_test.power_at_size,
            throughput_at_size=result.throughput_test.throughput_at_size,
            total_execution_time=result.total_benchmark_time,
            average_query_time=avg_query_time,
            median_query_time=median_query_time,
            query_time_std_dev=std_dev,
            throughput_efficiency=0.0,  # Will be calculated in __post_init__
            power_efficiency=0.0,  # Will be calculated in __post_init__
            scale_factor=result.scale_factor,
        )

    def _validate_result(self, result: TPCHOfficialBenchmarkResult) -> ValidationResult:
        """Validate benchmark result against TPC-H specification."""
        issues = self._check_basic_requirements(result)
        warnings = self._check_execution_warnings(result)
        recommendations = self._generate_recommendations(result)

        compliant = len(issues) == 0
        certification_ready = compliant and len(warnings) == 0

        return ValidationResult(
            compliant=compliant,
            certification_ready=certification_ready,
            issues=issues,
            warnings=warnings,
            recommendations=recommendations,
        )

    def _check_basic_requirements(self, result: TPCHOfficialBenchmarkResult) -> list[str]:
        """Check basic TPC-H compliance requirements."""
        issues = []
        if not result.success:
            issues.append("Benchmark did not complete successfully")
        if result.qphh_at_size <= 0:
            issues.append("QphH@Size must be positive")
        if not result.power_test.success:
            issues.append("Power Test failed")
        elif len(result.power_test.query_times) != 22:
            issues.append(f"Power Test must execute all 22 queries, got {len(result.power_test.query_times)}")
        if not result.throughput_test.success:
            issues.append("Throughput Test failed")
        elif result.throughput_test.num_streams < 1:
            issues.append("Throughput Test must have at least 1 stream")
        return issues

    def _check_execution_warnings(self, result: TPCHOfficialBenchmarkResult) -> list[str]:
        """Check for execution time warnings and query outliers."""
        warnings = []
        if result.power_test.total_time < 10:
            warnings.append("Power Test execution time seems unusually fast")
        if result.throughput_test.total_time < 10:
            warnings.append("Throughput Test execution time seems unusually fast")

        # Check for query time outliers
        if result.power_test.query_times:
            query_times = list(result.power_test.query_times.values())
            avg_time = statistics.mean(query_times)
            for query_id, query_time in result.power_test.query_times.items():
                if query_time > avg_time * 10:
                    warnings.append(f"Query {query_id} took unusually long: {query_time:.2f}s")
                elif query_time < avg_time * 0.01:
                    warnings.append(f"Query {query_id} completed unusually fast: {query_time:.2f}s")
        return warnings

    def _generate_recommendations(self, result: TPCHOfficialBenchmarkResult) -> list[str]:
        """Generate improvement recommendations."""
        recommendations = []
        if result.throughput_test.num_streams < 2:
            recommendations.append("Consider using more streams in Throughput Test for better performance measurement")
        if result.scale_factor < 1:
            recommendations.append("Consider using scale factor >= 1 for meaningful results")
        return recommendations

    def _classify_query_type(self, query_id: int) -> str:
        """Classify query type based on TPC-H query characteristics."""
        # Simplified classification based on TPC-H query patterns
        if query_id in [1, 6, 10, 14, 15, 19]:
            return "Pricing_Summary"
        elif query_id in [2, 4, 17, 20]:
            return "Minimum_Cost"
        elif query_id in [3, 5, 7, 8, 16, 21]:
            return "Shipping_Priority"
        elif query_id in [9, 11, 22]:
            return "Product_Type"
        elif query_id in [12, 13, 18]:
            return "Order_Priority"
        else:
            return "Mixed"

    def _calculate_query_complexity(self, query_id: int) -> int:
        """Calculate query complexity score (1-10) based on TPC-H query characteristics."""
        # Simplified complexity scoring based on typical TPC-H query patterns
        complexity_map = {
            1: 3,
            2: 7,
            3: 4,
            4: 5,
            5: 6,
            6: 2,
            7: 4,
            8: 5,
            9: 8,
            10: 4,
            11: 3,
            12: 3,
            13: 4,
            14: 3,
            15: 5,
            16: 4,
            17: 6,
            18: 5,
            19: 4,
            20: 7,
            21: 8,
            22: 9,
        }
        return complexity_map.get(query_id, 5)

    def _generate_html_report(
        self,
        result: TPCHOfficialBenchmarkResult,
        metrics: PerformanceMetrics,
        validation: ValidationResult,
        title: str,
        include_detailed_analysis: bool,
        include_certification_info: bool,
    ) -> str:
        """Generate HTML report content."""
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ background-color: #f0f0f0; padding: 20px; border-radius: 5px; }}
        .section {{ margin: 20px 0; }}
        .metrics {{ display: flex; justify-content: space-around; }}
        .metric {{ text-align: center; background-color: #e8f4f8; padding: 15px; border-radius: 5px; }}
        .success {{ color: green; }}
        .warning {{ color: orange; }}
        .error {{ color: red; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{title}</h1>
        <p>Generated on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
    </div>

    <div class="section">
        <h2>Executive Summary</h2>
        <div class="metrics">
            <div class="metric">
                <h3>QphH@Size</h3>
                <p><strong>{result.qphh_at_size:.2f}</strong></p>
            </div>
            <div class="metric">
                <h3>Power@Size</h3>
                <p><strong>{result.power_test.power_at_size:.2f}</strong></p>
            </div>
            <div class="metric">
                <h3>Throughput@Size</h3>
                <p><strong>{result.throughput_test.throughput_at_size:.2f}</strong></p>
            </div>
            <div class="metric">
                <h3>Scale Factor</h3>
                <p><strong>{result.scale_factor}</strong></p>
            </div>
        </div>
    </div>

    <div class="section">
        <h2>Test Results</h2>
        <h3>Power Test</h3>
        <p>Execution Time: {result.power_test.total_time:.2f} seconds</p>
        <p>Status: <span class="{"success" if result.power_test.success else "error"}">
            {"SUCCESS" if result.power_test.success else "FAILED"}</span></p>

        <h3>Throughput Test</h3>
        <p>Execution Time: {result.throughput_test.total_time:.2f} seconds</p>
        <p>Number of Streams: {result.throughput_test.num_streams}</p>
        <p>Status: <span class="{"success" if result.throughput_test.success else "error"}">
            {"SUCCESS" if result.throughput_test.success else "FAILED"}</span></p>
    </div>
"""

        if include_detailed_analysis:
            html += f"""
    <div class="section">
        <h2>Detailed Analysis</h2>
        <p>Average Query Time: {metrics.average_query_time:.3f} seconds</p>
        <p>Median Query Time: {metrics.median_query_time:.3f} seconds</p>
        <p>Query Time Standard Deviation: {metrics.query_time_std_dev:.3f} seconds</p>

        <h3>Query Performance</h3>
        <table>
            <tr><th>Query ID</th><th>Execution Time (s)</th><th>Relative Performance</th></tr>
"""

            for query_id, query_time in sorted(result.power_test.query_times.items()):
                relative_perf = query_time / metrics.average_query_time if metrics.average_query_time > 0 else 0
                html += f"<tr><td>{query_id}</td><td>{query_time:.3f}</td><td>{relative_perf:.2f}</td></tr>"

            html += "</table></div>"

        if include_certification_info:
            html += f"""
    <div class="section">
        <h2>Certification Information</h2>
        <p>Specification Compliant: <span class="{"success" if validation.compliant else "error"}">
            {"YES" if validation.compliant else "NO"}</span></p>
        <p>Certification Ready: <span class="{"success" if validation.certification_ready else "warning"}">
            {"YES" if validation.certification_ready else "NO"}</span></p>
"""

            if validation.issues:
                html += "<h3>Issues</h3><ul>"
                for issue in validation.issues:
                    html += f"<li class='error'>{issue}</li>"
                html += "</ul>"

            if validation.warnings:
                html += "<h3>Warnings</h3><ul>"
                for warning in validation.warnings:
                    html += f"<li class='warning'>{warning}</li>"
                html += "</ul>"

            html += "</div>"

        html += """
</body>
</html>
"""
        return html

    def _generate_comparison_html(
        self,
        baseline_result: TPCHOfficialBenchmarkResult,
        current_result: TPCHOfficialBenchmarkResult,
        comparison: ComparisonResult,
        title: str,
    ) -> str:
        """Generate HTML comparison report."""
        change_class = "success" if comparison.relative_change > 0 else "error"

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ background-color: #f0f0f0; padding: 20px; border-radius: 5px; }}
        .section {{ margin: 20px 0; }}
        .comparison {{ display: flex; justify-content: space-around; }}
        .result {{ text-align: center; background-color: #e8f4f8; padding: 15px; border-radius: 5px; }}
        .improvement {{ color: green; }}
        .regression {{ color: red; }}
        .neutral {{ color: gray; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{title}</h1>
        <p>Generated on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
    </div>

    <div class="section">
        <h2>Performance Comparison</h2>
        <div class="comparison">
            <div class="result">
                <h3>Baseline</h3>
                <p>QphH@Size: <strong>{comparison.baseline_qphh:.2f}</strong></p>
            </div>
            <div class="result">
                <h3>Current</h3>
                <p>QphH@Size: <strong>{comparison.current_qphh:.2f}</strong></p>
            </div>
            <div class="result">
                <h3>Change</h3>
                <p class="{change_class}">
                    {comparison.performance_change:+.2f} ({comparison.relative_change:+.1%})
                </p>
            </div>
        </div>
    </div>

    <div class="section">
        <h2>Query-Level Changes</h2>
        <table>
            <tr><th>Query ID</th><th>Baseline Time (s)</th><th>Current Time (s)</th><th>Change (%)</th></tr>
"""

        for query_id in range(1, 23):
            baseline_time = baseline_result.power_test.query_times.get(query_id, 0)
            current_time = current_result.power_test.query_times.get(query_id, 0)
            change = comparison.query_level_changes.get(query_id, 0)

            change_class = "improvement" if change < 0 else "regression" if change > 0 else "neutral"

            html += f"""
            <tr>
                <td>{query_id}</td>
                <td>{baseline_time:.3f}</td>
                <td>{current_time:.3f}</td>
                <td class="{change_class}">{change:+.1%}</td>
            </tr>
"""

        html += """
        </table>
    </div>
</body>
</html>
"""
        return html
