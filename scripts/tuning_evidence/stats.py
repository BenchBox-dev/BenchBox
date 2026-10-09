from __future__ import annotations

import math
import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

Samples = Mapping[str, Sequence[float | None]]

DEFAULT_RESAMPLES = 2000
DEFAULT_CONFIDENCE = 0.95
DEFAULT_PENALTY_SECONDS = 300.0


@dataclass(frozen=True)
class RuleThresholds:
    min_rounds: int = 7
    aa_point_low: float = 0.95
    aa_point_high: float = 1.05
    load_settle_ratio: float = 1.5
    slow_query_ratio: float = 1.5


@dataclass(frozen=True)
class QueryComparison:
    query: str
    base_median: float
    candidate_median: float
    ratio: float
    ci_low: float
    ci_high: float


@dataclass(frozen=True)
class Comparison:
    base: str
    candidate: str
    rounds: int
    queries: tuple[str, ...]
    common: tuple[str, ...]
    base_failures: tuple[str, ...]
    candidate_failures: tuple[str, ...]
    g: float | None
    g_ci_low: float | None
    g_ci_high: float | None
    g_penalized: float | None
    penalty_seconds: float
    base_total_median_seconds: float
    candidate_total_median_seconds: float
    per_query: tuple[QueryComparison, ...]
    resamples: int
    seed: int
    confidence: float


@dataclass(frozen=True)
class TotalsComparison:
    base: str
    candidate: str
    rounds: int
    base_median_seconds: float
    candidate_median_seconds: float
    ratio: float
    ci_low: float
    ci_high: float
    resamples: int
    seed: int
    confidence: float


@dataclass(frozen=True)
class Calibration:
    passed: bool
    g: float | None
    g_ci_low: float | None
    g_ci_high: float | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Verdict:
    label: str
    findings: tuple[str, ...]
    blocked_by: tuple[str, ...]


def query_sort_key(query: str) -> tuple:
    return tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in re.split(r"(\d+)", query) if part)


def median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("median of an empty sequence")
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def geometric_mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("geometric mean of an empty sequence")
    if any(value <= 0 for value in values):
        raise ValueError("geometric mean needs positive values")
    return math.exp(math.fsum(math.log(value) for value in values) / len(values))


def percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile of an empty sequence")
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def passes(samples: Sequence[float | None] | None) -> bool:
    return bool(samples) and all(value is not None for value in samples)


def _round_count(*sample_sets: Samples) -> int:
    lengths = {len(values) for samples in sample_sets for values in samples.values()}
    if len(lengths) > 1:
        raise ValueError(f"samples are not round-aligned: lengths {sorted(lengths)}")
    return lengths.pop() if lengths else 0


def _medians_at(samples: Samples, queries: Sequence[str], rounds: Sequence[int]) -> dict[str, float]:
    return {query: median([samples[query][index] for index in rounds]) for query in queries}


def resample_rounds(rounds: int, resamples: int, seed: int) -> list[list[int]]:
    rng = random.Random(seed)
    return [[rng.randrange(rounds) for _ in range(rounds)] for _ in range(resamples)]


def compare(
    base_name: str,
    base: Samples,
    candidate_name: str,
    candidate: Samples,
    *,
    seed: int,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    penalty_seconds: float = DEFAULT_PENALTY_SECONDS,
) -> Comparison:
    rounds = _round_count(base, candidate)
    queries = tuple(sorted(set(base) | set(candidate), key=query_sort_key))
    base_failures = tuple(query for query in queries if not passes(base.get(query)))
    candidate_failures = tuple(query for query in queries if not passes(candidate.get(query)))
    common = tuple(query for query in queries if query not in base_failures and query not in candidate_failures)
    every_round = list(range(rounds))
    base_medians = _medians_at(base, common, every_round)
    candidate_medians = _medians_at(candidate, common, every_round)
    ratios = {query: candidate_medians[query] / base_medians[query] for query in common}

    tail = (1.0 - confidence) / 2.0
    per_query: list[QueryComparison] = []
    g = g_low = g_high = None
    if common:
        g = geometric_mean(list(ratios.values()))
        boot_g: list[float] = []
        boot_ratios: dict[str, list[float]] = {query: [] for query in common}
        for indices in resample_rounds(rounds, resamples, seed):
            resampled_base = _medians_at(base, common, indices)
            resampled_candidate = _medians_at(candidate, common, indices)
            resampled = [resampled_candidate[query] / resampled_base[query] for query in common]
            for query, ratio in zip(common, resampled):
                boot_ratios[query].append(ratio)
            boot_g.append(geometric_mean(resampled))
        g_low, g_high = percentile(boot_g, tail), percentile(boot_g, 1.0 - tail)
        per_query = [
            QueryComparison(
                query=query,
                base_median=base_medians[query],
                candidate_median=candidate_medians[query],
                ratio=ratios[query],
                ci_low=percentile(boot_ratios[query], tail),
                ci_high=percentile(boot_ratios[query], 1.0 - tail),
            )
            for query in common
        ]

    return Comparison(
        base=base_name,
        candidate=candidate_name,
        rounds=rounds,
        queries=queries,
        common=common,
        base_failures=base_failures,
        candidate_failures=candidate_failures,
        g=g,
        g_ci_low=g_low,
        g_ci_high=g_high,
        g_penalized=penalized_g(base, candidate, queries, penalty_seconds),
        penalty_seconds=penalty_seconds,
        base_total_median_seconds=math.fsum(base_medians.values()),
        candidate_total_median_seconds=math.fsum(candidate_medians.values()),
        per_query=tuple(per_query),
        resamples=resamples,
        seed=seed,
        confidence=confidence,
    )


