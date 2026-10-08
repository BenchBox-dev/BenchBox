# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from typing import Any

from benchbox.utils import format_duration


def generate_report(result_data: dict[str, Any], verbosity: int = 0) -> str:
    report_lines = []
    benchmark_name = result_data.get("benchmark", "unknown").upper()

    report_lines.append(f"Benchmark: {benchmark_name}")
    report_lines.append(f"Scale Factor: {result_data.get('scale_factor', 'unknown')}")
    report_lines.append(f"Platform: {result_data.get('platform', 'unknown')}")

    success = result_data.get("success", False)
    report_lines.append(f"\nBenchmark Status: {'PASSED' if success else 'FAILED'}")

    if verbosity > 0 and "total_duration" in result_data:
        report_lines.append(f"Total Duration: {format_duration(result_data['total_duration'])}")
        if "schema_creation_time" in result_data:
            report_lines.append(f"Schema Creation: {format_duration(result_data['schema_creation_time'])}")
        if "data_loading_time" in result_data:
            report_lines.append(f"Data Loading: {format_duration(result_data['data_loading_time'])}")

    if "successful_queries" in result_data:
        report_lines.append(f"Queries: {result_data['successful_queries']}/{result_data['total_queries']} successful")

    if success and "total_execution_time" in result_data:
        report_lines.append(f"Query Execution Time: {format_duration(result_data['total_execution_time'])}")
        if "average_query_time" in result_data:
            report_lines.append(f"Average Query Time: {format_duration(result_data['average_query_time'])}")

    if success:
        report_lines.append(f"\n✅ {benchmark_name} benchmark completed!")
    else:
        report_lines.append(f"\n❌ {benchmark_name} benchmark failed.")

    return "\n".join(report_lines)
