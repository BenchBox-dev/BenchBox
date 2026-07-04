"""TPC-H Skew benchmark implementation module.

Provides TPC-H benchmark with configurable data skew for testing
database performance under realistic data distributions.

Based on the research: "Introducing Skew into the TPC-H Benchmark"
Reference: https://www.tpc.org/tpctc/tpctc2011/slides_and_papers/introducing_skew_into_the_tpc_h_benchmark.pdf

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from benchbox.core.tpch.benchmark import TPCHBenchmark
from benchbox.core.tpch_skew.generator import TPCHSkewDataGenerator
from benchbox.core.tpch_skew.skew_config import (
    SkewConfiguration,
    SkewPreset,
    get_preset_config,
)
from benchbox.utils.clock import elapsed_seconds, mono_time


class TPCHSkewBenchmark(TPCHBenchmark):
    """TPC-H Skew benchmark implementation.

    Extends TPC-H benchmark with configurable data skew to test
    database performance under realistic data distribution patterns.

    This benchmark generates TPC-H data with non-uniform distributions:
    - Attribute skew: Some values appear more frequently
    - Join skew: Some foreign key relationships are more common
    - Temporal skew: Some time periods have more activity

    The standard TPC-H queries (1-22) are used unchanged, allowing
    direct comparison between uniform and skewed data performance.

    Usage:
        >>> from benchbox import TPCHSkew
        >>> from benchbox.platforms.duckdb import DuckDBAdapter
        >>>
        >>> # Create benchmark with moderate skew
        >>> benchmark = TPCHSkew(scale_factor=1.0, skew_preset="moderate")
        >>>
        >>> # Or use custom configuration
        >>> from benchbox.core.tpch_skew import SkewConfiguration
        >>> config = SkewConfiguration(skew_factor=0.7, distribution_type="zipfian")
        >>> benchmark = TPCHSkew(scale_factor=1.0, skew_config=config)
        >>>
        >>> # Generate data and run queries
        >>> adapter = DuckDBAdapter(database=":memory:")
        >>> adapter.load_benchmark(benchmark)
        >>> results = adapter.run_benchmark(benchmark)

    Attributes:
        scale_factor: Scale factor (1.0 = ~1GB)
        output_dir: Data output directory
        skew_config: Skew configuration settings
        skew_preset: Name of preset used (if any)
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: str | Path | None = None,
        skew_preset: str | None = None,
        skew_config: SkewConfiguration | None = None,
        verbose: int | bool = 0,
        parallel: int = 1,
        force_regenerate: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize TPC-H Skew benchmark instance.

        Args:
            scale_factor: Scale factor (1.0 = ~1GB)
            output_dir: Data output directory
            skew_preset: Preset name ("none", "light", "moderate", "heavy", "extreme", "realistic")
            skew_config: Custom SkewConfiguration (overrides preset if both provided)
            verbose: Verbosity level
            parallel: Parallel processes for data generation
            force_regenerate: Force data regeneration
            **kwargs: Additional options

        Raises:
            ValueError: If both preset and config are invalid
        """
        # Determine skew configuration
        if skew_config is not None:
            self.skew_config = skew_config
            self.skew_preset = "custom"
        elif skew_preset is not None:
            try:
                preset_enum = SkewPreset(skew_preset.lower())
            except ValueError:
                valid = [p.value for p in SkewPreset]
                raise ValueError(f"Invalid skew preset: {skew_preset}. Valid: {valid}") from None
            self.skew_config = get_preset_config(preset_enum)
            self.skew_preset = skew_preset.lower()
        else:
            # Default to moderate skew
            self.skew_config = get_preset_config(SkewPreset.MODERATE)
            self.skew_preset = "moderate"

        # Initialize parent class (TPC-H benchmark)
        super().__init__(
            scale_factor=scale_factor,
            output_dir=output_dir,
            verbose=verbose,
            parallel=parallel,
            force_regenerate=force_regenerate,
            **kwargs,
        )

        # Replace data generator with skewed version
        self.data_generator = TPCHSkewDataGenerator(
            scale_factor=scale_factor,
            output_dir=self.output_dir,
            skew_config=self.skew_config,
            verbose=verbose,
            quiet=kwargs.get("quiet", False),
            parallel=parallel,
            force_regenerate=force_regenerate,
        )

        # Update benchmark name
        self._name = f"TPC-H Skew Benchmark ({self.skew_preset})"

    def generate_data(self) -> list[Path | list[Path]]:
        """Generate TPC-H data with skew applied.

        Returns:
            List of paths to generated data files (may include sharded file lists)
        """
        self.log_verbose(f"Generating TPC-H Skew data (preset: {self.skew_preset})")
        self.log_verbose(f"Skew factor: {self.skew_config.skew_factor}")

        # Use the skewed data generator
        self.tables = self.data_generator.generate()

        if self.verbose_enabled:
            self.logger.info(f"Generated {len(self.tables)} skewed TPC-H tables:")
            for table_name, file_path in self.tables.items():
                self.logger.info(f"  - {table_name}: {file_path}")

        return list(self.tables.values())

    def get_skew_info(self) -> dict[str, Any]:
        """Get information about the skew configuration.

        Returns:
            Dictionary containing skew configuration details
        """
        return {
            "preset": self.skew_preset,
            "skew_factor": self.skew_config.skew_factor,
            "distribution_type": self.skew_config.distribution_type,
            "attribute_skew_enabled": self.skew_config.enable_attribute_skew,
            "join_skew_enabled": self.skew_config.enable_join_skew,
            "temporal_skew_enabled": self.skew_config.enable_temporal_skew,
            "config_summary": self.skew_config.get_skew_summary(),
        }

    def get_benchmark_info(self) -> dict[str, Any]:
        """Get information about the benchmark.

        Returns:
            Dictionary containing benchmark metadata
        """
        base_info = {
            "name": "TPC-H Skew Benchmark",
            "version": "1.0",
            "description": (
                "TPC-H benchmark with configurable data skew based on "
                "'Introducing Skew into the TPC-H Benchmark' research paper"
            ),
            "reference": (
                "https://www.tpc.org/tpctc/tpctc2011/slides_and_papers/introducing_skew_into_the_tpc_h_benchmark.pdf"
            ),
            "scale_factor": self.scale_factor,
            "num_queries": 22,
            "tables": ["region", "nation", "supplier", "customer", "part", "partsupp", "orders", "lineitem"],
        }
        base_info["skew_info"] = self.get_skew_info()
        return base_info

    def compare_with_uniform(
        self,
        adapter,
        queries: list[int] | None = None,
        iterations: int = 1,
    ) -> dict[str, Any]:
        """Run comparison between skewed and uniform TPC-H data.

        This method orchestrates running the same queries on both uniform
        (standard TPC-H) and skewed data to measure performance differences.
        It uses the existing TPCHBenchmark for uniform data generation.

        Args:
            adapter: Platform adapter to use for query execution
            queries: List of query IDs to run (default: all 22)
            iterations: Number of times to run each query for averaging (default: 1)

        Returns:
            Dictionary with comparison results:
            - queries: List of query IDs compared
            - scale_factor: Scale factor used
            - skew_preset: Skew preset name
            - skew_config: Skew configuration details
            - uniform_results: Query timing results on uniform data
            - skewed_results: Query timing results on skewed data
            - comparison: Per-query comparison with ratios
            - summary: Aggregate statistics

        Raises:
            ValueError: If adapter is None or queries list is invalid
            RuntimeError: If benchmark execution fails

        Example:
            >>> from benchbox import TPCHSkew
            >>> from benchbox.platforms.duckdb import DuckDBAdapter
            >>>
            >>> benchmark = TPCHSkew(scale_factor=0.01, skew_preset="heavy")
            >>> adapter = DuckDBAdapter(database=":memory:")
            >>>
            >>> # Compare queries 1, 6, and 14
            >>> results = benchmark.compare_with_uniform(adapter, queries=[1, 6, 14])
            >>> emit(results["summary"]["avg_skew_slowdown"])
        """
        from benchbox.core.tpch.benchmark import TPCHBenchmark

        if adapter is None:
            raise ValueError("adapter cannot be None")

        queries = self._validate_comparison_queries(queries, iterations)

        self.log_verbose("Starting uniform vs skewed comparison")
        self.log_verbose(f"  Queries: {queries}")
        self.log_verbose(f"  Scale factor: {self.scale_factor}")
        self.log_verbose(f"  Skew preset: {self.skew_preset}")
        self.log_verbose(f"  Iterations: {iterations}")

        query_subset = [str(q) for q in queries]

        uniform_benchmark = TPCHBenchmark(
            scale_factor=self.scale_factor,
            verbose=self.verbose,
            parallel=getattr(self, "parallel", 1),
        )

        results: dict[str, Any] = {
            "queries": queries,
            "scale_factor": self.scale_factor,
            "skew_preset": self.skew_preset,
            "skew_config": self.get_skew_info(),
            "iterations": iterations,
            "uniform_results": {},
            "skewed_results": {},
            "comparison": {},
            "summary": {},
        }

        # Phase 1: Run queries on uniform data
        self._run_benchmark_phase(
            adapter, uniform_benchmark, query_subset, results["uniform_results"], "uniform", "Phase 1"
        )

        # Phase 2: Run queries on skewed data
        self._run_benchmark_phase(adapter, self, query_subset, results["skewed_results"], "skewed", "Phase 2")

        # Phase 3: Compute comparison statistics
        self.log_verbose("Phase 3: Computing comparison statistics...")
        results["comparison"], results["summary"] = self._compute_comparison_stats(queries, results)

        self.log_verbose("Comparison complete")
        return results

    @staticmethod
    def _validate_comparison_queries(queries: list[int] | None, iterations: int) -> list[int]:
        """Validate and return query list for comparison."""
        if queries is None:
            queries = list(range(1, 23))
        else:
            invalid = [q for q in queries if not isinstance(q, int) or q < 1 or q > 22]
            if invalid:
                raise ValueError(f"Invalid query IDs: {invalid}. Must be integers 1-22.")
        if iterations < 1:
            raise ValueError(f"iterations must be >= 1, got {iterations}")
        return queries

    def _run_benchmark_phase(
        self,
        adapter: Any,
        benchmark: Any,
        query_subset: list[str],
        target_results: dict[str, Any],
        label: str,
        phase_name: str,
    ) -> None:
        """Run a single benchmark phase (uniform or skewed) and collect results."""
        self.log_verbose(f"{phase_name}: Running queries on {label} TPC-H data...")
        start = mono_time()

        try:
            run_results = adapter.run_benchmark(
                benchmark,
                benchmark_name="tpch_skew",
                query_subset=query_subset,
                test_execution_type="standard",
            )
            duration = elapsed_seconds(start)
            self.log_verbose(f"  {label.capitalize()} benchmark completed in {duration:.2f}s")

            for qr in run_results.query_results:
                query_id = qr.get("query_id", "")
                exec_time = qr.get("execution_time_ms", 0) / 1000.0
                status = qr.get("status", "UNKNOWN")

                if query_id not in target_results:
                    target_results[query_id] = {"times": [], "status": status}
                target_results[query_id]["times"].append(exec_time)

        except Exception as e:
            raise RuntimeError(f"Failed to run {label} benchmark: {e}") from e

    def _compute_comparison_stats(
        self, queries: list[int], results: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Compute per-query comparison and summary statistics."""
        from statistics import mean, stdev

        comparison: dict[str, Any] = {}
        all_ratios: list[float] = []
        uniform_total = 0.0
        skewed_total = 0.0

        for query_id in [str(q) for q in queries]:
            uniform_times = results["uniform_results"].get(query_id, {}).get("times", [])
            skewed_times = results["skewed_results"].get(query_id, {}).get("times", [])

            if not uniform_times or not skewed_times:
                comparison[query_id] = {"status": "INCOMPLETE", "reason": "Missing timing data"}
                continue

            uniform_avg = mean(uniform_times)
            skewed_avg = mean(skewed_times)
            ratio = skewed_avg / uniform_avg if uniform_avg > 0 else float("inf")

            entry: dict[str, Any] = {
                "uniform_avg_seconds": uniform_avg,
                "skewed_avg_seconds": skewed_avg,
                "ratio": ratio,
                "status": "SUCCESS",
            }
            if len(uniform_times) > 1:
                entry["uniform_stdev"] = stdev(uniform_times)
            if len(skewed_times) > 1:
                entry["skewed_stdev"] = stdev(skewed_times)

            comparison[query_id] = entry
            all_ratios.append(ratio)
            uniform_total += uniform_avg
            skewed_total += skewed_avg

        summary = self._build_comparison_summary(all_ratios, uniform_total, skewed_total)
        return comparison, summary

    def _build_comparison_summary(
        self, all_ratios: list[float], uniform_total: float, skewed_total: float
    ) -> dict[str, Any]:
        """Build summary statistics from comparison ratios."""
        from statistics import mean, stdev

        if not all_ratios:
            return {"queries_compared": 0, "error": "No valid comparisons could be made"}

        summary: dict[str, Any] = {
            "queries_compared": len(all_ratios),
            "uniform_total_seconds": uniform_total,
            "skewed_total_seconds": skewed_total,
            "avg_ratio": mean(all_ratios),
            "min_ratio": min(all_ratios),
            "max_ratio": max(all_ratios),
            "geometric_mean_ratio": self._geometric_mean(all_ratios),
        }
        if len(all_ratios) > 1:
            summary["ratio_stdev"] = stdev(all_ratios)

        avg_ratio = summary["avg_ratio"]
        if avg_ratio > 1.1:
            summary["interpretation"] = f"Skewed data is {(avg_ratio - 1) * 100:.1f}% slower on average"
        elif avg_ratio < 0.9:
            summary["interpretation"] = f"Skewed data is {(1 - avg_ratio) * 100:.1f}% faster on average"
        else:
            summary["interpretation"] = "Performance is similar between uniform and skewed data"

        return summary

    @staticmethod
    def _geometric_mean(values: list[float]) -> float:
        """Compute geometric mean of positive values."""
        if not values:
            return 0.0
        from functools import reduce
        from operator import mul

        product = reduce(mul, values, 1.0)
        return product ** (1.0 / len(values))

    @staticmethod
    def get_available_presets() -> list[str]:
        """Get list of available skew presets.

        Returns:
            List of preset names
        """
        return [p.value for p in SkewPreset]

    @staticmethod
    def get_preset_description(preset_name: str) -> str:
        """Get description of a skew preset.

        Args:
            preset_name: Name of the preset

        Returns:
            Human-readable description

        Raises:
            ValueError: If preset name is invalid
        """
        descriptions = {
            "none": "Uniform distribution (standard TPC-H)",
            "light": "Light skew (z=0.2) - mild concentration in popular values",
            "moderate": "Moderate skew (z=0.5) - noticeable concentration",
            "heavy": "Heavy skew (z=0.8) - significant concentration, affects join performance",
            "extreme": "Extreme skew (z=1.0, Zipf's law) - few values dominate",
            "realistic": "Realistic e-commerce pattern with seasonal effects",
        }
        preset_lower = preset_name.lower()
        if preset_lower not in descriptions:
            raise ValueError(f"Unknown preset: {preset_name}. Valid: {list(descriptions.keys())}")
        return descriptions[preset_lower]


# ---------------------------------------------------------------------------
# Register benchmark-specific CLI option specs
# ---------------------------------------------------------------------------

from benchbox.core.hooks.benchmark_hooks import (  # noqa: E402
    BenchmarkHookRegistry,
    BenchmarkOptionSpec,
)

BenchmarkHookRegistry.register_option_specs(
    "tpch_skew",
    BenchmarkOptionSpec(
        name="skew_preset",
        default="moderate",
        help="Skew distribution preset",
        choices=("none", "light", "moderate", "heavy", "extreme", "realistic"),
        aliases=("skew-preset",),
    ),
    BenchmarkOptionSpec(
        name="force_regenerate",
        parser=lambda v: v.strip().lower() in ("true", "1", "yes"),
        help="Force data regeneration",
        aliases=("force-regenerate",),
    ),
)
