#!/usr/bin/env python3
"""Use Case: Systematic Platform Evaluation

This example demonstrates how to systematically evaluate multiple database
platforms to make informed platform selection decisions.

Use this pattern when:
- Migrating from one database platform to another
- Choosing a platform for a new project
- Evaluating cost vs performance trade-offs
- Comparing self-hosted vs cloud-managed options
- Validating vendor performance claims

Evaluation criteria:
- Query performance (latency and throughput)
- Data loading speed
- Cost (compute, storage, egress)
- Operational complexity
- Feature compatibility
- Scalability characteristics

Usage:
    # Evaluate multiple platforms
    python use_cases/platform_evaluation.py --platforms duckdb,sqlite,clickhouse

    # Dry-run first (preview without execution)
    python use_cases/platform_evaluation.py --platforms databricks,bigquery --dry-run

    # Custom scale factor
    python use_cases/platform_evaluation.py --platforms duckdb,clickhouse --scale 1.0
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Add parent directory to path for imports
_SCRIPT_DIR = Path(__file__).resolve().parent
_EXAMPLES_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_EXAMPLES_DIR))

from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.platforms.sqlite import SQLiteAdapter
from benchbox.tpch import TPCH


@dataclass
class PlatformEvaluation:
    """Results from evaluating a single platform."""

    platform_name: str
    total_time: float
    query_count: int
    successful_queries: int
    average_query_time: float
    data_loading_time: float | None = None
    cost_estimate: float | None = None
    notes: str = ""


class PlatformEvaluator:
    """Systematically evaluate database platforms."""

    def __init__(self, output_dir: Path):
        """Initialize evaluator.

        Args:
            output_dir: Directory to store evaluation results
        """
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.evaluations: list[PlatformEvaluation] = []

    def evaluate_duckdb(self, benchmark: TPCH) -> PlatformEvaluation:
        """Evaluate DuckDB."""
        print("Evaluating DuckDB...")
        print("  Type: Embedded OLAP database")
        print("  Cost: Free (open source)")
        print("  Deployment: In-process, no server required")
        print()

        adapter = DuckDBAdapter(database_path=":memory:")
        results = adapter.run_benchmark(benchmark, test_execution_type="power")

        return PlatformEvaluation(
            platform_name="DuckDB",
            total_time=results.total_execution_time,
            query_count=results.total_queries,
            successful_queries=results.successful_queries,
            average_query_time=results.average_query_time,
            cost_estimate=0.0,  # Free
            notes="Excellent for embedded analytics, local development, and single-machine workloads",
        )

    def evaluate_sqlite(self, benchmark: TPCH) -> PlatformEvaluation:
        """Evaluate SQLite."""
        print("Evaluating SQLite...")
        print("  Type: Embedded transactional database")
        print("  Cost: Free (open source)")
        print("  Deployment: Single file, no server required")
        print()

        db_path = self.output_dir / "sqlite_eval.db"
        adapter = SQLiteAdapter(database_path=str(db_path), force_recreate=True)
        results = adapter.run_benchmark(benchmark, test_execution_type="power")

        return PlatformEvaluation(
            platform_name="SQLite",
            total_time=results.total_execution_time,
            query_count=results.total_queries,
            successful_queries=results.successful_queries,
            average_query_time=results.average_query_time,
            cost_estimate=0.0,  # Free
            notes="Best for embedded applications, mobile apps, and small analytical workloads",
        )

    def compare_evaluations(self) -> None:
        """Generate comparison report."""
        if not self.evaluations:
            print("No evaluations to compare")
            return

        print("=" * 90)
        print("PLATFORM COMPARISON REPORT")
        print("=" * 90)
        print()

        # Overall performance table
        print("Performance Summary:")
        print("-" * 90)
        print(f"{'Platform':<15} {'Total Time':<15} {'Avg Query':<15} {'Success Rate':<15} {'Cost Est.':<15}")
        print("-" * 90)

        # Find fastest for relative comparison
        fastest_time = min(e.total_time for e in self.evaluations)

        for eval in sorted(self.evaluations, key=lambda e: e.total_time):
            relative_perf = eval.total_time / fastest_time if fastest_time > 0 else 1.0
            success_rate = (eval.successful_queries / eval.query_count * 100) if eval.query_count > 0 else 0

            cost_str = f"${eval.cost_estimate:.2f}" if eval.cost_estimate is not None else "N/A"

            print(
                f"{eval.platform_name:<15} "
                f"{eval.total_time:>10.2f}s ({relative_perf:.2f}x)  "
                f"{eval.average_query_time:>10.3f}s  "
                f"{success_rate:>10.0f}%  "
                f"{cost_str:>10}"
            )

        print("-" * 90)
        print()

        # Detailed notes
        print("Platform Notes:")
        print("-" * 90)
        for eval in self.evaluations:
            print(f"\n{eval.platform_name}:")
            print(f"  {eval.notes}")
        print()

        # Winner selection
        print("=" * 90)
        print("RECOMMENDATION")
        print("=" * 90)
        print()

        fastest = min(self.evaluations, key=lambda e: e.total_time)
        cheapest = min(
            (e for e in self.evaluations if e.cost_estimate is not None),
            key=lambda e: e.cost_estimate or float("inf"),
            default=None,
        )

        print(f"Fastest Platform: {fastest.platform_name}")
        print(f"  Total time: {fastest.total_time:.2f}s")
        print("  Use when: Performance is critical, cost is less important")
        print()

        if cheapest:
            print(f"Most Cost-Effective: {cheapest.platform_name}")
            print(f"  Cost estimate: ${cheapest.cost_estimate:.2f}")
            print(f"  Total time: {cheapest.total_time:.2f}s")
            print("  Use when: Cost optimization is priority")
            print()

        print("Decision Factors:")
        print("  • Performance: Consider query latency requirements")
        print("  • Cost: Evaluate total cost of ownership (compute + storage + egress)")
        print("  • Scale: Will data volume exceed platform limits?")
        print("  • Operations: Self-hosted vs managed trade-offs")
        print("  • Features: SQL compatibility, integrations, tooling")
        print("  • Team: Existing expertise and learning curve")
        print()

    def save_report(self, report_path: Path) -> None:
        """Save evaluation report as JSON."""
        report = {
            "evaluations": [
                {
                    "platform": e.platform_name,
                    "total_time": e.total_time,
                    "query_count": e.query_count,
                    "successful_queries": e.successful_queries,
                    "average_query_time": e.average_query_time,
                    "cost_estimate": e.cost_estimate,
                    "notes": e.notes,
                }
                for e in self.evaluations
            ]
        }

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print(f"✓ Evaluation report saved to: {report_path}")


def main() -> int:
    """Run platform evaluation."""
    parser = argparse.ArgumentParser(description="Systematic platform evaluation")
    parser.add_argument(
        "--platforms",
        type=str,
        default="duckdb,sqlite",
        help="Comma-separated list of platforms to evaluate (default: duckdb,sqlite)",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=0.01,
        help="Benchmark scale factor (default: 0.01)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview evaluation without executing (useful for cloud platforms)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./benchmark_runs/platform_evaluation"),
        help="Output directory for results",
    )
    args = parser.parse_args()

    print()
    print("=" * 90)
    print("PLATFORM EVALUATION")
    print("=" * 90)
    print()

    platforms = [p.strip() for p in args.platforms.split(",")]

    if args.dry_run:
        print("DRY-RUN MODE: Preview only, no execution")
        print()
        print("Platforms to evaluate:")
        for platform in platforms:
            print(f"  • {platform}")
        print()
        print("To execute evaluation:")
        print(f"  python {Path(__file__).name} --platforms {args.platforms} --scale {args.scale}")
        return 0

    # Create benchmark (shared across all platforms)
    print("Creating TPC-H benchmark...")
    print(f"  Scale factor: {args.scale}")
    print()

    benchmark = TPCH(
        scale_factor=args.scale,
        output_dir=args.output_dir / "data",
        force_regenerate=False,
        verbose=False,
    )

    benchmark.generate_data()
    print("✓ Data generated (will be reused across all platforms)")
    print()

    # Create evaluator
    evaluator = PlatformEvaluator(output_dir=args.output_dir)

    # Evaluate each platform
    for platform_name in platforms:
        print("=" * 90)

        if platform_name.lower() == "duckdb":
            evaluation = evaluator.evaluate_duckdb(benchmark)
            evaluator.evaluations.append(evaluation)
            print(f"✓ DuckDB evaluation complete: {evaluation.total_time:.2f}s")

        elif platform_name.lower() == "sqlite":
            evaluation = evaluator.evaluate_sqlite(benchmark)
            evaluator.evaluations.append(evaluation)
            print(f"✓ SQLite evaluation complete: {evaluation.total_time:.2f}s")

        else:
            print(f"⚠️  Platform '{platform_name}' not supported in this example")
            print("   Supported: duckdb, sqlite")
            print("   For cloud platforms (databricks, bigquery, snowflake):")
            print("   Use unified_runner.py instead")

        print()

    # Generate comparison report
    evaluator.compare_evaluations()

    # Save report
    report_path = args.output_dir / "evaluation_report.json"
    evaluator.save_report(report_path)
    print()

    print("=" * 90)
    print("NEXT STEPS")
    print("=" * 90)
    print()
    print("1. Review evaluation report and platform notes")
    print("2. Test at larger scale factors:")
    print(f"   python {Path(__file__).name} --platforms {args.platforms} --scale 1.0")
    print()
    print("3. Evaluate cloud platforms:")
    print("   python unified_runner.py --platform databricks --benchmark tpch --scale 1.0")
    print("   python unified_runner.py --platform bigquery --benchmark tpch --scale 1.0")
    print()
    print("4. Compare results with result_analysis.py:")
    print("   python features/result_analysis.py baseline.json current.json")
    print()
    print("5. Consider additional factors:")
    print("   • Total cost of ownership (5-year projection)")
    print("   • Operational overhead (self-hosted vs managed)")
    print("   • Team expertise and training costs")
    print("   • Vendor lock-in vs portability")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
