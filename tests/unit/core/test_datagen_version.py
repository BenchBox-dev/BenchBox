"""Tests for data-generation versioning and stale-datagen auto-detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchbox.utils.datagen_version import (
    DATA_GENERATION_VERSION,
    compute_base_constants_hash,
    current_datagen_stamp,
    describe_datagen_staleness,
    manifest_datagen_is_current,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_current_stamp_is_current() -> None:
    manifest = {"benchmark": "tpch", **current_datagen_stamp("tpch")}
    assert manifest_datagen_is_current(manifest, benchmark="tpch") is True
    assert describe_datagen_staleness(manifest, benchmark="tpch") is None


def test_missing_stamp_is_stale() -> None:
    manifest = {"benchmark": "tpch", "scale_factor": 1.0}
    assert manifest_datagen_is_current(manifest, benchmark="tpch") is False
    reason = describe_datagen_staleness(manifest, benchmark="tpch")
    assert reason is not None and "predates version stamping" in reason


def test_changed_base_constants_hash_is_stale() -> None:
    manifest = {"benchmark": "tpch", **current_datagen_stamp("tpch")}
    manifest["base_constants_hash"] = "0" * 64
    assert manifest_datagen_is_current(manifest, benchmark="tpch") is False
    reason = describe_datagen_staleness(manifest, benchmark="tpch")
    assert reason is not None and "base constants changed" in reason


def test_base_constants_hash_is_stable() -> None:
    assert compute_base_constants_hash("tpch") == compute_base_constants_hash("tpch")


def test_base_constants_hash_fingerprints_spec_files() -> None:
    """Distinct spec inputs must hash distinctly, or staleness is undetectable."""
    assert compute_base_constants_hash("tpch") != compute_base_constants_hash("tsbs_devops")


def test_base_constants_hash_changes_with_spec_contents(tmp_path, monkeypatch) -> None:
    import benchbox.utils.datagen_version as datagen_version

    specs = tmp_path / "generator_specs.yaml"
    specs.write_text("base_row_counts:\n  lineitem: 1\n")
    monkeypatch.setitem(datagen_version._BENCHMARK_SPECS_FILES, "probe", (str(specs),))
    before = compute_base_constants_hash("probe")
    specs.write_text("base_row_counts:\n  lineitem: 2\n")
    assert compute_base_constants_hash("probe") != before


def test_manifest_writer_stamps_version(tmp_path: Path) -> None:
    from benchbox.utils.datagen_manifest import DataGenerationManifest as DatagenManifest

    manifest = DatagenManifest(output_dir=tmp_path, benchmark="tpch", scale_factor=1.0)
    stamped = manifest.to_dict()
    assert stamped["data_generation_version"] == DATA_GENERATION_VERSION
    assert stamped["base_constants_hash"] == compute_base_constants_hash("tpch")
    assert manifest_datagen_is_current(stamped, benchmark="tpch") is True


def test_stale_manifest_fails_reuse_validation(tmp_path: Path) -> None:
    from benchbox.core.runner.runner import _validate_manifest_if_present

    data_file = tmp_path / "customer.tbl"
    data_file.write_text("1|a\n")
    manifest = {
        "benchmark": "tpch",
        "scale_factor": 1.0,
        "tables": {"customer": {"formats": {"tbl": [{"path": "customer.tbl"}]}}},
    }
    (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest))

    class _Benchmark:
        output_dir = tmp_path
        tables = None

    class _Config:
        scale_factor = 1.0
        options = {}

    valid, _data, found = _validate_manifest_if_present(_Benchmark(), _Config())
    assert found is True
    assert valid is False


def test_result_carries_verified_data_generation_version(tmp_path) -> None:
    import json

    from benchbox.core.results.loader import reconstruct_benchmark_results
    from benchbox.core.results.schema import build_result_payload
    from benchbox.core.runner.runner import _attach_datagen_version
    from tests.fixtures.result_dict_fixtures import make_benchmark_results

    (tmp_path / "_datagen_manifest.json").write_text(
        json.dumps({"benchmark": "Test Benchmark", **current_datagen_stamp("Test Benchmark")})
    )

    class _Benchmark:
        output_dir = tmp_path

    result = _attach_datagen_version(make_benchmark_results(), _Benchmark())
    assert result.data_generation_version == DATA_GENERATION_VERSION
    payload = build_result_payload(result)
    assert payload["benchmark"]["data_generation_version"] == DATA_GENERATION_VERSION
    assert reconstruct_benchmark_results(payload).data_generation_version == DATA_GENERATION_VERSION


def test_result_leaves_version_unset_without_verified_manifest(tmp_path) -> None:
    from benchbox.core.runner.runner import _attach_datagen_version
    from tests.fixtures.result_dict_fixtures import make_benchmark_results

    class _Benchmark:
        output_dir = tmp_path

    assert _attach_datagen_version(make_benchmark_results(), _Benchmark()).data_generation_version is None
    assert _attach_datagen_version(make_benchmark_results()).data_generation_version is None


def test_result_rejects_manifest_for_another_benchmark(tmp_path) -> None:
    """A current stamp from an unrelated dataset must not verify the result."""
    import json

    from benchbox.core.runner.runner import _attach_datagen_version
    from tests.fixtures.result_dict_fixtures import make_benchmark_results

    (tmp_path / "_datagen_manifest.json").write_text(
        json.dumps({"benchmark": "tpch", "scale_factor": 1.0, **current_datagen_stamp("tpch")})
    )

    class _Benchmark:
        output_dir = tmp_path

    result = _attach_datagen_version(make_benchmark_results(), _Benchmark())
    assert result.data_generation_version is None


def test_result_accepts_shared_data_alias_manifest(tmp_path) -> None:
    """Benchmarks reusing another benchmark's dataset keep verified provenance."""
    import json

    from benchbox.core.runner.runner import _attach_datagen_version
    from tests.fixtures.result_dict_fixtures import make_benchmark_results

    (tmp_path / "_datagen_manifest.json").write_text(json.dumps({"benchmark": "tpch", **current_datagen_stamp("tpch")}))

    class _Benchmark:
        output_dir = tmp_path

        def get_data_source_benchmark(self) -> str:
            return "tpch"

    result = _attach_datagen_version(make_benchmark_results(benchmark_name="Read Primitives"), _Benchmark())
    assert result.data_generation_version == DATA_GENERATION_VERSION
    assert result.data_generation_hash == compute_base_constants_hash("tpch")


