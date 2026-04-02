"""Platform ranking algorithms for benchmark comparison.

Provides various ranking strategies for comparing database platforms
based on benchmark performance data.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from benchbox.core.analysis.models import (
    ComparisonReport,
    PlatformRanking,
)
from benchbox.core.analysis.statistics import calculate_geometric_mean


class RankingStrategy(Enum):
    """Strategy for ranking platforms."""

    GEOMETRIC_MEAN = "geometric_mean"  # Rank by geometric mean (TPC standard)
    TOTAL_TIME = "total_time"  # Rank by total execution time
    WIN_RATE = "win_rate"  # Rank by head-to-head win rate
    COST_EFFICIENCY = "cost_efficiency"  # Rank by performance per dollar
    COMPOSITE = "composite"  # Weighted combination of factors


@dataclass
class RankingWeights:
    """Weights for composite ranking.

    Attributes:
        performance: Weight for performance (default 40%)
        cost: Weight for cost efficiency (default 30%)
        consistency: Weight for consistency (default 20%)
        features: Weight for features (default 10%)
    """

    performance: float = 0.40
    cost: float = 0.30
    consistency: float = 0.20
    features: float = 0.10

    def __post_init__(self) -> None:
        """Validate weights sum to 1.0."""
        total = self.performance + self.cost + self.consistency + self.features
        if abs(total - 1.0) > 0.001:
            # Normalize
            self.performance /= total
            self.cost /= total
            self.consistency /= total
            self.features /= total

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary representation."""
        return {
            "performance": self.performance,
            "cost": self.cost,
            "consistency": self.consistency,
            "features": self.features,
        }


@dataclass
class RankingConfig:
    """Configuration for ranking algorithms.

    Attributes:
        strategy: Ranking strategy to use
        weights: Weights for composite ranking
        normalize_scores: Whether to normalize scores to 0-100
        tie_threshold: Percentage difference to consider a tie (default 5%)
    """

    strategy: RankingStrategy = RankingStrategy.GEOMETRIC_MEAN
    weights: RankingWeights = field(default_factory=RankingWeights)
    normalize_scores: bool = True
    tie_threshold: float = 0.05  # 5%


