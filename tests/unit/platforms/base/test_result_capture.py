"""Tests for ResultCaptureMixin._merge_plan_capture_into_result.

The helper centralizes the plan-capture block that was previously copy-pasted
into all six adapters, and bakes in the capture_plans + status=="SUCCESS" guard
universally.
"""

from unittest.mock import MagicMock

import pytest

from benchbox.platforms.base.result_capture import ResultCaptureMixin

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _Host(ResultCaptureMixin):
    """Minimal ResultCaptureMixin host that records capture_query_plan calls."""

    def __init__(self, capture_plans=True, plan=None, capture_time_ms=1.5):
        self.capture_plans = capture_plans
        self._plan = plan
        self._capture_time_ms = capture_time_ms
        self.capture_calls = []

    def capture_query_plan(self, connection, query, query_id):
        self.capture_calls.append((connection, query, query_id))
        return self._plan, self._capture_time_ms


def _make_plan(fingerprint="fp123"):
    plan = MagicMock()
    plan.plan_fingerprint = fingerprint
    return plan


class TestMergePlanCaptureIntoResult:
    def test_noop_when_capture_disabled(self):
        host = _Host(capture_plans=False, plan=_make_plan())
        result = {"status": "SUCCESS"}
        host._merge_plan_capture_into_result(result, "conn", "SELECT 1", "q1")
        assert result == {"status": "SUCCESS"}
        assert host.capture_calls == [], "capture_plans=False must not issue EXPLAIN"

    def test_noop_when_status_failed(self):
        host = _Host(capture_plans=True, plan=_make_plan())
        result = {"status": "FAILED"}
        host._merge_plan_capture_into_result(result, "conn", "SELECT 1", "q1")
        assert result == {"status": "FAILED"}
        assert host.capture_calls == [], "FAILED status must not trigger capture"

    def test_noop_when_status_missing(self):
        host = _Host(capture_plans=True, plan=_make_plan())
        result = {}
        host._merge_plan_capture_into_result(result, "conn", "SELECT 1", "q1")
        assert result == {}
        assert host.capture_calls == []

    def test_merges_plan_fields_on_success(self):
        plan = _make_plan("fpX")
        host = _Host(capture_plans=True, plan=plan, capture_time_ms=2.0)
        result = {"status": "SUCCESS"}
        host._merge_plan_capture_into_result(result, "conn", "SELECT 1", "q1")
        assert result["query_plan"] is plan
        assert result["plan_fingerprint"] == "fpX"
        assert result["plan_capture_time_ms"] == 2.0
        assert host.capture_calls == [("conn", "SELECT 1", "q1")]

    def test_records_capture_time_even_when_no_plan(self):
        host = _Host(capture_plans=True, plan=None, capture_time_ms=0.0)
        result = {"status": "SUCCESS"}
        host._merge_plan_capture_into_result(result, "conn", "SELECT 1", "q1")
        assert "query_plan" not in result
        assert "plan_fingerprint" not in result
        # 0.0 is not None, so the timing is still recorded for observability.
        assert result["plan_capture_time_ms"] == 0.0

    def test_no_plan_and_none_capture_time_leaves_result_unchanged(self):
        host = _Host(capture_plans=True, plan=None, capture_time_ms=None)
        result = {"status": "SUCCESS"}
        host._merge_plan_capture_into_result(result, "conn", "SELECT 1", "q1")
        assert result == {"status": "SUCCESS"}

    def test_mutates_in_place_and_returns_none(self):
        host = _Host(capture_plans=True, plan=_make_plan())
        result = {"status": "SUCCESS"}
        ret = host._merge_plan_capture_into_result(result, "conn", "SELECT 1", "q1")
        assert ret is None, "helper mutates in place and must not return the dict"
