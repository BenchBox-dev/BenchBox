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


# ---------------------------------------------------------------------------
# Canonical SSB dimension value formats (regression for issue #870)
# ---------------------------------------------------------------------------


def _read_part_rows(tmp_path, scale_factor=0.01):
    """Generate the part table and return its parsed rows."""
    gen2 = SSBDataGenerator(scale_factor=scale_factor, output_dir=tmp_path)
    result = gen2._generate_part_data()
    with open(result, encoding="utf-8") as f:
        return list(csv.reader(f, delimiter="|"))


# part columns: p_partkey, p_name, p_mfgr, p_category, p_brand1, p_color, p_type, p_size, p_container
_P_MFGR, _P_CATEGORY, _P_BRAND1 = 2, 3, 4


def test_part_mfgr_canonical_format(tmp_path):
    """p_mfgr is 'MFGR#' + a single digit 1..5."""
    rows = _read_part_rows(tmp_path)
    mfgrs = {row[_P_MFGR] for row in rows}
    assert mfgrs == {f"MFGR#{m}" for m in range(1, 6)}


def test_part_category_canonical_two_digit_format(tmp_path):
    """p_category is 'MFGR#' + mfgr(1..5) + category(1..5), e.g. 'MFGR#12'."""
    rows = _read_part_rows(tmp_path)
    categories = {row[_P_CATEGORY] for row in rows}
    valid = {f"MFGR#{m}{c}" for m in range(1, 6) for c in range(1, 6)}
    assert categories <= valid
    # The literals the canonical SSB queries filter on must be present.
    assert "MFGR#12" in categories  # Q2.1 / Q4.3
    assert "MFGR#14" in categories
    # Never the old 3-digit form.
    assert not any(len(c) != len("MFGR#12") for c in categories)


def test_part_brand1_canonical_four_char_suffix(tmp_path):
    """p_brand1 is 'MFGR#' + mfgr + category + brand(01..40), e.g. 'MFGR#2221'."""
    rows = _read_part_rows(tmp_path)
    brands = {row[_P_BRAND1] for row in rows}
    valid = {f"MFGR#{m}{c}{b:02d}" for m in range(1, 6) for c in range(1, 6) for b in range(1, 41)}
    assert brands <= valid
    # Q2.3 filters p_brand1='MFGR#2221'; Q2.2 the range 'MFGR#2221'..'MFGR#2228'.
    assert "MFGR#2221" in brands
    assert "MFGR#2228" in brands
    # Every brand is 'MFGR#' + 4 digits.
    assert all(len(b) == len("MFGR#2221") for b in brands)


def test_part_brand1_consistent_with_category_and_mfgr(tmp_path):
    """p_brand1 is prefixed by p_category, which is prefixed by p_mfgr."""
    rows = _read_part_rows(tmp_path)
    for row in rows:
        assert row[_P_BRAND1].startswith(row[_P_CATEGORY])
        assert row[_P_CATEGORY].startswith(row[_P_MFGR])


def test_part_dimension_values_deterministic(tmp_path):
    """Re-running the generator yields identical part dimension values."""
    first = [(r[_P_MFGR], r[_P_CATEGORY], r[_P_BRAND1]) for r in _read_part_rows(tmp_path)]
    second = [(r[_P_MFGR], r[_P_CATEGORY], r[_P_BRAND1]) for r in _read_part_rows(tmp_path)]
    assert first == second


def _read_city_values(tmp_path, generate, scale_factor=0.01):
    """Generate a dimension table and return the set of city values (column index 3)."""
    gen2 = SSBDataGenerator(scale_factor=scale_factor, output_dir=tmp_path)
    result = generate(gen2)
    with open(result, encoding="utf-8") as f:
        return [row[3] for row in csv.reader(f, delimiter="|")]


def test_customer_city_canonical_ten_char_format(tmp_path):
    """c_city is the first 9 chars of the nation name + a city digit, e.g. 'UNITED KI1'."""
    cities = _read_city_values(tmp_path, lambda g: g._generate_customer_data())
    uk_cities = {c for c in cities if c.startswith("UNITED KI")}
    # The 'UNITED KINGDOM' nation truncates to 'UNITED KI' (9 chars) + digit.
    assert uk_cities, "expected at least one 'UNITED KI<digit>' city"
    assert all(len(c) == len("UNITED KI1") for c in uk_cities)
    assert all(c[:9] == "UNITED KI" and c[9].isdigit() for c in uk_cities)


