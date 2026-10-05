from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from benchbox.core.tpcds.official_benchmark import TPCDSOfficialBenchmark, TPCDSOfficialBenchmarkConfig

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _power(*, value=100.0, success=True, executed=99, successful=99):
    return SimpleNamespace(
        power_at_size=value,
        success=success,
        queries_executed=executed,
        queries_successful=successful,
        config=SimpleNamespace(scale_factor=0.01),
    )


def _throughput(value=64.0):
    return SimpleNamespace(throughput_at_size=value, success=True, outstanding_stream_ids=[])


@pytest.fixture
def phases():
    with (
        patch("benchbox.core.tpcds.power_test.TPCDSPowerTest") as power,
        patch("benchbox.core.tpcds.throughput_test.TPCDSThroughputTest") as throughput,
        patch("benchbox.core.tpcds.maintenance_test.TPCDSMaintenanceTest") as maintenance,
    ):
        power.return_value.run.return_value = _power()
        throughput.return_value.run.return_value = _throughput()
        maintenance.return_value.run.return_value = {"success": True}
        yield SimpleNamespace(power=power, throughput=throughput, maintenance=maintenance)


def _official(tmp_path, scale_factor=0.01):
    return TPCDSOfficialBenchmark(scale_factor=scale_factor, output_dir=tmp_path, verbose=False)


class TestScaleFactor:
    def test_power_and_throughput_receive_the_configured_scale_factor(self, tmp_path, phases):
        official = _official(tmp_path, scale_factor=0.01)

        result = official.run_official_benchmark(lambda: Mock())

        assert phases.power.call_args.kwargs["scale_factor"] == 0.01
        assert phases.throughput.call_args.kwargs["scale_factor"] == 0.01
        assert result.success is True

    def test_explicit_config_scale_factor_wins(self, tmp_path, phases):
        official = _official(tmp_path, scale_factor=1.0)
        config = TPCDSOfficialBenchmarkConfig(scale_factor=10.0, num_streams=3, output_dir=tmp_path)

        official.run_official_benchmark(lambda: Mock(), config=config)

        assert phases.power.call_args.kwargs["scale_factor"] == 10.0
        assert phases.throughput.call_args.kwargs["scale_factor"] == 10.0
        assert phases.throughput.call_args.kwargs["num_streams"] == 3


class TestPowerPhaseOutcome:
    @pytest.mark.parametrize(
        "power",
        [
            _power(success=True, executed=99, successful=70),
            _power(success=True, executed=99, successful=98),
            _power(success=False, executed=99, successful=99),
        ],
    )
    def test_partial_or_failed_power_phase_publishes_no_metric(self, tmp_path, phases, power):
        phases.power.return_value.run.return_value = power
        official = _official(tmp_path)

        result = official.run_official_benchmark(lambda: Mock())

        assert result.success is False
        assert result.power_at_size == 0.0
        assert not hasattr(result, "qphds_at_size")
        assert any("Power@Size withheld" in error for error in result.errors)

    def test_complete_power_phase_publishes_the_metric(self, tmp_path, phases):
        official = _official(tmp_path)

        result = official.run_official_benchmark(lambda: Mock())

        assert result.power_at_size == 100.0
        assert not hasattr(result, "qphds_at_size")
        assert result.errors == []


class TestStreamMinimum:
    def test_one_stream_is_refused_before_the_throughput_driver_is_built(self, tmp_path, phases):
        official = _official(tmp_path)
        config = TPCDSOfficialBenchmarkConfig(scale_factor=0.01, num_streams=1, output_dir=tmp_path)

        result = official.run_official_benchmark(lambda: Mock(), config=config)

        phases.throughput.assert_not_called()
        assert result.success is False
        assert result.throughput_at_size == 0.0
        assert any("at least 2" in error for error in result.errors)
