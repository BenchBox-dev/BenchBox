#!/usr/bin/env python3
"""Use Case: Incremental Performance Tuning

This example demonstrates an iterative approach to performance optimization,
showing how to systematically tune database performance through multiple rounds.

Use this pattern when:
- Optimizing query performance incrementally
- Testing optimization hypotheses
- Building performance tuning documentation
- Training teams on performance optimization

Workflow:
1. Establish baseline performance
2. Identify slowest queries
3. Apply targeted optimizations
4. Measure improvement
5. Iterate until targets met

Usage:
    # Run full tuning workflow
    python use_cases/incremental_tuning.py

    # Focus on specific slow queries
    python use_cases/incremental_tuning.py --queries 2,9,17

    # Test specific optimization
    python use_cases/incremental_tuning.py --optimization indexes
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# Add parent directory to path for imports
_SCRIPT_DIR = Path(__file__).resolve().parent
_EXAMPLES_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_EXAMPLES_DIR))

from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH

OptimizationType = Literal["baseline", "memory", "parallelism", "indexes"]


@dataclass
class TuningRound:
    """Results from a single tuning round."""

    round_number: int
    optimization_type: OptimizationType
    description: str
    total_time: float
    improvement_vs_baseline: float
    improvement_vs_previous: float


class IncrementalTuner:
    """Manage incremental tuning workflow."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.rounds: list[TuningRound] = []
        self.baseline_time: float | None = None

    def run_baseline(self, benchmark: TPCH) -> TuningRound:
        """Run baseline benchmark (no optimizations)."""
        print("Round 1: BASELINE (No Optimizations)")
        print("  Strategy: Measure current performance with default settings")
        print()

        adapter = DuckDBAdapter(database_path=":memory:")
        results = adapter.run_benchmark(benchmark, test_execution_type="power")

        self.baseline_time = results.total_execution_time

        round_data = TuningRound(
            round_number=1,
            optimization_type="baseline",
            description="Default configuration with no optimizations",
            total_time=results.total_execution_time,
            improvement_vs_baseline=0.0,
            improvement_vs_previous=0.0,
        )

        self.rounds.append(round_data)

        print(f"✓ Baseline: {results.total_execution_time:.2f}s")
        print()
        return round_data

    def run_tuning_round(
        self,
        benchmark: TPCH,
        round_number: int,
        optimization_type: OptimizationType,
        description: str,
    ) -> TuningRound:
        """Run a tuning round with specific optimizations."""
        print(f"Round {round_number}: {optimization_type.upper()}")
        print(f"  Strategy: {description}")
        print()

        # In real implementation, would apply actual optimizations
        # For this example, we simulate the concept
        adapter = DuckDBAdapter(database_path=":memory:")
        results = adapter.run_benchmark(benchmark, test_execution_type="power")

        previous_time = self.rounds[-1].total_time if self.rounds else results.total_execution_time
        improvement_vs_baseline = (
            ((self.baseline_time - results.total_execution_time) / self.baseline_time * 100)
            if self.baseline_time
            else 0
        )
        improvement_vs_previous = (
            ((previous_time - results.total_execution_time) / previous_time * 100) if previous_time else 0
        )

        round_data = TuningRound(
            round_number=round_number,
            optimization_type=optimization_type,
            description=description,
            total_time=results.total_execution_time,
            improvement_vs_baseline=improvement_vs_baseline,
            improvement_vs_previous=improvement_vs_previous,
        )

        self.rounds.append(round_data)

        print(f"✓ Round {round_number}: {results.total_execution_time:.2f}s")
        print(f"  Improvement vs baseline: {improvement_vs_baseline:+.1f}%")
        print(f"  Improvement vs previous: {improvement_vs_previous:+.1f}%")
        print()

        return round_data

    def generate_report(self) -> None:
        """Generate tuning report."""
        print("=" * 90)
        print("INCREMENTAL TUNING REPORT")
        print("=" * 90)
        print()

        print("Tuning Progress:")
        print("-" * 90)
        print(f"{'Round':<8} {'Optimization':<20} {'Time':<15} {'vs Baseline':<20} {'vs Previous':<15}")
        print("-" * 90)

        for round in self.rounds:
            print(
                f"{round.round_number:<8} "
                f"{round.optimization_type:<20} "
                f"{round.total_time:>10.2f}s    "
                f"{round.improvement_vs_baseline:>+10.1f}%         "
                f"{round.improvement_vs_previous:>+10.1f}%"
            )

        print("-" * 90)
        print()

        # Cumulative improvement
        if self.baseline_time and self.rounds:
            final_time = self.rounds[-1].total_time
            total_improvement = (self.baseline_time - final_time) / self.baseline_time * 100
            print(f"Total Improvement: {total_improvement:+.1f}%")
            print(f"Baseline Time: {self.baseline_time:.2f}s")
            print(f"Final Time: {final_time:.2f}s")
            print()

    def save_report(self, report_path: Path) -> None:
        """Save tuning report as JSON."""
        report = {
            "baseline_time": self.baseline_time,
            "rounds": [
                {
                    "round_number": r.round_number,
                    "optimization_type": r.optimization_type,
                    "description": r.description,
                    "total_time": r.total_time,
                    "improvement_vs_baseline": r.improvement_vs_baseline,
                    "improvement_vs_previous": r.improvement_vs_previous,
                }
                for r in self.rounds
            ],
        }

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print(f"✓ Tuning report saved to: {report_path}")


def main() -> int:
    """Run incremental tuning workflow."""
    parser = argparse.ArgumentParser(description="Incremental performance tuning")
    parser.add_argument(
        "--scale",
        type=float,
        default=0.01,
        help="Benchmark scale factor (default: 0.01)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./benchmark_runs/incremental_tuning"),
        help="Output directory for results",
    )
    args = parser.parse_args()

    print()
    print("=" * 90)
    print("INCREMENTAL PERFORMANCE TUNING")
    print("=" * 90)
    print()

    # Create benchmark
    benchmark = TPCH(
        scale_factor=args.scale,
        output_dir=args.output_dir / "data",
        force_regenerate=False,
        verbose=False,
    )

    benchmark.generate_data()
    print("✓ Data generated")
    print()

    # Create tuner
    tuner = IncrementalTuner(output_dir=args.output_dir)

    # Round 1: Baseline
    print("=" * 90)
    tuner.run_baseline(benchmark)

    # Round 2: Memory tuning
    print("=" * 90)
    tuner.run_tuning_round(
        benchmark,
        round_number=2,
        optimization_type="memory",
        description="Increase memory buffers for better caching",
    )

    # Round 3: Parallelism
    print("=" * 90)
    tuner.run_tuning_round(
        benchmark,
        round_number=3,
        optimization_type="parallelism",
        description="Enable parallel query execution",
    )

    # Round 4: Indexes
    print("=" * 90)
    tuner.run_tuning_round(
        benchmark,
        round_number=4,
        optimization_type="indexes",
        description="Add indexes on frequently filtered columns",
    )

    # Generate report
    tuner.generate_report()

    # Save report
    report_path = args.output_dir / "tuning_report.json"
    tuner.save_report(report_path)
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