def test_result_carries_generation_hash_round_trip(tmp_path) -> None:
    """The base-constants fingerprint survives attach, persist, and load."""
    import json

    from benchbox.core.results.loader import reconstruct_benchmark_results
    from benchbox.core.results.schema import build_result_payload
    from benchbox.core.runner.runner import _attach_datagen_version
    from tests.fixtures.result_dict_fixtures import make_benchmark_results

    (tmp_path / "_datagen_manifest.json").write_text(
        json.dumps({"benchmark": "Test Benchmark", **current_datagen_stamp("Test Benchmark")})
    )

    class _Benchmark:
        output_dir = tmp_path

    result = _attach_datagen_version(make_benchmark_results(), _Benchmark())
    assert result.data_generation_hash == compute_base_constants_hash("Test Benchmark")
    payload = build_result_payload(result)
    assert payload["benchmark"]["data_generation_hash"] == compute_base_constants_hash("Test Benchmark")
    assert reconstruct_benchmark_results(payload).data_generation_hash == compute_base_constants_hash("Test Benchmark")


def test_tpcds_direct_manifest_writer_stamps_version(tmp_path: Path) -> None:
    """The TPC-DS filesystem writer stamps freshly generated manifests."""
    import json

    from benchbox.core.tpcds.generator.filesystem import FileArtifactMixin

    class _Writer(FileArtifactMixin):
        def __init__(self) -> None:
            self.scale_factor = 0.01
            self.parallel = 1
            self._manifest_entries: dict = {}

        def should_use_compression(self) -> bool:
            return False

    data_file = tmp_path / "store_sales.dat"
    data_file.write_bytes(b"1|2|3\n")
    _Writer()._write_manifest(tmp_path, {"store_sales": [data_file]})
    manifest = json.loads((tmp_path / "_datagen_manifest.json").read_text())
    assert manifest_datagen_is_current(manifest, benchmark="tpcds") is True


def test_ssb_direct_manifest_writer_stamps_version(tmp_path: Path) -> None:
    """The SSB writer stamps freshly generated manifests."""
    import json

    from benchbox.core.ssb.generator import SSBDataGenerator

    data_file = tmp_path / "customer.tbl"
    data_file.write_bytes(b"1|Alice\n")
    SSBDataGenerator(scale_factor=0.01, output_dir=tmp_path)._write_manifest(tmp_path, {"customer": data_file})
    manifest = json.loads((tmp_path / "_datagen_manifest.json").read_text())
    assert manifest_datagen_is_current(manifest, benchmark="ssb") is True


def test_scan_rebuilt_manifest_carries_no_stamp(tmp_path: Path) -> None:
    """Scan-rebuilt manifests stay unstamped: a scan proves file presence, not provenance."""
    import json

    from benchbox.utils.data_validation import BenchmarkDataValidator

    (tmp_path / "customer.tbl").write_bytes(b"1|a\n")
    BenchmarkDataValidator(benchmark_name="tpch", scale_factor=1.0)._write_manifest_from_scan(tmp_path)
    manifest = json.loads((tmp_path / "_datagen_manifest.json").read_text())
    assert "data_generation_version" not in manifest
    assert "base_constants_hash" not in manifest
    assert manifest_datagen_is_current(manifest, benchmark="tpch") is False


