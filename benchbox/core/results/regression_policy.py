"""One regression and trend policy for every BenchBox surface.

Before this module, four places answered the same question differently: CLI
``compare``'s threshold check, CLI ``report``'s display cutoff, MCP analytics'
severity ladder and trend thresholds, and a hardcoded ``change > 10`` inside the
results database. An agent asking over MCP and a human asking over the CLI could
reach different verdicts from the same result files.

The canonical policy is MCP's, because it was the only one that classified
rather than merely thresholded: it had a severity ladder, an improvement class,
and an explicit trend vocabulary. The CLI's caller-supplied threshold semantics
are preserved as an override on top of it.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Final, Literal

# A run is a regression when it is more than this much slower than its baseline.
# Callers may override it -- CLI ``compare --fail-on-regression``, MCP
# ``analyze_results(threshold_percent=...)``, and ``report --threshold`` all map
# onto this same parameter -- but every surface starts here.
DEFAULT_REGRESSION_THRESHOLD_PERCENT: Final = 10.0

# Movement smaller than this is noise, not a trend. This is the cutoff behind
# report's "IMPROVED" label and MCP's improving/degrading trend directions; they
# were independently written as 5 and must stay one number.
TREND_SIGNIFICANCE_PERCENT: Final = 5.0

# Severity ladder, ordered most severe first. Read as "delta_percent >= bound".
SEVERITY_LADDER: Final = (
    ("critical", 100.0),
    ("high", 50.0),
    ("medium", 25.0),
)
DEFAULT_SEVERITY: Final = "low"

ChangeClass = Literal["regression", "improvement", "stable"]
TrendDirection = Literal["improving", "degrading", "stable", "insufficient_data", "unknown"]

CHANGE_CLASSES: Final = ("regression", "improvement", "stable")
TREND_DIRECTIONS: Final = ("improving", "degrading", "stable", "insufficient_data", "unknown")
SEVERITIES: Final = ("critical", "high", "medium", "low")


def percent_change(baseline: float, current: float) -> float | None:
    """Return the percentage change from ``baseline`` to ``current``.

    Positive means slower, which is the sign convention every surface uses.
    Returns None when ``baseline`` is not strictly positive, because a
    percentage change against a zero or negative baseline is not meaningful --
    callers must skip the comparison rather than report a fabricated number.
    """
    if baseline <= 0:
        return None
    return ((current - baseline) / baseline) * 100.0


def classify_severity(delta_percent: float) -> str:
    """Return the severity band for a regression's percentage change."""
    for severity, lower_bound in SEVERITY_LADDER:
        if delta_percent >= lower_bound:
            return severity
    return DEFAULT_SEVERITY


def classify_change(
    delta_percent: float,
    threshold_percent: float = DEFAULT_REGRESSION_THRESHOLD_PERCENT,
) -> ChangeClass:
    """Classify one percentage change against a symmetric threshold.

    The threshold is symmetric: a change slower than ``+threshold`` is a
    regression, faster than ``-threshold`` is an improvement, and anything
    between is stable.
    """
    if delta_percent > threshold_percent:
        return "regression"
    if delta_percent < -threshold_percent:
        return "improvement"
    return "stable"


def is_regression(
    delta_percent: float | None,
    threshold_percent: float = DEFAULT_REGRESSION_THRESHOLD_PERCENT,
) -> bool:
    """Return True when ``delta_percent`` is a regression at this threshold.

    A None delta -- an unusable baseline -- is not a regression.
    """
    if delta_percent is None:
        return False
    return classify_change(delta_percent, threshold_percent) == "regression"


def classify_trend(values: list[float]) -> tuple[TrendDirection, float]:
    """Classify a first-to-last trend across ordered measurements.

    Returns the direction and the percentage change. Fewer than two points is
    ``insufficient_data``; a non-positive first value is ``unknown``. Both
    return 0.0 rather than a fabricated percentage.

    Movement within +/- ``TREND_SIGNIFICANCE_PERCENT`` is ``stable``.
    """
    if len(values) < 2:
        return "insufficient_data", 0.0

    change = percent_change(values[0], values[-1])
    if change is None:
        return "unknown", 0.0

    if change < -TREND_SIGNIFICANCE_PERCENT:
        return "improving", change
    if change > TREND_SIGNIFICANCE_PERCENT:
        return "degrading", change
    return "stable", change


def is_meaningful_improvement(change_percent: float | None) -> bool:
    """Return True when a change is a large enough speedup to label as improved.

    This is the display-layer cutoff behind ``benchbox report trends``' IMPROVED
    label. It lives here rather than in the command file because a display
    cutoff is policy too -- an inline ``-5`` in a render function is how these
    four implementations drifted apart in the first place.
    """
    if change_percent is None:
        return False
    return change_percent < -TREND_SIGNIFICANCE_PERCENT


__all__ = [
    "CHANGE_CLASSES",
    "DEFAULT_REGRESSION_THRESHOLD_PERCENT",
    "DEFAULT_SEVERITY",
    "SEVERITIES",
    "SEVERITY_LADDER",
    "TREND_DIRECTIONS",
    "TREND_SIGNIFICANCE_PERCENT",
    "ChangeClass",
    "TrendDirection",
    "classify_change",
    "classify_severity",
    "classify_trend",
    "is_meaningful_improvement",
    "is_regression",
    "percent_change",
]
