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
        if module.startswith("__alias__:"):
            target = module.split(":", 1)[1]
            assert target in mod.all_benchmark_ids(), f"{benchmark}: alias target {target} missing"
            continue
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


def test_sum_paths_skips_transport_archives(tmp_path):
    mod = _load_script()
    archive = tmp_path / "joinorder-imdb-2013-v1.tar.zst"
    archive.write_text("z" * 70)
    data = tmp_path / "cast_info.tbl"
    data.write_text("y" * 50)
    total, count = mod._sum_paths(tmp_path)
    assert total == 50
    assert count == 1


def test_sum_paths_skips_parquet_footprints(tmp_path):
    """Parquet is encoded bytes, not uncompressed source: never counted."""
    mod = _load_script()
    (tmp_path / "cast_info.parquet").write_bytes(b"y" * 50)
    total, count = mod._sum_paths(tmp_path)
    assert total == 0
    assert count == 0


def test_sum_paths_counts_parquet_for_parquet_native_benchmarks(tmp_path):
    """joinorder ships only Parquet: its documented size is the on-disk footprint."""
    mod = _load_script()
    (tmp_path / "cast_info.parquet").write_bytes(b"y" * 50)
    total, count = mod._sum_paths(tmp_path, count_parquet=True)
    assert total == 50
    assert count == 1


def test_only_joinorder_counts_parquet():
    mod = _load_script()
    flagged = [bid for bid, _, _, extra in mod.GENERATORS + mod.BENCHMARK_LEVEL if extra.get("count_parquet")]
    assert flagged == ["joinorder"]


def test_measure_many_parallel_resolves_alias_without_regenerating(monkeypatch):
    """Aliases reuse the parent-process record instead of re-running the source generator."""
    mod = _load_script()
    calls: list[str] = []

    def fake_run(module, cls_name, extra):
        calls.append(cls_name)
        return 10, 1, None, 0.0

    monkeypatch.setattr(mod, "_run_generator", fake_run)
    mod._RECORD_CACHE.clear()

    class _InlinePool:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def map(self, fn, items):
            return [fn(item) for item in items]

    monkeypatch.setattr(mod.concurrent.futures, "ProcessPoolExecutor", _InlinePool)
    records = mod.measure_many(["tpchavoc", "tpch"], jobs=2)
    mod._RECORD_CACHE.clear()
    assert [r.benchmark for r in records] == ["tpchavoc", "tpch"]
    assert all(r.error is None and r.total_bytes == 10 for r in records)
    assert len(calls) == 1


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
    assert table.is_file()
    expected = set(mod.all_benchmark_ids()) | {"ai_primitives", "metadata_primitives"}
    # Compare against parsed table rows, not a substring search: a benchmark
    # mentioned only in prose must not satisfy the coverage check.
    assert expected <= set(_parse_calibrated_table()), "benchmark missing from calibrated size table rows"


def _parse_calibrated_table() -> dict[str, int]:
    table = Path(__file__).resolve().parents[3] / "docs" / "benchmarks" / "sf1-calibrated-sizes.md"
    rows = [line for line in table.read_text().splitlines() if line.startswith("| ") and "Benchmark" not in line]
    parsed: dict[str, int] = {}
    for row in rows:
        cells = [c.strip() for c in row.split("|")]
        parsed[cells[1]] = int(cells[2].replace(",", ""))
    return parsed


def _load_baseline() -> dict:
    fixture = Path(__file__).resolve().parent / "sf1_size_baseline.json"
    return json.loads(fixture.read_text(encoding="utf-8"))


def test_calibrated_table_values_are_positive():
    parsed = _parse_calibrated_table()
    assert len(parsed) >= 20
    for name, byte_value in parsed.items():
        if name == "metadata_primitives":
            assert byte_value == 0
        else:
            assert byte_value > 0, f"{name} has non-positive size"


