# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class SignificanceLevel(Enum):
    NOT_SIGNIFICANT = "not_significant"
    SIGNIFICANT = "significant"
    HIGHLY_SIGNIFICANT = "highly_significant"
    VERY_HIGHLY_SIGNIFICANT = "very_highly_significant"


class ComparisonOutcome(Enum):
    WIN = "win"
    LOSS = "loss"
    TIE = "tie"
    INCONCLUSIVE = "inconclusive"


@dataclass
class StatisticalTest:
    test_name: str
    statistic: float
    p_value: float
    significance: SignificanceLevel
    effect_size: Optional[float] = None
    sample_size_a: int = 0
    sample_size_b: int = 0
    notes: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_name": self.test_name,
            "statistic": round(self.statistic, 4),
            "p_value": round(self.p_value, 6),
            "significance": self.significance.value,
            "effect_size": round(self.effect_size, 4) if self.effect_size is not None else None,
            "sample_size_a": self.sample_size_a,
            "sample_size_b": self.sample_size_b,
            "notes": self.notes,
        }


@dataclass
class ConfidenceInterval:
    lower: float
    upper: float
    confidence_level: float = 0.95
    point_estimate: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "lower": round(self.lower, 4),
            "upper": round(self.upper, 4),
            "confidence_level": self.confidence_level,
            "point_estimate": round(self.point_estimate, 4) if self.point_estimate is not None else None,
        }

    def contains(self, value: float) -> bool:
        return self.lower <= value <= self.upper


@dataclass
class PerformanceMetrics:
    mean: float
    median: float
    std_dev: float
    min_time: float
    max_time: float
    cv: float
    sample_count: int
    confidence_interval: Optional[ConfidenceInterval] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mean": round(self.mean, 4),
            "median": round(self.median, 4),
            "std_dev": round(self.std_dev, 4),
            "min": round(self.min_time, 4),
            "max": round(self.max_time, 4),
            "cv": round(self.cv, 4),
            "sample_count": self.sample_count,
            "confidence_interval": self.confidence_interval.to_dict() if self.confidence_interval else None,
        }


@dataclass
class QueryComparison:
    query_id: str
    platforms: list[str]
    metrics: dict[str, PerformanceMetrics]
    winner: str
    performance_ratios: dict[str, float]
    statistical_test: Optional[StatisticalTest] = None
    outcome: ComparisonOutcome = ComparisonOutcome.INCONCLUSIVE
    insights: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "platforms": self.platforms,
            "metrics": {p: m.to_dict() for p, m in self.metrics.items()},
            "winner": self.winner,
            "performance_ratios": {p: round(r, 2) for p, r in self.performance_ratios.items()},
            "statistical_test": self.statistical_test.to_dict() if self.statistical_test else None,
            "outcome": self.outcome.value,
            "insights": self.insights,
        }


@dataclass
class WinLossRecord:
    platform: str
    wins: int = 0
    losses: int = 0
    ties: int = 0
    total: int = 0
    win_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
            "total": self.total,
            "win_rate": round(self.win_rate, 2),
        }


@dataclass
class HeadToHeadComparison:
    platform_a: str
    platform_b: str
    winner: Optional[str]
    performance_ratio: float
    wins_a: int
    wins_b: int
    ties: int
    statistical_test: Optional[StatisticalTest] = None
    insights: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform_a": self.platform_a,
            "platform_b": self.platform_b,
            "winner": self.winner,
            "performance_ratio": round(self.performance_ratio, 2),
            "wins_a": self.wins_a,
            "wins_b": self.wins_b,
            "ties": self.ties,
            "statistical_test": self.statistical_test.to_dict() if self.statistical_test else None,
            "insights": self.insights,
        }


@dataclass
class PlatformRanking:
    platform: str
    rank: int
    score: float
    geometric_mean_time: float
    total_time: float
    win_rate: float
    cost_efficiency: Optional[float] = None
    consistency_score: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "rank": self.rank,
            "score": round(self.score, 4),
            "geometric_mean_time_ms": round(self.geometric_mean_time, 2),
            "total_time_ms": round(self.total_time, 2),
            "win_rate": round(self.win_rate, 2),
            "cost_efficiency": round(self.cost_efficiency, 4) if self.cost_efficiency is not None else None,
            "consistency_score": round(self.consistency_score, 4) if self.consistency_score is not None else None,
        }


@dataclass
class CostPerformanceAnalysis:
    platforms: list[str]
    cost_per_query: dict[str, float]
    performance_per_dollar: dict[str, float]
    best_value: str
    cost_rankings: list[str]
    cost_efficiency_rankings: list[str]
    potential_savings: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "platforms": self.platforms,
            "cost_per_query": {p: round(c, 6) for p, c in self.cost_per_query.items()},
            "performance_per_dollar": {p: round(v, 4) for p, v in self.performance_per_dollar.items()},
            "best_value": self.best_value,
            "cost_rankings": self.cost_rankings,
            "cost_efficiency_rankings": self.cost_efficiency_rankings,
            "potential_savings": {p: round(s, 2) for p, s in self.potential_savings.items()},
        }


@dataclass
class ComparisonReport:
    benchmark_name: str
    scale_factor: float
    platforms: list[str]
    generated_at: datetime = field(default_factory=datetime.now)
    winner: Optional[str] = None
    rankings: list[PlatformRanking] = field(default_factory=list)
    query_comparisons: dict[str, QueryComparison] = field(default_factory=dict)
    head_to_head: list[HeadToHeadComparison] = field(default_factory=list)
    win_loss_matrix: dict[str, WinLossRecord] = field(default_factory=dict)
    cost_analysis: Optional[CostPerformanceAnalysis] = None
    statistical_summary: dict[str, Any] = field(default_factory=dict)
    insights: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_name": self.benchmark_name,
            "scale_factor": self.scale_factor,
            "platforms": self.platforms,
            "generated_at": self.generated_at.isoformat(),
            "winner": self.winner,
            "rankings": [r.to_dict() for r in self.rankings],
            "query_comparisons": {q: c.to_dict() for q, c in self.query_comparisons.items()},
            "head_to_head": [h.to_dict() for h in self.head_to_head],
            "win_loss_matrix": {p: r.to_dict() for p, r in self.win_loss_matrix.items()},
            "cost_analysis": self.cost_analysis.to_dict() if self.cost_analysis else None,
            "statistical_summary": self.statistical_summary,
            "insights": self.insights,
            "warnings": self.warnings,
            "metadata": self.metadata,
        }


@dataclass
class OutlierInfo:
    platform: str
    query_id: str
    value: float
    method: str
    threshold: float
    deviation: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "query_id": self.query_id,
            "value": round(self.value, 4),
            "method": self.method,
            "threshold": round(self.threshold, 4),
            "deviation": round(self.deviation, 4),
        }


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    platforms_validated: list[str] = field(default_factory=list)
    common_queries: list[str] = field(default_factory=list)
    outliers_detected: list[OutlierInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "platforms_validated": self.platforms_validated,
            "common_queries": self.common_queries,
            "outliers_detected": [o.to_dict() for o in self.outliers_detected],
        }
