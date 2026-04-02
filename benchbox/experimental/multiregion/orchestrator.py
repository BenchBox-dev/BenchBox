"""Multi-region benchmark orchestration.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from benchbox.experimental.multiregion.config import (
    MultiRegionConfig,
    Region,
    RegionConfig,
    calculate_distance_km,
)
from benchbox.experimental.multiregion.latency import (
    LatencyMeasurer,
    LatencyProfile,
    estimate_latency_from_distance,
)
from benchbox.experimental.multiregion.transfer import (
    TransferCostEstimate,
    TransferCostEstimator,
    TransferSummary,
    TransferTracker,
)
from benchbox.utils.clock import elapsed_seconds, mono_time

logger = logging.getLogger(__name__)


@dataclass
class RegionBenchmarkResult:
    """Results from running benchmark in a specific region."""

    region: Region
    start_time: float
    end_time: float
    duration_seconds: float

    # Query metrics
    queries_executed: int
    queries_succeeded: int
    queries_failed: int

    # Performance
    throughput_qps: float
    avg_latency_ms: float
    p95_latency_ms: float

    # Data transfer
    total_bytes_transferred: int

    # Errors
    errors: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Query success rate as percentage."""
        if self.queries_executed == 0:
            return 0.0
        return (self.queries_succeeded / self.queries_executed) * 100


@dataclass
class MultiRegionResult:
    """Aggregated results from multi-region benchmark."""

    config: MultiRegionConfig
    start_time: float
    end_time: float
    total_duration_seconds: float

    # Per-region results
    region_results: dict[str, RegionBenchmarkResult] = field(default_factory=dict)

    # Latency profiles
    latency_profiles: dict[tuple[str, str], LatencyProfile] = field(default_factory=dict)

    # Transfer metrics
    transfer_summary: TransferSummary | None = None
    transfer_cost_estimate: TransferCostEstimate | None = None

    # Comparison metrics
    region_comparison: dict[str, Any] = field(default_factory=dict)

    def get_best_region(self, metric: str = "throughput") -> str | None:
        """Get the best performing region by metric.

        Args:
            metric: "throughput", "latency", or "success_rate"

        Returns:
            Region code of best performer, or None if no results
        """
        if not self.region_results:
            return None

        if metric == "throughput":
            return max(
                self.region_results.keys(),
                key=lambda r: self.region_results[r].throughput_qps,
            )
        elif metric == "latency":
            return min(
                self.region_results.keys(),
                key=lambda r: self.region_results[r].avg_latency_ms,
            )
        elif metric == "success_rate":
            return max(
                self.region_results.keys(),
                key=lambda r: self.region_results[r].success_rate,
            )
        return None

    def get_latency_between(self, region1: str, region2: str) -> LatencyProfile | None:
        """Get latency profile between two regions.

        Args:
            region1: First region code
            region2: Second region code

        Returns:
            Latency profile if available
        """
        return self.latency_profiles.get((region1, region2))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_duration_seconds": self.total_duration_seconds,
            "regions_tested": list(self.region_results.keys()),
            "region_results": {
                code: {
                    "throughput_qps": result.throughput_qps,
                    "avg_latency_ms": result.avg_latency_ms,
                    "p95_latency_ms": result.p95_latency_ms,
                    "success_rate": result.success_rate,
                    "queries_executed": result.queries_executed,
                }
                for code, result in self.region_results.items()
            },
            "latency_profiles": {f"{k[0]}_{k[1]}": v.to_dict() for k, v in self.latency_profiles.items()},
            "transfer_summary": {
                "total_gb": self.transfer_summary.total_gb if self.transfer_summary else 0,
                "total_transfers": self.transfer_summary.total_transfers if self.transfer_summary else 0,
            },
            "transfer_cost_estimate": {
                "total_cost_usd": self.transfer_cost_estimate.total_cost_usd if self.transfer_cost_estimate else 0,
            },
            "best_region": {
                "by_throughput": self.get_best_region("throughput"),
                "by_latency": self.get_best_region("latency"),
            },
        }


