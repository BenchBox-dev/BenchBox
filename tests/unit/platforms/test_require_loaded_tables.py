"""A run stops before measuring when a benchmark's query tables were not loaded."""

from types import SimpleNamespace

import pytest

from benchbox.platforms.base.adapter import require_loaded_tables

pytestmark = [pytest.mark.unit, pytest.mark.fast]

OBT = SimpleNamespace(REQUIRED_LOADED_TABLES=("tpcds_sales_returns_obt",))


def test_passes_when_required_table_has_rows():
    require_loaded_tables(OBT, {"TPCDS_SALES_RETURNS_OBT": 2_880_404})


def test_fails_when_the_source_tables_were_loaded_instead():
    with pytest.raises(RuntimeError, match="tpcds_sales_returns_obt was not loaded"):
        require_loaded_tables(OBT, {"CALL_CENTER": 6, "STORE_SALES": 2_880_404})


def test_fails_when_required_table_is_empty():
    with pytest.raises(RuntimeError, match="has 0 rows"):
        require_loaded_tables(OBT, {"tpcds_sales_returns_obt": 0})


def test_benchmarks_without_requirements_are_not_checked():
    require_loaded_tables(SimpleNamespace(), {})
    require_loaded_tables(object(), None)
