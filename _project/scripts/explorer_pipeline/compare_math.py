"""Canonical cohort-comparison arithmetic for the results explorer.

These are the reference formulas that both the DuckDB pipeline populate step
and any runtime SQL window-function computation must agree with. Kept here
(under ``_project/scripts/explorer_pipeline/``) so the registry in
``_project/planning/visible_metrics.yaml`` can reference them as the
canonical_ref for derived speedup / delta columns. TypeScript is NEVER the
oracle for these semantics - any future TS renderer that needs the same value
reads it from DuckDB (either from a pre-populated column or from a SQL window
function that evaluates the same formula at query time).

Each helper accepts and returns plain Python floats. ``None`` inputs and
non-positive values always yield ``None`` so callers can uniformly handle
missing data.
"""

from __future__ import annotations


def speedup_vs_best(
    this_value: float | None,
    best_value: float | None,
    *,
    higher_is_better: bool,
) -> float | None:
    """Return this row's speedup relative to the cohort best, in ``(0, 1]``.

    The best row in a cohort maps to ``1.0``; every worse row maps to a value
    strictly below ``1.0``. Direction-aware on the primary metric:

      - ``higher_is_better=True``  (e.g. power_score):  ``this / best``
      - ``higher_is_better=False`` (e.g. geomean_ms):   ``best / this``
    """
    if this_value is None or best_value is None or this_value <= 0 or best_value <= 0:
        return None
    return this_value / best_value if higher_is_better else best_value / this_value


def speedup_vs_slowest(
    this_value: float | None,
    slowest_value: float | None,
    *,
    higher_is_better: bool,
) -> float | None:
    """Return this row's speedup relative to the cohort slowest, in ``[1.0, ∞)``.

    The slowest row in a cohort maps to ``1.0``; every better row maps to a
    value strictly above ``1.0``. Direction-aware on the primary metric:

      - ``higher_is_better=True``  (e.g. power_score):  ``this / slowest``
      - ``higher_is_better=False`` (e.g. geomean_ms):   ``slowest / this``
    """
    if this_value is None or slowest_value is None or this_value <= 0 or slowest_value <= 0:
        return None
    return this_value / slowest_value if higher_is_better else slowest_value / this_value


def per_query_speedup_spread(values: list[float]) -> float | None:
    """Return slowest / fastest across a set of per-query timings.

    Used by the Compare page per-query breakdown column. ``None`` when the
    input is empty or contains no positive values. Always ``>= 1.0`` when
    defined.
    """
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
    """Return ``baseline_ms / this_ms`` - per-baseline per-query speedup.

    Used by NormalizedSpeedupChart where the user selects any result as the
    baseline. ``> 1`` means this result is faster than the baseline; ``< 1``
    means slower. ``None`` for invalid inputs.
    """
    if baseline_ms is None or this_ms is None or baseline_ms <= 0 or this_ms <= 0:
        return None
    return baseline_ms / this_ms


def delta_pct(
    this_ms: float | None,
    baseline_ms: float | None,
) -> float | None:
    """Return the percent change of ``this_ms`` relative to ``baseline_ms``.

    ``(this - baseline) / baseline * 100``. Negative = faster than baseline;
    positive = slower. Used by DivergingBarChart.
    """
    if this_ms is None or baseline_ms is None or baseline_ms <= 0 or this_ms <= 0:
        return None
    return ((this_ms - baseline_ms) / baseline_ms) * 100.0
