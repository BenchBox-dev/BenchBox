"""Coverage tests for TPCH skew data generator."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from benchbox.core.tpch_skew.generator import TPCHSkewDataGenerator
from benchbox.core.tpch_skew.skew_config import (
    AttributeSkewConfig,
    JoinSkewConfig,
    SkewConfiguration,
    TemporalSkewConfig,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _make_config(distribution: str = "zipfian") -> SkewConfiguration:
    return SkewConfiguration(
        skew_factor=0.7,
        distribution_type=distribution,
        attribute_skew=AttributeSkewConfig(
            customer_nation_skew=0.6,
            customer_segment_skew=0.5,
            supplier_nation_skew=0.5,
            part_brand_skew=0.5,
            part_type_skew=0.5,
            part_container_skew=0.5,
            order_priority_skew=0.4,
            shipmode_skew=0.4,
            returnflag_skew=0.4,
        ),
        join_skew=JoinSkewConfig(
            customer_order_skew=0.5,
            part_popularity_skew=0.5,
            supplier_volume_skew=0.5,
        ),
        temporal_skew=TemporalSkewConfig(
            order_date_skew=0.5,
            ship_date_seasonality=0.5,
        ),
        enable_attribute_skew=True,
        enable_join_skew=True,
        enable_temporal_skew=True,
        seed=42,
    )


def _small_skewed_values(num_values: int, min_val: int, max_val: int, _skew: float) -> np.ndarray:
    span = max_val - min_val + 1
    return np.array([min_val + (i % span) for i in range(num_values)])


@pytest.mark.parametrize("dist", ["zipfian", "normal", "exponential", "uniform"])
def test_create_distribution_variants(dist: str, tmp_path: Path):
    gen = TPCHSkewDataGenerator(scale_factor=0.01, output_dir=tmp_path, skew_config=_make_config(dist))
    assert gen.distribution.get_description()


def test_check_existing_and_collect_table_files(tmp_path: Path):
    gen = TPCHSkewDataGenerator(scale_factor=0.01, output_dir=tmp_path, skew_config=_make_config())
    assert gen._check_existing_data() is False

    tables = ["customer", "lineitem", "nation", "orders", "part", "partsupp", "region", "supplier"]
    for name in tables:
        (tmp_path / f"{name}.tbl").write_text("1|x|\n", encoding="utf-8")

    # Files alone are not enough: reuse requires a current manifest stamp.
    assert gen._check_existing_data() is False
    gen._write_manifest({name: tmp_path / f"{name}.tbl" for name in tables})
    assert gen._check_existing_data() is True
    found = gen._collect_table_files()
    assert set(found) == {"customer", "lineitem", "nation", "orders", "part", "partsupp", "region", "supplier"}


def test_check_existing_rejects_stale_manifest(tmp_path: Path):
    import json

    from benchbox.utils.datagen_version import DATA_GENERATION_VERSION

    gen = TPCHSkewDataGenerator(scale_factor=0.01, output_dir=tmp_path, skew_config=_make_config())
    for name in ["customer", "lineitem"]:
        (tmp_path / f"{name}.tbl").write_text("1|x|\n", encoding="utf-8")
    (tmp_path / "_datagen_manifest.json").write_text(
        json.dumps(
            {
                "benchmark": "tpch_skew",
                "scale_factor": 0.01,
                "data_generation_version": DATA_GENERATION_VERSION - 1,
                "base_constants_hash": "0" * 64,
                "tables": {},
            }
        )
    )
    assert gen._check_existing_data() is False


def test_written_manifest_carries_current_skew_stamp(tmp_path: Path):
    import json

    from benchbox.utils.datagen_version import manifest_datagen_is_current

    gen = TPCHSkewDataGenerator(scale_factor=0.01, output_dir=tmp_path, skew_config=_make_config())
    (tmp_path / "customer.tbl").write_text("1|x|\n", encoding="utf-8")
    gen._write_manifest({"customer": tmp_path / "customer.tbl"})
    manifest = json.loads((tmp_path / "_datagen_manifest.json").read_text(encoding="utf-8"))
    assert manifest["benchmark"] == "tpch_skew"
    assert manifest_datagen_is_current(manifest, benchmark="tpch_skew") is True
    assert manifest["skew_configuration"] == gen.skew_config.datagen_identity()
    assert manifest["skew_configuration_hash"] == gen.skew_config.datagen_identity_hash()
    assert manifest["data_generation_identity_hash"]


def test_changed_skew_configuration_rejects_manifest_reuse(tmp_path: Path):
    """The generator and core runner reject a cache after a skew input changes."""
    from benchbox.core.runner.runner import _validate_manifest_if_present

    tables = ["customer", "lineitem", "nation", "orders", "part", "partsupp", "region", "supplier"]
    original = TPCHSkewDataGenerator(scale_factor=0.01, output_dir=tmp_path, skew_config=_make_config())
    for name in tables:
        (tmp_path / f"{name}.tbl").write_text("1|x|\n", encoding="utf-8")
    original._write_manifest({name: tmp_path / f"{name}.tbl" for name in tables})
    assert original._check_existing_data() is True

    changed_config = _make_config()
    changed_config.attribute_skew.part_brand_skew = 0.9
    changed = TPCHSkewDataGenerator(scale_factor=0.01, output_dir=tmp_path, skew_config=changed_config)
    assert changed._check_existing_data() is False

    valid, manifest, found = _validate_manifest_if_present(
        changed,
        SimpleNamespace(name="tpch_skew", scale_factor=0.01),
        quiet=True,
    )
    assert found is True
    assert valid is False
    assert manifest is None


def test_read_and_write_tbl_file_roundtrip(tmp_path: Path):
    gen = TPCHSkewDataGenerator(scale_factor=0.01, output_dir=tmp_path, skew_config=_make_config())
    src = tmp_path / "src.tbl"
    src.write_text("1|A|B|\n2|C|D|\n", encoding="utf-8")
    rows = gen._read_tbl_file(src)
    assert rows == [["1", "A", "B"], ["2", "C", "D"]]

    out = tmp_path / "out.tbl"
    gen._write_tbl_file(rows, out)
    assert out.read_text(encoding="utf-8") == "1|A|B\n2|C|D\n"


def test_generate_skewed_values_uniform_and_non_uniform(tmp_path: Path):
    gen_uniform = TPCHSkewDataGenerator(
        scale_factor=0.01,
        output_dir=tmp_path,
        skew_config=_make_config("uniform"),
    )
    uniform_vals = gen_uniform._generate_skewed_values(8, 1, 3, 0.0)
    assert len(uniform_vals) == 8
    assert all(1 <= v <= 3 for v in uniform_vals)

    gen_zipf = TPCHSkewDataGenerator(
        scale_factor=0.01,
        output_dir=tmp_path,
        skew_config=_make_config("zipfian"),
    )
    zipf_vals = gen_zipf._generate_skewed_values(8, 1, 5, 0.7)
    assert len(zipf_vals) == 8
    assert all(1 <= v <= 5 for v in zipf_vals)


def test_generate_uses_existing_data_short_circuit(monkeypatch, tmp_path: Path):
    existing = {"customer": tmp_path / "customer.tbl"}
    existing["customer"].write_text("1|x|\n", encoding="utf-8")
    gen = TPCHSkewDataGenerator(scale_factor=0.01, output_dir=tmp_path, skew_config=_make_config())

    monkeypatch.setattr(gen, "_check_existing_data", lambda: True)
    monkeypatch.setattr(gen, "_collect_table_files", lambda: existing)
    out = gen.generate()
    assert out == existing


def test_generate_full_flow_calls_base_generator_and_apply(monkeypatch, tmp_path: Path):
    base_tables = {"customer": tmp_path / "base_customer.tbl"}
    base_tables["customer"].write_text("1|x|\n", encoding="utf-8")
    expected = {"customer": tmp_path / "customer.tbl"}

    class _FakeBaseGen:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def generate(self):
            return base_tables

    gen = TPCHSkewDataGenerator(scale_factor=0.01, output_dir=tmp_path, skew_config=_make_config())
    monkeypatch.setattr("benchbox.core.tpch_skew.generator.TPCHDataGenerator", _FakeBaseGen)
    monkeypatch.setattr(gen, "_check_existing_data", lambda: False)
    monkeypatch.setattr(gen, "_apply_skew_to_tables", lambda _tables: expected)

    out = gen.generate()
    assert out == expected


def test_apply_skew_to_tables_dispatches_transforms(monkeypatch, tmp_path: Path):
    gen = TPCHSkewDataGenerator(scale_factor=0.01, output_dir=tmp_path, skew_config=_make_config())
    called = []

    def _mark(name):
        def _inner(_src, dst):
            called.append(name)
            dst.write_text("ok\n", encoding="utf-8")

        return _inner

    monkeypatch.setattr(gen, "_transform_customer", _mark("customer"))
    monkeypatch.setattr(gen, "_transform_supplier", _mark("supplier"))
    monkeypatch.setattr(gen, "_transform_part", _mark("part"))
    monkeypatch.setattr(gen, "_transform_partsupp", _mark("partsupp"))
    monkeypatch.setattr(gen, "_transform_orders", _mark("orders"))
    monkeypatch.setattr(gen, "_transform_lineitem", _mark("lineitem"))

    base_tables = {}
    for table in ["customer", "supplier", "part", "partsupp", "orders", "lineitem", "nation", "region", "unknown"]:
        p = tmp_path / f"base_{table}.tbl"
        p.write_text("1|x|\n", encoding="utf-8")
        base_tables[table] = p

    out = gen._apply_skew_to_tables(base_tables)
    assert set(out) == set(base_tables)
    assert set(called) == {"customer", "supplier", "part", "partsupp", "orders", "lineitem"}
    assert (gen.output_dir / "nation.tbl").exists()
    assert (gen.output_dir / "region.tbl").exists()


def test_transform_methods_apply_configured_skews(monkeypatch, tmp_path: Path):
    gen = TPCHSkewDataGenerator(scale_factor=0.01, output_dir=tmp_path, skew_config=_make_config())
    monkeypatch.setattr(gen, "_generate_skewed_values", _small_skewed_values)

    captured: dict[str, list[list[str]]] = {}
    monkeypatch.setattr(gen, "_write_tbl_file", lambda rows, path: captured.__setitem__(path.name, rows))

    customer_rows = [["1", "name", "addr", "1", "ph", "1.0", "BUILDING", "c"]]
    supplier_rows = [["1", "n", "a", "1", "ph", "1.0", "c"]]
    part_rows = [["1", "n", "Brand#11", "b", "STANDARD", "1", "SM CASE", "1.0", "c"]]
    orders_rows = [["1", "1", "O", "1", "1993-01-01", "5-LOW", "cl", "0", "c"]]
    line_rows = [
        ["1", "1", "1", "1", "1", "1", "0", "0", "N", "O", "1993-01-01", "1993-01-02", "1993-01-03", "x", "AIR", "c"]
    ]

    monkeypatch.setattr(
        gen,
        "_read_tbl_file",
        lambda path: {
            "customer.tbl": [r[:] for r in customer_rows],
            "supplier.tbl": [r[:] for r in supplier_rows],
            "part.tbl": [r[:] for r in part_rows],
            "orders.tbl": [r[:] for r in orders_rows],
            "lineitem.tbl": [r[:] for r in line_rows],
        }[path.name],
    )
    monkeypatch.setattr(
        gen,
        "_apply_temporal_skew_to_dates",
        lambda rows, col, _sk: rows.__setitem__(0, rows[0][:col] + ["1998-12-31"] + rows[0][col + 1 :]),
    )

    gen._transform_customer(tmp_path / "customer.tbl", tmp_path / "customer_out.tbl")
    gen._transform_supplier(tmp_path / "supplier.tbl", tmp_path / "supplier_out.tbl")
    gen._transform_part(tmp_path / "part.tbl", tmp_path / "part_out.tbl")
    gen._transform_orders(tmp_path / "orders.tbl", tmp_path / "orders_out.tbl")
    gen._transform_lineitem(tmp_path / "lineitem.tbl", tmp_path / "lineitem_out.tbl")

    assert captured["customer_out.tbl"][0][3].isdigit()
    assert captured["supplier_out.tbl"][0][3].isdigit()
    assert captured["part_out.tbl"][0][2].startswith("Brand#")
    assert captured["orders_out.tbl"][0][1].isdigit()
    assert captured["orders_out.tbl"][0][4] == "1998-12-31"
    assert captured["lineitem_out.tbl"][0][1].isdigit()
    assert captured["lineitem_out.tbl"][0][14] in {"REG AIR", "AIR", "RAIL", "SHIP", "TRUCK", "MAIL", "FOB"}


def test_temporal_skew_and_statistics(tmp_path: Path):
    cfg = _make_config("exponential")
    gen = TPCHSkewDataGenerator(scale_factor=0.1, output_dir=tmp_path, skew_config=cfg)

    rows = [["1993-01-01"], ["1994-01-01"], ["1995-01-01"]]
    gen._apply_temporal_skew_to_dates(rows, 0, 0.5)
    assert all(len(r[0]) == 10 and r[0].count("-") == 2 for r in rows)

    stats = gen.get_skew_statistics()
    assert stats["scale_factor"] == 0.1
    assert stats["skew_factor"] == cfg.skew_factor
    assert "distribution" in stats and "config_summary" in stats


def test_transform_partsupp_copies_input(tmp_path: Path):
    gen = TPCHSkewDataGenerator(scale_factor=0.01, output_dir=tmp_path, skew_config=_make_config())
    src = tmp_path / "partsupp.tbl"
    dst = tmp_path / "partsupp_out.tbl"
    src.write_text("1|1|10|20.0|c\n", encoding="utf-8")
    gen._transform_partsupp(src, dst)
    assert dst.read_text(encoding="utf-8") == "1|1|10|20.0|c\n"


def test_get_skew_statistics_uses_distribution_methods(monkeypatch, tmp_path: Path):
    gen = TPCHSkewDataGenerator(scale_factor=0.01, output_dir=tmp_path, skew_config=_make_config())
    gen.distribution = SimpleNamespace(get_description=lambda: "mock-desc", get_skew_factor=lambda: 0.25)
    stats = gen.get_skew_statistics()
    assert stats["distribution"] == "mock-desc"
    assert stats["effective_skew"] == 0.25
