"""Unit tests for TPC patterns module.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.

NOTE: This module previously tested a generic concurrent-stream execution
framework (StreamExecutor, QueryPermutator, ParameterManager,
TransactionManager, ErrorHandler, ProgressTracker, ResultAggregator,
BenchmarkTestRunner, and related dataclasses/utilities) that has been removed
as part of the concurrency-executor consolidation. That framework was never
wired into the TPC-H or TPC-DS execution paths -- the only external consumer
of ``benchbox.core.tpc_patterns`` imports ``generate_official_benchmark_audit_trail``,
which is what remains in the module and is covered below.
"""

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchbox.core.tpc_patterns import generate_official_benchmark_audit_trail

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@dataclass
class _FakeConfig:
    output_dir: Path
    scale_factor: float = 1.0
    num_streams: int = 2


@dataclass
class _FakeResult:
    config: _FakeConfig
    start_time: str = "2026-07-09T00:00:00"
    end_time: str = "2026-07-09T00:01:00"
    total_time: float = 60.0
    power_at_size: float = 100.0
    throughput_at_size: float = 200.0
    qphh_at_size: float = 150.0
    success: bool = True
    errors: list = field(default_factory=list)


class TestGenerateOfficialBenchmarkAuditTrail:
    """Test the shared official-benchmark audit trail writer."""

    def test_writes_audit_trail_with_default_output_file(self, tmp_path):
        """When output_file is omitted, a timestamped file is created under config.output_dir."""
        result = _FakeResult(config=_FakeConfig(output_dir=tmp_path))

        output_path = generate_official_benchmark_audit_trail(
            result=result,
            benchmark_title="TPC-H",
            benchmark_slug="tpch",
            qph_label="QphH@Size",
            qph_attr="qphh_at_size",
        )

        assert output_path.exists()
        assert output_path.parent == tmp_path
        assert output_path.name.startswith("tpch_audit_trail_")

        content = output_path.read_text(encoding="utf-8")
        assert "TPC-H Official Benchmark Audit Trail" in content
        assert "Scale Factor: 1.0" in content
        assert "Number of Streams: 2" in content
        assert "Power@Size: 100.00" in content
        assert "Throughput@Size: 200.00" in content
        assert "QphH@Size: 150.00" in content
        assert "Success: True" in content
        assert "Errors:" not in content

    def test_writes_audit_trail_with_explicit_output_file(self, tmp_path):
        """An explicit output_file overrides the default naming/location."""
        result = _FakeResult(config=_FakeConfig(output_dir=None))
        explicit_path = tmp_path / "nested" / "custom_audit.txt"

        output_path = generate_official_benchmark_audit_trail(
            result=result,
            benchmark_title="TPC-DS",
            benchmark_slug="tpcds",
            qph_label="QphDS@Size",
            qph_attr="qphh_at_size",
            output_file=explicit_path,
        )

        assert output_path == explicit_path
        assert output_path.exists()
        assert "TPC-DS Official Benchmark Audit Trail" in output_path.read_text(encoding="utf-8")

    def test_writes_errors_section_when_present(self, tmp_path):
        """Errors accumulated on the result are listed in the audit trail."""
        result = _FakeResult(config=_FakeConfig(output_dir=tmp_path), success=False, errors=["stream 0 failed"])

        output_path = generate_official_benchmark_audit_trail(
            result=result,
            benchmark_title="TPC-H",
            benchmark_slug="tpch",
            qph_label="QphH@Size",
            qph_attr="qphh_at_size",
        )

        content = output_path.read_text(encoding="utf-8")
        assert "Success: False" in content
        assert "Errors:" in content
        assert "stream 0 failed" in content

    def test_falls_back_to_cwd_benchmark_results_when_no_output_dir(self, tmp_path, monkeypatch):
        """With no output_dir and no output_file, the file lands under cwd/benchmark_results."""
        monkeypatch.chdir(tmp_path)
        result = _FakeResult(config=_FakeConfig(output_dir=None))

        output_path = generate_official_benchmark_audit_trail(
            result=result,
            benchmark_title="TPC-H",
            benchmark_slug="tpch",
            qph_label="QphH@Size",
            qph_attr="qphh_at_size",
        )

        assert output_path.parent == tmp_path / "benchmark_results"
        assert output_path.exists()

    def test_qph_attr_is_resolved_dynamically(self, tmp_path):
        """qph_attr selects the result attribute used for the QPH line."""
        result = SimpleNamespace(
            config=_FakeConfig(output_dir=tmp_path),
            start_time="t0",
            end_time="t1",
            total_time=1.0,
            power_at_size=1.0,
            throughput_at_size=1.0,
            custom_qph=42.5,
            success=True,
            errors=[],
        )

        output_path = generate_official_benchmark_audit_trail(
            result=result,
            benchmark_title="TPC-DS",
            benchmark_slug="tpcds",
            qph_label="QphDS@Size",
            qph_attr="custom_qph",
        )

        assert "QphDS@Size: 42.50" in output_path.read_text(encoding="utf-8")
