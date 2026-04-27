#!/usr/bin/env python3
"""Enhanced test runner with parallel execution and caching.

This module provides optimized test execution capabilities including:
- Parallel test execution using pytest-xdist
- Test result caching for faster iteration
- Selective test execution by category
- Performance monitoring and reporting
- CI/CD optimization strategies

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path


class BenchmarkCategory(Enum):
    """Test categories for selective execution."""

    UNIT = "unit"
    INTEGRATION = "integration"
    PERFORMANCE = "performance"
    SPECIALIZED = "specialized"
    SLOW = "slow"
    FAST = "fast"
    ALL = "all"


@dataclass
class BenchmarkTestResult:
    """Test execution result data."""

    category: str
    total_tests: int
    passed: int
    failed: int
    skipped: int
    errors: int
    warnings: int
    duration: float
    cache_hit: bool = False
    parallel_workers: int = 1
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class RunnerConfiguration:
    """Test runner configuration."""

    categories: list[BenchmarkCategory]
    parallel_workers: int
    cache_enabled: bool
    verbose: bool
    fail_fast: bool
    coverage: bool
    benchmark: bool
    output_format: str
    markers: list[str]
    exclude_markers: list[str]
    max_duration: float | None
    memory_limit: int | None


class ResultCache:
    """Test result caching for faster iteration."""

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or Path.home() / ".benchbox" / "test_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "test_results.json"
        self._load_cache()

    def _load_cache(self) -> None:
        """Load cache from disk."""
        self.cache = {}
        if self.cache_file.exists():
            try:
                with open(self.cache_file, encoding="utf-8") as f:
                    self.cache = json.load(f)
            except (OSError, json.JSONDecodeError):
                self.cache = {}

    def _save_cache(self) -> None:
        """Save cache to disk."""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2)
        except OSError:
            pass

    def get_cache_key(self, test_files: list[str], config: RunnerConfiguration) -> str:
        """Generate cache key for test configuration."""
        import hashlib

        # Include file modification times
        file_data = []
        for test_file in sorted(test_files):
            if os.path.exists(test_file):
                mtime = os.path.getmtime(test_file)
                file_data.append(f"{test_file}:{mtime}")

        # Include configuration
        config_data = {
            "categories": [c.value for c in config.categories],
            "markers": sorted(config.markers),
            "exclude_markers": sorted(config.exclude_markers),
            "coverage": config.coverage,
            "benchmark": config.benchmark,
        }

        cache_input = json.dumps(file_data + [config_data], sort_keys=True)
        return hashlib.md5(cache_input.encode()).hexdigest()

    def get_cached_result(self, cache_key: str) -> BenchmarkTestResult | None:
        """Get cached test result."""
        if cache_key in self.cache:
            try:
                result_data = self.cache[cache_key]
                result = BenchmarkTestResult(**result_data)
                result.cache_hit = True
                return result
            except (TypeError, ValueError):
                # Invalid cache entry, remove it
                del self.cache[cache_key]
        return None

    def cache_result(self, cache_key: str, result: BenchmarkTestResult) -> None:
        """Cache test result."""
        self.cache[cache_key] = asdict(result)
        self._save_cache()

    def clear_cache(self) -> None:
        """Clear all cached results."""
        self.cache = {}
        if self.cache_file.exists():
            self.cache_file.unlink()


class BenchmarkRunner:
    """Enhanced test runner with optimization features."""

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root or Path.cwd()
        self.tests_dir = self.project_root / "tests"
        self.cache = ResultCache()
        self.results_history: list[BenchmarkTestResult] = []

    def discover_test_files(self, categories: list[BenchmarkCategory]) -> list[str]:
        """Discover test files based on categories."""
        test_files = []

        if BenchmarkCategory.ALL in categories:
            # Find all test files
            for pattern in ["test_*.py", "*_test.py"]:
                test_files.extend(self.tests_dir.glob(f"**/{pattern}"))
        else:
            # Find files by category
            for category in categories:
                if category == BenchmarkCategory.UNIT:
                    test_files.extend(self.tests_dir.glob("unit/**/*.py"))
                elif category == BenchmarkCategory.INTEGRATION:
                    test_files.extend(self.tests_dir.glob("integration/**/*.py"))
                elif category == BenchmarkCategory.PERFORMANCE:
                    test_files.extend(self.tests_dir.glob("performance/**/*.py"))
                elif category == BenchmarkCategory.SPECIALIZED:
                    test_files.extend(self.tests_dir.glob("specialized/**/*.py"))
                elif category == BenchmarkCategory.FAST:
                    # Fast tests are those not marked as slow
                    fast_files = []
                    for test_file in self.tests_dir.glob("**/*.py"):
                        if not self._is_slow_test(test_file):
                            fast_files.append(test_file)
                    test_files.extend(fast_files)
                elif category == BenchmarkCategory.SLOW:
                    # Slow tests
                    slow_files = []
                    for test_file in self.tests_dir.glob("**/*.py"):
                        if self._is_slow_test(test_file):
                            slow_files.append(test_file)
                    test_files.extend(slow_files)

        return [str(f.relative_to(self.project_root)) for f in set(test_files)]

    def _is_slow_test(self, test_file: Path) -> bool:
        """Check if test file contains slow tests."""
        try:
            content = test_file.read_text(encoding="utf-8")
            return "@pytest.mark.slow" in content or "slow" in str(test_file)
        except OSError:
            return False

    def build_pytest_command(self, test_files: list[str], config: RunnerConfiguration) -> list[str]:
        """Build pytest command with optimizations."""
        cmd = ["python", "-m", "pytest"]

        # Include test files
        if test_files:
            cmd.extend(test_files)

        # Parallel execution
        if config.parallel_workers > 1:
            cmd.extend(["-n", str(config.parallel_workers)])

        # Verbosity
        if config.verbose:
            cmd.append("-v")
        else:
            cmd.append("-q")

        # Fail fast
        if config.fail_fast:
            cmd.append("-x")

        # Coverage
        if config.coverage:
            cmd.extend(["--cov=benchbox", "--cov-report=term-missing", "--cov-report=html"])

        # Benchmark
        if config.benchmark:
            cmd.append("--benchmark-only")

        # Markers
        if config.markers:
            for marker in config.markers:
                cmd.extend(["-m", marker])

        # Exclude markers
        if config.exclude_markers:
            exclude_expr = " and ".join(f"not {marker}" for marker in config.exclude_markers)
            if config.markers:
                # Combine with existing markers
                cmd[-1] = f"({cmd[-1]}) and ({exclude_expr})"
            else:
                cmd.extend(["-m", exclude_expr])

        # Output format
        if config.output_format == "json":
            cmd.append("--json-report")
        elif config.output_format == "junit":
            cmd.append("--junit-xml=test_results.xml")

        # Timeout
        if config.max_duration:
            cmd.extend(["--timeout", str(int(config.max_duration))])

        # Memory limit (if available)
        if config.memory_limit:
            cmd.extend(["--memray-bin-path", "/tmp/memray"])

        return cmd

    def execute_tests(self, config: RunnerConfiguration) -> BenchmarkTestResult:
        """Execute tests with optimization and caching."""
        start_time = time.time()

        # Discover test files
        test_files = self.discover_test_files(config.categories)

        # Check cache if enabled
        if config.cache_enabled:
            cache_key = self.cache.get_cache_key(test_files, config)
            cached_result = self.cache.get_cached_result(cache_key)
            if cached_result:
                print(f"Using cached result for {len(test_files)} test files")
                return cached_result

        # Build command
        cmd = self.build_pytest_command(test_files, config)

        # Execute tests
        print(f"Running {len(test_files)} test files with {config.parallel_workers} workers...")
        print(f"Command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.project_root,
                timeout=config.max_duration,
            )

            # Parse results
            test_result = self._parse_test_output(result, config)
            test_result.duration = time.time() - start_time
            test_result.parallel_workers = config.parallel_workers

            # Cache result if enabled
            if config.cache_enabled:
                self.cache.cache_result(cache_key, test_result)

            # Store in history
            self.results_history.append(test_result)

            return test_result

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return BenchmarkTestResult(
                category=",".join(c.value for c in config.categories),
                total_tests=0,
                passed=0,
                failed=1,
                skipped=0,
                errors=1,
                warnings=0,
                duration=duration,
                parallel_workers=config.parallel_workers,
            )

    def _parse_test_output(
        self, result: subprocess.CompletedProcess, config: RunnerConfiguration
    ) -> BenchmarkTestResult:
        """Parse pytest output to extract test results."""
        output = result.stdout + result.stderr

        # Default values
        total_tests = 0
        passed = 0
        failed = 0
        skipped = 0
        errors = 0
        warnings = 0

        # Parse pytest output
        lines = output.split("\n")
        for line in lines:
            if "passed" in line and "failed" in line:
                # Summary line like "5 passed, 2 failed, 1 skipped"
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == "passed" and i > 0:
                        passed = int(parts[i - 1])
                    elif part == "failed" and i > 0:
                        failed = int(parts[i - 1])
                    elif part == "skipped" and i > 0:
                        skipped = int(parts[i - 1])
                    elif part == "error" and i > 0:
                        errors = int(parts[i - 1])
                break

        # Count warnings
        warnings = output.count("warning")

        # Calculate total
        total_tests = passed + failed + skipped + errors

        return BenchmarkTestResult(
            category=",".join(c.value for c in config.categories),
            total_tests=total_tests,
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            warnings=warnings,
            duration=0.0,  # Will be set by caller
            parallel_workers=config.parallel_workers,
        )

    def run_ci_mode(self) -> dict[str, BenchmarkTestResult]:
        """Run tests for CI/CD environment."""
        results = {}

        # Fast tests first
        print("Running fast tests...")
        fast_config = RunnerConfiguration(
            categories=[BenchmarkCategory.FAST],
            parallel_workers=4,
            cache_enabled=False,
            verbose=False,
            fail_fast=True,
            coverage=False,
            benchmark=False,
            output_format="junit",
            markers=[],
            exclude_markers=["slow"],
            max_duration=300.0,  # 5 minutes
            memory_limit=None,
        )
        results["fast"] = self.execute_tests(fast_config)

        # If fast tests pass, run slow tests
        if results["fast"].failed == 0:
            print("Running slow tests...")
            slow_config = RunnerConfiguration(
                categories=[BenchmarkCategory.SLOW],
                parallel_workers=2,
                cache_enabled=False,
                verbose=False,
                fail_fast=False,
                coverage=True,
                benchmark=False,
                output_format="junit",
                markers=["slow"],
                exclude_markers=[],
                max_duration=900.0,  # 15 minutes
                memory_limit=None,
            )
            results["slow"] = self.execute_tests(slow_config)

        return results

    def run_development_mode(self) -> dict[str, BenchmarkTestResult]:
        """Run tests optimized for development environment."""
        results = {}

        # Unit tests with caching
        print("Running unit tests...")
        unit_config = RunnerConfiguration(
            categories=[BenchmarkCategory.UNIT],
            parallel_workers=2,
            cache_enabled=True,
            verbose=True,
            fail_fast=True,
            coverage=False,
            benchmark=False,
            output_format="term",
            markers=[],
            exclude_markers=["slow"],
            max_duration=120.0,  # 2 minutes
            memory_limit=None,
        )
        results["unit"] = self.execute_tests(unit_config)

        return results

    def generate_report(self, results: dict[str, BenchmarkTestResult]) -> str:
        """Generate test execution report."""
        report = []
        report.append("# Test Execution Report")
        report.append(f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")

        total_duration = 0.0
        total_tests = 0
        total_passed = 0
        total_failed = 0

        for category, result in results.items():
            total_duration += result.duration
            total_tests += result.total_tests
            total_passed += result.passed
            total_failed += result.failed

            cache_status = "✅ (cached)" if result.cache_hit else "❌ (executed)"

            report.append(f"## {category.upper()} Tests")
            report.append(f"- Duration: {result.duration:.2f}s")
            report.append(f"- Workers: {result.parallel_workers}")
            report.append(f"- Cache: {cache_status}")
            report.append(f"- Total: {result.total_tests}")
            report.append(f"- Passed: {result.passed}")
            report.append(f"- Failed: {result.failed}")
            report.append(f"- Skipped: {result.skipped}")
            report.append(f"- Errors: {result.errors}")
            report.append(f"- Warnings: {result.warnings}")
            report.append("")

        report.append("## Summary")
        report.append(f"- Total Duration: {total_duration:.2f}s")
        report.append(f"- Total Tests: {total_tests}")
        report.append(f"- Total Passed: {total_passed}")
        report.append(f"- Total Failed: {total_failed}")
        report.append(
            f"- Success Rate: {(total_passed / total_tests * 100):.1f}%" if total_tests > 0 else "- Success Rate: 0%"
        )

        return "\n".join(report)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Enhanced test runner for BenchBox")
    parser.add_argument(
        "--categories",
        nargs="+",
        choices=[c.value for c in BenchmarkCategory],
        default=["unit"],
        help="Test categories to run",
    )
    parser.add_argument("--workers", type=int, default=2, help="Number of parallel workers")
    parser.add_argument("--no-cache", action="store_true", help="Disable result caching")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--fail-fast", "-x", action="store_true", help="Stop on first failure")
    parser.add_argument("--coverage", action="store_true", help="Run with coverage")
    parser.add_argument("--benchmark", action="store_true", help="Run benchmark tests only")
    parser.add_argument(
        "--output-format",
        choices=["term", "json", "junit"],
        default="term",
        help="Output format",
    )
    parser.add_argument("--markers", nargs="+", default=[], help="Include tests with these markers")
    parser.add_argument(
        "--exclude-markers",
        nargs="+",
        default=[],
        help="Exclude tests with these markers",
    )
    parser.add_argument("--max-duration", type=float, help="Maximum test duration in seconds")
    parser.add_argument("--ci", action="store_true", help="Run in CI mode")
    parser.add_argument("--dev", action="store_true", help="Run in development mode")
    parser.add_argument("--clear-cache", action="store_true", help="Clear test cache")
    parser.add_argument("--report", action="store_true", help="Generate execution report")

    args = parser.parse_args()

    # Initialize runner
    runner = BenchmarkRunner()

    # Clear cache if requested
    if args.clear_cache:
        runner.cache.clear_cache()
        print("Test cache cleared")
        return

    # Run tests
    results = {}

    if args.ci:
        results = runner.run_ci_optimized()
    elif args.dev:
        results = runner.run_development_optimized()
    else:
        # Custom configuration
        config = RunnerConfiguration(
            categories=[BenchmarkCategory(c) for c in args.categories],
            parallel_workers=args.workers,
            cache_enabled=not args.no_cache,
            verbose=args.verbose,
            fail_fast=args.fail_fast,
            coverage=args.coverage,
            benchmark=args.benchmark,
            output_format=args.output_format,
            markers=args.markers,
            exclude_markers=args.exclude_markers,
            max_duration=args.max_duration,
            memory_limit=None,
        )
        results["custom"] = runner.execute_tests(config)

    # Generate report if requested
    if args.report:
        report = runner.generate_report(results)
        print(report)

        # Save report to file
        report_file = Path("test_execution_report.md")
        report_file.write_text(report, encoding="utf-8")
        print(f"\nReport saved to: {report_file}")

    # Exit with appropriate code
    total_failed = sum(r.failed for r in results.values())
    sys.exit(0 if total_failed == 0 else 1)


if __name__ == "__main__":
    main()
