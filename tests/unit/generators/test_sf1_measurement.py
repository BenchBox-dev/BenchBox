"""SF=1 measurement script and calibrated size table tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "measure_sf1_sizes.py"


def _load_script():
    import sys

    spec = importlib.util.spec_from_file_location("measure_sf1_sizes", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["measure_sf1_sizes"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_all_registry_benchmarks_have_measurement_entry():
    from benchbox.core.benchmark_registry import get_all_benchmarks

    mod = _load_script()
    registry_ids = set(get_all_benchmarks())
    measured = set(mod.all_benchmark_ids())
    # ai_primitives reuses TPC-H data; metadata_primitives has no data files.
    # Both are documented in the calibrated table rather than generated.
    documented_without_generation = {"ai_primitives", "metadata_primitives"}
    missing = registry_ids - measured - documented_without_generation
    assert not missing, f"benchmarks without measurement entry: {sorted(missing)}"


def test_measurement_entries_resolve_to_importable_classes():
    mod = _load_script()
    for benchmark, module, cls_name, _ in mod.GENERATORS + mod.BENCHMARK_LEVEL:
        module_obj = __import__(module, fromlist=[cls_name])
        assert hasattr(module_obj, cls_name), f"{benchmark}: {module}.{cls_name} missing"


def test_sum_paths_handles_nested_returns(tmp_path):
    mod = _load_script()
    leaf = tmp_path / "a.tbl"
    leaf.write_text("x" * 100)
    nested = {"t1": str(leaf), "t2": [str(leaf)]}
    total, count = mod._sum_paths(nested)
    assert total == 100
    assert count == 1


def test_sum_paths_skips_manifest(tmp_path):
    mod = _load_script()
    manifest = tmp_path / "_datagen_manifest.json"
    manifest.write_text("{}")
    data = tmp_path / "b.tbl"
    data.write_text("y" * 50)
    total, count = mod._sum_paths({"m": str(manifest), "d": str(data)})
    assert total == 50
    assert count == 1


def test_measure_unknown_benchmark_records_error():
    mod = _load_script()
    record = mod.measure_one("no-such-benchmark")
    assert record.error is not None
    assert "no measurement entry" in record.error


def test_main_rejects_unknown_subset():
    mod = _load_script()
    assert mod.main(["--benchmark", "no-such-benchmark"]) == 2


def test_calibrated_table_covers_all_measured_benchmarks():
    mod = _load_script()
    table = Path(__file__).resolve().parents[3] / "docs" / "benchmarks" / "sf1-calibrated-sizes.md"
    text = table.read_text()
    for benchmark in mod.all_benchmark_ids() + ["ai_primitives", "metadata_primitives"]:
        assert benchmark in text, f"{benchmark} missing from calibrated size table"


def test_calibrated_table_values_are_positive():
    table = Path(__file__).resolve().parents[3] / "docs" / "benchmarks" / "sf1-calibrated-sizes.md"
    rows = [line for line in table.read_text().splitlines() if line.startswith("| ") and "Benchmark" not in line]
    assert len(rows) >= 20
    for row in rows:
        cells = [c.strip() for c in row.split("|")]
        name, byte_cell = cells[1], cells[2]
        byte_value = int(byte_cell.replace(",", ""))
        if name == "metadata_primitives":
            assert byte_value == 0
        else:
            assert byte_value > 0, f"{name} has non-positive size"


def test_size_record_json_shape():
    mod = _load_script()
    record = mod.SizeRecord(benchmark="ssb", total_bytes=5, file_count=1)
    payload = json.dumps({"records": [record.__dict__]})
    assert '"benchmark": "ssb"' in payload