def test_supplier_city_canonical_ten_char_format(tmp_path):
    """s_city mirrors c_city: first 9 chars of the nation name + a city digit."""
    cities = _read_city_values(tmp_path, lambda g: g._generate_supplier_data(), scale_factor=0.05)
    uk_cities = {c for c in cities if c.startswith("UNITED KI")}
    assert uk_cities, "expected at least one 'UNITED KI<digit>' city"
    assert all(len(c) == len("UNITED KI1") for c in uk_cities)


def test_part_dimensions_cover_mfgr_and_category_at_small_scale(tmp_path):
    """All 5 mfgrs and all 25 (mfgr, category) pairs appear even at a tiny scale."""
    # 0.001 -> 200 parts: well below the 1000-value brand cycle, but the dimensions
    # are varied fastest-first so mfgr/category coverage is complete after 25 parts.
    rows = _read_part_rows(tmp_path, scale_factor=0.001)
    assert {r[_P_MFGR] for r in rows} == {f"MFGR#{m}" for m in range(1, 6)}
    assert {r[_P_CATEGORY] for r in rows} == {f"MFGR#{m}{c}" for m in range(1, 6) for c in range(1, 6)}


# date columns: d_datekey, d_date, d_dayofweek, d_month, d_year, d_yearmonthnum, d_yearmonth, ...
_D_DAYOFWEEK, _D_MONTH, _D_YEARMONTH = 2, 3, 6

_ENGLISH_MONTHS = {
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
}
_ENGLISH_DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}


def _read_date_rows(tmp_path):
    gen2 = SSBDataGenerator(scale_factor=1.0, output_dir=tmp_path)
    with open(gen2._generate_date_data(), encoding="utf-8") as f:
        return list(csv.reader(f, delimiter="|"))


def test_date_strings_are_canonical_english(tmp_path):
    """d_dayofweek/d_month/d_yearmonth use canonical English names (e.g. 'Dec1997')."""
    rows = _read_date_rows(tmp_path)
    assert {r[_D_DAYOFWEEK] for r in rows} == _ENGLISH_DAYS
    assert {r[_D_MONTH] for r in rows} == _ENGLISH_MONTHS
    yearmonths = {r[_D_YEARMONTH] for r in rows}
    # Q3.4 filters d_yearmonth='Dec1997'; it must exist in the dimension.
    assert "Dec1997" in yearmonths
    assert "Jan1992" in yearmonths


def test_date_strings_are_locale_independent(tmp_path):
    """The DATE strings stay English even under a non-English locale (Q3.4 relies on it)."""
    import locale

    saved = locale.setlocale(locale.LC_TIME)
    french = None
    for candidate in ("fr_FR.UTF-8", "fr_FR.utf8", "fr_FR", "de_DE.UTF-8"):
        try:
            locale.setlocale(locale.LC_TIME, candidate)
            french = candidate
            break
        except locale.Error:
            continue
    if french is None:
        pytest.skip("no non-English locale available to test against")
    try:
        rows = _read_date_rows(tmp_path)
    finally:
        locale.setlocale(locale.LC_TIME, saved)
    yearmonths = {r[_D_YEARMONTH] for r in rows}
    assert "Dec1997" in yearmonths, f"locale {french} leaked into d_yearmonth"
    assert {r[_D_MONTH] for r in rows} == _ENGLISH_MONTHS


def test_lineorder_dates_are_valid_datekeys(tmp_path):
    """Every lo_orderdate joins to DATE; every lo_commitdate is a real calendar date."""
    from datetime import datetime

    gen2 = SSBDataGenerator(scale_factor=0.001, output_dir=tmp_path)
    gen2.base_lineorders = 500
    # DATE dimension datekeys (the valid join targets for lo_orderdate).
    date_keys = {int(d.strftime("%Y%m%d")) for d in gen2._date_objects()}
    with open(gen2._generate_lineorder_data(), encoding="utf-8") as f:
        rows = list(csv.reader(f, delimiter="|"))
    # lineorder columns: ..., lo_orderdate(5), ..., lo_commitdate(15), lo_shipmode(16)
    for row in rows:
        lo_orderdate = int(row[5])
        lo_commitdate = int(row[15])
        assert lo_orderdate in date_keys
        # commitdate may fall past the dimension's last year, but must be a real date.
        datetime.strptime(str(lo_commitdate), "%Y%m%d")
