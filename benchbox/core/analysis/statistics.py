# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import math
from typing import Optional

from benchbox.core.analysis.models import (
    ConfidenceInterval,
    OutlierInfo,
    PerformanceMetrics,
    SignificanceLevel,
    StatisticalTest,
)

MIN_SAMPLE_SIZE = 3

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

P_VALUE_SIGNIFICANT = 0.05
P_VALUE_HIGHLY_SIGNIFICANT = 0.01
P_VALUE_VERY_HIGHLY_SIGNIFICANT = 0.001


def interpret_p_value(p_value: float) -> SignificanceLevel:
    if p_value < P_VALUE_VERY_HIGHLY_SIGNIFICANT:
        return SignificanceLevel.VERY_HIGHLY_SIGNIFICANT
    elif p_value < P_VALUE_HIGHLY_SIGNIFICANT:
        return SignificanceLevel.HIGHLY_SIGNIFICANT
    elif p_value < P_VALUE_SIGNIFICANT:
        return SignificanceLevel.SIGNIFICANT
    else:
        return SignificanceLevel.NOT_SIGNIFICANT


def calculate_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def calculate_geometric_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    if any(v <= 0 for v in values):
        positive_values = [v for v in values if v > 0]
        if not positive_values:
            return 0.0
        values = positive_values

    log_sum = sum(math.log(v) for v in values)
    return math.exp(log_sum / len(values))


def calculate_median(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    n = len(sorted_values)
    if n % 2 == 1:
        return sorted_values[n // 2]
    else:
        return (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2


def calculate_std_dev(values: list[float], mean: Optional[float] = None) -> float:
    if len(values) < 2:
        return 0.0
    if mean is None:
        mean = calculate_mean(values)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def calculate_variance(values: list[float], mean: Optional[float] = None) -> float:
    if len(values) < 2:
        return 0.0
    if mean is None:
        mean = calculate_mean(values)
    return sum((x - mean) ** 2 for x in values) / (len(values) - 1)


def calculate_coefficient_of_variation(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = calculate_mean(values)
    if mean == 0:
        return 0.0
    std_dev = calculate_std_dev(values, mean)
    return std_dev / mean


def _lookup_t_critical(confidence_level: float, n: int) -> float:
    thresholds = _T_CRITICAL.get(confidence_level)
    if thresholds is None:
        return 1.96
    for max_n, t_value in thresholds:
        if n <= max_n:
            return t_value
    return thresholds[-1][1]


def calculate_confidence_interval(
    values: list[float],
    confidence_level: float = 0.95,
) -> ConfidenceInterval:
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
    if len(values_a) < 2 or len(values_b) < 2:
        return 0.0

    mean_a = calculate_mean(values_a)
    mean_b = calculate_mean(values_b)
    std_a = calculate_std_dev(values_a, mean_a)
    std_b = calculate_std_dev(values_b, mean_b)

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

    numerator = (var_a / n_a + var_b / n_b) ** 2
    denominator = (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1)
    if denominator == 0:
        df = min(n_a, n_b) - 1
    else:
        df = numerator / denominator

    p_value = _approximate_t_pvalue(abs(t_stat), df)

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

    combined = [(v, "a") for v in values_a] + [(v, "b") for v in values_b]
    combined.sort(key=lambda x: x[0])

    ranks: dict[int, float] = {}
    i = 0
    while i < len(combined):
        j = i
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        avg_rank = (i + 1 + j) / 2
        for k in range(i, j):
            ranks[k] = avg_rank
        i = j

    rank_sum_a = sum(ranks[i] for i, (_, group) in enumerate(combined) if group == "a")

    u_a = rank_sum_a - n_a * (n_a + 1) / 2
    u_b = n_a * n_b - u_a
    u_stat = min(u_a, u_b)

    mean_u = n_a * n_b / 2
    std_u = math.sqrt(n_a * n_b * (n_a + n_b + 1) / 12)

    if std_u == 0:
        z = 0.0
    else:
        z = (u_stat - mean_u) / std_u

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
    return OutlierInfo(
        platform=platform,
        query_id=query_id,
        value=value,
        method=method,
        threshold=threshold,
        deviation=deviation,
    )


def apply_bonferroni_correction(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    n = len(p_values)
    return [min(p * n, 1.0) for p in p_values]


def calculate_statistical_power(
    effect_size: float,
    sample_size: int,
    alpha: float = 0.05,
) -> float:
    if sample_size < 2 or effect_size == 0:
        return 0.0

    ncp = effect_size * math.sqrt(sample_size / 2)

    critical = 1.96 if alpha == 0.05 else 2.576

    power = _normal_cdf(ncp - critical) + _normal_cdf(-ncp - critical)

    return max(0.0, min(1.0, power))


def recommend_sample_size(
    effect_size: float,
    target_power: float = 0.80,
    alpha: float = 0.05,
) -> int:
    if effect_size == 0:
        return 1000

    z_alpha = 1.96 if alpha == 0.05 else 2.576
    z_beta = 0.84 if target_power == 0.80 else 1.28

    n = 2 * ((z_alpha + z_beta) / abs(effect_size)) ** 2

    return max(MIN_SAMPLE_SIZE, int(math.ceil(n)))


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _approximate_t_pvalue(t_stat: float, df: float) -> float:
    if df >= 30:
        return 2 * (1 - _normal_cdf(t_stat))

    adjustment = 1 + 1 / (4 * df)
    adjusted_t = t_stat / adjustment

    return 2 * (1 - _normal_cdf(adjusted_t))
