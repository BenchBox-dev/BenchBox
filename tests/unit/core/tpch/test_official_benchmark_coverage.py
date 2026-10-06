from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from benchbox.core.tpch.official_benchmark import (
    TPCHOfficialBenchmark,
    TPCHOfficialBenchmarkConfig,
    TPCHOfficialBenchmarkResult,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class FakeConnection:
    connection_string = "duckdb://mem"

    def close(self):
        return None


class FakeBenchmark:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def run_power_test(self, **kwargs):
        return {"power_at_size": 100.0}

    def run_throughput_test(self, **kwargs):
        return {"throughput_at_size": 64.0}

    def run_maintenance_test(self, **kwargs):
        return {"ok": True}


def test_run_official_benchmark_success(monkeypatch, tmp_path):
    monkeypatch.setattr("benchbox.core.tpch.official_benchmark.TPCHBenchmark", FakeBenchmark)

    benchmark = TPCHOfficialBenchmark(scale_factor=1.0, output_dir=tmp_path, verbose=False)
    result = benchmark.run_official_benchmark(connection_factory=FakeConnection)

    assert result.success is True
    assert result.power_at_size == 100.0
    assert result.throughput_at_size == 64.0
    assert not hasattr(result, "qphh_at_size")


def test_run_official_benchmark_collects_phase_errors(monkeypatch, tmp_path):
    class FlakyBenchmark(FakeBenchmark):
        def run_power_test(self, **kwargs):
            raise RuntimeError("power fail")

        def run_throughput_test(self, **kwargs):
            raise RuntimeError("throughput fail")

        def run_maintenance_test(self, **kwargs):
            raise RuntimeError("maintenance fail")

    monkeypatch.setattr("benchbox.core.tpch.official_benchmark.TPCHBenchmark", FlakyBenchmark)

    benchmark = TPCHOfficialBenchmark(scale_factor=1.0, output_dir=tmp_path, verbose=False)
    result = benchmark.run_official_benchmark(connection_factory=FakeConnection)

    assert result.success is False
    assert len(result.errors) == 3
    assert any("Power Test failed" in err for err in result.errors)


def test_validate_compliance_checks():
    benchmark = TPCHOfficialBenchmark.__new__(TPCHOfficialBenchmark)
    result = TPCHOfficialBenchmarkResult(
        config=TPCHOfficialBenchmarkConfig(scale_factor=1.0),
        start_time="s",
        end_time="e",
        total_time=1.0,
        power_test_result=None,
        throughput_test_result=None,
        maintenance_test_result=None,
        power_at_size=10.0,
        throughput_at_size=20.0,
        success=True,
        errors=[],
    )

    assert benchmark.validate_compliance(result) is True
    result.success = False
    assert benchmark.validate_compliance(result) is False
    result.success = True
    result.power_at_size = 0
    assert benchmark.validate_compliance(result) is False


def test_generate_audit_trail_writes_file(monkeypatch, tmp_path):
    monkeypatch.setattr("benchbox.core.tpch.official_benchmark.TPCHBenchmark", FakeBenchmark)
    benchmark = TPCHOfficialBenchmark(scale_factor=1.0, output_dir=tmp_path, verbose=False)

    result = TPCHOfficialBenchmarkResult(
        config=TPCHOfficialBenchmarkConfig(scale_factor=1.0, output_dir=tmp_path, num_streams=2),
        start_time="2026-01-01T00:00:00",
        end_time="2026-01-01T00:01:00",
        total_time=60.0,
        power_test_result=None,
        throughput_test_result=None,
        maintenance_test_result=None,
        power_at_size=10.0,
        throughput_at_size=20.0,
        success=True,
        errors=[],
    )

    path = benchmark.generate_audit_trail(result)

    assert path.exists()
    content = path.read_text()
    assert "TPC-H Official Benchmark Audit Trail" in content
    assert "QphH" not in content
    assert "Power@Size: 10.00" in content