def test_calibrated_table_matches_baseline_fixture():
    """The doc table must reproduce the persisted measurement baseline.

    The baseline fixture holds the byte counts emitted by
    scripts/measure_sf1_sizes.py; the table is its human-readable mirror.
    A generator change that shifts SF=1 sizes must update both together,
    so a drift in either file fails here rather than passing silently.
    """
    baseline = _load_baseline()
    parsed = _parse_calibrated_table()
    tolerance = baseline["tolerance"]
    mod = _load_script()
    documented_without_generation = {"ai_primitives", "metadata_primitives"}
    for benchmark, expected in baseline["sizes"].items():
        assert benchmark in mod.all_benchmark_ids(), f"{benchmark}: baseline entry without measurement entry"
        assert benchmark in parsed, f"{benchmark} missing from calibrated size table"
        actual = parsed[benchmark]
        assert actual == pytest.approx(expected, rel=tolerance), (
            f"{benchmark}: table has {actual}, baseline expects {expected} (tolerance {tolerance})"
        )
    for benchmark in set(parsed) - set(baseline["sizes"]) - documented_without_generation:
        raise AssertionError(f"{benchmark}: table entry without baseline entry")
    # ai_primitives reuses TPC-H data, so its row must track the tpch row.
    assert parsed["ai_primitives"] == parsed["tpch"]


def test_jobs_option_runs_subset():
    mod = _load_script()
    assert mod.main(["--benchmark", "no-such-benchmark", "--jobs", "2"]) == 2
    with pytest.raises(ValueError, match="--jobs must be"):
        mod.measure_many(["tpch"], jobs=0)


@pytest.mark.slow
def test_measure_one_runs_a_lightweight_generator_end_to_end():
    """measure_one executes a real generator and counts only its outputs."""
    mod = _load_script()
    record = mod.measure_one("coffeeshop")
    assert record.error is None, record.error
    assert record.total_bytes > 0
    assert record.file_count > 0


def test_compressed_variants_and_parquet_do_not_count(tmp_path):
    mod = _load_script()
    (tmp_path / "a.tbl").write_text("x" * 100)
    (tmp_path / "a.tbl.gz").write_text("x" * 10)
    (tmp_path / "b.parquet").write_bytes(b"y" * 50)
    (tmp_path / ".bulk_load_metadata.json").write_text('{"ts": "now"}')
    total, count = mod._sum_paths(str(tmp_path))
    assert total == 100
    assert count == 1


def test_source_cache_is_excluded_from_measurement(tmp_path):
    mod = _load_script()
    (tmp_path / "orders.tbl").write_text("x" * 64)
    cache = tmp_path / "source_cache" / "tpch_sf1"
    cache.mkdir(parents=True)
    (cache / "lineitem.tbl").write_text("y" * 1024)
    total, count = mod._sum_tree_excluding(tmp_path, {tmp_path / "source_cache"}, set())
    assert total == 64
    assert count == 1


def test_manifest_rows_use_first_format_only(tmp_path):
    mod = _load_script()
    manifest = {
        "tables": {
            "orders": {
                "formats": {
                    "tbl": [{"path": "orders.tbl", "row_count": 1500000}],
                    "parquet": [{"path": "orders.parquet", "row_count": 1500000}],
                }
            }
        }
    }
    (tmp_path / "_datagen_manifest.json").write_text(json.dumps(manifest))
    assert mod._sum_manifest_rows(tmp_path) == 1500000


def test_synthetic_fallback_aborts_measurement():
    mod = _load_script()

    class _Downloader:
        _synthetic_fallback_months = ["2024-01"]

    class _Benchmark:
        downloader = _Downloader()

    with pytest.raises(RuntimeError, match="synthetic fallback"):
        mod._reject_synthetic_fallback(_Benchmark(), "NYCTaxiBenchmark")


@pytest.mark.slow
def test_tpchavoc_aliases_tpch_without_regeneration(monkeypatch):
    mod = _load_script()
    calls: list[str] = []
    real_run = mod._run_generator

    def _spy(module: str, cls_name: str, extra: dict):
        calls.append(module)
        return real_run(module, cls_name, extra)

    monkeypatch.setattr(mod, "_run_generator", _spy)
    tpch = mod.measure_one("tpch")
    assert tpch.error is None, tpch.error
    assert calls == ["benchbox.core.tpch.generator"]
    havoc = mod.measure_one("tpchavoc")
    assert havoc.error is None, havoc.error
    assert havoc.total_bytes == tpch.total_bytes
    assert "alias of tpch" in havoc.notes
    assert calls == ["benchbox.core.tpch.generator"], "alias must not regenerate"


def test_size_record_json_shape():
    mod = _load_script()
    record = mod.SizeRecord(benchmark="ssb", total_bytes=5, file_count=1)
    payload = json.dumps({"records": [record.__dict__]})
    assert '"benchmark": "ssb"' in payload
