#!/usr/bin/env python3
"""Analyze pytest timing output and generate test reclassification report.

This script parses pytest --durations output to identify tests that should be
reclassified from 'fast' to 'medium' or 'slow' based on actual execution time.

Usage:
    # First, collect timing data:
    uv run -- python -m pytest tests -m "fast" --durations=0 -v --tb=no -q \
      --ignore=tests/unit/platforms/pyspark \
      --ignore=tests/unit/platforms/dataframe/test_pyspark_df.py \
      2>&1 | tee _project/timing_report.txt

    # Then analyze:
    uv run -- python scripts/analyze_test_timings.py _project/timing_report.txt \
      --output _project/reclassification.yaml

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Default speed thresholds in seconds (can be overridden via CLI)
DEFAULT_FAST_THRESHOLD = 1.0  # Tests < 1s are "fast"
DEFAULT_MEDIUM_THRESHOLD = 10.0  # Tests 1-10s are "medium", >10s are "slow"

# Runtime thresholds (set by main())
_fast_threshold = DEFAULT_FAST_THRESHOLD
_medium_threshold = DEFAULT_MEDIUM_THRESHOLD

# Regex to parse pytest --durations output
# Matches lines like: "0.52s call     tests/unit/foo/test_bar.py::test_something"
DURATION_PATTERN = re.compile(r"^\s*(\d+\.\d+)s\s+(call|setup|teardown)\s+(.+?::[\w\[\]]+)")


def get_speed_category(duration: float) -> str:
    """Categorize test by speed using current thresholds."""
    if duration < _fast_threshold:
        return "fast"
    elif duration < _medium_threshold:
        return "medium"
    else:
        return "slow"


@dataclass
class TestTiming:
    """Timing information for a single test."""

    test_path: str
    test_name: str
    duration: float
    phase: str = "call"  # call, setup, or teardown

    @property
    def full_name(self) -> str:
        return f"{self.test_path}::{self.test_name}"

    @property
    def module_path(self) -> str:
        """Get the module path (file path without test name)."""
        return self.test_path

    @property
    def speed_category(self) -> str:
        """Categorize test by speed."""
        return get_speed_category(self.duration)


@dataclass
class ModuleStats:
    """Aggregate statistics for a test module."""

    path: str
    tests: list[TestTiming] = field(default_factory=list)

    @property
    def total_duration(self) -> float:
        return sum(t.duration for t in self.tests)

    @property
    def test_count(self) -> int:
        return len(self.tests)

    @property
    def max_duration(self) -> float:
        return max((t.duration for t in self.tests), default=0.0)

    @property
    def avg_duration(self) -> float:
        if not self.tests:
            return 0.0
        return self.total_duration / len(self.tests)

    @property
    def slow_test_count(self) -> int:
        return sum(1 for t in self.tests if t.duration >= _fast_threshold)

    @property
    def recommended_marker(self) -> str:
        """Recommend a marker based on test durations."""
        # If any test is slow (>10s), mark module as slow
        if any(t.duration >= _medium_threshold for t in self.tests):
            return "slow"
        # If most tests are medium speed, mark as medium
        if self.slow_test_count > len(self.tests) / 2:
            return "medium"
        # If max duration is >1s, mark as medium
        if self.max_duration >= _fast_threshold:
            return "medium"
        return "fast"


def parse_duration_line(line: str) -> TestTiming | None:
    """Parse a single duration line from pytest output."""
    match = DURATION_PATTERN.match(line.strip())
    if not match:
        return None

    duration = float(match.group(1))
    phase = match.group(2)
    full_path = match.group(3)

    # Split path::test_name
    if "::" in full_path:
        parts = full_path.split("::")
        test_path = parts[0]
        test_name = "::".join(parts[1:])
    else:
        test_path = full_path
        test_name = ""

    return TestTiming(
        test_path=test_path,
        test_name=test_name,
        duration=duration,
        phase=phase,
    )


def parse_timing_report(report_path: Path) -> list[TestTiming]:
    """Parse pytest --durations output file."""
    timings = []
    in_durations_section = False

    with open(report_path, encoding="utf-8") as f:
        for line in f:
            # Detect start of durations section
            if "slowest" in line.lower() and "durations" in line.lower():
                in_durations_section = True
                continue

            # Detect end of durations section (empty line or summary)
            if in_durations_section and (
                line.strip() == "" or line.startswith("=") or "passed" in line.lower() or "failed" in line.lower()
            ):
                # Check if this is actually a test timing line
                timing = parse_duration_line(line)
                if timing and timing.phase == "call":
                    timings.append(timing)
                continue

            if in_durations_section:
                timing = parse_duration_line(line)
                if timing and timing.phase == "call":  # Only count "call" phase
                    timings.append(timing)

    return timings


def aggregate_by_module(timings: list[TestTiming]) -> dict[str, ModuleStats]:
    """Group timings by module path."""
    modules: dict[str, ModuleStats] = defaultdict(lambda: ModuleStats(path=""))

    for timing in timings:
        path = timing.module_path
        if not modules[path].path:
            modules[path] = ModuleStats(path=path)
        modules[path].tests.append(timing)

    return dict(modules)


def aggregate_by_directory(modules: dict[str, ModuleStats]) -> dict[str, list[ModuleStats]]:
    """Group modules by parent directory."""
    directories: dict[str, list[ModuleStats]] = defaultdict(list)

    for module in modules.values():
        # Get parent directory path
        path = Path(module.path)
        parent = str(path.parent)
        directories[parent].append(module)

    return dict(directories)


def identify_patterns(timings: list[TestTiming]) -> dict[str, list[str]]:
    """Identify common patterns in slow tests."""
    patterns = {
        "subprocess": [],  # Tests that spawn subprocesses (CLI tests)
        "database": [],  # Database-related tests
        "generator": [],  # Data generation tests
        "heavy_import": [],  # Tests with heavy import overhead
        "parameterized": [],  # Heavily parameterized tests
    }

    for timing in timings:
        if timing.duration < _fast_threshold:
            continue

        path_lower = timing.full_name.lower()

        # CLI tests typically spawn subprocesses
        if "cli" in path_lower or "subprocess" in path_lower:
            patterns["subprocess"].append(timing.full_name)
        # Generator tests are typically slow
        elif "generator" in path_lower or "datagen" in path_lower:
            patterns["generator"].append(timing.full_name)
        # Database tests
        elif "database" in path_lower or "db" in path_lower or "duckdb" in path_lower:
            patterns["database"].append(timing.full_name)
        # Parameterized tests (indicated by [param] in name)
        elif "[" in timing.test_name:
            patterns["parameterized"].append(timing.full_name)
        # Default to heavy import
        else:
            patterns["heavy_import"].append(timing.full_name)

    return {k: v for k, v in patterns.items() if v}


def generate_report(
    timings: list[TestTiming],
    modules: dict[str, ModuleStats],
) -> dict:
    """Generate the reclassification report."""
    # Categorize tests
    fast_tests = [t for t in timings if t.speed_category == "fast"]
    medium_tests = [t for t in timings if t.speed_category == "medium"]
    slow_tests = [t for t in timings if t.speed_category == "slow"]

    # Find modules needing reclassification
    modules_needing_medium = [m for m in modules.values() if m.recommended_marker == "medium" and m.slow_test_count > 0]
    modules_needing_slow = [m for m in modules.values() if m.recommended_marker == "slow"]

    # Sort by total duration (slowest first)
    modules_needing_medium.sort(key=lambda m: m.total_duration, reverse=True)
    modules_needing_slow.sort(key=lambda m: m.total_duration, reverse=True)

    # Identify patterns
    patterns = identify_patterns(timings)

    report = {
        "summary": {
            "total_tests": len(timings),
            "fast_tests": len(fast_tests),
            "medium_tests": len(medium_tests),
            "slow_tests": len(slow_tests),
            "total_duration_seconds": sum(t.duration for t in timings),
            "thresholds": {
                "fast": f"< {_fast_threshold}s",
                "medium": f"{_fast_threshold}s - {_medium_threshold}s",
                "slow": f"> {_medium_threshold}s",
            },
        },
        "modules_to_mark_medium": [
            {
                "path": m.path,
                "test_count": m.test_count,
                "total_duration": round(m.total_duration, 2),
                "max_duration": round(m.max_duration, 2),
                "avg_duration": round(m.avg_duration, 2),
                "slow_tests": m.slow_test_count,
            }
            for m in modules_needing_medium[:30]  # Top 30
        ],
        "modules_to_mark_slow": [
            {
                "path": m.path,
                "test_count": m.test_count,
                "total_duration": round(m.total_duration, 2),
                "max_duration": round(m.max_duration, 2),
            }
            for m in modules_needing_slow
        ],
        "pattern_categories": {
            pattern: {
                "count": len(tests),
                "examples": tests[:5],  # First 5 examples
            }
            for pattern, tests in patterns.items()
        },
        "directory_recommendations": {},
    }

    # Aggregate directory recommendations
    directories = aggregate_by_directory(modules)
    for dir_path, dir_modules in directories.items():
        total_duration = sum(m.total_duration for m in dir_modules)
        if total_duration > 5.0:  # Only include directories with >5s total
            markers_needed = [m.recommended_marker for m in dir_modules if m.recommended_marker != "fast"]
            if markers_needed:
                report["directory_recommendations"][dir_path] = {
                    "module_count": len(dir_modules),
                    "total_duration": round(total_duration, 2),
                    "recommended_marker": ("slow" if "slow" in markers_needed else "medium"),
                }

    return report


def main():
    parser = argparse.ArgumentParser(description="Analyze pytest timing output for test reclassification")
    parser.add_argument(
        "timing_file",
        type=Path,
        help="Path to pytest --durations output file",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output YAML file path (default: stdout)",
    )
    parser.add_argument(
        "--fast-threshold",
        type=float,
        default=DEFAULT_FAST_THRESHOLD,
        help=f"Threshold for fast tests in seconds (default: {DEFAULT_FAST_THRESHOLD})",
    )
    parser.add_argument(
        "--medium-threshold",
        type=float,
        default=DEFAULT_MEDIUM_THRESHOLD,
        help=f"Threshold for medium tests in seconds (default: {DEFAULT_MEDIUM_THRESHOLD})",
    )

    args = parser.parse_args()

    # Update thresholds if provided
    global _fast_threshold, _medium_threshold
    _fast_threshold = args.fast_threshold
    _medium_threshold = args.medium_threshold

    if not args.timing_file.exists():
        print(f"Error: Timing file not found: {args.timing_file}", file=sys.stderr)
        sys.exit(1)

    # Parse timing data
    timings = parse_timing_report(args.timing_file)

    if not timings:
        print("Error: No timing data found in file", file=sys.stderr)
        print("Make sure to run pytest with --durations=0 flag", file=sys.stderr)
        sys.exit(1)

    # Aggregate by module
    modules = aggregate_by_module(timings)

    # Generate report
    report = generate_report(timings, modules)

    # Output
    yaml_output = yaml.dump(report, default_flow_style=False, sort_keys=False)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(yaml_output)
        print(f"Report written to: {args.output}")

        # Print summary to stdout
        print("\n=== Summary ===")
        print(f"Total tests analyzed: {report['summary']['total_tests']}")
        print(f"  Fast (< {_fast_threshold}s): {report['summary']['fast_tests']}")
        print(f"  Medium ({_fast_threshold}s - {_medium_threshold}s): {report['summary']['medium_tests']}")
        print(f"  Slow (> {_medium_threshold}s): {report['summary']['slow_tests']}")
        print(f"Total duration: {report['summary']['total_duration_seconds']:.1f}s")
        print(f"\nModules to mark 'medium': {len(report['modules_to_mark_medium'])}")
        print(f"Modules to mark 'slow': {len(report['modules_to_mark_slow'])}")
    else:
        print(yaml_output)


if __name__ == "__main__":
    main()
