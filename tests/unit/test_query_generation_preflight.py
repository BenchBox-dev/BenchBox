"""Tests for preflight query generation validation for TPC-DS and TPC-H."""

from unittest.mock import Mock

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


def _mk_tpcds_power(raise_on_ids=None):
    from benchbox.core.tpcds.benchmark import TPCDSBenchmark
    from benchbox.core.tpcds.power_test import TPCDSPowerTest

    bench = TPCDSBenchmark(scale_factor=1.0, verbose=False)
    # Patch benchmark.get_query to simulate dsqgen failures for certain IDs
    raise_on_ids = set(raise_on_ids or [])

    def _get_query(query_id, **kwargs):
        if query_id in raise_on_ids:
            raise RuntimeError(f"Template substitution error for q{query_id}")
        return f"SELECT {query_id}"

    bench.get_query = _get_query  # type: ignore[attr-defined]
    power = TPCDSPowerTest(benchmark=bench, connection_factory=lambda: Mock(), scale_factor=0.01)
    return power


def _mk_tpch_power(raise_on_ids=None):
    from benchbox.core.tpch.benchmark import TPCHBenchmark
    from benchbox.core.tpch.power_test import TPCHPowerTest

    bench = TPCHBenchmark(scale_factor=0.01, verbose=False)
    raise_on_ids = set(raise_on_ids or [])

    def _get_query(query_id, **kwargs):
        if query_id in raise_on_ids:
            raise RuntimeError(f"QGen error for q{query_id}")
        return f"SELECT {query_id}"

    bench.get_query = _get_query  # type: ignore[attr-defined]
    power = TPCHPowerTest(benchmark=bench, connection=Mock(), scale_factor=0.01)
    return power


def test_tpcds_power_preflight_detects_generation_failures():
    power = _mk_tpcds_power(raise_on_ids={3, 17})
    with pytest.raises(RuntimeError) as ei:
        # Call run which performs preflight first
        power.run()
    assert "preflight failed" in str(ei.value).lower()


def test_tpch_power_preflight_detects_generation_failures():
    power = _mk_tpch_power(raise_on_ids={5})
    with pytest.raises(RuntimeError) as ei:
        power.run()
    assert "preflight failed" in str(ei.value).lower()


def test_tpcds_throughput_preflight_detects_generation_failures():
    from benchbox.core.tpcds.benchmark import TPCDSBenchmark
    from benchbox.core.tpcds.throughput_test import TPCDSThroughputTest

    bench = TPCDSBenchmark(scale_factor=1.0, verbose=False)

    def _get_query(query_id, **kwargs):
        # Fail one query to trigger preflight error
        if query_id == 7:
            raise RuntimeError("Template substitution error for q7")
        return f"SELECT {query_id}"

    bench.get_query = _get_query  # type: ignore[attr-defined]
    thr = TPCDSThroughputTest(
        benchmark=bench,
        connection_factory=lambda: Mock(),
        scale_factor=0.01,
        num_streams=2,
    )

    with pytest.raises(RuntimeError) as ei:
        thr.run()
    assert "preflight failed" in str(ei.value).lower()