def test_stale_stamp_fails_directory_validation(tmp_path: Path) -> None:
    """A complete dataset with a stale stamp must regenerate, not reuse."""
    import json

    from benchbox.utils.data_validation import BenchmarkDataValidator

    (tmp_path / "customer.tbl").write_bytes(b"1|a\n")
    manifest = {
        "benchmark": "ssb",
        "scale_factor": 1.0,
        "data_generation_version": DATA_GENERATION_VERSION - 1,
        "base_constants_hash": "0" * 64,
        "tables": {},
    }
    (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest))
    result = BenchmarkDataValidator(benchmark_name="ssb", scale_factor=1.0).validate_data_directory(tmp_path)
    assert result.valid is False
    assert any("stale" in issue for issue in result.issues)


def test_attach_leaves_provenance_unset_without_dataset_identity(tmp_path: Path) -> None:
    """Execute-only runs must not inherit the local manifest's stamp."""
    import json

    from benchbox.core.runner.runner import _attach_datagen_version
    from tests.fixtures.result_dict_fixtures import make_benchmark_results

    (tmp_path / "_datagen_manifest.json").write_text(
        json.dumps({"benchmark": "Test Benchmark", **current_datagen_stamp("Test Benchmark")})
    )

    class _Benchmark:
        output_dir = tmp_path

    result = _attach_datagen_version(make_benchmark_results(), _Benchmark(), dataset_identity_established=False)
    assert result.data_generation_version is None
    assert result.data_generation_hash is None


def test_compare_flags_generation_mismatch() -> None:
    """Comparisons across data generations warn instead of ranking silently."""
    from benchbox.core.results.exporter import ResultExporter

    def _data(version: int | None, hash_value: str | None) -> dict:
        benchmark: dict = {"name": "tpch", "scale_factor": 1.0}
        if version is not None:
            benchmark["data_generation_version"] = version
        if hash_value is not None:
            benchmark["data_generation_hash"] = hash_value
        return {"benchmark": benchmark}

    same = ResultExporter._check_generation_compatibility(
        _data(DATA_GENERATION_VERSION, "a" * 64), _data(DATA_GENERATION_VERSION, "a" * 64)
    )
    assert same["status"] == "compatible"
    assert same["compatible"] is True
    assert same["warning"] is None

    mismatch = ResultExporter._check_generation_compatibility(
        _data(DATA_GENERATION_VERSION, "a" * 64), _data(DATA_GENERATION_VERSION + 1, "b" * 64)
    )
    assert mismatch["status"] == "incompatible"
    assert mismatch["compatible"] is False
    assert mismatch["warning"] is not None and "different data generations" in mismatch["warning"]

    evolved_specs = ResultExporter._check_generation_compatibility(
        _data(DATA_GENERATION_VERSION, "a" * 64), _data(DATA_GENERATION_VERSION, "b" * 64)
    )
    assert evolved_specs["status"] == "incompatible"
    assert evolved_specs["compatible"] is False
    assert evolved_specs["warning"] is not None and "fingerprints differ" in evolved_specs["warning"]

    legacy = ResultExporter._check_generation_compatibility(_data(None, None), _data(DATA_GENERATION_VERSION, "a" * 64))
    assert legacy["status"] == "unknown"
    assert legacy["compatible"] is None
    assert legacy["warning"] is not None and "predate" in legacy["warning"]

    missing_hash = ResultExporter._check_generation_compatibility(
        _data(DATA_GENERATION_VERSION, None), _data(DATA_GENERATION_VERSION, "a" * 64)
    )
    assert missing_hash["status"] == "unknown"
    assert missing_hash["compatible"] is None


def test_generation_warning_travels_with_saved_artifacts() -> None:
    """Saved text/markdown/HTML comparisons must carry the generation caveat."""
    from benchbox.cli.commands.compare import (
        _format_html_comparison,
        _format_markdown_comparison,
        _format_text_comparison,
    )

    comparison = {
        "baseline_file": "b.json",
        "current_file": "c.json",
        "generation_compatibility": {"status": "incompatible", "compatible": False, "warning": "dataset differences"},
    }

    class _Result:
        benchmark_name = "tpch"
        platform = "duckdb"
        scale_factor = 1.0

    assert "dataset differences" in _format_text_comparison(comparison, _Result(), _Result(), False)
    assert "dataset differences" in _format_markdown_comparison(comparison, _Result(), _Result(), False)
    assert "dataset differences" in _format_html_comparison(comparison, _Result(), _Result())

    clean = dict(comparison, generation_compatibility={"status": "compatible", "compatible": True, "warning": None})
    assert "DATA GENERATION" not in _format_text_comparison(clean, _Result(), _Result(), False)