@dataclass
class RankingResult:
    """Result of a ranking operation.

    Attributes:
        rankings: Ordered list of platform rankings
        strategy_used: Strategy used for ranking
        ties_detected: Whether ties were detected
        tie_groups: Groups of tied platforms
        metadata: Additional ranking metadata
    """

    rankings: list[PlatformRanking]
    strategy_used: RankingStrategy
    ties_detected: bool = False
    tie_groups: list[list[str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "rankings": [r.to_dict() for r in self.rankings],
            "strategy_used": self.strategy_used.value,
            "ties_detected": self.ties_detected,
            "tie_groups": self.tie_groups,
            "metadata": self.metadata,
        }


def _extract_platform_times(report: "ComparisonReport", platform: str) -> list[float]:
    """Extract query execution times for a platform from a comparison report."""
    return [qc.metrics[platform].mean for qc in report.query_comparisons.values() if platform in qc.metrics]


class PlatformRanker:
    """Ranks platforms based on benchmark comparison results.

    Supports multiple ranking strategies including geometric mean (TPC standard),
    total execution time, win rate, cost efficiency, and weighted composite scores.

    Example:
        >>> from benchbox.core.analysis import PlatformRanker, RankingStrategy
        >>>
        >>> ranker = PlatformRanker(strategy=RankingStrategy.COMPOSITE)
        >>> result = ranker.rank(comparison_report)
        >>> for r in result.rankings:
        ...     emit(f"{r.rank}. {r.platform}: {r.score:.2f}")
    """

    def __init__(
        self,
        config: Optional[RankingConfig] = None,
    ) -> None:
        """Initialize the ranker.

        Args:
            config: Configuration for ranking
        """
        self.config = config or RankingConfig()

    def rank(self, report: ComparisonReport) -> RankingResult:
        """Rank platforms based on comparison report.

        Args:
            report: ComparisonReport to rank

        Returns:
            RankingResult with ordered platform rankings
        """
        if self.config.strategy == RankingStrategy.GEOMETRIC_MEAN:
            return self._rank_by_geometric_mean(report)
        elif self.config.strategy == RankingStrategy.TOTAL_TIME:
            return self._rank_by_total_time(report)
        elif self.config.strategy == RankingStrategy.WIN_RATE:
            return self._rank_by_win_rate(report)
        elif self.config.strategy == RankingStrategy.COST_EFFICIENCY:
            return self._rank_by_cost_efficiency(report)
        elif self.config.strategy == RankingStrategy.COMPOSITE:
            return self._rank_by_composite(report)
        else:
            return self._rank_by_geometric_mean(report)

    def _rank_by_geometric_mean(self, report: ComparisonReport) -> RankingResult:
        """Rank by geometric mean of query times (TPC standard).

        Args:
            report: Comparison report

        Returns:
            RankingResult ordered by geometric mean (lower is better)
        """
        return self._rank_by_metric(
            report=report,
            strategy=RankingStrategy.GEOMETRIC_MEAN,
            metric_name="geometric_mean_ms",
            metric_fn=calculate_geometric_mean,
            empty_score=float("inf"),
            empty_geometric_mean=float("inf"),
            empty_total_time=0.0,
        )

    def _rank_by_total_time(self, report: ComparisonReport) -> RankingResult:
        """Rank by total execution time.

        Args:
            report: Comparison report

        Returns:
            RankingResult ordered by total time (lower is better)
        """
        return self._rank_by_metric(
            report=report,
            strategy=RankingStrategy.TOTAL_TIME,
            metric_name="total_time_ms",
            metric_fn=sum,
            empty_score=float("inf"),
            empty_geometric_mean=0.0,
            empty_total_time=float("inf"),
        )

    def _rank_by_metric(
        self,
        report: ComparisonReport,
        strategy: RankingStrategy,
        metric_name: str,
        metric_fn: Callable[[list[float]], float],
        empty_score: float,
        empty_geometric_mean: float,
        empty_total_time: float,
    ) -> RankingResult:
        """Rank platforms by a derived metric while preserving common metadata."""
        rankings = []

        for platform in report.platforms:
            times = _extract_platform_times(report, platform)
            score = metric_fn(times) if times else empty_score
            geo_mean = calculate_geometric_mean(times) if times else empty_geometric_mean
            total_time = sum(times) if times else empty_total_time
            win_rate = report.win_loss_matrix.get(platform, None)

            rankings.append(
                PlatformRanking(
                    platform=platform,
                    rank=0,
                    score=score,
                    geometric_mean_time=geo_mean,
                    total_time=total_time,
                    win_rate=win_rate.win_rate if win_rate else 0.0,
                )
            )

        rankings.sort(key=lambda r: r.score)

        ties_detected, tie_groups = self._assign_ranks_with_ties(rankings)

        return RankingResult(
            rankings=rankings,
            strategy_used=strategy,
            ties_detected=ties_detected,
            tie_groups=tie_groups,
            metadata={"metric": metric_name},
        )

    def _rank_by_win_rate(self, report: ComparisonReport) -> RankingResult:
        """Rank by head-to-head win rate.

        Args:
            report: Comparison report

        Returns:
            RankingResult ordered by win rate (higher is better)
        """
        rankings = []

        for platform in report.platforms:
            wl = report.win_loss_matrix.get(platform)
            win_rate = wl.win_rate if wl else 0.0

            # Collect metrics
            times = []
            for qc in report.query_comparisons.values():
                if platform in qc.metrics:
                    times.append(qc.metrics[platform].mean)

            geo_mean = calculate_geometric_mean(times) if times else 0.0
            total_time = sum(times) if times else 0.0

            rankings.append(
                PlatformRanking(
                    platform=platform,
                    rank=0,
                    score=100 - win_rate,  # Invert so lower is better
                    geometric_mean_time=geo_mean,
                    total_time=total_time,
                    win_rate=win_rate,
                )
            )

        # Sort by inverted win rate (lower score = higher win rate = better)
        rankings.sort(key=lambda r: r.score)

        ties_detected, tie_groups = self._assign_ranks_with_ties(rankings)

        return RankingResult(
            rankings=rankings,
            strategy_used=RankingStrategy.WIN_RATE,
            ties_detected=ties_detected,
            tie_groups=tie_groups,
            metadata={"metric": "win_rate_percent"},
        )

    def _rank_by_cost_efficiency(self, report: ComparisonReport) -> RankingResult:
        """Rank by cost efficiency (performance per dollar).

        Args:
            report: Comparison report

        Returns:
            RankingResult ordered by cost efficiency (higher is better)
        """
        rankings = []

        for platform in report.platforms:
            times = []
            for qc in report.query_comparisons.values():
                if platform in qc.metrics:
                    times.append(qc.metrics[platform].mean)

            geo_mean = calculate_geometric_mean(times) if times else float("inf")
            total_time = sum(times) if times else 0.0
            win_rate = report.win_loss_matrix.get(platform, None)

            # Get cost efficiency if available
            cost_efficiency = None
            if report.cost_analysis and platform in report.cost_analysis.performance_per_dollar:
                cost_efficiency = report.cost_analysis.performance_per_dollar[platform]

            # Score: lower is better
            # If cost data available, use inverted cost efficiency
            # Otherwise, fall back to geometric mean
            if cost_efficiency is not None and cost_efficiency > 0:
                score = 1.0 / cost_efficiency
            else:
                score = geo_mean

            rankings.append(
                PlatformRanking(
                    platform=platform,
                    rank=0,
                    score=score,
                    geometric_mean_time=geo_mean,
                    total_time=total_time,
                    win_rate=win_rate.win_rate if win_rate else 0.0,
                    cost_efficiency=cost_efficiency,
                )
            )

        # Sort by score (lower is better = more cost efficient)
        rankings.sort(key=lambda r: r.score)

        ties_detected, tie_groups = self._assign_ranks_with_ties(rankings)

        return RankingResult(
            rankings=rankings,
            strategy_used=RankingStrategy.COST_EFFICIENCY,
            ties_detected=ties_detected,
            tie_groups=tie_groups,
            metadata={"metric": "performance_per_dollar" if report.cost_analysis else "geometric_mean_ms"},
        )

    def _rank_by_composite(self, report: ComparisonReport) -> RankingResult:
        """Rank by weighted composite score.

        Combines performance, cost, consistency, and features.

        Args:
            report: Comparison report

        Returns:
            RankingResult ordered by composite score (lower is better)
        """
        weights = self.config.weights
        raw_scores = self._compute_raw_scores(report)
        normalized_scores = self._normalize_scores(raw_scores, report.platforms)

        rankings = []
        for platform in report.platforms:
            composite_score = (
                weights.performance * normalized_scores[platform]["performance"]
                + weights.cost * normalized_scores[platform]["cost"]
                + weights.consistency * normalized_scores[platform]["consistency"]
                + weights.features * normalized_scores[platform]["features"]
            )

            times = _extract_platform_times(report, platform)
            geo_mean = calculate_geometric_mean(times) if times else 0.0
            win_rate = report.win_loss_matrix.get(platform, None)

            cost_efficiency = None
            if report.cost_analysis and platform in report.cost_analysis.performance_per_dollar:
                cost_efficiency = report.cost_analysis.performance_per_dollar[platform]

            rankings.append(
                PlatformRanking(
                    platform=platform,
                    rank=0,
                    score=composite_score,
                    geometric_mean_time=geo_mean,
                    total_time=sum(times) if times else 0.0,
                    win_rate=win_rate.win_rate if win_rate else 0.0,
                    cost_efficiency=cost_efficiency,
                    consistency_score=1.0 - normalized_scores[platform]["consistency"],
                )
            )

        rankings.sort(key=lambda r: r.score)
        ties_detected, tie_groups = self._assign_ranks_with_ties(rankings)

        if self.config.normalize_scores:
            max_score = max(r.score for r in rankings) if rankings else 1
            for r in rankings:
                r.score = (1 - r.score / max_score) * 100 if max_score > 0 else 0

        return RankingResult(
            rankings=rankings,
            strategy_used=RankingStrategy.COMPOSITE,
            ties_detected=ties_detected,
            tie_groups=tie_groups,
            metadata={
                "metric": "composite_score",
                "weights": weights.to_dict(),
            },
        )

    @staticmethod
    def _compute_raw_scores(report: ComparisonReport) -> dict[str, dict[str, float]]:
        """Compute raw performance, cost, consistency, and feature scores per platform.

        Platforms with no query times receive float('inf') for performance; platforms
        with zero cost-efficiency (ce == 0) also receive float('inf') for cost.
        Callers (e.g. _normalize_scores) must handle non-finite values.
        """
        raw_scores: dict[str, dict[str, float]] = {p: {} for p in report.platforms}

        for platform in report.platforms:
            times = _extract_platform_times(report, platform)

            geo_mean = calculate_geometric_mean(times) if times else float("inf")
            raw_scores[platform]["performance"] = geo_mean

            if report.cost_analysis and platform in report.cost_analysis.performance_per_dollar:
                ce = report.cost_analysis.performance_per_dollar[platform]
                raw_scores[platform]["cost"] = 1.0 / ce if ce > 0 else float("inf")
            else:
                raw_scores[platform]["cost"] = geo_mean

            if times and len(times) > 1:
                mean_time = sum(times) / len(times)
                variance = sum((t - mean_time) ** 2 for t in times) / (len(times) - 1)
                cv = (variance**0.5) / mean_time if mean_time > 0 else 0
                raw_scores[platform]["consistency"] = cv
            else:
                raw_scores[platform]["consistency"] = 0.0

            raw_scores[platform]["features"] = 0.0

        return raw_scores

    @staticmethod
    def _normalize_scores(raw_scores: dict[str, dict[str, float]], platforms: list[str]) -> dict[str, dict[str, float]]:
        """Normalize raw scores to 0-1 range within each dimension using min-max scaling.

        Non-finite values (inf, -inf, NaN) are replaced with a penalty value above
        the maximum finite value (offset by the finite range, or 1.0 as fallback),
        ensuring they always normalize to the worst score.
        """
        normalized: dict[str, dict[str, float]] = {p: {} for p in platforms}

        for dimension in ["performance", "cost", "consistency", "features"]:
            values = [raw_scores[p][dimension] for p in platforms]

            # Replace non-finite values with a penalty above the finite maximum
            finite_values = [v for v in values if math.isfinite(v)]
            if finite_values:
                max_finite = max(finite_values)
                min_finite = min(finite_values)
                spread = max_finite - min_finite if max_finite > min_finite else 1.0
                inf_replacement = max_finite + spread
            else:
                inf_replacement = 1.0
            values = [v if math.isfinite(v) else inf_replacement for v in values]

            min_val = min(values) if values else 0
            max_val = max(values) if values else 1
            range_val = max_val - min_val if max_val > min_val else 1

            for platform, val in zip(platforms, values):
                normalized[platform][dimension] = (val - min_val) / range_val

        return normalized

    def _assign_ranks_with_ties(
        self,
        rankings: list[PlatformRanking],
    ) -> tuple[bool, list[list[str]]]:
        """Assign ranks, detecting and grouping ties.

        Args:
            rankings: Pre-sorted list of rankings

        Returns:
            Tuple of (ties_detected, tie_groups)
        """
        if not rankings:
            return False, []

        ties_detected = False
        tie_groups: list[list[str]] = []
        current_group: list[str] = [rankings[0].platform]
        current_rank = 1

        rankings[0].rank = current_rank

        for i in range(1, len(rankings)):
            # Check if within tie threshold of previous
            prev_score = rankings[i - 1].score
            curr_score = rankings[i].score

            if prev_score > 0:
                diff_pct = abs(curr_score - prev_score) / prev_score
            else:
                diff_pct = 0 if curr_score == 0 else 1

            if diff_pct <= self.config.tie_threshold:
                # Tie - same rank
                rankings[i].rank = rankings[i - 1].rank
                current_group.append(rankings[i].platform)
                ties_detected = True
            else:
                # Not a tie - new rank
                if len(current_group) > 1:
                    tie_groups.append(current_group)
                current_group = [rankings[i].platform]
                current_rank = i + 1
                rankings[i].rank = current_rank

        # Final group
        if len(current_group) > 1:
            tie_groups.append(current_group)

        return ties_detected, tie_groups


def rank_platforms(
    report: ComparisonReport,
    strategy: RankingStrategy = RankingStrategy.GEOMETRIC_MEAN,
    weights: Optional[RankingWeights] = None,
) -> RankingResult:
    """Convenience function to rank platforms.

    Args:
        report: Comparison report to rank
        strategy: Ranking strategy to use
        weights: Weights for composite ranking (only used if strategy is COMPOSITE)

    Returns:
        RankingResult with ordered rankings
    """
    config = RankingConfig(
        strategy=strategy,
        weights=weights or RankingWeights(),
    )
    ranker = PlatformRanker(config)
    return ranker.rank(report)