class MultiRegionBenchmark:
    """Orchestrates benchmark execution across multiple regions.

    This class manages:
    - Running benchmarks in multiple regions (sequential or parallel)
    - Measuring cross-region latency
    - Tracking data transfer
    - Aggregating and comparing results
    """

    def __init__(
        self,
        config: MultiRegionConfig,
        benchmark_factory: Callable[[RegionConfig], Any],
        connection_factory: Callable[[RegionConfig], Any] | None = None,
    ):
        """Initialize multi-region benchmark.

        Args:
            config: Multi-region configuration
            benchmark_factory: Factory that creates benchmark executor for a region
            connection_factory: Optional factory for database connections
        """
        self._config = config
        self._benchmark_factory = benchmark_factory
        self._connection_factory = connection_factory
        self._transfer_tracker = TransferTracker(config.client_region)

    def run(
        self,
        parallel: bool = False,
        measure_latency: bool = True,
        latency_samples: int = 10,
    ) -> MultiRegionResult:
        """Run benchmark across all configured regions.

        Args:
            parallel: Whether to run regions in parallel
            measure_latency: Whether to measure cross-region latency
            latency_samples: Number of latency samples to collect

        Returns:
            Multi-region results
        """
        start_time = mono_time()
        region_results: dict[str, RegionBenchmarkResult] = {}
        latency_profiles: dict[tuple[str, str], LatencyProfile] = {}

        logger.info(f"Starting multi-region benchmark: {len(self._config.all_regions)} regions, parallel={parallel}")

        # Measure latency if enabled
        if measure_latency and self._config.enable_latency_measurement:
            latency_profiles = self._measure_all_latencies(latency_samples)

        # Run benchmarks
        if parallel:
            region_results = self._run_parallel()
        else:
            region_results = self._run_sequential()

        end_time = mono_time()

        # Get transfer summary
        transfer_summary = self._transfer_tracker.get_summary()

        # Estimate transfer cost
        transfer_cost = None
        if self._config.enable_transfer_tracking:
            provider = self._config.primary_region.region.provider
            estimator = TransferCostEstimator(provider)
            transfer_cost = estimator.estimate_cost(transfer_summary)

        result = MultiRegionResult(
            config=self._config,
            start_time=start_time,
            end_time=end_time,
            total_duration_seconds=elapsed_seconds(start_time, end_time),
            region_results=region_results,
            latency_profiles=latency_profiles,
            transfer_summary=transfer_summary,
            transfer_cost_estimate=transfer_cost,
            region_comparison=self._build_comparison(region_results),
        )

        logger.info(
            f"Multi-region benchmark complete: {len(region_results)} regions, "
            f"duration={result.total_duration_seconds:.2f}s"
        )

        return result

    def _run_sequential(self) -> dict[str, RegionBenchmarkResult]:
        """Run benchmarks sequentially in each region."""
        results = {}

        for region_config in self._config.all_regions:
            logger.info(f"Running benchmark in region: {region_config.region.code}")
            result = self._run_in_region(region_config)
            results[region_config.region.code] = result

        return results

    def _run_parallel(self) -> dict[str, RegionBenchmarkResult]:
        """Run benchmarks in parallel across regions."""
        results: dict[str, RegionBenchmarkResult] = {}

        with ThreadPoolExecutor(max_workers=len(self._config.all_regions)) as executor:
            futures: dict[Future, RegionConfig] = {}

            for region_config in self._config.all_regions:
                future = executor.submit(self._run_in_region, region_config)
                futures[future] = region_config

            for future in futures:
                region_config = futures[future]
                try:
                    result = future.result()
                    results[region_config.region.code] = result
                except Exception as e:
                    logger.error(f"Error in region {region_config.region.code}: {e}")
                    results[region_config.region.code] = RegionBenchmarkResult(
                        region=region_config.region,
                        start_time=mono_time(),
                        end_time=mono_time(),
                        duration_seconds=0,
                        queries_executed=0,
                        queries_succeeded=0,
                        queries_failed=0,
                        throughput_qps=0,
                        avg_latency_ms=0,
                        p95_latency_ms=0,
                        total_bytes_transferred=0,
                        errors=[str(e)],
                    )

        return results

    def _run_in_region(self, region_config: RegionConfig) -> RegionBenchmarkResult:
        """Run benchmark in a single region."""
        start_time = mono_time()
        queries_executed = 0
        queries_succeeded = 0
        queries_failed = 0
        latencies: list[float] = []
        total_bytes = 0
        errors: list[str] = []

        try:
            # Create benchmark executor for this region
            benchmark = self._benchmark_factory(region_config)

            # Run benchmark and collect metrics
            # This assumes benchmark has a run() method returning results
            if hasattr(benchmark, "run"):
                result = benchmark.run()

                # Extract metrics from result
                if hasattr(result, "queries_executed"):
                    queries_executed = result.queries_executed
                if hasattr(result, "queries_succeeded"):
                    queries_succeeded = result.queries_succeeded
                if hasattr(result, "queries_failed"):
                    queries_failed = result.queries_failed
                if hasattr(result, "latencies"):
                    latencies = result.latencies
                if hasattr(result, "total_bytes_transferred"):
                    total_bytes = result.total_bytes_transferred
            else:
                # Fallback for simpler benchmark interfaces
                queries_executed = 1
                queries_succeeded = 1

        except Exception as e:
            errors.append(str(e))
            logger.error(f"Benchmark error in {region_config.region.code}: {e}")

        end_time = mono_time()
        duration = elapsed_seconds(start_time, end_time)

        # Track data transfer
        if total_bytes > 0:
            self._transfer_tracker.record_query_result(
                source_region=region_config.region,
                result_bytes=total_bytes,
            )

        # Calculate metrics
        throughput = queries_executed / duration if duration > 0 else 0
        avg_latency = sum(latencies) / len(latencies) if latencies else 0

        # Calculate p95
        if latencies:
            sorted_latencies = sorted(latencies)
            p95_idx = int(len(sorted_latencies) * 0.95)
            p95_latency = sorted_latencies[min(p95_idx, len(sorted_latencies) - 1)]
        else:
            p95_latency = 0

        return RegionBenchmarkResult(
            region=region_config.region,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration,
            queries_executed=queries_executed,
            queries_succeeded=queries_succeeded,
            queries_failed=queries_failed,
            throughput_qps=throughput,
            avg_latency_ms=avg_latency,
            p95_latency_ms=p95_latency,
            total_bytes_transferred=total_bytes,
            errors=errors,
        )

    def _measure_all_latencies(self, samples: int) -> dict[tuple[str, str], LatencyProfile]:
        """Measure latency between all region pairs."""
        profiles: dict[tuple[str, str], LatencyProfile] = {}

        if self._config.client_region is None:
            logger.warning("No client region configured, skipping latency measurement")
            return profiles

        # Measure latency from client to each region
        for region_config in self._config.all_regions:
            measurer = LatencyMeasurer(
                source_region=self._config.client_region,
                target_config=region_config,
                connection_factory=(
                    lambda rc=region_config: self._connection_factory(rc) if self._connection_factory else None
                ),
            )

            # Try TCP measurement first, fall back to estimated
            try:
                profile = measurer.measure_latency_profile(samples=samples, method="tcp")
            except Exception as e:
                logger.warning(f"TCP latency measurement failed for {region_config.region.code}: {e}")
                # Create estimated profile
                distance = calculate_distance_km(
                    self._config.client_region,
                    region_config.region,
                )
                profile = LatencyProfile(
                    source_region=self._config.client_region,
                    target_region=region_config.region,
                )
                if distance:
                    min_latency, typical_latency = estimate_latency_from_distance(distance)
                    logger.info(
                        f"Estimated latency to {region_config.region.code}: "
                        f"{typical_latency}ms (distance: {distance:.0f}km)"
                    )

            key = (self._config.client_region.code, region_config.region.code)
            profiles[key] = profile

        return profiles

    def _build_comparison(
        self,
        region_results: dict[str, RegionBenchmarkResult],
    ) -> dict[str, Any]:
        """Build comparison metrics across regions."""
        if not region_results:
            return {}

        throughputs = {r: res.throughput_qps for r, res in region_results.items()}
        latencies = {r: res.avg_latency_ms for r, res in region_results.items()}
        success_rates = {r: res.success_rate for r, res in region_results.items()}

        best_throughput = max(throughputs.values()) if throughputs else 0
        best_latency = min(latencies.values()) if latencies else float("inf")

        comparison = {
            "throughput_comparison": {
                region: {
                    "value": tput,
                    "relative_to_best": tput / best_throughput if best_throughput > 0 else 0,
                }
                for region, tput in throughputs.items()
            },
            "latency_comparison": {
                region: {
                    "value": lat,
                    "relative_to_best": best_latency / lat if lat > 0 else 0,
                }
                for region, lat in latencies.items()
            },
            "success_rate_comparison": success_rates,
            "rankings": {
                "by_throughput": sorted(throughputs.keys(), key=lambda r: -throughputs[r]),
                "by_latency": sorted(latencies.keys(), key=lambda r: latencies[r]),
            },
        }

        return comparison
