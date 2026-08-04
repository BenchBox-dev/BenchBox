"""Every surface must reach the same regression verdict from the same numbers.

Before `one-engine-unify-regression-policy` four implementations answered this
question: CLI ``compare``'s threshold check, CLI ``report``'s display cutoff,
MCP analytics' severity ladder and trend thresholds, and a hardcoded
``change > 10`` inside the results database. This module pins that they now
agree, and characterizes the one behavior that deliberately changed.
"""

from __future__ import annotations

import pytest

from benchbox.core.results.regression_policy import (
    DEFAULT_REGRESSION_THRESHOLD_PERCENT,
    SEVERITIES,
    TREND_DIRECTIONS,
    TREND_SIGNIFICANCE_PERCENT,
    classify_change,
    classify_severity,
    classify_trend,
    is_meaningful_improvement,
    is_regression,
    percent_change,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# Percentage changes spanning every band boundary, including the exact edges.
SHARED_DELTAS = [-150.0, -100.0, -50.0, -10.1, -10.0, -5.1, -5.0, 0.0, 5.0, 5.1, 10.0, 10.1, 25.0, 50.0, 100.0, 250.0]


class TestPolicyIsSelfConsistent:
    @pytest.mark.parametrize("delta", SHARED_DELTAS)
    def test_classification_and_predicate_agree(self, delta: float):
        assert is_regression(delta) is (classify_change(delta) == "regression")

    @pytest.mark.parametrize("delta", SHARED_DELTAS)
    def test_severity_is_always_a_declared_band(self, delta: float):
        assert classify_severity(delta) in SEVERITIES

    def test_thresholds_are_exclusive_at_the_boundary(self):
        """Exactly at the threshold is stable, not a regression."""
        assert classify_change(DEFAULT_REGRESSION_THRESHOLD_PERCENT) == "stable"
        assert classify_change(DEFAULT_REGRESSION_THRESHOLD_PERCENT + 0.1) == "regression"
        assert classify_change(-DEFAULT_REGRESSION_THRESHOLD_PERCENT) == "stable"
        assert classify_change(-DEFAULT_REGRESSION_THRESHOLD_PERCENT - 0.1) == "improvement"

    def test_severity_ladder_boundaries(self):
        assert classify_severity(100.0) == "critical"
        assert classify_severity(99.9) == "high"
        assert classify_severity(50.0) == "high"
        assert classify_severity(49.9) == "medium"
        assert classify_severity(25.0) == "medium"
        assert classify_severity(24.9) == "low"

    def test_unusable_baseline_is_not_a_regression(self):
        assert percent_change(0.0, 100.0) is None
        assert percent_change(-1.0, 100.0) is None
        assert is_regression(None) is False

    @pytest.mark.parametrize(
        ("values", "direction"),
        [
            ([], "insufficient_data"),
            ([100.0], "insufficient_data"),
            ([0.0, 100.0], "unknown"),
            ([100.0, 90.0], "improving"),
            ([100.0, 110.0], "degrading"),
            ([100.0, 103.0], "stable"),
            ([100.0, 105.0], "stable"),
            ([100.0, 95.0], "stable"),
        ],
    )
    def test_trend_directions(self, values: list[float], direction: str):
        assert classify_trend(values)[0] == direction
        assert classify_trend(values)[0] in TREND_DIRECTIONS

    def test_trend_reports_zero_rather_than_a_fabricated_percentage(self):
        assert classify_trend([])[1] == 0.0
        assert classify_trend([0.0, 100.0])[1] == 0.0

    def test_improvement_label_uses_the_same_significance_cutoff(self):
        assert is_meaningful_improvement(-TREND_SIGNIFICANCE_PERCENT) is False
        assert is_meaningful_improvement(-TREND_SIGNIFICANCE_PERCENT - 0.1) is True
        assert is_meaningful_improvement(None) is False
        assert classify_trend([100.0, 100.0 - TREND_SIGNIFICANCE_PERCENT - 0.1])[0] == "improving"


class TestThreeSurfaceRegressionParity:
    """CLI compare, MCP analytics, and the results DB must agree."""

    @pytest.mark.parametrize("delta", SHARED_DELTAS)
    def test_cli_compare_and_core_agree(self, delta: float):
        from benchbox.cli.commands.compare import _check_regression

        comparison = {"query_comparisons": [{"change_percent": delta}], "performance_changes": {}}
        # CLI takes the threshold as a decimal fraction.
        cli_verdict = _check_regression(comparison, DEFAULT_REGRESSION_THRESHOLD_PERCENT / 100)

        assert cli_verdict is is_regression(delta)

    @pytest.mark.parametrize("delta", SHARED_DELTAS)
    def test_mcp_analytics_and_core_agree(self, delta: float):
        from benchbox.mcp.tools.analytics import _classify_query_changes

        baseline = 100.0
        current = baseline * (1 + delta / 100)
        regressions, improvements, stable = _classify_query_changes(
            {"1": baseline}, {"1": current}, DEFAULT_REGRESSION_THRESHOLD_PERCENT
        )

        # Classify the delta the analytics path actually computed, not the
        # nominal one: `100.0 * (1 + 10.0/100)` is 110.00000000000001, and a
        # parity test must not turn that float artifact into a policy claim.
        actual_delta = percent_change(baseline, current)
        assert actual_delta is not None
        expected = classify_change(actual_delta)
        assert bool(regressions) is (expected == "regression")
        assert bool(improvements) is (expected == "improvement")
        assert bool(stable) is (expected == "stable")

    @pytest.mark.parametrize("delta", [d for d in SHARED_DELTAS if d > 0])
    def test_mcp_severity_matches_core(self, delta: float):
        from benchbox.mcp.tools.analytics import _classify_query_changes

        baseline = 100.0
        current = baseline * (1 + delta / 100)
        regressions, _, _ = _classify_query_changes(
            {"1": baseline}, {"1": current}, DEFAULT_REGRESSION_THRESHOLD_PERCENT
        )

        if regressions:
            actual_delta = percent_change(baseline, current)
            assert actual_delta is not None
            assert regressions[0]["severity"] == classify_severity(actual_delta)

    @pytest.mark.parametrize("delta", SHARED_DELTAS)
    def test_results_database_and_core_agree(self, delta: float):
        """The DB's PerformanceTrend flag is the same predicate."""
        from benchbox.core.results import database as database_module

        assert database_module.is_regression(delta) is is_regression(delta)

    def test_all_three_surfaces_agree_on_one_shared_delta(self):
        """A single explicit end-to-end check, not just parametrized pairs."""
        from benchbox.cli.commands.compare import _check_regression
        from benchbox.mcp.tools.analytics import _classify_query_changes

        delta = 12.0  # just over the default threshold
        cli = _check_regression({"query_comparisons": [{"change_percent": delta}]}, 0.10)
        regressions, _, _ = _classify_query_changes({"1": 100.0}, {"1": 112.0}, 10.0)

        assert cli is True
        assert len(regressions) == 1
        assert is_regression(delta) is True


class TestNoSurfaceKeepsALocalPolicy:
    def test_surface_modules_do_not_redefine_policy_helpers(self):
        import benchbox.cli.commands.compare as compare_module
        import benchbox.cli.commands.report as report_module
        import benchbox.mcp.tools.analytics as analytics_module

        for module in (compare_module, report_module, analytics_module):
            for banned in ("_classify_regression_severity", "_compute_trend_direction"):
                assert not hasattr(module, banned), f"{module.__name__}.{banned}"


class TestReportThresholdIsNoLongerInert:
    """Characterizes the one deliberate behavior change in this migration."""

    def test_a_sub_default_threshold_now_selects_regressions(self):
        """Previously `detect_regressions(5.0)` could not report a 7% slowdown.

        get_performance_trends set is_regression at the fixed 10% policy, and
        detect_regressions required BOTH that flag and change_pct > threshold,
        so any threshold below 10 was silently inert.
        """
        superseded = lambda change, threshold: (change > 10) and (change > threshold)  # noqa: E731

        assert superseded(7.0, 5.0) is False
        assert is_regression(7.0, 5.0) is True

    def test_thresholds_at_or_above_the_default_are_unchanged(self):
        superseded = lambda change, threshold: (change > 10) and (change > threshold)  # noqa: E731

        for change in (0.0, 5.0, 7.0, 11.0, 25.0, 120.0):
            for threshold in (10.0, 15.0, 20.0):
                assert superseded(change, threshold) is is_regression(change, threshold)
