#!/usr/bin/env python3
"""Demonstrate exporting benchmark results in multiple formats.

This example shows how to:
- Export results as JSON for programmatic processing
- Export results as CSV for spreadsheet analysis
- Export results as HTML for stakeholder reports
- Choose the right format for your audience

Usage:
    python features/export_formats.py

Key Concepts:
    - JSON: Machine-readable, preserves structure, ideal for automation
    - CSV: Human-readable, easy to import into Excel/Google Sheets
    - HTML: Formatted reports with visualizations for stakeholders
    - Format selection based on audience and use case
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

# Add parent directory to path for imports
_SCRIPT_DIR = Path(__file__).resolve().parent
_EXAMPLES_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_EXAMPLES_DIR))

from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH


def run_sample_benchmark():
    """Run a sample benchmark to generate results for export."""
    print("=" * 70)
    print("GENERATING SAMPLE RESULTS")
    print("=" * 70)
    print()
    print("Running TPC-H benchmark to generate results...")
    print()

    benchmark = TPCH(
        scale_factor=0.01,
        output_dir=Path("./benchmark_runs/features/export"),
        force_regenerate=False,
    )

    benchmark.generate_data()

    adapter = DuckDBAdapter(database_path=":memory:")

    results = adapter.run_benchmark(
        benchmark,
        test_execution_type="power",
        query_subset=["1", "3", "6", "12", "14"],  # Subset for demo
    )

    print("✓ Benchmark complete!")
    print(f"  Queries: {results.total_queries}")
    print(f"  Total time: {results.total_execution_time:.2f}s")
    print()

    return results


def export_json(results, output_dir: Path):
    """Export results as JSON.

    JSON format is best for:
    - Programmatic processing (scripts, CI/CD)
    - Preserving full result structure
    - API integration
    - Automated analysis

    JSON includes:
    - All query results with timing
    - Metadata (platform, benchmark, timestamp)
    - Configuration details
    - Error information if any
    """
    print("=" * 70)
    print("EXPORT FORMAT 1: JSON")
    print("=" * 70)
    print()

    json_file = output_dir / "results.json"
    json_file.parent.mkdir(parents=True, exist_ok=True)

    # Convert results to dictionary
    results_dict = results.model_dump()

    # Write JSON file
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(results_dict, f, indent=2)

    print(f"✓ JSON exported to: {json_file}")
    print(f"  Size: {json_file.stat().st_size / 1024:.1f} KB")
    print()

    print("JSON structure:")
    print("""
{
  "benchmark_name": "tpch",
  "total_execution_time": 1.23,
  "total_queries": 5,
  "query_results": [
    {
      "query_name": "Q1",
      "execution_time": 0.234,
      "status": "success"
    },
    ...
  ]
}
    """)

    print("Use cases:")
    print("  • Load in Python: results = json.load(open('results.json'))")
    print("  • CI/CD integration: Parse results to detect regressions")
    print("  • API endpoints: Serve results via REST API")
    print("  • Data pipelines: Feed into analysis tools")
    print()

    return json_file


def export_csv(results, output_dir: Path):
    """Export results as CSV.

    CSV format is best for:
    - Spreadsheet analysis (Excel, Google Sheets)
    - Simple data sharing with non-technical users
    - Quick manual inspection
    - Import into BI tools

    CSV includes:
    - One row per query
    - Key metrics (query name, time, status)
    - Easy to sort/filter in spreadsheets
    """
    print("=" * 70)
    print("EXPORT FORMAT 2: CSV")
    print("=" * 70)
    print()

    csv_file = output_dir / "results.csv"
    csv_file.parent.mkdir(parents=True, exist_ok=True)

    # Write CSV file
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Header row
        writer.writerow(["Query Name", "Execution Time (s)", "Status", "Rows Returned"])

        # Data rows
        for query_result in results.query_results:
            writer.writerow(
                [
                    query_result.query_name,
                    f"{query_result.execution_time:.3f}",
                    query_result.status,
                    query_result.rows_returned,
                ]
            )

        # Summary row
        writer.writerow([])
        writer.writerow(["TOTAL", f"{results.total_execution_time:.3f}", f"{results.total_queries} queries", ""])

    print(f"✓ CSV exported to: {csv_file}")
    print(f"  Size: {csv_file.stat().st_size / 1024:.1f} KB")
    print()

    print("CSV preview:")
    print("  Query Name, Execution Time (s), Status, Rows Returned")
    print("  Q1,         0.234,              success, 4")
    print("  Q3,         0.567,              success, 11223")
    print("  ...")
    print()

    print("Use cases:")
    print("  • Open in Excel: Double-click the CSV file")
    print("  • Google Sheets: Import → Upload CSV")
    print("  • Pivot tables: Analyze by query type, time range")
    print("  • Charts: Create performance visualizations")
    print()

    return csv_file


def export_html(results, output_dir: Path):
    """Export results as HTML report.

    HTML format is best for:
    - Stakeholder reports
    - Management presentations
    - Documentation
    - Sharing results via web/email

    HTML includes:
    - Formatted tables
    - Summary statistics
    - Visual highlighting (fast/slow queries)
    - Self-contained (no external dependencies)
    """
    print("=" * 70)
    print("EXPORT FORMAT 3: HTML")
    print("=" * 70)
    print()

    html_file = output_dir / "results.html"
    html_file.parent.mkdir(parents=True, exist_ok=True)

    # Build HTML content
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>BenchBox Results: {results.benchmark_name}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            max-width: 1200px;
            margin: 40px auto;
            padding: 0 20px;
            background: #f5f5f5;
        }}
        .header {{
            background: white;
            padding: 30px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            margin: 0 0 10px 0;
            color: #333;
        }}
        .metadata {{
            color: #666;
            font-size: 14px;
        }}
        .summary {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .metric {{
            display: inline-block;
            margin-right: 30px;
            padding: 10px 0;
        }}
        .metric-label {{
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
        }}
        .metric-value {{
            font-size: 24px;
            font-weight: bold;
            color: #333;
        }}
        table {{
            width: 100%;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            border-collapse: collapse;
        }}
        th {{
            background: #f8f9fa;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            color: #333;
            border-bottom: 2px solid #dee2e6;
        }}
        td {{
            padding: 12px;
            border-bottom: 1px solid #dee2e6;
        }}
        tr:hover {{
            background: #f8f9fa;
        }}
        .fast {{
            color: #28a745;
            font-weight: 600;
        }}
        .slow {{
            color: #dc3545;
            font-weight: 600;
        }}
        .status-success {{
            color: #28a745;
        }}
        .status-error {{
            color: #dc3545;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Benchmark Results: {results.benchmark_name.upper()}</h1>
        <div class="metadata">
            Platform: {results.platform} |
            Test Type: {results.test_execution_type} |
            Generated by BenchBox
        </div>
    </div>

    <div class="summary">
        <div class="metric">
            <div class="metric-label">Total Time</div>
            <div class="metric-value">{results.total_execution_time:.2f}s</div>
        </div>
        <div class="metric">
            <div class="metric-label">Total Queries</div>
            <div class="metric-value">{results.total_queries}</div>
        </div>
        <div class="metric">
            <div class="metric-label">Average Time</div>
            <div class="metric-value">{results.average_query_time:.3f}s</div>
        </div>
    </div>

    <table>
        <thead>
            <tr>
                <th>Query</th>
                <th>Execution Time</th>
                <th>Status</th>
                <th>Rows</th>
            </tr>
        </thead>
        <tbody>
"""

    # Add query rows
    for query_result in results.query_results:
        # Color-code based on execution time
        time_class = (
            "fast" if query_result.execution_time < 0.5 else "slow" if query_result.execution_time > 2.0 else ""
        )
        status_class = f"status-{query_result.status}"

        html_content += f"""            <tr>
                <td><strong>{query_result.query_name}</strong></td>
                <td class="{time_class}">{query_result.execution_time:.3f}s</td>
                <td class="{status_class}">{query_result.status}</td>
                <td>{query_result.rows_returned:,}</td>
            </tr>
"""

    html_content += """        </tbody>
    </table>
</body>
</html>
"""

    # Write HTML file
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"✓ HTML exported to: {html_file}")
    print(f"  Size: {html_file.stat().st_size / 1024:.1f} KB")
    print()

    print("HTML features:")
    print("  • Formatted tables with styling")
    print("  • Summary metrics at the top")
    print("  • Color-coded performance (green=fast, red=slow)")
    print("  • Self-contained (no external CSS/JS)")
    print("  • Open directly in browser")
    print()

    print("Use cases:")
    print("  • Email to stakeholders: Attach HTML file")
    print("  • Web dashboard: Host on internal server")
    print("  • Documentation: Embed in confluence/wiki")
    print("  • Presentations: Screenshot or link")
    print()

    return html_file


