"""Unified benchmark suite for cross-platform comparisons.

Provides a single interface for running benchmarks across both SQL and
DataFrame platforms with unified result collection and reporting.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import json
import logging
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from benchbox.core.comparison.types import (
    PlatformType,
    UnifiedBenchmarkConfig,
    UnifiedComparisonSummary,
    UnifiedPlatformResult,
    UnifiedQueryResult,
    detect_platform_types,
)

logger = logging.getLogger(__name__)


#: Sentinel query id recorded when a platform fails before running any query.
FAILED_PLATFORM_QUERY_ID = "ALL"


class PlatformRunner(Protocol):
    """Runs one benchmark on one platform and returns its BenchmarkResults.

    Implemented by the surface (see ``benchbox.cli.commands.compare``) so
    ``benchbox.core`` stays free of a ``benchbox.cli`` import.
    """

    def __call__(
        self,
        *,
        platform: str,
        benchmark: str,
        scale_factor: float,
        query_ids: list[str] | None,
        iterations: int,
        data_dir: str | Path | None,
    ) -> Any: ...


def _query_sort_key(query_id: str) -> tuple[int, float, str]:
    """Sort query ids numerically when possible, alphabetically otherwise."""
    text = query_id[1:] if query_id[:1].upper() == "Q" else query_id
    try:
        return (0, float(text), "")
    except ValueError:
        return (1, 0.0, query_id)


class UnifiedBenchmarkSuite:
    """Unified benchmark suite for SQL and DataFrame platform comparisons.

    Provides a single interface for:
    - Running benchmarks across multiple platforms
    - Collecting and normalizing results
    - Statistical analysis
    - Report generation

    Example:
        suite = UnifiedBenchmarkSuite(
            config=UnifiedBenchmarkConfig(
                platform_type=PlatformType.AUTO,
                scale_factor=0.01,
                benchmark="tpch",
            )
        )

        # Run comparison
        results = suite.run_comparison(
            platforms=["duckdb", "sqlite"],  # SQL platforms
            data_dir="benchmark_runs/tpch/sf001/data",
        )

        # Get summary
        summary = suite.get_summary(results)
        emit(f"Fastest: {summary.fastest_platform}")
    """

    def __init__(
        self,
        config: UnifiedBenchmarkConfig | None = None,
        platform_runner: PlatformRunner | None = None,
    ):
        """Initialize the unified benchmark suite.

        Args:
            config: Benchmark configuration. Defaults to standard config.
            platform_runner: Callable that runs one benchmark on one platform
                and returns its ``BenchmarkResults``. The surface injects this
                -- ``benchbox.core`` must not import ``benchbox.cli``, so the
                orchestrator wiring lives in the CLI, mirroring the
                ``execute_run(adapter_factory=...)`` contract in
                ``benchbox.core.run_service``. Without it, SQL run mode cannot
                execute and raises rather than reporting an empty success.
        """
        self.config = config or UnifiedBenchmarkConfig()
        self._platform_runner = platform_runner

    def get_available_platforms(self, platform_type: PlatformType | None = None) -> list[str]:
        """Get available platforms of the specified type.

        Args:
            platform_type: Filter by platform type. None returns all.

        Returns:
            List of available platform names.
        """
        platforms = []

        # Get SQL platforms
        if platform_type in (None, PlatformType.SQL, PlatformType.AUTO):
            from benchbox.platforms import list_available_platforms

            sql_available = list_available_platforms()
            platforms.extend(sql_available)

        # Get DataFrame platforms
        if platform_type in (None, PlatformType.DATAFRAME, PlatformType.AUTO):
            from benchbox.platforms import list_available_dataframe_platforms

            df_available = list_available_dataframe_platforms()
            platforms.extend([name for name, available in df_available.items() if available])

        return sorted(set(platforms))

    def run_comparison(
        self,
        platforms: list[str],
        data_dir: str | Path | None = None,
    ) -> list[UnifiedPlatformResult]:
        """Run benchmark comparison across multiple platforms.

        Args:
            platforms: List of platform names to benchmark
            data_dir: Directory containing benchmark data (for DataFrame platforms)

        Returns:
            List of UnifiedPlatformResult for each platform
        """
        if not platforms:
            raise ValueError("At least one platform is required")

        # Detect platform type if auto
        if self.config.platform_type == PlatformType.AUTO:
            detected_type, inconsistent = detect_platform_types(platforms)
            if inconsistent:
                raise ValueError(
                    f"Mixed platform types detected. "
                    f"Cannot compare {detected_type.value} platforms with: {inconsistent}. "
                    f"Use --type to explicitly specify platform type."
                )
            platform_type = detected_type
        else:
            platform_type = self.config.platform_type

        logger.info(f"Running {platform_type.value} comparison across {len(platforms)} platforms")

        # Route to appropriate benchmark runner
        if platform_type == PlatformType.DATAFRAME:
            return self._run_dataframe_comparison(platforms, data_dir)
        else:
            return self._run_sql_comparison(platforms, data_dir)

    def _run_sql_comparison(
        self,
        platforms: list[str],
        data_dir: str | Path | None = None,
    ) -> list[UnifiedPlatformResult]:
        """Run SQL platform comparison.

        Args:
            platforms: SQL platform names
            data_dir: Data directory (for embedded platforms)

        Returns:
            List of results for each platform
        """
        results = []

        for platform in platforms:
            logger.info(f"Benchmarking SQL platform: {platform}")
            try:
                result = self._benchmark_sql_platform(platform, data_dir)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to benchmark {platform}: {e}")
                # Build through _build_platform_result so the aggregates match
                # the failure: success_rate 0, no geomean, no total time. A
                # directly-constructed result kept the dataclass default and
                # reported a failed platform as 100% successful.
                results.append(
                    self._build_platform_result(
                        platform,
                        PlatformType.SQL,
                        [
                            UnifiedQueryResult(
                                query_id=FAILED_PLATFORM_QUERY_ID,
                                platform=platform,
                                platform_type=PlatformType.SQL,
                                status="ERROR",
                                error_message=str(e),
                            )
                        ],
                    )
                )

        return results

    def _benchmark_sql_platform(
        self,
        platform: str,
        data_dir: str | Path | None = None,
    ) -> UnifiedPlatformResult:
        """Benchmark a single SQL platform through the canonical run path.

        Delegates to :meth:`benchbox.cli.orchestrator.BenchmarkOrchestrator.execute_benchmark`
        -- the same entry point ``benchbox run`` uses -- so data generation,
        schema creation, loading, adapter configuration and phase handling are
        shared with the single-platform command rather than reimplemented here.

        The previous implementation was a hardcoded TPC-H path that required
        pre-generated data at a guessed directory, never generated data, and
        never reached a real runner, so the documented
        ``benchbox compare -p duckdb -p sqlite`` invocation could not work.

        Args:
            platform: Platform name
            data_dir: Optional pre-existing data directory. When given it is
                passed through as the benchmark output root.

        Returns:
            UnifiedPlatformResult with real per-query timings

        Raises:
            Exception: Any failure from the run path, so the caller records the
                platform as failed rather than silently successful.
        """
        results = self._execute_platform_run(platform, data_dir)
        query_results = self._to_unified_query_results(results, platform)
        return self._build_platform_result(platform, PlatformType.SQL, query_results)

    def _execute_platform_run(self, platform: str, data_dir: str | Path | None):
        """Run one benchmark on one platform through the injected runner.

        Raises:
            RuntimeError: When no runner was injected. The caller records the
                platform as failed rather than reporting a vacuous success.
        """
        if self._platform_runner is None:
            raise RuntimeError(
                "No platform runner configured for SQL comparison. "
                "Construct UnifiedBenchmarkSuite with platform_runner=... "
                "(the CLI supplies one via benchbox.cli.commands.compare)."
            )
        return self._platform_runner(
            platform=platform,
            benchmark=self.config.benchmark,
            scale_factor=self.config.scale_factor,
            query_ids=self._normalized_query_ids(),
            iterations=self.config.benchmark_iterations,
            data_dir=data_dir,
        )

    def _normalized_query_ids(self) -> list[str] | None:
        """Return configured query ids in the form the run path expects.

        The comparison surface accepts ``Q1`` style ids; the run path expects
        bare ids (``1``). ``None`` means every query in the benchmark.
        """
        if not self.config.query_ids:
            return None
        normalized = []
        for qid in self.config.query_ids:
            text = str(qid).strip()
            normalized.append(text[1:] if text[:1].upper() == "Q" and text[1:] else text)
        return normalized

    @staticmethod
    def _to_unified_query_results(results: Any, platform: str) -> list[UnifiedQueryResult]:
        """Convert a BenchmarkResults into per-query comparison records.

        Measurement iterations for one query id are folded into a single
        :class:`UnifiedQueryResult`. Warmup rows are excluded so they cannot
        distort the comparison. A query whose every iteration failed is kept
        with ``status="ERROR"`` so it counts against the success rate instead
        of vanishing from the denominator.
        """
        by_query: dict[str, dict[str, Any]] = {}
        for row in getattr(results, "query_results", None) or []:
            if not isinstance(row, dict):
                continue
            if row.get("run_type") == "warmup":
                continue
            query_id = str(row.get("query_id") or row.get("id") or "")
            if not query_id:
                continue
            bucket = by_query.setdefault(query_id, {"times": [], "rows": 0, "errors": []})
            if row.get("status") == "SUCCESS":
                seconds = row.get("execution_time_seconds")
                if seconds is None:
                    seconds = row.get("execution_time")
                if seconds is not None:
                    bucket["times"].append(float(seconds) * 1000.0)
                elif row.get("execution_time_ms") is not None:
                    bucket["times"].append(float(row["execution_time_ms"]))
                bucket["rows"] = bucket["rows"] or int(row.get("rows_returned") or 0)
            else:
                bucket["errors"].append(str(row.get("error") or row.get("error_message") or "query failed"))

        query_results: list[UnifiedQueryResult] = []
        for query_id, bucket in sorted(by_query.items(), key=lambda kv: _query_sort_key(kv[0])):
            times = bucket["times"]
            if not times:
                query_results.append(
                    UnifiedQueryResult(
                        query_id=query_id,
                        platform=platform,
                        platform_type=PlatformType.SQL,
                        status="ERROR",
                        error_message=bucket["errors"][0] if bucket["errors"] else "no measurement iteration",
                    )
                )
                continue
            query_results.append(
                UnifiedQueryResult(
                    query_id=query_id,
                    platform=platform,
                    platform_type=PlatformType.SQL,
                    iterations=len(times),
                    execution_times_ms=times,
                    mean_time_ms=statistics.mean(times),
                    std_time_ms=statistics.stdev(times) if len(times) > 1 else 0.0,
                    min_time_ms=min(times),
                    max_time_ms=max(times),
                    rows_returned=bucket["rows"],
                    status="SUCCESS",
                )
            )
        return query_results

    def _run_dataframe_comparison(
        self,
        platforms: list[str],
        data_dir: str | Path | None = None,
    ) -> list[UnifiedPlatformResult]:
        """Run DataFrame platform comparison.

        Delegates to the existing DataFrameBenchmarkSuite.

        Args:
            platforms: DataFrame platform names
            data_dir: Data directory

        Returns:
            List of results for each platform
        """
        from benchbox.core.dataframe.benchmark_suite import (
            BenchmarkConfig,
            DataFrameBenchmarkSuite,
        )

        # Create DataFrame benchmark config
        df_config = BenchmarkConfig(
            scale_factor=self.config.scale_factor,
            query_ids=self.config.query_ids,
            warmup_iterations=self.config.warmup_iterations,
            benchmark_iterations=self.config.benchmark_iterations,
            track_memory=self.config.track_memory,
            timeout_seconds=self.config.timeout_seconds,
        )

        suite = DataFrameBenchmarkSuite(config=df_config)

        if data_dir is None:
            sf_str = f"sf{self.config.scale_factor}".replace(".", "")
            data_dir = Path(f"benchmark_runs/tpch/{sf_str}/data")

        # Run DataFrame comparison
        df_results = suite.run_comparison(platforms=platforms, data_dir=data_dir)

        # Convert to unified format
        unified_results = []
        for df_result in df_results:
            query_results = []
            for qr in df_result.query_results:
                query_results.append(
                    UnifiedQueryResult(
                        query_id=qr.query_id,
                        platform=qr.platform,
                        platform_type=PlatformType.DATAFRAME,
                        iterations=qr.iterations,
                        execution_times_ms=qr.execution_times_ms,
                        mean_time_ms=qr.mean_time_ms,
                        std_time_ms=qr.std_time_ms,
                        min_time_ms=qr.min_time_ms,
                        max_time_ms=qr.max_time_ms,
                        memory_peak_mb=qr.memory_peak_mb,
                        rows_returned=qr.rows_returned,
                        status=qr.status,
                        error_message=qr.error_message,
                    )
                )

            unified_results.append(
                UnifiedPlatformResult(
                    platform=df_result.platform,
                    platform_type=PlatformType.DATAFRAME,
                    query_results=query_results,
                    total_time_ms=df_result.total_time_ms,
                    geometric_mean_ms=df_result.geometric_mean_ms,
                    success_rate=df_result.success_rate,
                )
            )

        return unified_results

    def _build_platform_result(
        self,
        platform: str,
        platform_type: PlatformType,
        query_results: list[UnifiedQueryResult],
    ) -> UnifiedPlatformResult:
        """Build platform result with calculated aggregates.

        Args:
            platform: Platform name
            platform_type: Platform type
            query_results: Query results

        Returns:
            UnifiedPlatformResult with aggregates
        """
        successful = [r for r in query_results if r.status == "SUCCESS"]

        # Calculate total time and geometric mean
        total_time = sum(r.mean_time_ms for r in successful)
        geometric_mean = 0.0

        if successful:
            mean_times = [r.mean_time_ms for r in successful if r.mean_time_ms > 0]
            if mean_times:
                log_sum = sum(math.log(t) for t in mean_times)
                geometric_mean = math.exp(log_sum / len(mean_times))

        # Calculate success rate
        success_rate = (len(successful) / len(query_results) * 100) if query_results else 0

        return UnifiedPlatformResult(
            platform=platform,
            platform_type=platform_type,
            query_results=query_results,
            total_time_ms=total_time,
            geometric_mean_ms=geometric_mean,
            success_rate=success_rate,
        )

    def get_summary(self, results: list[UnifiedPlatformResult]) -> UnifiedComparisonSummary:
        """Generate comparison summary from results.

        Args:
            results: List of platform results

        Returns:
            UnifiedComparisonSummary with comparison metrics
        """
        if not results:
            raise ValueError("No results to summarize")

        platforms = [r.platform for r in results]
        platform_type = results[0].platform_type

        # Get geometric means for ranking
        geomeans = {r.platform: r.geometric_mean_ms for r in results if r.geometric_mean_ms > 0}

        if not geomeans:
            # Nothing timed successfully, so there is no ranking to report.
            # Naming platforms[0] as both fastest and slowest with a 1.00x
            # speedup presented total failure as a valid comparison.
            return UnifiedComparisonSummary(
                platforms=platforms,
                platform_type=platform_type,
                fastest_platform=None,
                slowest_platform=None,
                speedup_ratio=None,
                query_winners={},
                total_queries=0,
            )

        fastest = min(geomeans, key=geomeans.get)
        slowest = max(geomeans, key=geomeans.get)
        if len(geomeans) < 2:
            # Only one platform produced timings. It is not faster than
            # anything, so there is no ratio to report.
            slowest = None
            speedup_ratio = None
        else:
            speedup_ratio = geomeans[slowest] / geomeans[fastest] if geomeans[fastest] > 0 else None

        # Find query winners
        query_winners: dict[str, str] = {}
        all_query_ids = set()
        for result in results:
            for qr in result.query_results:
                # ALL is the sentinel for "this platform failed before running
                # any query"; counting it would inflate the query total.
                if qr.query_id == FAILED_PLATFORM_QUERY_ID:
                    continue
                all_query_ids.add(qr.query_id)

        for query_id in all_query_ids:
            best_time = float("inf")
            best_platform = ""
            for result in results:
                for qr in result.query_results:
                    if qr.query_id == query_id and qr.status == "SUCCESS" and qr.mean_time_ms < best_time:
                        best_time = qr.mean_time_ms
                        best_platform = result.platform
            if best_platform:
                query_winners[query_id] = best_platform

        return UnifiedComparisonSummary(
            platforms=platforms,
            platform_type=platform_type,
            fastest_platform=fastest,
            slowest_platform=slowest,
            speedup_ratio=speedup_ratio,
            query_winners=query_winners,
            total_queries=len(all_query_ids),
        )

    def export_results(
        self,
        results: list[UnifiedPlatformResult],
        output_path: str | Path,
        format: str = "json",
    ) -> Path:
        """Export benchmark results to file.

        Args:
            results: List of platform results
            output_path: Output file path
            format: Output format (json, markdown, text)

        Returns:
            Path to created file
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if format == "json":
            data = {
                "benchmark_suite": "unified_comparison",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "config": {
                    "platform_type": self.config.platform_type.value,
                    "scale_factor": self.config.scale_factor,
                    "benchmark": self.config.benchmark,
                    "query_ids": self.config.query_ids,
                    "warmup_iterations": self.config.warmup_iterations,
                    "benchmark_iterations": self.config.benchmark_iterations,
                },
                "results": [r.to_dict() for r in results],
                "summary": self.get_summary(results).to_dict() if results else None,
            }
            output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        elif format == "markdown":
            content = self._generate_markdown_report(results)
            output_path.write_text(content, encoding="utf-8")

        elif format == "text":
            content = self._generate_text_report(results)
            output_path.write_text(content, encoding="utf-8")

        else:
            raise ValueError(f"Unsupported export format: {format}")

        return output_path

    def _generate_markdown_report(self, results: list[UnifiedPlatformResult]) -> str:
        """Generate markdown report from results."""
        lines = []
        summary = self.get_summary(results)

        lines.append("# Platform Comparison Report")
        lines.append("")
        lines.append(f"**Platform Type:** {summary.platform_type.value}")
        lines.append(f"**Scale Factor:** {self.config.scale_factor}")
        lines.append(f"**Benchmark:** {self.config.benchmark}")
        lines.append(f"**Iterations:** {self.config.benchmark_iterations}")
        lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        if summary.speedup_ratio is not None:
            lines.append(f"**Fastest Platform:** {summary.fastest_platform}")
            lines.append(f"**Slowest Platform:** {summary.slowest_platform}")
            lines.append(f"**Speedup Ratio:** {summary.speedup_ratio:.2f}x")
        elif summary.is_comparable:
            lines.append(f"**Fastest Platform:** {summary.fastest_platform} (only platform with timings)")
            lines.append("**Slowest Platform:** n/a")
            lines.append("**Speedup Ratio:** n/a - nothing to compare against")
        else:
            lines.append("**Fastest Platform:** n/a - no platform produced a usable timing")
            lines.append("**Slowest Platform:** n/a")
            lines.append("**Speedup Ratio:** n/a")
        lines.append("")

        lines.append("## Platform Results")
        lines.append("")
        lines.append("| Platform | Geomean (ms) | Total (ms) | Success Rate |")
        lines.append("|----------|--------------|------------|--------------|")

        for result in sorted(results, key=lambda r: r.geometric_mean_ms or float("inf")):
            geomean = f"{result.geometric_mean_ms:.2f}" if result.geometric_mean_ms else "N/A"
            total = f"{result.total_time_ms:.2f}" if result.total_time_ms else "N/A"
            success = f"{result.success_rate:.1f}%"
            lines.append(f"| {result.platform} | {geomean} | {total} | {success} |")

        lines.append("")

        if summary.query_winners:
            lines.append("## Query Winners")
            lines.append("")
            for query_id, winner in sorted(summary.query_winners.items()):
                lines.append(f"- **{query_id}**: {winner}")
            lines.append("")

        return "\n".join(lines)

    def _generate_text_report(self, results: list[UnifiedPlatformResult]) -> str:
        """Generate text report from results."""
        lines = []
        summary = self.get_summary(results)

        lines.append("=" * 60)
        lines.append("PLATFORM COMPARISON RESULTS")
        lines.append("=" * 60)
        lines.append("")

        lines.append(f"Platform Type: {summary.platform_type.value}")
        lines.append(f"Platforms: {', '.join(summary.platforms)}")
        lines.append(f"Total Queries: {summary.total_queries}")
        lines.append("")

        if summary.speedup_ratio is not None:
            lines.append(f"Fastest: {summary.fastest_platform}")
            lines.append(f"Slowest: {summary.slowest_platform}")
            lines.append(f"Speedup: {summary.speedup_ratio:.2f}x")
        elif summary.is_comparable:
            lines.append(f"Fastest: {summary.fastest_platform} (only platform with timings)")
            lines.append("Slowest: n/a")
            lines.append("Speedup: n/a - nothing to compare against")
        else:
            lines.append("Fastest: n/a - no platform produced a usable timing")
            lines.append("Slowest: n/a")
            lines.append("Speedup: n/a")
        lines.append("")

        lines.append(f"{'Platform':15s} {'Geomean (ms)':>15s} {'Total (ms)':>15s} {'Success':>10s}")
        lines.append("-" * 60)

        for result in sorted(results, key=lambda r: r.geometric_mean_ms or float("inf")):
            geomean = f"{result.geometric_mean_ms:.2f}" if result.geometric_mean_ms else "N/A"
            total = f"{result.total_time_ms:.2f}" if result.total_time_ms else "N/A"
            success = f"{result.success_rate:.0f}%"
            lines.append(f"{result.platform:15s} {geomean:>15s} {total:>15s} {success:>10s}")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)


def run_unified_comparison(
    platforms: list[str],
    platform_type: PlatformType = PlatformType.AUTO,
    scale_factor: float = 0.01,
    benchmark: str = "tpch",
    query_ids: list[str] | None = None,
    data_dir: str | Path | None = None,
    platform_runner: PlatformRunner | None = None,
) -> list[UnifiedPlatformResult]:
    """Run a unified cross-platform comparison.

    Convenience function for quick comparisons.

    Args:
        platforms: Platforms to compare
        platform_type: SQL, DATAFRAME, or AUTO
        scale_factor: Benchmark scale factor
        benchmark: Benchmark name
        query_ids: Optional query subset
        data_dir: Data directory

    Returns:
        List of UnifiedPlatformResult
    """
    suite = UnifiedBenchmarkSuite(
        config=UnifiedBenchmarkConfig(
            platform_type=platform_type,
            scale_factor=scale_factor,
            benchmark=benchmark,
            query_ids=query_ids,
        ),
        platform_runner=platform_runner,
    )
    return suite.run_comparison(platforms=platforms, data_dir=data_dir)


__all__ = [
    "PlatformRunner",
    "UnifiedBenchmarkSuite",
    "run_unified_comparison",
]
