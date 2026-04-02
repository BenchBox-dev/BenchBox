"""Tests for power test fail-fast / abort-on-total-failure logic.

Verifies that measurement run loops abort early when:
1. All queries in a run fail (infrastructure issue) — always
2. Any query fails and power_fail_fast is enabled
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ---------------------------------------------------------------------------
# Generic power test
# ---------------------------------------------------------------------------


class TestGenericPowerTestFailFast:
    """Tests for _execute_generic_power_test abort logic."""

    @pytest.fixture
    def adapter(self):
        from benchbox.platforms.duckdb import DuckDBAdapter

        a = DuckDBAdapter()
        a._execute_all_queries = MagicMock()
        return a

    @pytest.fixture
    def bench_instance(self):
        b = MagicMock()
        b._name = "TestBench"
        b.scale_factor = 1.0
        return b

    @pytest.fixture
    def connection(self):
        return MagicMock()

    def test_all_queries_failed_aborts_remaining_iterations(self, adapter, bench_instance, connection):
        """When all queries fail, remaining measurement runs are skipped."""
        run_config = {
            "iterations": 3,
            "warm_up_iterations": 0,
            "scale_factor": 1.0,
        }

        adapter._execute_all_queries.return_value = [
            {"query_id": "Q1", "status": "FAILED", "execution_time": 0.0},
            {"query_id": "Q2", "status": "FAILED", "execution_time": 0.0},
        ]

        results = adapter._execute_generic_power_test(bench_instance, connection, run_config)

        # Should only execute 1 iteration then abort
        assert adapter._execute_all_queries.call_count == 1
        assert len(results) == 2

    def test_partial_failure_continues_without_fail_fast(self, adapter, bench_instance, connection):
        """When some queries succeed and fail_fast is off, all iterations run."""
        run_config = {
            "iterations": 3,
            "warm_up_iterations": 0,
            "scale_factor": 1.0,
            "power_fail_fast": False,
        }

        def mixed_results():
            return [
                {"query_id": "Q1", "status": "SUCCESS", "execution_time": 1.0},
                {"query_id": "Q2", "status": "FAILED", "execution_time": 0.0},
            ]

        adapter._execute_all_queries.side_effect = [
            mixed_results(),
            mixed_results(),
            mixed_results(),
        ]

        results = adapter._execute_generic_power_test(bench_instance, connection, run_config)

        # All 3 iterations should run
        assert adapter._execute_all_queries.call_count == 3
        assert len(results) == 6

    def test_partial_failure_aborts_with_fail_fast(self, adapter, bench_instance, connection):
        """When any query fails and fail_fast is enabled, remaining runs abort."""
        run_config = {
            "iterations": 3,
            "warm_up_iterations": 0,
            "scale_factor": 1.0,
            "power_fail_fast": True,
        }

        adapter._execute_all_queries.return_value = [
            {"query_id": "Q1", "status": "SUCCESS", "execution_time": 1.0},
            {"query_id": "Q2", "status": "FAILED", "execution_time": 0.0},
        ]

        results = adapter._execute_generic_power_test(bench_instance, connection, run_config)

        # Should abort after first iteration
        assert adapter._execute_all_queries.call_count == 1
        assert len(results) == 2

    def test_all_success_completes_all_iterations(self, adapter, bench_instance, connection):
        """When all queries succeed, all iterations complete normally."""
        run_config = {
            "iterations": 3,
            "warm_up_iterations": 0,
            "scale_factor": 1.0,
        }

        def success_results():
            return [
                {"query_id": "Q1", "status": "SUCCESS", "execution_time": 1.0},
            ]

        adapter._execute_all_queries.side_effect = [
            success_results(),
            success_results(),
            success_results(),
        ]

        results = adapter._execute_generic_power_test(bench_instance, connection, run_config)

        assert adapter._execute_all_queries.call_count == 3
        assert len(results) == 3


# ---------------------------------------------------------------------------
# TPC-H power test
# ---------------------------------------------------------------------------


def _make_power_test_result(*, success: bool, queries_successful: int, queries_executed: int):
    """Create a mock TPCHPowerTestResult."""
    return SimpleNamespace(
        success=success,
        queries_successful=queries_successful,
        queries_executed=queries_executed,
        power_at_size=0.0,
        total_time=1.0,
        errors=["Query X failed: timeout"] if not success else [],
        query_results=[
            {
                "query_id": str(i + 1),
                "execution_time_seconds": 1.0 if i < queries_successful else 0.0,
                "success": i < queries_successful,
                "result_count": 10 if i < queries_successful else 0,
                "error": None if i < queries_successful else "timeout",
                "stream_id": 0,
                "position": i,
            }
            for i in range(queries_executed)
        ],
    )


class TestTPCHPowerTestFailFast:
    """Tests for _execute_tpch_power_test abort logic."""

    @pytest.fixture
    def adapter(self):
        from benchbox.platforms.duckdb import DuckDBAdapter

        a = DuckDBAdapter()
        a.get_target_dialect = MagicMock(return_value="duckdb")
        return a

    @pytest.fixture
    def bench_instance(self):
        b = MagicMock()
        b._name = "tpch"
        return b

    @pytest.fixture
    def connection(self):
        return MagicMock()

    @patch("benchbox.core.tpch.power_test.TPCHPowerTest")
    @patch("benchbox.platforms.base.adapter.PlatformAdapterConnection")
    def test_all_queries_failed_aborts(self, mock_conn_cls, mock_pt_cls, adapter, bench_instance, connection):
        """When all queries fail (0% success), remaining measurement runs abort."""
        run_config = {
            "iterations": 3,
            "warm_up_iterations": 0,
            "scale_factor": 0.01,
            "stream_id": 0,
        }

        all_failed = _make_power_test_result(success=False, queries_successful=0, queries_executed=22)
        mock_pt_cls.return_value.run.return_value = all_failed

        results = adapter._execute_tpch_power_test(bench_instance, connection, run_config)

        # Should only create 1 TPCHPowerTest (aborted after first run)
        assert mock_pt_cls.call_count == 1
        assert len(results) == 22

    @patch("benchbox.core.tpch.power_test.TPCHPowerTest")
    @patch("benchbox.platforms.base.adapter.PlatformAdapterConnection")
    def test_partial_failure_continues_without_fail_fast(
        self, mock_conn_cls, mock_pt_cls, adapter, bench_instance, connection
    ):
        """Partial failures continue when fail_fast is off."""
        run_config = {
            "iterations": 3,
            "warm_up_iterations": 0,
            "scale_factor": 0.01,
            "stream_id": 0,
            "power_fail_fast": False,
        }

        partial_fail = _make_power_test_result(success=False, queries_successful=20, queries_executed=22)
        mock_pt_cls.return_value.run.return_value = partial_fail

        results = adapter._execute_tpch_power_test(bench_instance, connection, run_config)

        # All 3 iterations should run (20/22 succeeded, fail_fast is off)
        assert mock_pt_cls.call_count == 3
        assert len(results) == 66  # 22 * 3

    @patch("benchbox.core.tpch.power_test.TPCHPowerTest")
    @patch("benchbox.platforms.base.adapter.PlatformAdapterConnection")
    def test_partial_failure_aborts_with_fail_fast(
        self, mock_conn_cls, mock_pt_cls, adapter, bench_instance, connection
    ):
        """Partial failures abort when fail_fast is enabled."""
        run_config = {
            "iterations": 3,
            "warm_up_iterations": 0,
            "scale_factor": 0.01,
            "stream_id": 0,
            "power_fail_fast": True,
        }

        partial_fail = _make_power_test_result(success=False, queries_successful=20, queries_executed=22)
        mock_pt_cls.return_value.run.return_value = partial_fail

        results = adapter._execute_tpch_power_test(bench_instance, connection, run_config)

        # Should abort after first iteration
        assert mock_pt_cls.call_count == 1
        assert len(results) == 22

    @patch("benchbox.core.tpch.power_test.TPCHPowerTest")
    @patch("benchbox.platforms.base.adapter.PlatformAdapterConnection")
    def test_all_success_completes_all_iterations(
        self, mock_conn_cls, mock_pt_cls, adapter, bench_instance, connection
    ):
        """Full success runs all iterations."""
        run_config = {
            "iterations": 3,
            "warm_up_iterations": 0,
            "scale_factor": 0.01,
            "stream_id": 0,
        }

        all_ok = _make_power_test_result(success=True, queries_successful=22, queries_executed=22)
        mock_pt_cls.return_value.run.return_value = all_ok

        results = adapter._execute_tpch_power_test(bench_instance, connection, run_config)

        assert mock_pt_cls.call_count == 3
        assert len(results) == 66