def show_format_comparison():
    """Show when to use each export format."""
    print("=" * 70)
    print("FORMAT SELECTION GUIDE")
    print("=" * 70)
    print()

    print("JSON - Machine-Readable Data")
    print("  ✓ CI/CD pipelines and automation")
    print("  ✓ API integration")
    print("  ✓ Programmatic analysis in Python/JavaScript")
    print("  ✓ Preserves complete result structure")
    print("  ✓ Time-series storage (one JSON per run)")
    print("  ✗ Not human-friendly for quick viewing")
    print()

    print("CSV - Spreadsheet Analysis")
    print("  ✓ Excel/Google Sheets analysis")
    print("  ✓ Pivot tables and charts")
    print("  ✓ Quick manual inspection")
    print("  ✓ Import into BI tools (Tableau, Power BI)")
    print("  ✓ Version control friendly (text-based)")
    print("  ✗ Limited to tabular data (loses structure)")
    print()

    print("HTML - Stakeholder Reports")
    print("  ✓ Non-technical stakeholders")
    print("  ✓ Management presentations")
    print("  ✓ Email distribution")
    print("  ✓ Web dashboards")
    print("  ✓ Self-contained and styled")
    print("  ✗ Not suitable for automated processing")
    print()


def show_unified_runner_usage():
    """Show how to export formats using unified_runner.py."""
    print("=" * 70)
    print("USING unified_runner.py")
    print("=" * 70)
    print()

    print("Export single format:")
    print("  python unified_runner.py --platform duckdb --benchmark tpch \\")
    print("    --scale 1.0 --phases power --formats json")
    print()

    print("Export multiple formats:")
    print("  python unified_runner.py --platform duckdb --benchmark tpch \\")
    print("    --scale 1.0 --phases power --formats json,csv,html")
    print()

    print("This generates:")
    print("  ./benchmark_runs/tpch/results.json")
    print("  ./benchmark_runs/tpch/results.csv")
    print("  ./benchmark_runs/tpch/results.html")
    print()


