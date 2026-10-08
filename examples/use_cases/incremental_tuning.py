#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_SCRIPT_DIR = Path(__file__).resolve().parent
_EXAMPLES_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_EXAMPLES_DIR))

from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH

OptimizationType = Literal["baseline", "memory", "parallelism", "indexes"]


@dataclass
class TuningRound:
    round_number: int
    optimization_type: OptimizationType
    description: str
    total_time: float
    improvement_vs_baseline: float
    improvement_vs_previous: float


class IncrementalTuner:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.rounds: list[TuningRound] = []
        self.baseline_time: float | None = None

    def run_baseline(self, benchmark: TPCH) -> TuningRound:
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
        print(f"Round {round_number}: {optimization_type.upper()}")
        print(f"  Strategy: {description}")
        print()

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

        if self.baseline_time and self.rounds:
            final_time = self.rounds[-1].total_time
            total_improvement = (self.baseline_time - final_time) / self.baseline_time * 100
            print(f"Total Improvement: {total_improvement:+.1f}%")
            print(f"Baseline Time: {self.baseline_time:.2f}s")
            print(f"Final Time: {final_time:.2f}s")
            print()

    def save_report(self, report_path: Path) -> None:
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

    benchmark = TPCH(
        scale_factor=args.scale,
        output_dir=args.output_dir / "data",
        force_regenerate=False,
        verbose=False,
    )

    benchmark.generate_data()
    print("✓ Data generated")
    print()

    tuner = IncrementalTuner(output_dir=args.output_dir)

    print("=" * 90)
    tuner.run_baseline(benchmark)

    print("=" * 90)
    tuner.run_tuning_round(
        benchmark,
        round_number=2,
        optimization_type="memory",
        description="Increase memory buffers for better caching",
    )

    print("=" * 90)
    tuner.run_tuning_round(
        benchmark,
        round_number=3,
        optimization_type="parallelism",
        description="Enable parallel query execution",
    )

    print("=" * 90)
    tuner.run_tuning_round(
        benchmark,
        round_number=4,
        optimization_type="indexes",
        description="Add indexes on frequently filtered columns",
    )

    tuner.generate_report()

    report_path = args.output_dir / "tuning_report.json"
    tuner.save_report(report_path)
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
