from __future__ import annotations


def speedup_vs_best(
    this_value: float | None,
    best_value: float | None,
    *,
    higher_is_better: bool,
) -> float | None:
    if this_value is None or best_value is None or this_value <= 0 or best_value <= 0:
        return None
    return this_value / best_value if higher_is_better else best_value / this_value


def speedup_vs_slowest(
    this_value: float | None,
    slowest_value: float | None,
    *,
    higher_is_better: bool,
) -> float | None:
    if this_value is None or slowest_value is None or this_value <= 0 or slowest_value <= 0:
        return None
    return this_value / slowest_value if higher_is_better else slowest_value / this_value


def per_query_speedup_spread(values: list[float]) -> float | None:
    valid = [v for v in values if v > 0]
    if not valid:
        return None
    fastest = min(valid)
    slowest = max(valid)
    return slowest / fastest if fastest > 0 else None


def baseline_speedup_ratio(
    baseline_ms: float | None,
    this_ms: float | None,
) -> float | None:
    if baseline_ms is None or this_ms is None or baseline_ms <= 0 or this_ms <= 0:
        return None
    return baseline_ms / this_ms


def delta_pct(
    this_ms: float | None,
    baseline_ms: float | None,
) -> float | None:
    if this_ms is None or baseline_ms is None or baseline_ms <= 0 or this_ms <= 0:
        return None
    return ((this_ms - baseline_ms) / baseline_ms) * 100.0