def penalized_g(base: Samples, candidate: Samples, queries: Sequence[str], penalty_seconds: float) -> float | None:
    if not queries:
        return None

    def value(samples: Samples, query: str) -> float:
        values = samples.get(query)
        if not passes(values):
            return penalty_seconds
        return median([sample for sample in values or () if sample is not None])

    return geometric_mean([value(candidate, query) / value(base, query) for query in queries])


def compare_totals(
    base_name: str,
    base: Sequence[float],
    candidate_name: str,
    candidate: Sequence[float],
    *,
    seed: int,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
) -> TotalsComparison:
    if len(base) != len(candidate) or not base:
        raise ValueError("totals must be non-empty and round-aligned")
    tail = (1.0 - confidence) / 2.0
    boot = [
        median([candidate[index] for index in indices]) / median([base[index] for index in indices])
        for indices in resample_rounds(len(base), resamples, seed)
    ]
    return TotalsComparison(
        base=base_name,
        candidate=candidate_name,
        rounds=len(base),
        base_median_seconds=median(base),
        candidate_median_seconds=median(candidate),
        ratio=median(candidate) / median(base),
        ci_low=percentile(boot, tail),
        ci_high=percentile(boot, 1.0 - tail),
        resamples=resamples,
        seed=seed,
        confidence=confidence,
    )


def calibration_check(
    comparison: Comparison,
    thresholds: RuleThresholds,
    *,
    answer_mismatches: Sequence[str] = (),
    unsettled_arms: Sequence[str] = (),
    blockers: Sequence[str] = (),
) -> Calibration:
    reasons: list[str] = list(blockers)
    if comparison.rounds < thresholds.min_rounds:
        reasons.append(f"{comparison.rounds} rounds is below the minimum of {thresholds.min_rounds}")
    if comparison.g is None or comparison.g_ci_low is None or comparison.g_ci_high is None:
        reasons.append("no query passed in both arms")
    else:
        if not comparison.g_ci_low <= 1.0 <= comparison.g_ci_high:
            reasons.append(f"CI [{comparison.g_ci_low:.4f}, {comparison.g_ci_high:.4f}] does not contain 1.0")
        if not thresholds.aa_point_low <= comparison.g <= thresholds.aa_point_high:
            reasons.append(f"G {comparison.g:.4f} is outside [{thresholds.aa_point_low}, {thresholds.aa_point_high}]")
    if comparison.base_failures != comparison.candidate_failures:
        reasons.append(
            f"arms fail different queries: {list(comparison.base_failures)} vs {list(comparison.candidate_failures)}"
        )
    if answer_mismatches:
        reasons.append(f"answers differ between identical arms: {list(answer_mismatches)}")
    if unsettled_arms:
        reasons.append(f"arms not settled: {list(unsettled_arms)}")
    return Calibration(
        passed=not reasons,
        g=comparison.g,
        g_ci_low=comparison.g_ci_low,
        g_ci_high=comparison.g_ci_high,
        reasons=tuple(reasons),
    )


def slow_queries(comparison: Comparison, thresholds: RuleThresholds) -> tuple[QueryComparison, ...]:
    return tuple(
        query for query in comparison.per_query if query.ratio > thresholds.slow_query_ratio and query.ci_low > 1.0
    )


def verdict(
    comparison: Comparison,
    thresholds: RuleThresholds,
    *,
    calibrated: bool,
    answer_mismatches: Sequence[str],
    base_load_settle_seconds: float | None,
    candidate_load_settle_seconds: float | None,
    blockers: Sequence[str] = (),
    extra_failures: Sequence[str] = (),
) -> Verdict:
    blocked = list(blockers)
    if not calibrated:
        blocked.append("uncalibrated: no passing A/A run for this platform, benchmark and scale")
    if comparison.rounds < thresholds.min_rounds:
        blocked.append(f"{comparison.rounds} rounds is below the minimum of {thresholds.min_rounds}")
    if comparison.g is None:
        blocked.append("no query passed in both arms")

    regressions: list[str] = []
    newly_failing = [query for query in comparison.candidate_failures if query not in comparison.base_failures]
    if newly_failing:
        regressions.append(f"passes in {comparison.base}, fails in {comparison.candidate}: {newly_failing}")
    if extra_failures:
        regressions.append(f"fails in {comparison.candidate} under concurrent streams only: {list(extra_failures)}")
    if answer_mismatches:
        regressions.append(f"answers differ: {list(answer_mismatches)}")
    if comparison.g_ci_low is not None and comparison.g_ci_low > 1.0:
        regressions.append(f"CI lower bound {comparison.g_ci_low:.4f} is above 1.0")
    benefit = comparison.g_ci_high is not None and comparison.g_ci_high < 1.0
    if (
        not regressions
        and not benefit
        and base_load_settle_seconds
        and candidate_load_settle_seconds is not None
        and candidate_load_settle_seconds > thresholds.load_settle_ratio * base_load_settle_seconds
    ):
        regressions.append(
            f"load plus settle {candidate_load_settle_seconds:.1f}s is more than "
            f"{thresholds.load_settle_ratio}x {comparison.base}'s {base_load_settle_seconds:.1f}s"
        )

    findings = list(regressions)
    if benefit and comparison.g_ci_high is not None:
        findings.append(f"CI upper bound {comparison.g_ci_high:.4f} is below 1.0")
    outcome = "regression" if regressions else "benefit" if benefit else "neutral"
    return Verdict(
        label="none" if blocked else outcome,
        findings=tuple(findings),
        blocked_by=tuple(blocked),
    )
