"""Unit tests for generic power test handler in platform adapters.

Tests the _execute_generic_power_test method that provides warmup + iteration
support for non-TPC benchmarks (ClickBench, SSB, H2O-DB, etc.).
"""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestGenericPowerTest:
    """Test suite for _execute_generic_power_test method."""

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock platform adapter with required methods."""
        from benchbox.platforms.duckdb import DuckDBAdapter

        adapter = DuckDBAdapter()
        # Mock the _execute_all_queries method to avoid actual query execution
        adapter._execute_all_queries = MagicMock()
        return adapter

    @pytest.fixture
    def mock_benchmark(self):
        """Create a mock benchmark instance."""
        benchmark = MagicMock()
        benchmark.scale_factor = 1.0
        return benchmark

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        return MagicMock()

    def test_warmup_results_discarded(self, mock_adapter, mock_benchmark, mock_connection):
        """Test that warmup results are tagged with run_type='warmup' for filtering."""
        # Configure warmup + measurement runs
        run_config = {
            "benchmark_name": "clickbench",
            "iterations": 2,
            "warm_up_iterations": 1,
            "scale_factor": 1.0,
        }

        # Mock _execute_all_queries to return different results each call
        mock_adapter._execute_all_queries.side_effect = [
            # Warmup run (tagged as warmup)
            [{"query_id": "Q1", "status": "SUCCESS", "execution_time": 1.0}],
            # Measurement run 1
            [{"query_id": "Q1", "status": "SUCCESS", "execution_time": 2.0}],
            # Measurement run 2
            [{"query_id": "Q1", "status": "SUCCESS", "execution_time": 3.0}],
        ]

        results = mock_adapter._execute_generic_power_test(mock_benchmark, mock_connection, run_config)

        # Assert _execute_all_queries called 3 times (1 warmup + 2 measurement)
        assert mock_adapter._execute_all_queries.call_count == 3

        # All results are now returned (warmup + measurement) for traceability
        assert len(results) == 3

        # Warmup results are tagged with run_type='warmup'
        warmup_results = [r for r in results if r.get("run_type") == "warmup"]
        measurement_results = [r for r in results if r.get("run_type") == "measurement"]

        assert len(warmup_results) == 1
        assert len(measurement_results) == 2
        assert warmup_results[0]["execution_time"] == 1.0
        assert measurement_results[0]["execution_time"] == 2.0
        assert measurement_results[1]["execution_time"] == 3.0

    def test_iteration_tagging(self, mock_adapter, mock_benchmark, mock_connection):
        """Test that measurement results are tagged with iteration number."""
        run_config = {
            "benchmark_name": "clickbench",
            "iterations": 3,
            "warm_up_iterations": 0,
            "scale_factor": 1.0,
        }

        # Mock _execute_all_queries to return NEW dict each time (avoid reference reuse)
        def return_new_result():
            return [{"query_id": "Q1", "status": "SUCCESS", "execution_time": 1.0}]

        mock_adapter._execute_all_queries.side_effect = [
            return_new_result(),
            return_new_result(),
            return_new_result(),
        ]

        results = mock_adapter._execute_generic_power_test(mock_benchmark, mock_connection, run_config)

        # Assert 3 results (one per iteration)
        assert len(results) == 3

        # Assert each result tagged with iteration number
        assert results[0]["iteration"] == 1
        assert results[0]["run_type"] == "measurement"

        assert results[1]["iteration"] == 2
        assert results[1]["run_type"] == "measurement"

        assert results[2]["iteration"] == 3
        assert results[2]["run_type"] == "measurement"

    def test_no_warmup_runs(self, mock_adapter, mock_benchmark, mock_connection):
        """Test behavior when warm_up_iterations is 0."""
        run_config = {
            "benchmark_name": "clickbench",
            "iterations": 2,
            "warm_up_iterations": 0,
            "scale_factor": 1.0,
        }

        mock_adapter._execute_all_queries.return_value = [
            {"query_id": "Q1", "status": "SUCCESS", "execution_time": 1.0}
        ]

        results = mock_adapter._execute_generic_power_test(mock_benchmark, mock_connection, run_config)

        # Assert _execute_all_queries called exactly 2 times (no warmup)
        assert mock_adapter._execute_all_queries.call_count == 2

        # Assert 2 results
        assert len(results) == 2

    def test_default_iterations_value(self, mock_adapter, mock_benchmark, mock_connection):
        """Test that iterations defaults to 3 when not specified."""
        run_config = {
            "benchmark_name": "clickbench",
            "warm_up_iterations": 0,
            "scale_factor": 1.0,
        }

        mock_adapter._execute_all_queries.return_value = [
            {"query_id": "Q1", "status": "SUCCESS", "execution_time": 1.0}
        ]

        results = mock_adapter._execute_generic_power_test(mock_benchmark, mock_connection, run_config)

        # Assert _execute_all_queries called 3 times (default iterations=3)
        assert mock_adapter._execute_all_queries.call_count == 3

        # Assert 3 results
        assert len(results) == 3

    def test_multiple_queries_per_iteration(self, mock_adapter, mock_benchmark, mock_connection):
        """Test behavior with multiple queries per iteration."""
        run_config = {
            "benchmark_name": "clickbench",
            "iterations": 2,
            "warm_up_iterations": 1,
            "scale_factor": 1.0,
        }

        # Mock _execute_all_queries to return NEW dicts each time
        def return_new_queries():
            return [
                {"query_id": "Q1", "status": "SUCCESS", "execution_time": 1.0},
                {"query_id": "Q2", "status": "SUCCESS", "execution_time": 2.0},
                {"query_id": "Q3", "status": "SUCCESS", "execution_time": 3.0},
            ]

        mock_adapter._execute_all_queries.side_effect = [
            return_new_queries(),  # Warmup
            return_new_queries(),  # Iteration 1
            return_new_queries(),  # Iteration 2
        ]

        results = mock_adapter._execute_generic_power_test(mock_benchmark, mock_connection, run_config)

        # All results returned: 9 total (3 queries × 3 runs including warmup)
        assert len(results) == 9

        # Filter to measurement results only
        measurement_results = [r for r in results if r.get("run_type") == "measurement"]
        assert len(measurement_results) == 6  # 3 queries × 2 measurement iterations

        # Assert each query appears in each measurement iteration
        q1_results = [r for r in measurement_results if r["query_id"] == "Q1"]
        assert len(q1_results) == 2
        assert q1_results[0]["iteration"] == 1
        assert q1_results[1]["iteration"] == 2

    @patch("benchbox.platforms.base.execution.quiet_console")
    def test_console_output_displays_warmup_and_measurement(
        self, mock_console, mock_adapter, mock_benchmark, mock_connection
    ):
        """Test that console prints warmup and measurement run labels."""
        run_config = {
            "benchmark_name": "clickbench",
            "iterations": 2,
            "warm_up_iterations": 1,
            "scale_factor": 1.0,
        }

        # Return new dicts each time
        def return_new_result():
            return [{"query_id": "Q1", "status": "SUCCESS", "execution_time": 1.0}]

        mock_adapter._execute_all_queries.side_effect = [
            return_new_result(),  # Warmup
            return_new_result(),  # Iteration 1
            return_new_result(),  # Iteration 2
        ]

        mock_adapter._execute_generic_power_test(mock_benchmark, mock_connection, run_config)

        # Check console.print was called with warmup/measurement labels
        console_calls = [str(call) for call in mock_console.print.call_args_list]

        # Should contain warmup label
        assert any("Warm-up Run" in str(c) for c in console_calls)

        # Should contain measurement label
        assert any("Measurement Run" in str(c) for c in console_calls)

        # Should display warmup + measurement counts
        assert any("Warm-up runs: 1" in str(c) for c in console_calls)
        assert any("Measurement runs: 2" in str(c) for c in console_calls)

    def test_failed_queries_included_in_results(self, mock_adapter, mock_benchmark, mock_connection):
        """Test that failed queries are still included with iteration tags."""
        run_config = {
            "benchmark_name": "clickbench",
            "iterations": 2,
            "warm_up_iterations": 0,
            "scale_factor": 1.0,
        }

        # Mock _execute_all_queries to return NEW dicts each time (mix of success/failure)
        def return_new_mixed_results():
            return [
                {"query_id": "Q1", "status": "SUCCESS", "execution_time": 1.0},
                {"query_id": "Q2", "status": "FAILED", "execution_time": 0.0, "error": "timeout"},
            ]

        mock_adapter._execute_all_queries.side_effect = [
            return_new_mixed_results(),  # Iteration 1
            return_new_mixed_results(),  # Iteration 2
        ]

        results = mock_adapter._execute_generic_power_test(mock_benchmark, mock_connection, run_config)

        # Assert 4 total results (2 queries × 2 iterations)
        assert len(results) == 4

        # Assert failed queries have iteration tags
        failed_results = [r for r in results if r["status"] == "FAILED"]
        assert len(failed_results) == 2
        assert all("iteration" in r for r in failed_results)
        assert all(r["run_type"] == "measurement" for r in failed_results)

    def test_plan_capture_deferred_to_single_pass_after_iterations(self, mock_adapter, mock_benchmark, mock_connection):
        """Phase-eligible capture runs once after all iterations, not once per iteration."""
        run_config = {
            "benchmark_name": "clickbench",
            "iterations": 3,
            "warm_up_iterations": 1,
            "scale_factor": 1.0,
        }

        # Make the adapter phase-eligible for isolated post-measurement plan capture.
        mock_adapter.capture_plans = True
        mock_adapter.plan_capture_phase_eligible = True
        mock_adapter.dry_run_mode = False

        mock_adapter._execute_all_queries.side_effect = [
            [{"query_id": "Q1", "status": "SUCCESS"}],  # warmup
            [{"query_id": "Q1", "status": "SUCCESS"}],  # measurement 1
            [{"query_id": "Q1", "status": "SUCCESS"}],  # measurement 2
            [{"query_id": "Q1", "status": "SUCCESS"}],  # measurement 3
        ]
        mock_adapter._get_dialect_queries = MagicMock(return_value={"Q1": "SELECT 1"})
        mock_adapter._filter_queries = MagicMock(side_effect=lambda q, *a, **k: q)
        mock_adapter._capture_plans_post_measurement = MagicMock()

        mock_adapter._execute_generic_power_test(mock_benchmark, mock_connection, run_config)

        # Every per-iteration query pass deferred its own capture.
        assert mock_adapter._execute_all_queries.call_count == 4
        for call in mock_adapter._execute_all_queries.call_args_list:
            assert call.kwargs.get("defer_post_capture") is True

        # Capture ran exactly once, after the loop, over the final measurement run.
        mock_adapter._capture_plans_post_measurement.assert_called_once()
        captured_results = mock_adapter._capture_plans_post_measurement.call_args.args[2]
        assert [r["query_id"] for r in captured_results] == ["Q1"]
        assert captured_results[0]["run_type"] == "measurement"
        assert captured_results[0]["iteration"] == 3
