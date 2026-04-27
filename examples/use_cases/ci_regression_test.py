#!/usr/bin/env python3
"""Use Case: CI/CD Regression Testing

This example demonstrates how to integrate BenchBox into CI/CD pipelines
for automated performance regression testing.

Use this pattern when:
- Running performance tests in GitHub Actions, GitLab CI, Jenkins, etc.
- Detecting performance regressions before merging pull requests
- Maintaining performance SLAs across releases
- Automating performance validation

Key requirements for CI/CD:
- Fast execution (< 30 seconds preferred, < 5 minutes maximum)
- Clear pass/fail criteria (exit codes)
- Minimal console output (concise logs)
- Stable results (low variance)
- Baseline comparison

Usage:
    # Run in CI pipeline
    python use_cases/ci_regression_test.py --baseline results/baseline.json

    # Generate baseline (run once on main branch)
    python use_cases/ci_regression_test.py --save-baseline results/baseline.json

    # GitHub Actions example
    # See ci_regression_test_github.yml for full workflow
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add parent directory to path for imports
_SCRIPT_DIR = Path(__file__).resolve().parent
_EXAMPLES_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_EXAMPLES_DIR))

from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH


class RegressionDetector:
    """Detect performance regressions by comparing against baseline."""

    def __init__(self, threshold_percent: float = 15.0):
        """Initialize regression detector.

        Args:
            threshold_percent: Percentage change threshold for regression (default 15%)
        """
        self.threshold_percent = threshold_percent

    def detect_regression(
        self,
        baseline_results: dict,
        current_results: dict,
    ) -> tuple[bool, str]:
        """Detect if current results show regression vs baseline.

        Returns:
            (has_regression, report_message)
        """
        baseline_time = baseline_results.get("total_execution_time", 0)
        current_time = current_results.get("total_execution_time", 0)

        if baseline_time == 0:
            return False, "⚠️  No baseline time available"

        percent_change = ((current_time - baseline_time) / baseline_time) * 100

        if percent_change > self.threshold_percent:
            return True, (
                f"❌ REGRESSION DETECTED: {percent_change:.1f}% slower\n"
                f"   Baseline: {baseline_time:.2f}s\n"
                f"   Current:  {current_time:.2f}s\n"
                f"   Threshold: {self.threshold_percent}%"
            )
        elif percent_change < -self.threshold_percent:
            return False, (
                f"✅ IMPROVEMENT: {-percent_change:.1f}% faster\n"
                f"   Baseline: {baseline_time:.2f}s\n"
                f"   Current:  {current_time:.2f}s"
            )
        else:
            return False, (
                f"✅ STABLE: {percent_change:+.1f}% change (within {self.threshold_percent}% threshold)\n"
                f"   Baseline: {baseline_time:.2f}s\n"
                f"   Current:  {current_time:.2f}s"
            )


def run_ci_benchmark() -> dict:
    """Run lightweight benchmark suitable for CI/CD.

    Strategy for CI/CD benchmarks:
    - Use smallest scale factor (0.01) for speed
    - Run subset of queries (2-3 fast queries)
    - Use in-memory database (no I/O overhead)
    - Disable verbose output
    - Cache data generation
    """
    print("Running CI performance test...")

    # Create benchmark with minimal scale
    benchmark = TPCH(
        scale_factor=0.01,  # ~10MB, < 1 second to generate
        output_dir=Path("./benchmark_runs/ci_test"),
        force_regenerate=False,  # Reuse cached data
        verbose=False,  # Minimal output
    )

    # Generate data (cached after first run)
    benchmark.generate_data()

    # Create adapter
    adapter = DuckDBAdapter(database_path=":memory:")

    # Run smoke test queries only (Q1 and Q6 are fastest)
    # This provides quick validation without full benchmark overhead
    results = adapter.run_benchmark(
        benchmark,
        test_execution_type="power",
        query_subset=["1", "6"],  # ~2-5 seconds total
    )

    print(f"✓ Benchmark complete: {results.total_execution_time:.2f}s")

    return results.model_dump()


def save_baseline(results: dict, baseline_path: Path) -> None:
    """Save results as baseline for future comparisons."""
    baseline_path.parent.mkdir(parents=True, exist_ok=True)

    with open(baseline_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"✓ Baseline saved to: {baseline_path}")


def load_baseline(baseline_path: Path) -> dict:
    """Load baseline results from file."""
    if not baseline_path.exists():
        raise FileNotFoundError(f"Baseline file not found: {baseline_path}")

    with open(baseline_path, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    """Run CI regression test.

    Returns:
        0 if no regression detected
        1 if regression detected
    """
    parser = argparse.ArgumentParser(description="CI/CD performance regression test")
    parser.add_argument(
        "--baseline",
        type=Path,
        help="Path to baseline results JSON file",
    )
    parser.add_argument(
        "--save-baseline",
        type=Path,
        metavar="PATH",
        help="Run benchmark and save as baseline (run once on main branch)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=15.0,
        help="Regression threshold percentage (default: 15%%)",
    )
    args = parser.parse_args()

    # Mode 1: Save baseline (run on main/master branch)
    if args.save_baseline:
        print("=" * 70)
        print("GENERATING BASELINE")
        print("=" * 70)
        print()
        results = run_ci_benchmark()
        save_baseline(results, args.save_baseline)
        print()
        print("Baseline generated successfully!")
        print("Use this baseline for future regression tests:")
        print(f"  python {Path(__file__).name} --baseline {args.save_baseline}")
        return 0

    # Mode 2: Regression test (run on pull requests)
    if not args.baseline:
        print("Error: Must specify --baseline or --save-baseline")
        print()
        print("Usage:")
        print(f"  Generate baseline:  python {Path(__file__).name} --save-baseline baseline.json")
        print(f"  Test for regression: python {Path(__file__).name} --baseline baseline.json")
        return 1

    print("=" * 70)
    print("CI/CD REGRESSION TEST")
    print("=" * 70)
    print()

    # Load baseline
    try:
        baseline_results = load_baseline(args.baseline)
        print(f"✓ Loaded baseline from: {args.baseline}")
    except FileNotFoundError:
        print(f"❌ Error: Baseline file not found: {args.baseline}")
        print()
        print("Generate baseline first:")
        print(f"  python {Path(__file__).name} --save-baseline {args.baseline}")
        return 1

    print()

    # Run current benchmark
    current_results = run_ci_benchmark()
    print()

    # Detect regression
    detector = RegressionDetector(threshold_percent=args.threshold)
    has_regression, report = detector.detect_regression(baseline_results, current_results)

    print("=" * 70)
    print("REGRESSION ANALYSIS")
    print("=" * 70)
    print()
    print(report)
    print()

    if has_regression:
        print("=" * 70)
        print("RECOMMENDED ACTIONS")
        print("=" * 70)
        print()
        print("1. Review recent code changes that may impact performance")
        print("2. Run the test locally to reproduce the issue")
        print("3. Profile the slow queries to identify bottlenecks:")
        print("   python features/result_analysis.py baseline.json current.json")
        print("4. If regression is expected (e.g., new features), update baseline:")
        print(f"   python {Path(__file__).name} --save-baseline {args.baseline}")
        print()
        return 1
    else:
        print("✅ Performance regression test PASSED")
        print()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
