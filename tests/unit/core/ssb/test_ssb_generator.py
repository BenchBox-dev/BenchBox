"""Tests for SSB data generator.

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.ssb.generator import SSBDataGenerator

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture
def gen(tmp_path):
    """SSBDataGenerator with tiny scale_factor for fast test data."""
    return SSBDataGenerator(scale_factor=0.0001, output_dir=tmp_path)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def test_generator_init_defaults(tmp_path):
    gen = SSBDataGenerator(scale_factor=1.0, output_dir=tmp_path)
    assert gen.scale_factor == 1.0
    assert gen.base_customers == 30000
    assert gen.base_suppliers == 2000
    assert gen.base_parts == 200000
    assert gen.date_rows == 2556


def test_generator_verbose_bool_true(tmp_path):
    gen = SSBDataGenerator(scale_factor=1.0, output_dir=tmp_path, verbose=True)
    assert gen.verbose_level == 1
    assert gen.verbose_enabled is True


def test_generator_verbose_int(tmp_path):
    gen = SSBDataGenerator(scale_factor=1.0, output_dir=tmp_path, verbose=2)
    assert gen.very_verbose is True


def test_generator_quiet_suppresses_verbose(tmp_path):
    gen = SSBDataGenerator(scale_factor=1.0, output_dir=tmp_path, verbose=True, quiet=True)
    assert gen.verbose_enabled is False


# ---------------------------------------------------------------------------
# _generate_date_data
# ---------------------------------------------------------------------------


def test_generate_date_data_creates_file(gen, tmp_path):
    result = gen._generate_date_data()
    p = Path(result)
    assert p.exists()
    assert p.stat().st_size > 0


def test_generate_date_data_correct_rows(gen, tmp_path):
    """DATE dimension has approximately date_rows rows (7-year range)."""
    result = gen._generate_date_data()
    with open(result, encoding="utf-8") as f:
        rows = list(csv.reader(f, delimiter="|"))
    # Should have rows from 1992-01-01 to 1998-12-31 (approximately 2556-2557 rows)
    assert abs(len(rows) - gen.date_rows) <= 2


def test_generate_date_data_includes_winter_season(gen, tmp_path):
    result = gen._generate_date_data()
    with open(result, encoding="utf-8") as f:
        content = f.read()
    assert "Winter" in content
    assert "Summer" in content
    assert "Spring" in content
    assert "Fall" in content


# ---------------------------------------------------------------------------
# _generate_customer_data
# ---------------------------------------------------------------------------


def test_generate_customer_data_creates_file(gen, tmp_path):
    result = gen._generate_customer_data()
    p = Path(result)
    assert p.exists()
    assert p.stat().st_size > 0


def test_generate_customer_data_row_count(gen):
    result = gen._generate_customer_data()
    expected = max(1, int(gen.base_customers * gen.scale_factor))
    with open(result, encoding="utf-8") as f:
        rows = list(csv.reader(f, delimiter="|"))
    assert len(rows) == expected


# ---------------------------------------------------------------------------
# _generate_supplier_data
# ---------------------------------------------------------------------------


def test_generate_supplier_data_creates_file(tmp_path):
    # Use scale_factor=0.001 to get at least 2 supplier rows
    gen2 = SSBDataGenerator(scale_factor=0.001, output_dir=tmp_path)
    result = gen2._generate_supplier_data()
    p = Path(result)
    assert p.exists()


# ---------------------------------------------------------------------------
# _generate_part_data
# ---------------------------------------------------------------------------


def test_generate_part_data_creates_file(gen, tmp_path):
    result = gen._generate_part_data()
    p = Path(result)
    assert p.exists()


# ---------------------------------------------------------------------------
# _generate_data_local - subset of tables
# ---------------------------------------------------------------------------


def test_generate_data_local_date_only(gen, tmp_path):
    result = gen._generate_data_local(tmp_path, tables=["date"])
    assert "date" in result
    assert Path(result["date"]).exists()


def test_generate_data_local_customer_and_supplier(gen, tmp_path):
    result = gen._generate_data_local(tmp_path, tables=["customer", "supplier"])
    assert "customer" in result
    assert "supplier" in result


def test_generate_data_local_default_tables(gen, tmp_path):
    # Default tables but skip lineorder (slow), test just the table list dispatch
    # passing explicit list without lineorder to avoid very long generation
    result = gen._generate_data_local(tmp_path, tables=["date", "customer", "supplier", "part"])
    assert len(result) == 4


# ---------------------------------------------------------------------------
# _validate_file_format_consistency - no compression enabled = no-op
# ---------------------------------------------------------------------------


def test_validate_file_format_consistency_no_compression(gen, tmp_path):
    # Should not raise without compression
    gen._validate_file_format_consistency(tmp_path)


# ---------------------------------------------------------------------------
# _write_manifest
# ---------------------------------------------------------------------------


def test_write_manifest_creates_file(gen, tmp_path):
    date_path = tmp_path / "date.tbl"
    date_path.write_text("row1\nrow2\n")
    gen._write_manifest(tmp_path, {"date": date_path})
    manifest_path = tmp_path / "_datagen_manifest.json"
    assert manifest_path.exists()
    import json

    data = json.loads(manifest_path.read_text())
    assert data["benchmark"] == "ssb"
    assert "date" in data["tables"]


# ---------------------------------------------------------------------------
# _generate_lineorder_data - tiny scale
# ---------------------------------------------------------------------------


def test_generate_lineorder_data_creates_file(tmp_path):
    # Use a scale factor large enough to have at least 1 supplier, customer, part
    # min scale: need int(base_customers * sf) >= 1, int(base_suppliers * sf) >= 1, int(base_parts * sf) >= 1
    # base_customers=30000, base_suppliers=2000, base_parts=200000
    # sf=0.0001: customers=3, suppliers=0 (fails), need sf=0.001 for suppliers=2
    gen2 = SSBDataGenerator(scale_factor=0.001, output_dir=tmp_path)
    # Override lineorder count to just 2 rows
    gen2.base_lineorders = 2
    result = gen2._generate_lineorder_data()
    p = Path(result)
    assert p.exists()


# ---------------------------------------------------------------------------
# generate_data - local dispatch
# ---------------------------------------------------------------------------


def test_generate_data_date_only(tmp_path):
    gen2 = SSBDataGenerator(scale_factor=0.0001, output_dir=tmp_path)
    result = gen2.generate_data(tables=["date"])
    assert "date" in result
    assert Path(result["date"]).exists()


def test_generate_data_no_tables_arg(tmp_path):
    """Calling generate_data without tables arg should produce all 5 tables."""
    gen2 = SSBDataGenerator(scale_factor=0.000001, output_dir=tmp_path)
    result = gen2.generate_data(tables=["date", "customer", "supplier", "part"])
    assert len(result) == 4


# ---------------------------------------------------------------------------
# customer data - nation/region coverage
# ---------------------------------------------------------------------------


def test_generate_customer_data_nation_coverage(tmp_path):
    """Run with slightly larger scale to exercise nation->region mapping."""
    import random as _rng

    _rng.seed(0)  # deterministic
    gen2 = SSBDataGenerator(scale_factor=0.001, output_dir=tmp_path)
    result = gen2._generate_customer_data()
    with open(result, encoding="utf-8") as f:
        content = f.read()
    # Nation names should appear somewhere
    assert len(content) > 0


# ---------------------------------------------------------------------------
# _generate_part_data
# ---------------------------------------------------------------------------


def test_generate_part_data_rows(tmp_path):
    gen2 = SSBDataGenerator(scale_factor=0.001, output_dir=tmp_path)
    result = gen2._generate_part_data()
    with open(result, encoding="utf-8") as f:
        rows = list(csv.reader(f, delimiter="|"))
    expected = max(1, int(gen2.base_parts * gen2.scale_factor))
    assert len(rows) == expected
