from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from benchbox.core.throughput.entrypoints import (
    finalize_throughput_metrics,
    require_stream_minimum,
    run_factory_throughput,
    warn_legacy_throughput_api,
)
from benchbox.core.throughput.result import ThroughputResult, ThroughputStreamResult

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _stream(stream_id: int, failed: int = 0) -> ThroughputStreamResult:
    return ThroughputStreamResult(
        stream_id=stream_id,
        start_time=0.0,
        end_time=1.0,
        duration=1.0,
        queries_executed=22,
        queries_successful=22 - failed,
        queries_failed=failed,
        success=failed == 0,
    )


def _result(streams: list[ThroughputStreamResult], metric: float | None = 10.0) -> ThroughputResult:
    return ThroughputResult(
        start_time="s",
        end_time="e",
        total_time=1.0,
        throughput_at_size=metric,
        streams_executed=len(streams),
        streams_successful=sum(1 for stream in streams if stream.success),
        stream_results=streams,
        query_throughput=5.0,
    )


class TestStreamMinimum:
    @pytest.mark.parametrize("count", [-1, 0, 1])
    def test_counts_below_two_are_rejected_with_the_source(self, count):
        with pytest.raises(ValueError, match=r"at least 2.*'num_streams'"):
            require_stream_minimum(count, "num_streams")

    def test_two_or_more_pass_through(self):
        assert require_stream_minimum(2, "num_streams") == 2
        assert require_stream_minimum(7, "num_streams") == 7


class TestFinalizeMetrics:
    def test_all_streams_successful_keeps_the_metric(self):
        result = _result([_stream(0), _stream(1)])

        finalize_throughput_metrics(result, 2, None)

        assert result.success is True
        assert result.throughput_at_size == 10.0

    def test_any_failed_stream_withholds_the_metric(self):
        result = _result([_stream(0), _stream(1, failed=1)])

        finalize_throughput_metrics(result, 2, None)

        assert result.success is False
        assert result.throughput_at_size is None
        assert result.query_throughput == 0.0

    def test_missing_stream_withholds_the_metric(self):
        result = _result([_stream(0)])

        finalize_throughput_metrics(result, 2, None)

        assert result.success is False
        assert result.throughput_at_size is None

    def test_query_subset_runs_report_no_metric(self):
        result = _result([_stream(0), _stream(1)])

        finalize_throughput_metrics(result, 2, ["1", "6"])

        assert result.success is True
        assert result.throughput_at_size is None


class TestDeprecationNotice:
    def test_warning_names_the_api_and_the_supported_driver(self):
        with pytest.warns(DeprecationWarning, match=r"Some.api is deprecated.*TPCDSThroughputTest"):
            warn_legacy_throughput_api("Some.api", "tpcds")

    def test_warning_points_at_the_caller(self):
        with pytest.warns(DeprecationWarning) as caught:
            warn_legacy_throughput_api("Some.api", "tpch", stacklevel=2)

        assert caught[0].filename == __file__


class TestFactoryRoute:
    def test_tpcds_driver_receives_scale_factor_seed_timeout_and_dialect(self):
        healthy = _result([_stream(0), _stream(1)])
        with (
            patch("benchbox.core.tpcds.throughput_test.TPCDSThroughputTest") as driver_cls,
            patch("benchbox.core.tpcds.throughput_test.TPCDSThroughputTestConfig") as config_cls,
        ):
            driver_cls.return_value.run.return_value = healthy
            config_cls.return_value.query_subset = None
            factory = Mock()
            benchmark = Mock()

            result = run_factory_throughput(
                "tpcds",
                benchmark,
                factory,
                scale_factor=10.0,
                num_streams=3,
                base_seed=11,
                stream_timeout=90,
                dialect="duckdb",
            )

        driver_kwargs = driver_cls.call_args.kwargs
        assert driver_kwargs["benchmark"] is benchmark
        assert driver_kwargs["connection_factory"] is factory
        assert driver_kwargs["scale_factor"] == 10.0
        assert driver_kwargs["num_streams"] == 3
        assert driver_kwargs["dialect"] == "duckdb"
        config_kwargs = config_cls.call_args.kwargs
        assert config_kwargs["scale_factor"] == 10.0
        assert config_kwargs["num_streams"] == 3
        assert config_kwargs["base_seed"] == 11
        assert config_kwargs["stream_timeout"] == 90
        assert result is healthy

    def test_tpch_failed_stream_withholds_the_metric(self):
        failed = _result([_stream(0), _stream(1, failed=2)])
        with patch("benchbox.core.tpch.throughput_test.TPCHThroughputTest") as driver_cls:
            driver_cls.return_value.run.return_value = failed

            result = run_factory_throughput("tpch", Mock(), Mock(), scale_factor=0.01, num_streams=2)

        assert result.success is False
        assert result.throughput_at_size is None

    def test_one_stream_is_refused_before_any_driver_is_built(self):
        with patch("benchbox.core.tpch.throughput_test.TPCHThroughputTest") as driver_cls:
            with pytest.raises(ValueError, match="at least 2"):
                run_factory_throughput("tpch", Mock(), Mock(), scale_factor=1.0, num_streams=1)

        driver_cls.assert_not_called()

    def test_unknown_benchmark_type_is_rejected(self):
        with pytest.raises(ValueError, match="No supported throughput driver"):
            run_factory_throughput("ssb", Mock(), Mock(), scale_factor=1.0, num_streams=2)

    def test_query_subset_is_forwarded_and_suppresses_the_metric(self):
        healthy = _result([_stream(0), _stream(1)])
        seen = SimpleNamespace()
        with patch("benchbox.core.tpch.throughput_test.TPCHThroughputTest") as driver_cls:

            def run(config):
                seen.config = config
                return healthy

            driver_cls.return_value.run.side_effect = run

            result = run_factory_throughput(
                "tpch", Mock(), Mock(), scale_factor=1.0, num_streams=2, query_subset=["1", "6"]
            )

        assert seen.config.query_subset == ["1", "6"]
        assert result.throughput_at_size is None