def main() -> int:
    """Demonstrate export format options."""
    print()
    print("=" * 70)
    print("BENCHBOX FEATURE: EXPORT FORMATS")
    print("=" * 70)
    print()
    print("This example shows how to export benchmark results in")
    print("different formats for different audiences and use cases.")
    print()

    # Run sample benchmark
    results = run_sample_benchmark()

    output_dir = Path("./benchmark_runs/features/export")

    # Export in all formats
    json_file = export_json(results, output_dir)
    csv_file = export_csv(results, output_dir)
    html_file = export_html(results, output_dir)

    # Show comparison
    show_format_comparison()

    # Show unified_runner usage
    show_unified_runner_usage()

    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print("You learned how to:")
    print("  ✓ Export results as JSON for automation")
    print("  ✓ Export results as CSV for spreadsheets")
    print("  ✓ Export results as HTML for reports")
    print("  ✓ Choose the right format for your audience")
    print()
    print("Generated files:")
    print(f"  • JSON: {json_file}")
    print(f"  • CSV:  {csv_file}")
    print(f"  • HTML: {html_file}")
    print()
    print("Next steps:")
    print("  • Open HTML in browser: open results.html")
    print("  • Open CSV in Excel: Double-click the file")
    print("  • Process JSON in Python:")
    print("    import json")
    print("    results = json.load(open('results.json'))")
    print("    print(results['total_execution_time'])")
    print()
    print("  • Use with unified_runner.py:")
    print("    --formats json,csv,html")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
