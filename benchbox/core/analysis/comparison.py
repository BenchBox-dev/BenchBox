"""Platform comparison engine for benchmark results.

Provides automated comparison of benchmark results across multiple platforms
with statistical analysis, ranking, and insight generation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from benchbox.core.analysis.models import (
    ComparisonOutcome,
    ComparisonReport,
    CostPerformanceAnalysis,
    HeadToHeadComparison,
    PlatformRanking,
    QueryComparison,
    ValidationResult,
    WinLossRecord,
)
from benchbox.core.analysis.statistics import (
    apply_bonferroni_correction,
    calculate_geometric_mean,
    calculate_performance_metrics,
    create_outlier_info,
    detect_outliers_iqr,
    welchs_t_test,
)
from benchbox.core.results.models import BenchmarkResults

logger = logging.getLogger(__name__)


@dataclass
class ComparisonConfig:
    """Configuration for platform comparison.

    Attributes:
        significance_level: Alpha level for statistical tests (default 0.05)
        min_sample_size: Minimum samples required for statistics (default 3)
        outlier_method: Method for outlier detection ("iqr", "zscore", "none")
        outlier_threshold: Threshold for outlier detection (default 1.5 for IQR)
        exclude_outliers: Whether to exclude outliers from analysis
        require_all_queries: Require all queries present in all results
        performance_ratio_threshold: Minimum ratio to declare a winner (default 1.05)
        apply_bonferroni: Apply Bonferroni correction for multiple comparisons
    """

    significance_level: float = 0.05
    min_sample_size: int = 3
    outlier_method: str = "iqr"  # "iqr", "zscore", "none"
    outlier_threshold: float = 1.5
    exclude_outliers: bool = False
    require_all_queries: bool = False
    performance_ratio_threshold: float = 1.05
    apply_bonferroni: bool = True


class PlatformComparison:
    """Compares benchmark results across multiple platforms.

    This class provides comprehensive comparison functionality including:
    - Loading and validating benchmark results
    - Statistical significance testing
    - Performance ranking and win/loss analysis
    - Cost-performance analysis
    - Automated insight generation

    Example:
        >>> from benchbox.core.analysis import PlatformComparison
        >>>
        >>> # Load results from files
        >>> comparison = PlatformComparison.from_files([
        ...     "results/duckdb_tpch_sf10.json",
        ...     "results/clickhouse_tpch_sf10.json",
        ... ])
        >>>
        >>> # Generate comparison report
        >>> report = comparison.compare()
        >>> emit(f"Winner: {report.winner}")
        >>> emit(f"Rankings: {[r.platform for r in report.rankings]}")
    """

    def __init__(
        self,
        results: list[BenchmarkResults],
        config: Optional[ComparisonConfig] = None,
    ) -> None:
        """Initialize the platform comparison.

        Args:
            results: List of benchmark results to compare
            config: Configuration options for comparison

        Raises:
            ValueError: If results list is empty
        """
        if not results:
            raise ValueError("At least one benchmark result is required")

        self.results = results
        self.config = config or ComparisonConfig()
        self._validation_result: Optional[ValidationResult] = None
        self._comparison_report: Optional[ComparisonReport] = None

    @classmethod
    def from_files(
        cls,
        file_paths: list[Union[str, Path]],
        config: Optional[ComparisonConfig] = None,
    ) -> "PlatformComparison":
        """Create a comparison from result files.

        Args:
            file_paths: List of paths to benchmark result JSON files
            config: Configuration options for comparison

        Returns:
            PlatformComparison instance

        Raises:
            FileNotFoundError: If a file does not exist
            ValueError: If a file cannot be parsed
        """
        results = []
        for path in file_paths:
            path = Path(path)
            if not path.exists():
                raise FileNotFoundError(f"Result file not found: {path}")

            try:
                with open(path) as f:
                    data = json.load(f)
                result = _dict_to_benchmark_results(data)
                results.append(result)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in {path}: {e}") from e
            except Exception as e:
                raise ValueError(f"Failed to parse {path}: {e}") from e

        return cls(results, config)

    @classmethod
    def from_directory(
        cls,
        directory: Union[str, Path],
        pattern: str = "*.json",
        config: Optional[ComparisonConfig] = None,
    ) -> "PlatformComparison":
        """Create a comparison from all results in a directory.

        Args:
            directory: Directory containing result files
            pattern: Glob pattern for result files (default "*.json")
            config: Configuration options for comparison

        Returns:
            PlatformComparison instance

        Raises:
            FileNotFoundError: If directory does not exist
            ValueError: If no matching files found
        """
        directory = Path(directory)
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")

        file_paths = list(directory.glob(pattern))
        if not file_paths:
            raise ValueError(f"No files matching '{pattern}' found in {directory}")

        return cls.from_files(file_paths, config)

    @property
    def platforms(self) -> list[str]:
        """Get list of platform names being compared."""
        return [r.platform for r in self.results]

    @property
    def benchmark_name(self) -> str:
        """Get the benchmark name (from first result)."""
        return self.results[0].benchmark_name if self.results else "unknown"

    @property
    def scale_factor(self) -> float:
        """Get the scale factor (from first result)."""
        return self.results[0].scale_factor if self.results else 0.0

    def validate(self) -> ValidationResult:
        """Validate that results are suitable for comparison.

        Checks:
        - All results are from the same benchmark
        - All results have the same scale factor
        - Query overlap exists between platforms
        - Data quality (outlier detection)

        Returns:
            ValidationResult with is_valid flag and any errors/warnings
        """
        errors: list[str] = []
        warnings: list[str] = []

        if len(self.results) < 2:
            errors.append("At least two results are required for comparison")

        benchmark_names = {r.benchmark_name for r in self.results}
        if len(benchmark_names) > 1:
            errors.append(f"Results are from different benchmarks: {benchmark_names}")

        scale_factors = {r.scale_factor for r in self.results}
        if len(scale_factors) > 1:
            warnings.append(f"Results have different scale factors: {scale_factors}")

        common_queries = self._validate_query_overlap(errors, warnings)
        outliers_detected = self._detect_outliers(warnings)

        self._validation_result = ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            platforms_validated=self.platforms,
            common_queries=sorted(common_queries),
            outliers_detected=outliers_detected,
        )

        return self._validation_result

    def _validate_query_overlap(self, errors: list[str], warnings: list[str]) -> set[str]:
        """Check query overlap across results and append any errors/warnings.

        Mutates *errors* and *warnings* in-place by appending validation messages.
        """
        query_sets = [set(_extract_query_ids(result)) for result in self.results]

        if not query_sets:
            return set()

        common_queries = set.intersection(*query_sets)
        all_queries = set.union(*query_sets)

        if not common_queries:
            errors.append("No common queries found across all platforms")
        elif len(common_queries) < len(all_queries):
            missing_pct = (1 - len(common_queries) / len(all_queries)) * 100
            warnings.append(
                f"Only {len(common_queries)}/{len(all_queries)} queries "
                f"are common across all platforms ({missing_pct:.1f}% missing)"
            )
            if self.config.require_all_queries:
                errors.append("Not all queries present in all results")

        return common_queries

    def _detect_outliers(self, warnings: list[str]) -> list[Any]:
        """Detect outliers across all results using IQR method.

        Mutates *warnings* in-place by appending an outlier summary message.
        """
        if self.config.outlier_method == "none":
            return []

        outliers_detected: list[Any] = []
        for result in self.results:
            times = _extract_query_times(result)
            if not times:
                continue
            outlier_indices = detect_outliers_iqr(
                list(times.values()),
                self.config.outlier_threshold,
            )
            for _idx, value, deviation in outlier_indices:
                outliers_detected.append(
                    create_outlier_info(
                        platform=result.platform,
                        query_id="overall",
                        value=value,
                        method=self.config.outlier_method,
                        threshold=self.config.outlier_threshold,
                        deviation=deviation,
                    )
                )

        if outliers_detected:
            warnings.append(f"Detected {len(outliers_detected)} outliers in results")

        return outliers_detected

    def compare(self) -> ComparisonReport:
        """Generate a comprehensive comparison report.

        This is the main entry point for comparison. It:
        1. Validates results (if not already done)
        2. Compares queries across platforms
        3. Calculates rankings
        4. Performs head-to-head comparisons
        5. Analyzes cost-performance (if cost data available)
        6. Generates insights

        Returns:
            ComparisonReport with all comparison results

        Raises:
            ValueError: If validation fails with critical errors
        """
        # Validate if not already done
        if self._validation_result is None:
            self.validate()

        if self._validation_result and not self._validation_result.is_valid:
            raise ValueError(f"Cannot compare invalid results: {self._validation_result.errors}")

        # Get common queries
        common_queries = (
            self._validation_result.common_queries if self._validation_result else _get_common_queries(self.results)
        )

        # Compare each query
        query_comparisons: dict[str, QueryComparison] = {}
        all_p_values: list[float] = []

        for query_id in common_queries:
            comparison = self._compare_query(query_id)
            query_comparisons[query_id] = comparison
            if comparison.statistical_test:
                all_p_values.append(comparison.statistical_test.p_value)

        # Apply Bonferroni correction if configured
        if self.config.apply_bonferroni and all_p_values:
            corrected_p_values = apply_bonferroni_correction(all_p_values)
            for i, query_id in enumerate(common_queries):
                if query_comparisons[query_id].statistical_test:
                    test = query_comparisons[query_id].statistical_test
                    test.p_value = corrected_p_values[i]
                    test.notes = (test.notes or "") + " (Bonferroni corrected)"

        # Calculate win/loss records
        win_loss_matrix = self._calculate_win_loss_matrix(query_comparisons)

        # Calculate rankings
        rankings = self._calculate_rankings(query_comparisons, win_loss_matrix)

        # Generate head-to-head comparisons
        head_to_head = self._generate_head_to_head(query_comparisons)

        # Analyze cost-performance if available
        cost_analysis = self._analyze_cost_performance()

        # Determine overall winner
        winner = rankings[0].platform if rankings else None

        # Generate insights
        insights = self._generate_insights(rankings, query_comparisons, head_to_head, cost_analysis)

        # Create report
        self._comparison_report = ComparisonReport(
            benchmark_name=self.benchmark_name,
            scale_factor=self.scale_factor,
            platforms=self.platforms,
            generated_at=datetime.now(),
            winner=winner,
            rankings=rankings,
            query_comparisons=query_comparisons,
            head_to_head=head_to_head,
            win_loss_matrix=win_loss_matrix,
            cost_analysis=cost_analysis,
            statistical_summary=self._create_statistical_summary(query_comparisons),
            insights=insights,
            warnings=self._validation_result.warnings if self._validation_result else [],
            metadata={
                "num_platforms": len(self.platforms),
                "num_queries_compared": len(common_queries),
                "config": {
                    "significance_level": self.config.significance_level,
                    "outlier_method": self.config.outlier_method,
                    "apply_bonferroni": self.config.apply_bonferroni,
                },
            },
        )

        return self._comparison_report

    def compare_overall_performance(self) -> ComparisonReport:
        """Compare overall performance across platforms.

        Alias for compare() method.

        Returns:
            ComparisonReport with overall comparison
        """
        return self.compare()

    def compare_by_query(self) -> dict[str, QueryComparison]:
        """Get per-query comparisons.

        Returns:
            Dictionary of query_id to QueryComparison
        """
        if self._comparison_report is None:
            self.compare()
        return self._comparison_report.query_comparisons if self._comparison_report else {}

    def compare_cost_performance(self) -> Optional[CostPerformanceAnalysis]:
        """Get cost vs performance analysis.

        Returns:
            CostPerformanceAnalysis if cost data available, None otherwise
        """
        if self._comparison_report is None:
            self.compare()
        return self._comparison_report.cost_analysis if self._comparison_report else None

    def get_head_to_head(
        self,
        platform_a: str,
        platform_b: str,
    ) -> Optional[HeadToHeadComparison]:
        """Get head-to-head comparison between two specific platforms.

        Args:
            platform_a: First platform name
            platform_b: Second platform name

        Returns:
            HeadToHeadComparison if both platforms exist, None otherwise
        """
        if self._comparison_report is None:
            self.compare()

        if not self._comparison_report:
            return None

        for h2h in self._comparison_report.head_to_head:
            if (h2h.platform_a == platform_a and h2h.platform_b == platform_b) or (
                h2h.platform_a == platform_b and h2h.platform_b == platform_a
            ):
                return h2h

        return None

    def _compare_query(self, query_id: str) -> QueryComparison:
        """Compare a single query across all platforms.

        Args:
            query_id: The query identifier

        Returns:
            QueryComparison with metrics and statistical test
        """
        metrics: dict[str, Any] = {}
        times_by_platform: dict[str, list[float]] = {}

        # Collect times for each platform
        for result in self.results:
            times = _get_query_times_for_query(result, query_id)
            if times:
                times_by_platform[result.platform] = times
                metrics[result.platform] = calculate_performance_metrics(times)

        # Find winner (lowest mean time)
        winner = min(metrics.keys(), key=lambda p: metrics[p].mean) if metrics else ""

        # Calculate performance ratios vs winner
        winner_mean = metrics[winner].mean if winner and winner in metrics else 1.0
        performance_ratios = {p: m.mean / winner_mean if winner_mean > 0 else 1.0 for p, m in metrics.items()}

        # Perform statistical test if we have exactly 2 platforms
        statistical_test = None
        outcome = ComparisonOutcome.INCONCLUSIVE

        if len(times_by_platform) == 2:
            platforms = list(times_by_platform.keys())
            statistical_test = welchs_t_test(
                times_by_platform[platforms[0]],
                times_by_platform[platforms[1]],
            )

            # Determine outcome
            if statistical_test.p_value < self.config.significance_level:
                ratio = performance_ratios[platforms[1]]
                if ratio > self.config.performance_ratio_threshold:
                    outcome = ComparisonOutcome.WIN  # First is faster
                elif ratio < 1 / self.config.performance_ratio_threshold:
                    outcome = ComparisonOutcome.LOSS  # Second is faster
                else:
                    outcome = ComparisonOutcome.TIE
            else:
                outcome = ComparisonOutcome.TIE  # Not significant = tie

        # Generate insights
        insights = []
        if winner and len(metrics) > 1:
            slowest = max(metrics.keys(), key=lambda p: metrics[p].mean)
            ratio = performance_ratios[slowest]
            if ratio > 1.1:
                insights.append(f"{winner} is {ratio:.1f}x faster than {slowest} on query {query_id}")

        return QueryComparison(
            query_id=query_id,
            platforms=list(metrics.keys()),
            metrics=metrics,
            winner=winner,
            performance_ratios=performance_ratios,
            statistical_test=statistical_test,
            outcome=outcome,
            insights=insights,
        )

    def _calculate_win_loss_matrix(
        self,
        query_comparisons: dict[str, QueryComparison],
    ) -> dict[str, WinLossRecord]:
        """Calculate win/loss records for each platform.

        Args:
            query_comparisons: Per-query comparison results

        Returns:
            Dictionary of platform to WinLossRecord
        """
        records: dict[str, WinLossRecord] = {p: WinLossRecord(platform=p) for p in self.platforms}

        for comparison in query_comparisons.values():
            for platform in comparison.platforms:
                records[platform].total += 1

                if platform == comparison.winner:
                    # Check if it's a clear win
                    ratio = (
                        max(r for p, r in comparison.performance_ratios.items() if p != platform)
                        if len(comparison.performance_ratios) > 1
                        else 1.0
                    )

                    if ratio > self.config.performance_ratio_threshold:
                        records[platform].wins += 1
                    else:
                        records[platform].ties += 1
                else:
                    # Check if it's a clear loss
                    winner_ratio = comparison.performance_ratios.get(platform, 1.0)
                    if winner_ratio > self.config.performance_ratio_threshold:
                        records[platform].losses += 1
                    else:
                        records[platform].ties += 1

        # Calculate win rates
        for record in records.values():
            if record.total > 0:
                record.win_rate = record.wins / record.total * 100

        return records

    def _calculate_rankings(
        self,
        query_comparisons: dict[str, QueryComparison],
        win_loss_matrix: dict[str, WinLossRecord],
    ) -> list[PlatformRanking]:
        """Calculate platform rankings.

        Ranking is based on:
        1. Geometric mean of query times (primary)
        2. Win rate (secondary)
        3. Total time (tertiary)

        Args:
            query_comparisons: Per-query comparison results
            win_loss_matrix: Win/loss records

        Returns:
            Sorted list of PlatformRanking (best first)
        """
        rankings = []

        for result in self.results:
            platform = result.platform
            times = _extract_query_times(result)
            query_times = list(times.values()) if times else []

            geo_mean = calculate_geometric_mean(query_times) if query_times else 0.0
            total_time = sum(query_times) if query_times else 0.0
            win_rate = win_loss_matrix[platform].win_rate if platform in win_loss_matrix else 0.0

            # Composite score: lower is better
            # Weight geometric mean heavily, with win rate as tiebreaker
            score = geo_mean * (1 - win_rate / 100 * 0.1) if geo_mean > 0 else float("inf")

            rankings.append(
                PlatformRanking(
                    platform=platform,
                    rank=0,  # Will be set after sorting
                    score=score,
                    geometric_mean_time=geo_mean,
                    total_time=total_time,
                    win_rate=win_rate,
                )
            )

        # Sort by score (lower is better)
        rankings.sort(key=lambda r: r.score)

        # Assign ranks
        for i, ranking in enumerate(rankings):
            ranking.rank = i + 1

        return rankings

    def _generate_head_to_head(
        self,
        query_comparisons: dict[str, QueryComparison],
    ) -> list[HeadToHeadComparison]:
        """Generate head-to-head comparisons for all platform pairs.

        Args:
            query_comparisons: Per-query comparison results

        Returns:
            List of HeadToHeadComparison objects
        """
        comparisons = []
        platforms = self.platforms

        for i, platform_a in enumerate(platforms):
            for platform_b in platforms[i + 1 :]:
                wins_a, wins_b, ties, total_ratio = self._score_platform_pair(
                    query_comparisons,
                    platform_a,
                    platform_b,
                )

                # Calculate overall performance ratio
                geo_ratio = calculate_geometric_mean(total_ratio) if total_ratio else 1.0

                # Determine winner
                if wins_a > wins_b + ties:
                    winner = platform_a
                elif wins_b > wins_a + ties:
                    winner = platform_b
                else:
                    winner = None  # Too close to call

                comparisons.append(
                    HeadToHeadComparison(
                        platform_a=platform_a,
                        platform_b=platform_b,
                        winner=winner,
                        performance_ratio=geo_ratio,
                        wins_a=wins_a,
                        wins_b=wins_b,
                        ties=ties,
                        insights=self._build_head_to_head_insights(
                            platform_a,
                            platform_b,
                            winner,
                            geo_ratio,
                            wins_a,
                            wins_b,
                            ties,
                        ),
                    )
                )

        return comparisons

    def _analyze_cost_performance(self) -> Optional[CostPerformanceAnalysis]:
        """Analyze cost vs performance if cost data is available.

        Returns:
            CostPerformanceAnalysis or None if no cost data
        """
        cost_data = {}
        perf_data = {}

        for result in self.results:
            if result.cost_summary and "total_cost" in result.cost_summary:
                total_cost = result.cost_summary["total_cost"]
                if total_cost > 0:
                    cost_data[result.platform] = total_cost

                    # Calculate queries per second
                    total_time_sec = result.total_execution_time / 1000 if result.total_execution_time else 1.0
                    qps = result.total_queries / total_time_sec if total_time_sec > 0 else 0

                    # Performance per dollar (QPS / cost)
                    perf_data[result.platform] = qps / total_cost if total_cost > 0 else 0

        if not cost_data:
            return None

        # Cost per query
        cost_per_query = {
            p: cost / self.results[i].total_queries
            for i, (p, cost) in enumerate(cost_data.items())
            if self.results[i].total_queries > 0
        }

        # Rankings
        cost_rankings = sorted(cost_data.keys(), key=lambda p: cost_data[p])
        efficiency_rankings = sorted(perf_data.keys(), key=lambda p: perf_data[p], reverse=True)

        # Best value
        best_value = efficiency_rankings[0] if efficiency_rankings else cost_rankings[0]

        # Potential savings vs most expensive
        max_cost = max(cost_data.values()) if cost_data else 0
        potential_savings = {p: max_cost - c for p, c in cost_data.items()}

        return CostPerformanceAnalysis(
            platforms=list(cost_data.keys()),
            cost_per_query=cost_per_query,
            performance_per_dollar=perf_data,
            best_value=best_value,
            cost_rankings=cost_rankings,
            cost_efficiency_rankings=efficiency_rankings,
            potential_savings=potential_savings,
        )

    def _create_statistical_summary(
        self,
        query_comparisons: dict[str, QueryComparison],
    ) -> dict[str, Any]:
        """Create summary of statistical test results.

        Args:
            query_comparisons: Per-query comparison results

        Returns:
            Dictionary with statistical summary
        """
        significant_count = 0
        total_tests = 0
        avg_effect_size = []

        for qc in query_comparisons.values():
            if qc.statistical_test:
                total_tests += 1
                if qc.statistical_test.p_value < self.config.significance_level:
                    significant_count += 1
                if qc.statistical_test.effect_size is not None:
                    avg_effect_size.append(abs(qc.statistical_test.effect_size))

        return {
            "total_tests": total_tests,
            "significant_count": significant_count,
            "significant_percent": significant_count / total_tests * 100 if total_tests > 0 else 0,
            "average_effect_size": sum(avg_effect_size) / len(avg_effect_size) if avg_effect_size else 0,
            "bonferroni_applied": self.config.apply_bonferroni,
        }

    def _generate_insights(
        self,
        rankings: list[PlatformRanking],
        query_comparisons: dict[str, QueryComparison],
        head_to_head: list[HeadToHeadComparison],
        cost_analysis: Optional[CostPerformanceAnalysis],
    ) -> list[str]:
        """Generate automated insights from comparison results.

        Args:
            rankings: Platform rankings
            query_comparisons: Per-query comparisons
            head_to_head: Head-to-head comparisons
            cost_analysis: Cost performance analysis

        Returns:
            List of insight strings
        """
        del query_comparisons, head_to_head
        insights: list[str] = []
        insights.extend(self._insight_overall_winner(rankings))
        insights.extend(self._insight_win_rates(rankings))
        insights.extend(self._insight_consistency())
        insights.extend(self._insight_cost(cost_analysis))
        return insights

    def _score_platform_pair(
        self,
        query_comparisons: dict[str, QueryComparison],
        platform_a: str,
        platform_b: str,
    ) -> tuple[int, int, int, list[float]]:
        """Compute wins, ties, and relative ratios for a platform pair."""
        wins_a = 0
        wins_b = 0
        ties = 0
        total_ratio: list[float] = []
        threshold = self.config.performance_ratio_threshold

        for qc in query_comparisons.values():
            if platform_a not in qc.metrics or platform_b not in qc.metrics:
                continue
            ratio_a = qc.performance_ratios.get(platform_a, 1.0)
            ratio_b = qc.performance_ratios.get(platform_b, 1.0)
            if qc.metrics[platform_b].mean > 0:
                total_ratio.append(qc.metrics[platform_a].mean / qc.metrics[platform_b].mean)
            if ratio_a < ratio_b / threshold:
                wins_a += 1
            elif ratio_b < ratio_a / threshold:
                wins_b += 1
            else:
                ties += 1

        return wins_a, wins_b, ties, total_ratio

    @staticmethod
    def _build_head_to_head_insights(
        platform_a: str,
        platform_b: str,
        winner: str | None,
        geo_ratio: float,
        wins_a: int,
        wins_b: int,
        ties: int,
    ) -> list[str]:
        """Build human-readable insights for a head-to-head comparison."""
        if not winner:
            return []

        loser = platform_b if winner == platform_a else platform_a
        wins = wins_a if winner == platform_a else wins_b
        total = wins_a + wins_b + ties
        insights = [f"{winner} wins {wins}/{total} queries against {loser}"]
        if geo_ratio == 1.0:
            return insights
        if geo_ratio > 1.0:
            insights.append(f"{platform_b} is {geo_ratio:.2f}x faster overall than {platform_a}")
        else:
            insights.append(f"{platform_a} is {1 / geo_ratio:.2f}x faster overall than {platform_b}")
        return insights

    @staticmethod
    def _insight_overall_winner(rankings: list[PlatformRanking]) -> list[str]:
        """Summarize the overall winner when rankings are available."""
        if not rankings or len(rankings) == 1:
            return []
        winner = rankings[0]
        runner_up = rankings[1]
        speedup = runner_up.geometric_mean_time / winner.geometric_mean_time
        if speedup > 1.1:
            return [f"{winner.platform} is the overall winner, {speedup:.2f}x faster than {runner_up.platform}"]
        return [f"{winner.platform} edges out {runner_up.platform} with similar performance"]

    @staticmethod
    def _insight_win_rates(rankings: list[PlatformRanking]) -> list[str]:
        """Summarize dominant win-rate results for the top-ranked platforms."""
        return [
            f"{ranking.platform} wins {ranking.win_rate:.0f}% of queries"
            for ranking in rankings[:3]
            if ranking.win_rate >= 70
        ]

    def _insight_consistency(self) -> list[str]:
        """Summarize consistency and variance across benchmark results."""
        insights: list[str] = []
        for result in self.results:
            times = _extract_query_times(result)
            if not times:
                continue
            cv = _calculate_cv(list(times.values()))
            if cv < 0.2:
                insights.append(f"{result.platform} shows very consistent performance (CV={cv:.2f})")
            elif cv > 0.5:
                insights.append(f"{result.platform} shows high variance in query times (CV={cv:.2f})")
        return insights

    @staticmethod
    def _insight_cost(cost_analysis: Optional[CostPerformanceAnalysis]) -> list[str]:
        """Summarize price/performance insights when cost data is available."""
        if not cost_analysis:
            return []
        insights = [f"{cost_analysis.best_value} offers the best price/performance"]
        if len(cost_analysis.cost_rankings) <= 1:
            return insights
        cheapest = cost_analysis.cost_rankings[0]
        most_expensive = cost_analysis.cost_rankings[-1]
        savings = cost_analysis.potential_savings.get(cheapest, 0)
        if savings > 0:
            insights.append(f"Switching from {most_expensive} to {cheapest} could save ${savings:.2f}")
        return insights


# Helper functions


def _dict_to_benchmark_results(data: dict[str, Any]) -> BenchmarkResults:
    """Convert a dictionary to BenchmarkResults.

    Supports schema v2.0 format only.

    Args:
        data: Dictionary representation of benchmark results in v2.0 format

    Returns:
        BenchmarkResults instance

    Raises:
        ValueError: If schema version is not v2.0
    """
    from benchbox.core.results.loader import reconstruct_benchmark_results

    # Validate schema version
    version = data.get("version")
    if version != "2.0":
        raise ValueError(f"Unsupported schema version: {version}. Only schema v2.0 is supported for comparison.")

    return reconstruct_benchmark_results(data)


def _extract_query_ids(result: BenchmarkResults) -> list[str]:
    """Extract query IDs from benchmark results.

    Args:
        result: Benchmark results

    Returns:
        List of query identifiers
    """
    query_ids = set()

    # From query_results
    for qr in result.query_results or []:
        if "query_id" in qr:
            query_ids.add(str(qr["query_id"]))

    # From per_query_timings
    for timing in result.per_query_timings or []:
        if "query_id" in timing:
            query_ids.add(str(timing["query_id"]))

    return sorted(query_ids)


def _extract_query_times(result: BenchmarkResults) -> dict[str, float]:
    """Extract query execution times from benchmark results.

    Args:
        result: Benchmark results

    Returns:
        Dictionary of query_id to execution time in ms
    """
    times: dict[str, float] = {}

    # From query_results
    for qr in result.query_results or []:
        query_id = str(qr.get("query_id", ""))
        time_ms = qr.get("execution_time_ms") or qr.get("execution_time_seconds", qr.get("execution_time", 0))
        if query_id and time_ms > 0:
            times[query_id] = float(time_ms)

    # From per_query_timings (may have multiple runs)
    for timing in result.per_query_timings or []:
        query_id = str(timing.get("query_id", ""))
        time_ms = timing.get("execution_time_ms") or timing.get(
            "execution_time_seconds", timing.get("execution_time", 0)
        )
        if query_id and time_ms > 0:
            # Average if we already have a time
            if query_id in times:
                times[query_id] = (times[query_id] + float(time_ms)) / 2
            else:
                times[query_id] = float(time_ms)

    return times


def _get_query_times_for_query(
    result: BenchmarkResults,
    query_id: str,
) -> list[float]:
    """Get all execution times for a specific query.

    Useful when there are multiple runs of the same query.

    Args:
        result: Benchmark results
        query_id: Query identifier

    Returns:
        List of execution times in ms
    """
    times = []

    # From query_results
    for qr in result.query_results or []:
        if str(qr.get("query_id", "")) == query_id:
            time_ms = qr.get("execution_time_ms") or qr.get("execution_time_seconds", qr.get("execution_time", 0))
            if time_ms > 0:
                times.append(float(time_ms))

    # From per_query_timings
    for timing in result.per_query_timings or []:
        if str(timing.get("query_id", "")) == query_id:
            time_ms = timing.get("execution_time_ms") or timing.get(
                "execution_time_seconds", timing.get("execution_time", 0)
            )
            if time_ms > 0:
                times.append(float(time_ms))

    return times


def _get_common_queries(results: list[BenchmarkResults]) -> list[str]:
    """Get queries common to all results.

    Args:
        results: List of benchmark results

    Returns:
        Sorted list of common query IDs
    """
    if not results:
        return []

    query_sets = [set(_extract_query_ids(r)) for r in results]
    common = set.intersection(*query_sets) if query_sets else set()
    return sorted(common)


def _calculate_cv(values: list[float]) -> float:
    """Calculate coefficient of variation.

    Args:
        values: List of numeric values

    Returns:
        Coefficient of variation
    """
    if not values or len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    std_dev = variance**0.5
    return std_dev / mean
