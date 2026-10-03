from types import SimpleNamespace

import pytest

from benchbox.core.loaded_tables import require_loaded_tables

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


def test_public_obt_wrapper_exposes_the_contract():

    from benchbox.tpcds_obt import TPCDSOBT

    assert TPCDSOBT.REQUIRED_LOADED_TABLES == ("tpcds_sales_returns_obt",)
    assert TPCDSOBT.GENERATES_OWN_OUTPUT is True
    with pytest.raises(RuntimeError, match="was not loaded"):
        require_loaded_tables(TPCDSOBT.__new__(TPCDSOBT), {"CALL_CENTER": 6})


def test_manifest_reuse_rejects_the_source_manifest_for_own_output_benchmarks():
    from benchbox.core.runner.runner import _resolve_manifest_allowed_names
    from benchbox.core.schemas import BenchmarkConfig

    obt = SimpleNamespace(GENERATES_OWN_OUTPUT=True, get_data_source_benchmark=lambda: "tpcds")
    sharer = SimpleNamespace(get_data_source_benchmark=lambda: "tpch")
    config = BenchmarkConfig(name="tpcds_obt", display_name="OBT", scale_factor=1.0)

    assert _resolve_manifest_allowed_names(obt, config) == {"tpcds_obt"}
    assert "tpch" in _resolve_manifest_allowed_names(sharer, config)
