from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import pytest

from benchbox.core.throughput.containment import await_quiescence
from benchbox.core.tpcds.streams import StreamQuery
from benchbox.core.tpcds.throughput_test import _apply_query_subset
from benchbox.platforms.base.connection_wrappers import StreamConnectionCapability
from benchbox.platforms.base.execution import (
    TestDriversMixin,
    _resolve_requested_stream_count,
    _throughput_config_options,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _Driver(TestDriversMixin):
    stream_connection_capability = StreamConnectionCapability.SHARED_CURSOR
    platform_name = "stub"
    very_verbose = False

    def __init__(self, gate: threading.Event | None = None) -> None:
        self.calls: list[tuple[Any, bool]] = []
        self.gate = gate
        self._lock = threading.Lock()
        self._last_throughput_test_result = None

    def get_target_dialect(self) -> str | None:
        return None

    def new_stream_connection(self, connection: Any, *, benchmark_type: str | None = None) -> Any:
        return connection

    def execute_query(
        self,
        connection: Any,
        query: str,
        query_id: Any,
        benchmark_type: str | None = None,
        scale_factor: float | None = None,
        validate_row_count: bool = True,
        stream_id: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self.calls.append((query_id, validate_row_count))
        if self.gate is not None:
            self.gate.wait(timeout=30)
        return {"query_id": query_id, "status": "SUCCESS", "rows_returned": 1, "execution_time_seconds": 0.0}


def _tpch_benchmark() -> Mock:
    benchmark = Mock()
    benchmark.get_query.return_value = "SELECT 1"
    return benchmark


def _run_tpch(driver: _Driver, **run_config: Any):
    config = {"scale_factor": 1.0, "num_streams": 2, **run_config}
    results = driver._execute_tpch_throughput_test(_tpch_benchmark(), Mock(), config)
    return driver._last_throughput_test_result, results


class TestStreamCountResolution:
    @pytest.mark.parametrize("key", ["num_streams", "streams"])
    @pytest.mark.parametrize("value", [0, 1, -1])
    def test_explicit_count_below_two_is_rejected(self, key, value):
        with pytest.raises(ValueError, match="at least 2"):
            _resolve_requested_stream_count({key: value})

    def test_non_positive_schema_count_is_rejected(self):
        with pytest.raises(ValueError, match="at least 2"):
            _resolve_requested_stream_count({"concurrent_streams": 0})

    @pytest.mark.parametrize("run_config", [{}, {"concurrent_streams": None}, {"concurrent_streams": 1}])
    def test_unset_count_uses_the_default(self, run_config):
        assert _resolve_requested_stream_count(run_config) == 2

    def test_requested_count_passes_through(self):
        assert _resolve_requested_stream_count({"concurrent_streams": 5}) == 5
        assert _resolve_requested_stream_count({"num_streams": 3, "concurrent_streams": 8}) == 3

    def test_driver_reports_the_rejection_without_running_streams(self):
        driver = _Driver()

        result, rows = _run_tpch(driver, num_streams=1)

        assert result is None
        assert driver.calls == []
        assert rows[0]["query_id"] == "throughput_test_error"
        assert "at least 2" in rows[0]["error"]


class TestValidationMode:
    def test_disabled_turns_row_count_validation_off_for_every_stream(self):
        driver = _Driver()

        result, _rows = _run_tpch(driver, validation_mode="disabled")

        assert result.streams_executed == 2
        assert driver.calls
        assert {validate for _query_id, validate in driver.calls} == {False}

    @pytest.mark.parametrize("mode", [None, "exact", "loose"])
    def test_other_modes_keep_validation_on(self, mode):
        driver = _Driver()

        _run_tpch(driver, validation_mode=mode)

        assert {validate for _query_id, validate in driver.calls} == {True}


class TestQuerySubset:
    def test_tpch_streams_run_only_the_requested_queries(self):
        driver = _Driver()

        result, _rows = _run_tpch(driver, query_subset=["1", "Q6"])

        assert result.streams_executed == 2
        assert {query_id for query_id, _validate in driver.calls} == {1, 6}
        assert len(driver.calls) == 4
        assert all(len(stream.query_results) == 2 for stream in result.stream_results)

    def test_tpch_unknown_query_ids_fail_the_run_clearly(self):
        driver = _Driver()

        result, _rows = _run_tpch(driver, query_subset=["99"])

        assert result.success is False
        assert any("Invalid TPC-H query ids" in error for error in result.errors)
        assert driver.calls == []

    def test_tpch_without_a_subset_runs_all_queries(self):
        driver = _Driver()

        _run_tpch(driver)

        assert len(driver.calls) == 44

    def test_tpcds_subset_selects_by_id_and_variant(self):
        queries = [
            StreamQuery(stream_id=0, position=0, query_id=1),
            StreamQuery(stream_id=0, position=1, query_id=14, variant="a"),
            StreamQuery(stream_id=0, position=2, query_id=14, variant="b"),
            StreamQuery(stream_id=0, position=3, query_id=7),
        ]

        assert [q.position for q in _apply_query_subset(queries, ["Q14a", "7"])] == [1, 3]
        assert [q.position for q in _apply_query_subset(queries, ["14"])] == [1, 2]
        assert _apply_query_subset(queries, None) is queries

    def test_tpcds_unknown_query_ids_are_rejected(self):
        queries = [StreamQuery(stream_id=0, position=0, query_id=1)]

        with pytest.raises(ValueError, match="Invalid TPC-DS query ids"):
            _apply_query_subset(queries, ["5"])

    def test_tpcds_driver_hands_the_subset_to_the_throughput_config(self):
        driver = _Driver()
        captured: dict[str, Any] = {}

        def fake_run(self_, config=None):
            captured["config"] = config
            return SimpleNamespace(
                success=False,
                throughput_at_size=None,
                query_throughput=0.0,
                stream_results=[],
                errors=[],
                streams_executed=0,
                streams_successful=0,
                total_time=0.0,
            )

        with patch("benchbox.core.tpcds.throughput_test.TPCDSThroughputTest.run", fake_run):
            driver._execute_tpcds_throughput_test(
                Mock(),
                Mock(),
                {
                    "scale_factor": 1.0,
                    "num_streams": 2,
                    "query_subset": ["1", "14a"],
                    "stream_timeout_seconds": 90,
                    "cancel_on_timeout": True,
                },
            )

        config = captured["config"]
        assert config.query_subset == ["1", "14a"]
        assert config.stream_timeout == 90
        assert config.cancel_on_timeout is True


class TestStreamTimeoutOptions:
    def test_defaults_leave_the_driver_timeouts_in_place(self):
        options = _throughput_config_options({})

        assert "stream_timeout" not in options
        assert options["cancel_on_timeout"] is False

    def test_negative_timeout_is_rejected(self):
        with pytest.raises(ValueError, match="stream_timeout_seconds"):
            _throughput_config_options({"stream_timeout_seconds": -1})

    def test_zero_timeout_disables_the_deadline(self):
        assert _throughput_config_options({"stream_timeout_seconds": 0})["stream_timeout"] == 0

    @pytest.mark.parametrize(("cancel", "max_calls_per_stream"), [(True, 2), (False, 22)])
    def test_run_config_timeout_and_cancellation_reach_the_streams(self, cancel, max_calls_per_stream):
        gate = threading.Event()
        driver = _Driver(gate)

        try:
            result, _rows = _run_tpch(driver, stream_timeout_seconds=1, cancel_on_timeout=cancel)

            assert sorted(result.outstanding_stream_ids) == [0, 1]
            gate.set()
            assert await_quiescence(result, timeout=30.0) is True
            if cancel:
                assert len(driver.calls) <= 2 * max_calls_per_stream
            else:
                assert len(driver.calls) == 2 * max_calls_per_stream
        finally:
            gate.set()


class TestRunConfigPlumbing:
    def test_run_service_carries_stream_timeout_options_into_the_run_config(self, tmp_path):
        from benchbox.core.config import BenchmarkConfig
        from benchbox.core.run_service import resolve_run_config
        from benchbox.utils.verbosity import VerbositySettings

        config = BenchmarkConfig(
            name="tpch",
            display_name="TPC-H",
            scale_factor=1.0,
            options={"stream_timeout_seconds": 120, "cancel_on_timeout": True},
        )

        run_config = resolve_run_config(config, database_path=tmp_path / "db", verbosity=VerbositySettings())

        assert run_config.stream_timeout_seconds == 120
        assert run_config.cancel_on_timeout is True

    def test_run_service_defaults_leave_timeouts_unset(self, tmp_path):
        from benchbox.core.config import BenchmarkConfig
        from benchbox.core.run_service import resolve_run_config
        from benchbox.utils.verbosity import VerbositySettings

        config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=1.0)

        run_config = resolve_run_config(config, database_path=tmp_path / "db", verbosity=VerbositySettings())

        assert run_config.stream_timeout_seconds is None
        assert run_config.cancel_on_timeout is False


class TestStreamCountEntryPoints:
    @pytest.mark.parametrize("streams", [0, 1, -3])
    def test_official_run_validation_rejects_counts_below_two(self, streams):
        from benchbox.core.run_service import validate_stream_count

        with pytest.raises(ValueError, match="must be >= 2"):
            validate_stream_count(streams, "throughput")

    def test_official_run_validation_accepts_two_and_unset(self):
        from benchbox.core.run_service import validate_stream_count

        validate_stream_count(2, "throughput")
        validate_stream_count(None, "power")

    @pytest.mark.parametrize("streams", ["0", "1"])
    def test_run_command_rejects_counts_below_two(self, streams):
        import click

        from benchbox.cli.commands.run import run

        with pytest.raises(click.BadParameter, match="x>=2"):
            run.make_context("run", ["--streams", streams])


class TestMaintenanceSessions:
    @pytest.mark.parametrize(
        ("family", "patch_target"),
        [
            ("tpch", "benchbox.core.tpch.maintenance_test.TPCHMaintenanceTest"),
            ("tpcds", "benchbox.core.tpcds.maintenance_test.TPCDSMaintenanceTest"),
        ],
    )
    @pytest.mark.parametrize(("run_config", "expected"), [({}, "olap"), ({"benchmark_type": "htap"}, "htap")])
    def test_maintenance_sessions_open_through_the_stream_hook_with_benchmark_type(
        self, family, patch_target, run_config, expected
    ):
        driver = _Driver()
        seen: list[str | None] = []

        def new_stream_connection(connection, *, benchmark_type=None):
            seen.append(benchmark_type)
            return connection

        driver.new_stream_connection = new_stream_connection
        driver._plan_capture_checkpoint = lambda connection: None
        method = getattr(driver, f"_execute_{family}_maintenance_test")

        with patch(patch_target) as maintenance:
            maintenance.return_value.run.side_effect = RuntimeError("stop after capturing the factory")
            maintenance.return_value.run_maintenance_test.side_effect = RuntimeError("stop")
            method(Mock(), Mock(), {"scale_factor": 1.0, **run_config})
            factory = maintenance.call_args.kwargs["connection_factory"]
            factory()

        assert seen == [expected]
