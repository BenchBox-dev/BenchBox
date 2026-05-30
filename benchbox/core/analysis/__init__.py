"""Analysis module for benchmark comparison.

This module provides comprehensive tools for comparing benchmark results
across multiple database platforms with:

- Statistical significance testing (Welch's t-test, Mann-Whitney U)
- Cost vs performance analysis
- Head-to-head platform comparisons

Example:
    >>> from benchbox.core.analysis import PlatformComparison
    >>>
    >>> # Compare results from multiple platforms
    >>> comparison = PlatformComparison.from_directory("benchmark_runs/tpch/sf10/")
    >>> report = comparison.compare()
    >>>
    >>> # Get the winner
    >>> emit(f"Winner: {report.winner}")

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

# Comparison engine
from benchbox.core.analysis.comparison import (
    ComparisonConfig,
    PlatformComparison,
)

# Data models
from benchbox.core.analysis.models import (
    ComparisonOutcome,
    ComparisonReport,
    ConfidenceInterval,
    CostPerformanceAnalysis,
    HeadToHeadComparison,
    OutlierInfo,
    PerformanceMetrics,
    PlatformRanking,
    QueryComparison,
    SignificanceLevel,
    StatisticalTest,
    ValidationResult,
    WinLossRecord,
)

# Statistical utilities
from benchbox.core.analysis.statistics import (
    apply_bonferroni_correction,
    calculate_coefficient_of_variation,
    calculate_cohens_d,
    calculate_confidence_interval,
    calculate_geometric_mean,
    calculate_mean,
    calculate_median,
    calculate_performance_metrics,
    calculate_statistical_power,
    calculate_std_dev,
    detect_outliers_iqr,
    detect_outliers_zscore,
    interpret_p_value,
    mann_whitney_u_test,
    recommend_sample_size,
    welchs_t_test,
)

__all__ = [
    # Models
    "ComparisonOutcome",
    "ComparisonReport",
    "ConfidenceInterval",
    "CostPerformanceAnalysis",
    "HeadToHeadComparison",
    "OutlierInfo",
    "PerformanceMetrics",
    "PlatformRanking",
    "QueryComparison",
    "SignificanceLevel",
    "StatisticalTest",
    "ValidationResult",
    "WinLossRecord",
    # Comparison
    "ComparisonConfig",
    "PlatformComparison",
    # Statistics
    "apply_bonferroni_correction",
    "calculate_coefficient_of_variation",
    "calculate_cohens_d",
    "calculate_confidence_interval",
    "calculate_geometric_mean",
    "calculate_mean",
    "calculate_median",
    "calculate_performance_metrics",
    "calculate_statistical_power",
    "calculate_std_dev",
    "detect_outliers_iqr",
    "detect_outliers_zscore",
    "interpret_p_value",
    "mann_whitney_u_test",
    "recommend_sample_size",
    "welchs_t_test",
]
