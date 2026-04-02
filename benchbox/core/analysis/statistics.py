"""Statistical testing utilities for benchmark comparison.

Provides statistical significance tests, confidence intervals, and
effect size calculations for comparing benchmark results.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import math
from typing import Optional

from benchbox.core.analysis.models import (
    ConfidenceInterval,
    OutlierInfo,
    PerformanceMetrics,
    SignificanceLevel,
    StatisticalTest,
)

# Minimum sample size for reliable statistical tests
MIN_SAMPLE_SIZE = 3

# T-critical values for common confidence levels (two-tailed).
# Each confidence level maps to a sorted list of (max_n, t_value) tuples.
# The first entry whose threshold >= n is selected; the final entry
# (math.inf) serves as the large-sample z-value fallback.
_T_CRITICAL: dict[float, list[tuple[float, float]]] = {
    0.95: [
        (5, 2.776),
        (10, 2.262),
        (20, 2.093),
        (30, 2.045),
        (math.inf, 1.96),
    ],
    0.99: [
        (5, 4.604),
        (10, 3.250),
        (20, 2.861),
        (30, 2.756),
        (math.inf, 2.576),
    ],
}

# P-value thresholds for significance levels
P_VALUE_SIGNIFICANT = 0.05
P_VALUE_HIGHLY_SIGNIFICANT = 0.01
P_VALUE_VERY_HIGHLY_SIGNIFICANT = 0.001


def interpret_p_value(p_value: float) -> SignificanceLevel:
    """Interpret a p-value into a significance level.

    Args:
        p_value: The p-value from a statistical test

    Returns:
        SignificanceLevel indicating the level of significance
    """
    if p_value < P_VALUE_VERY_HIGHLY_SIGNIFICANT:
        return SignificanceLevel.VERY_HIGHLY_SIGNIFICANT
    elif p_value < P_VALUE_HIGHLY_SIGNIFICANT:
        return SignificanceLevel.HIGHLY_SIGNIFICANT
    elif p_value < P_VALUE_SIGNIFICANT:
        return SignificanceLevel.SIGNIFICANT
    else:
        return SignificanceLevel.NOT_SIGNIFICANT


def calculate_mean(values: list[float]) -> float:
    """Calculate arithmetic mean.

    Args:
        values: List of numeric values

    Returns:
        Arithmetic mean, or 0.0 if empty
    """
    if not values:
        return 0.0
    return sum(values) / len(values)


def calculate_geometric_mean(values: list[float]) -> float:
    """Calculate geometric mean.

    Used for averaging ratios and rates in benchmark comparisons.

    Args:
        values: List of positive numeric values

    Returns:
        Geometric mean, or 0.0 if empty or contains non-positive values
    """
    if not values:
        return 0.0
    if any(v <= 0 for v in values):
        # Filter out non-positive values
        positive_values = [v for v in values if v > 0]
        if not positive_values:
            return 0.0
        values = positive_values

    log_sum = sum(math.log(v) for v in values)
    return math.exp(log_sum / len(values))


def calculate_median(values: list[float]) -> float:
    """Calculate median value.

    Args:
        values: List of numeric values

    Returns:
        Median value, or 0.0 if empty
    """
    if not values:
        return 0.0
    sorted_values = sorted(values)
    n = len(sorted_values)
    if n % 2 == 1:
        return sorted_values[n // 2]
    else:
        return (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2


def calculate_std_dev(values: list[float], mean: Optional[float] = None) -> float:
    """Calculate sample standard deviation.

    Args:
        values: List of numeric values
        mean: Pre-calculated mean (optional)

    Returns:
        Sample standard deviation, or 0.0 if fewer than 2 values
    """
    if len(values) < 2:
        return 0.0
    if mean is None:
        mean = calculate_mean(values)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def calculate_variance(values: list[float], mean: Optional[float] = None) -> float:
    """Calculate sample variance.

    Args:
        values: List of numeric values
        mean: Pre-calculated mean (optional)

    Returns:
        Sample variance, or 0.0 if fewer than 2 values
    """
    if len(values) < 2:
        return 0.0
    if mean is None:
        mean = calculate_mean(values)
    return sum((x - mean) ** 2 for x in values) / (len(values) - 1)


def calculate_coefficient_of_variation(values: list[float]) -> float:
    """Calculate coefficient of variation (CV).

    CV = std_dev / mean, expressed as a ratio.
    Lower CV indicates more consistent performance.

    Args:
        values: List of numeric values

    Returns:
        Coefficient of variation, or 0.0 if mean is 0 or empty
    """
    if not values:
        return 0.0
    mean = calculate_mean(values)
    if mean == 0:
        return 0.0
    std_dev = calculate_std_dev(values, mean)
    return std_dev / mean


def _lookup_t_critical(confidence_level: float, n: int) -> float:
    """Look up the t-critical value for a given confidence level and sample size.

    Falls back to the 95% z-value (1.96) for unsupported confidence levels.
    """
    thresholds = _T_CRITICAL.get(confidence_level)
    if thresholds is None:
        return 1.96
    for max_n, t_value in thresholds:
        if n <= max_n:
            return t_value
    # Should not be reached since the last entry uses math.inf,
    # but return the final value as a safeguard.
    return thresholds[-1][1]


def calculate_confidence_interval(
    values: list[float],
    confidence_level: float = 0.95,
) -> ConfidenceInterval:
    """Calculate confidence interval for the mean.

    Uses t-distribution for small samples. For larger samples (n >= 30),
    this approximates the normal distribution.

    Args:
        values: List of numeric values
        confidence_level: Confidence level (default 0.95 for 95%)

    Returns:
        ConfidenceInterval with lower, upper bounds and point estimate
    """
    if not values or len(values) < 2:
        mean = calculate_mean(values) if values else 0.0
        return ConfidenceInterval(
            lower=mean,
            upper=mean,
            confidence_level=confidence_level,
            point_estimate=mean,
        )

    n = len(values)
    mean = calculate_mean(values)
    std_dev = calculate_std_dev(values, mean)
    std_err = std_dev / math.sqrt(n)

    t_critical = _lookup_t_critical(confidence_level, n)

    margin_of_error = t_critical * std_err

    return ConfidenceInterval(
        lower=mean - margin_of_error,
        upper=mean + margin_of_error,
        confidence_level=confidence_level,
        point_estimate=mean,
    )


def calculate_performance_metrics(values: list[float]) -> PerformanceMetrics:
    """Calculate comprehensive performance metrics from a list of times.

    Args:
        values: List of execution times in milliseconds

    Returns:
        PerformanceMetrics with mean, median, std_dev, etc.
    """
    if not values:
        return PerformanceMetrics(
            mean=0.0,
            median=0.0,
            std_dev=0.0,
            min_time=0.0,
            max_time=0.0,
            cv=0.0,
            sample_count=0,
            confidence_interval=None,
        )

    mean = calculate_mean(values)
    median = calculate_median(values)
    std_dev = calculate_std_dev(values, mean)
    cv = std_dev / mean if mean > 0 else 0.0
    ci = calculate_confidence_interval(values)

    return PerformanceMetrics(
        mean=mean,
        median=median,
        std_dev=std_dev,
        min_time=min(values),
        max_time=max(values),
        cv=cv,
        sample_count=len(values),
        confidence_interval=ci,
    )


def calculate_cohens_d(
    values_a: list[float],
    values_b: list[float],
) -> float:
    """Calculate Cohen's d effect size.

    Cohen's d measures the standardized difference between two means.
    Interpretation:
    - 0.2: small effect
    - 0.5: medium effect
    - 0.8: large effect

    Args:
        values_a: Values from group A
        values_b: Values from group B

    Returns:
        Cohen's d effect size, or 0.0 if insufficient data
    """
    if len(values_a) < 2 or len(values_b) < 2:
        return 0.0

    mean_a = calculate_mean(values_a)
    mean_b = calculate_mean(values_b)
    std_a = calculate_std_dev(values_a, mean_a)
    std_b = calculate_std_dev(values_b, mean_b)

    # Pooled standard deviation
    n_a = len(values_a)
    n_b = len(values_b)
    pooled_std = math.sqrt(((n_a - 1) * std_a**2 + (n_b - 1) * std_b**2) / (n_a + n_b - 2))

    if pooled_std == 0:
        return 0.0

    return (mean_a - mean_b) / pooled_std


def welchs_t_test(
    values_a: list[float],
    values_b: list[float],
) -> StatisticalTest:
    """Perform Welch's t-test for comparing two groups.

    Welch's t-test is more robust than Student's t-test when
    variances are unequal and/or sample sizes differ.

    Args:
        values_a: Values from group A
        values_b: Values from group B

    Returns:
        StatisticalTest with test statistic, p-value, and significance
    """
    n_a = len(values_a)
    n_b = len(values_b)

    if n_a < MIN_SAMPLE_SIZE or n_b < MIN_SAMPLE_SIZE:
        return StatisticalTest(
            test_name="welch_t_test",
            statistic=0.0,
            p_value=1.0,
            significance=SignificanceLevel.NOT_SIGNIFICANT,
            sample_size_a=n_a,
            sample_size_b=n_b,
            notes=f"Insufficient sample size (min {MIN_SAMPLE_SIZE} required)",
        )

    mean_a = calculate_mean(values_a)
    mean_b = calculate_mean(values_b)
    var_a = calculate_variance(values_a, mean_a)
    var_b = calculate_variance(values_b, mean_b)

    # Welch's t-statistic
    se_diff = math.sqrt(var_a / n_a + var_b / n_b)
    if se_diff == 0:
        return StatisticalTest(
            test_name="welch_t_test",
            statistic=0.0,
            p_value=1.0,
            significance=SignificanceLevel.NOT_SIGNIFICANT,
            sample_size_a=n_a,
            sample_size_b=n_b,
            notes="Zero variance in one or both groups",
        )

    t_stat = (mean_a - mean_b) / se_diff

    # Welch-Satterthwaite degrees of freedom
    numerator = (var_a / n_a + var_b / n_b) ** 2
    denominator = (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1)
    if denominator == 0:
        df = min(n_a, n_b) - 1
    else:
        df = numerator / denominator

    # Approximate p-value using t-distribution
    # For large df, this approaches normal distribution
    p_value = _approximate_t_pvalue(abs(t_stat), df)

    # Calculate effect size
    effect_size = calculate_cohens_d(values_a, values_b)

    return StatisticalTest(
        test_name="welch_t_test",
        statistic=t_stat,
        p_value=p_value,
        significance=interpret_p_value(p_value),
        effect_size=effect_size,
        sample_size_a=n_a,
        sample_size_b=n_b,
    )


def mann_whitney_u_test(
    values_a: list[float],
    values_b: list[float],
) -> StatisticalTest:
    """Perform Mann-Whitney U test (non-parametric).

    This test is useful when data is not normally distributed.
    It tests whether one group tends to have larger values than the other.

    Args:
        values_a: Values from group A
        values_b: Values from group B

    Returns:
        StatisticalTest with test statistic, p-value, and significance
    """
    n_a = len(values_a)
    n_b = len(values_b)

    if n_a < MIN_SAMPLE_SIZE or n_b < MIN_SAMPLE_SIZE:
        return StatisticalTest(
            test_name="mann_whitney_u",
            statistic=0.0,
            p_value=1.0,
            significance=SignificanceLevel.NOT_SIGNIFICANT,
            sample_size_a=n_a,
            sample_size_b=n_b,
            notes=f"Insufficient sample size (min {MIN_SAMPLE_SIZE} required)",
        )

    # Combine and rank all values
    combined = [(v, "a") for v in values_a] + [(v, "b") for v in values_b]
    combined.sort(key=lambda x: x[0])

    # Assign ranks (handling ties with average rank)
    ranks: dict[int, float] = {}
    i = 0
    while i < len(combined):
        j = i
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        # Average rank for tied values
        avg_rank = (i + 1 + j) / 2
        for k in range(i, j):
            ranks[k] = avg_rank
        i = j

    # Sum of ranks for group A
    rank_sum_a = sum(ranks[i] for i, (_, group) in enumerate(combined) if group == "a")

    # Mann-Whitney U statistic
    u_a = rank_sum_a - n_a * (n_a + 1) / 2
    u_b = n_a * n_b - u_a
    u_stat = min(u_a, u_b)

    # Normal approximation for p-value (valid for n_a, n_b >= 8)
    mean_u = n_a * n_b / 2
    std_u = math.sqrt(n_a * n_b * (n_a + n_b + 1) / 12)

    if std_u == 0:
        z = 0.0
    else:
        z = (u_stat - mean_u) / std_u

    # Two-tailed p-value from normal approximation
    p_value = 2 * (1 - _normal_cdf(abs(z)))

    return StatisticalTest(
        test_name="mann_whitney_u",
        statistic=u_stat,
        p_value=p_value,
        significance=interpret_p_value(p_value),
        sample_size_a=n_a,
        sample_size_b=n_b,
        notes="Non-parametric test, does not assume normality",
    )


def detect_outliers_iqr(
    values: list[float],
    multiplier: float = 1.5,
) -> list[tuple[int, float, float]]:
    """Detect outliers using Interquartile Range (IQR) method.

    A value is an outlier if it's below Q1 - multiplier*IQR
    or above Q3 + multiplier*IQR.

    Args:
        values: List of numeric values
        multiplier: IQR multiplier (1.5 for outliers, 3.0 for extreme outliers)

    Returns:
        List of (index, value, deviation) tuples for outliers
    """
    if len(values) < 4:
        return []

    sorted_values = sorted(values)
    n = len(sorted_values)
    q1_idx = n // 4
    q3_idx = 3 * n // 4

    q1 = sorted_values[q1_idx]
    q3 = sorted_values[q3_idx]
    iqr = q3 - q1

    lower_bound = q1 - multiplier * iqr
    upper_bound = q3 + multiplier * iqr

    outliers = []
    for i, v in enumerate(values):
        if v < lower_bound:
            outliers.append((i, v, lower_bound - v))
        elif v > upper_bound:
            outliers.append((i, v, v - upper_bound))

    return outliers


def detect_outliers_zscore(
    values: list[float],
    threshold: float = 3.0,
) -> list[tuple[int, float, float]]:
    """Detect outliers using Z-score method.

    A value is an outlier if its z-score exceeds the threshold.

    Args:
        values: List of numeric values
        threshold: Z-score threshold (default 3.0)

    Returns:
        List of (index, value, z_score) tuples for outliers
    """
    if len(values) < 3:
        return []

    mean = calculate_mean(values)
    std_dev = calculate_std_dev(values, mean)

    if std_dev == 0:
        return []

    outliers = []
    for i, v in enumerate(values):
        z_score = abs(v - mean) / std_dev
        if z_score > threshold:
            outliers.append((i, v, z_score))

    return outliers


def create_outlier_info(
    platform: str,
    query_id: str,
    value: float,
    method: str,
    threshold: float,
    deviation: float,
) -> OutlierInfo:
    """Create an OutlierInfo object.

    Args:
        platform: Platform name
        query_id: Query identifier
        value: The outlier value
        method: Detection method used
        threshold: Threshold used for detection
        deviation: How far outside the threshold

    Returns:
        OutlierInfo object
    """
    return OutlierInfo(
        platform=platform,
        query_id=query_id,
        value=value,
        method=method,
        threshold=threshold,
        deviation=deviation,
    )


def apply_bonferroni_correction(p_values: list[float]) -> list[float]:
    """Apply Bonferroni correction for multiple comparisons.

    Adjusts p-values to control family-wise error rate.
    Adjusted p = original p * number of tests (capped at 1.0)

    Args:
        p_values: List of original p-values

    Returns:
        List of adjusted p-values
    """
    if not p_values:
        return []
    n = len(p_values)
    return [min(p * n, 1.0) for p in p_values]


def calculate_statistical_power(
    effect_size: float,
    sample_size: int,
    alpha: float = 0.05,
) -> float:
    """Estimate statistical power for a comparison.

    Power is the probability of detecting an effect if it exists.
    Generally, power >= 0.8 is considered adequate.

    This is a simplified approximation based on effect size and sample size.

    Args:
        effect_size: Cohen's d or similar effect size
        sample_size: Sample size per group
        alpha: Significance level (default 0.05)

    Returns:
        Estimated power (0 to 1)
    """
    if sample_size < 2 or effect_size == 0:
        return 0.0

    # Simplified power calculation based on non-central t-distribution
    # This is an approximation; for precise values, use scipy.stats.power
    ncp = effect_size * math.sqrt(sample_size / 2)  # Non-centrality parameter

    # Critical value for alpha=0.05, two-tailed (approximation)
    critical = 1.96 if alpha == 0.05 else 2.576  # 0.01

    # Power approximation using normal distribution
    power = _normal_cdf(ncp - critical) + _normal_cdf(-ncp - critical)

    return max(0.0, min(1.0, power))


def recommend_sample_size(
    effect_size: float,
    target_power: float = 0.80,
    alpha: float = 0.05,
) -> int:
    """Recommend minimum sample size for desired power.

    Args:
        effect_size: Expected effect size (Cohen's d)
        target_power: Desired statistical power (default 0.80)
        alpha: Significance level (default 0.05)

    Returns:
        Recommended sample size per group
    """
    if effect_size == 0:
        return 1000  # Cannot calculate for zero effect

    # Use power analysis formula (approximation)
    z_alpha = 1.96 if alpha == 0.05 else 2.576  # Two-tailed critical value
    z_beta = 0.84 if target_power == 0.80 else 1.28  # Power = 0.90

    # Sample size formula: n = 2 * ((z_alpha + z_beta) / d)^2
    n = 2 * ((z_alpha + z_beta) / abs(effect_size)) ** 2

    return max(MIN_SAMPLE_SIZE, int(math.ceil(n)))


def _normal_cdf(x: float) -> float:
    """Approximate standard normal CDF using error function approximation."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _approximate_t_pvalue(t_stat: float, df: float) -> float:
    """Approximate two-tailed p-value from t-distribution.

    Uses normal approximation for large df, and lookup tables for small df.

    Args:
        t_stat: Absolute t-statistic
        df: Degrees of freedom

    Returns:
        Two-tailed p-value (approximation)
    """
    # For large df (>= 30), use normal approximation
    if df >= 30:
        return 2 * (1 - _normal_cdf(t_stat))

    # For smaller df, use approximation based on Student's t-distribution
    # This is a rough approximation; for exact values, use scipy.stats.t
    # Using the relationship: t-distribution approaches normal as df -> infinity
    # Adjustment factor for small df
    adjustment = 1 + 1 / (4 * df)  # Conservative adjustment
    adjusted_t = t_stat / adjustment

    return 2 * (1 - _normal_cdf(adjusted_t))
