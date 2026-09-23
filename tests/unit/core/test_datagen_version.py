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

    (tmp_path / "_datagen_manifest.json").write_text(json.dumps({"benchmark": "tpch", **current_datagen_stamp("tpch")}))

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
