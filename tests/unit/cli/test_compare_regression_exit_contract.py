"""`benchbox compare --fail-on-regression` exit-code contract.

Scripts and CI jobs branch on this exit status, so it is a public contract even
though it is only two integers. `one-engine-unify-regression-policy` moved the
predicate behind it into benchbox.core.results.regression_policy; these tests
pin the observable behavior across that move.
"""

from __future__ import annotations

from typing import Any

import pytest

from benchbox.cli.commands.compare import (
    _check_regression,
    _check_regression_threshold,
    _parse_threshold,
    _validate_regression_threshold,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _comparison(query_change: float | None = None, metric_change: float | None = None) -> dict[str, Any]:
    comparison: dict[str, Any] = {"query_comparisons": [], "performance_changes": {}}
    if query_change is not None:
        comparison["query_comparisons"].append({"query_id": "1", "change_percent": query_change})
    if metric_change is not None:
        comparison["performance_changes"]["geometric_mean"] = {"change_percent": metric_change}
    return comparison


class TestRegressionExitCode:
    def test_regression_exits_nonzero(self):
        with pytest.raises(SystemExit) as exit_info:
            _check_regression_threshold(_comparison(query_change=25.0), 0.10)

        assert exit_info.value.code == 1

    def test_no_regression_does_not_exit(self):
        assert _check_regression_threshold(_comparison(query_change=2.0), 0.10) is None

    def test_improvement_does_not_exit(self):
        assert _check_regression_threshold(_comparison(query_change=-40.0), 0.10) is None

    def test_omitted_threshold_never_exits(self):
        """Without --fail-on-regression the command must stay exit 0."""
        assert _check_regression_threshold(_comparison(query_change=500.0), None) is None

    def test_metric_level_regression_also_exits(self):
        with pytest.raises(SystemExit) as exit_info:
            _check_regression_threshold(_comparison(metric_change=25.0), 0.10)

        assert exit_info.value.code == 1

    def test_exactly_at_the_threshold_does_not_exit(self):
        assert _check_regression_threshold(_comparison(query_change=10.0), 0.10) is None

    def test_just_over_the_threshold_exits(self):
        with pytest.raises(SystemExit) as exit_info:
            _check_regression_threshold(_comparison(query_change=10.5), 0.10)

        assert exit_info.value.code == 1


class TestThresholdParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("10%", 0.10), ("5.5%", 0.055), ("0.1", 0.1), ("0.05", 0.05), (" 10% ", 0.10)],
    )
    def test_accepted_threshold_spellings(self, raw: str, expected: float):
        assert _parse_threshold(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", ["abc", "%", "10%%", ""])
    def test_rejected_threshold_spellings(self, raw: str):
        assert _parse_threshold(raw) is None

    def test_invalid_threshold_exits_one(self):
        with pytest.raises(SystemExit) as exit_info:
            _validate_regression_threshold("not-a-threshold")

        assert exit_info.value.code == 1

    def test_absent_flag_yields_no_threshold(self):
        assert _validate_regression_threshold(None) is None
        assert _validate_regression_threshold("") is None


class TestFailOnRegressionUsesTheSharedPolicy:
    @pytest.mark.parametrize("change", [-50.0, -10.0, 0.0, 9.9, 10.0, 10.1, 50.0, 150.0])
    def test_predicate_matches_core(self, change: float):
        from benchbox.core.results.regression_policy import is_regression

        assert _check_regression(_comparison(query_change=change), 0.10) is is_regression(change, 10.0)

    def test_caller_threshold_overrides_the_default(self):
        """A 7% slowdown is a regression at --fail-on-regression 5%, not at 10%."""
        assert _check_regression(_comparison(query_change=7.0), 0.05) is True
        assert _check_regression(_comparison(query_change=7.0), 0.10) is False

    def test_non_dict_metric_entries_are_skipped(self):
        comparison = {"query_comparisons": [], "performance_changes": {"geometric_mean": "not-a-dict"}}

        assert _check_regression(comparison, 0.10) is False
