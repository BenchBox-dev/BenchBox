"""Coverage-focused tests for analysis insights and ranking modules."""

from __future__ import annotations

from datetime import datetime

import pytest

from benchbox.core.analysis.insights import (
    InsightGenerator,
    InsightReport,
    generate_blog_snippet,
    generate_comparison_narrative,
)
from benchbox.core.analysis.models import (
    ComparisonOutcome,
    ComparisonReport,
    CostPerformanceAnalysis,
    HeadToHeadComparison,
    PerformanceMetrics,
    PlatformRanking,
    QueryComparison,
    WinLossRecord,
)
from benchbox.core.analysis.ranking import (
    PlatformRanker,
    RankingConfig,
    RankingStrategy,
    RankingWeights,
    rank_platforms,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _metrics(value: float) -> PerformanceMetrics:
    return PerformanceMetrics(
        mean=value,
        median=value,
        std_dev=0.1,
        min_time=value * 0.8,
        max_time=value * 1.2,
        cv=0.05,
        sample_count=5,
    )


def _sample_report() -> ComparisonReport:
    platforms = ["duckdb", "snowflake", "athena"]
    query_comparisons = {
        "Q1": QueryComparison(
            query_id="Q1",
            platforms=platforms,
            metrics={"duckdb": _metrics(10), "snowflake": _metrics(20), "athena": _metrics(40)},
            winner="duckdb",
            performance_ratios={"duckdb": 1.0, "snowflake": 2.0, "athena": 4.0},
            outcome=ComparisonOutcome.WIN,
        ),
        "Q2": QueryComparison(
            query_id="Q2",
            platforms=platforms,
            metrics={"duckdb": _metrics(12), "snowflake": _metrics(24), "athena": _metrics(30)},
            winner="duckdb",
            performance_ratios={"duckdb": 1.0, "snowflake": 2.0, "athena": 2.5},
            outcome=ComparisonOutcome.WIN,
        ),
        "Q3": QueryComparison(
            query_id="Q3",
            platforms=platforms,
            metrics={"duckdb": _metrics(11), "snowflake": _metrics(10), "athena": _metrics(25)},
            winner="snowflake",
            performance_ratios={"duckdb": 1.1, "snowflake": 1.0, "athena": 2.5},
            outcome=ComparisonOutcome.WIN,
        ),
    }
    rankings = [
        PlatformRanking("duckdb", 1, 11, 11, 33, 67),
        PlatformRanking("snowflake", 2, 18, 18, 54, 33),
        PlatformRanking("athena", 3, 32, 32, 95, 0),
    ]
    cost_analysis = CostPerformanceAnalysis(
        platforms=platforms,
        cost_per_query={"duckdb": 0.1, "snowflake": 0.4, "athena": 0.2},
        performance_per_dollar={"duckdb": 10.0, "snowflake": 2.5, "athena": 5.0},
        best_value="duckdb",
        cost_rankings=["duckdb", "athena", "snowflake"],
        cost_efficiency_rankings=["duckdb", "athena", "snowflake"],
        potential_savings={"duckdb": 3.0, "athena": 2.0},
    )
    return ComparisonReport(
        benchmark_name="tpch",
        scale_factor=1.0,
        platforms=platforms,
        generated_at=datetime.now(),
        winner="duckdb",
        rankings=rankings,
        query_comparisons=query_comparisons,
        head_to_head=[HeadToHeadComparison("duckdb", "snowflake", "duckdb", 2.0, 2, 1, 0)],
        win_loss_matrix={
            "duckdb": WinLossRecord("duckdb", wins=2, losses=1, ties=0, total=3, win_rate=67),
            "snowflake": WinLossRecord("snowflake", wins=1, losses=2, ties=0, total=3, win_rate=33),
            "athena": WinLossRecord("athena", wins=0, losses=3, ties=2, total=5, win_rate=0),
        },
        cost_analysis=cost_analysis,
        statistical_summary={"significant_percent": 80, "significant_count": 8, "total_tests": 10},
    )


def test_insight_report_serialization_and_markdown():
    report = InsightReport(
        executive_summary="summary",
        winner_announcement="winner",
        key_findings=["f1"],
        performance_insights=["p1"],
        cost_insights=["c1"],
        recommendations=["r1"],
        query_highlights=["q1"],
    )
    as_dict = report.to_dict()
    assert as_dict["executive_summary"] == "summary"
    md = report.to_markdown()
    assert "Executive Summary" in md
    assert "Winner" in md


def test_insight_generator_full_and_convenience_functions():
    report = _sample_report()
    generator = InsightGenerator()
    insights = generator.generate(report)

    assert insights.winner_announcement
    assert insights.executive_summary
    assert insights.key_findings
    assert insights.performance_insights
    assert insights.cost_insights
    assert insights.recommendations
    assert insights.query_highlights
    assert insights.blog_snippet

    assert "## " in generate_comparison_narrative(report)
    assert generate_blog_snippet(report)


def test_insight_generator_edge_cases():
    # No rankings branch
    empty_report = ComparisonReport(benchmark_name="tpch", scale_factor=1.0, platforms=["duckdb"])
    generator = InsightGenerator()
    insights = generator.generate(empty_report)
    assert insights.winner_announcement == "No clear winner could be determined."
    assert "Insufficient data" in insights.executive_summary

    # Single ranking branch
    one_rank_report = ComparisonReport(
        benchmark_name="tpch",
        scale_factor=1.0,
        platforms=["duckdb"],
        rankings=[PlatformRanking("duckdb", 1, 1.0, 10.0, 10.0, 100.0)],
    )
    assert "only platform tested" in generator.generate(one_rank_report).winner_announcement


def test_ranking_weights_and_strategies():
    # normalization path
    weights = RankingWeights(performance=1, cost=1, consistency=1, features=1)
    assert round(sum(weights.to_dict().values()), 6) == 1.0

    report = _sample_report()

    for strategy in [
        RankingStrategy.GEOMETRIC_MEAN,
        RankingStrategy.TOTAL_TIME,
        RankingStrategy.WIN_RATE,
        RankingStrategy.COST_EFFICIENCY,
        RankingStrategy.COMPOSITE,
    ]:
        result = PlatformRanker(RankingConfig(strategy=strategy)).rank(report)
        assert result.rankings
        assert result.strategy_used == strategy
        assert isinstance(result.to_dict(), dict)

    # invalid strategy fallback branch
    ranker = PlatformRanker(RankingConfig(strategy=RankingStrategy.GEOMETRIC_MEAN))
    ranker.config.strategy = "invalid"  # type: ignore[assignment]
    fallback = ranker.rank(report)
    assert fallback.strategy_used == RankingStrategy.GEOMETRIC_MEAN

    # convenience API
    ranked = rank_platforms(report, strategy=RankingStrategy.COMPOSITE)
    assert ranked.rankings


def test_tie_detection_and_cost_efficiency_fallback():
    report = _sample_report()
    # Force tie by giving same values
    report.query_comparisons["Q1"].metrics["duckdb"] = _metrics(10)
    report.query_comparisons["Q1"].metrics["snowflake"] = _metrics(10)
    result = PlatformRanker(RankingConfig(strategy=RankingStrategy.GEOMETRIC_MEAN, tie_threshold=1.0)).rank(report)
    assert isinstance(result.ties_detected, bool)

    # No cost analysis fallback path for cost efficiency strategy
    report_no_cost = _sample_report()
    report_no_cost.cost_analysis = None
    result_no_cost = PlatformRanker(RankingConfig(strategy=RankingStrategy.COST_EFFICIENCY)).rank(report_no_cost)
    assert result_no_cost.rankings
