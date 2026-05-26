"""Regression tests for checked-in Databricks TPC tuning examples."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from benchbox.cli.config import ConfigManager

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
DATABRICKS_TUNING_DIR = REPO_ROOT / "examples" / "tunings" / "databricks"

EXPECTED_CLUSTERING_COLUMNS = {
    "tpch_tuned.yaml": {
        "LINEITEM": {"L_SUPPKEY": ("INTEGER", 3)},
        "ORDERS": {"O_CUSTKEY": ("INTEGER", 2)},
        "PART": {"P_TYPE": ("VARCHAR", 2), "P_SIZE": ("INTEGER", 3)},
        "SUPPLIER": {"S_NATIONKEY": ("INTEGER", 2)},
        "CUSTOMER": {"C_NATIONKEY": ("INTEGER", 2)},
    },
    "tpcds_tuned.yaml": {
        "STORE_SALES": {
            "SS_STORE_SK": ("INTEGER", 3),
            "SS_PROMO_SK": ("INTEGER", 4),
            "SS_TICKET_NUMBER": ("INTEGER", 5),
        },
        "STORE_RETURNS": {
            "SR_CUSTOMER_SK": ("INTEGER", 2),
            "SR_STORE_SK": ("INTEGER", 3),
            "SR_TICKET_NUMBER": ("INTEGER", 4),
        },
        "CATALOG_SALES": {"CS_SHIP_MODE_SK": ("INTEGER", 2)},
        "WEB_SALES": {
            "WS_WEB_PAGE_SK": ("INTEGER", 2),
            "WS_WEB_SITE_SK": ("INTEGER", 3),
            "WS_SHIP_MODE_SK": ("INTEGER", 4),
        },
        "DATE_DIM": {"D_YEAR": ("INTEGER", 2), "D_MOY": ("INTEGER", 3)},
        "ITEM": {"I_CATEGORY": ("VARCHAR", 2), "I_CLASS": ("VARCHAR", 3)},
        "CUSTOMER": {
            "C_CURRENT_ADDR_SK": ("INTEGER", 2),
            "C_CURRENT_CDEMO_SK": ("INTEGER", 3),
        },
    },
}

LOW_EVIDENCE_COLUMNS = {
    "tpcds_tuned.yaml": {
        "WEB_RETURNS": {"WR_WEB_PAGE_SK"},
        "CATALOG_RETURNS": {"CR_SHIP_MODE_SK"},
    },
}


def _load_databricks_tuning(filename: str):
    return ConfigManager().load_unified_tuning_config(DATABRICKS_TUNING_DIR / filename, platform="databricks")


@pytest.mark.parametrize(("filename", "expected_by_table"), EXPECTED_CLUSTERING_COLUMNS.items())
def test_databricks_tpc_tuned_examples_keep_query_evidenced_clustering_columns(
    filename: str,
    expected_by_table: dict[str, dict[str, tuple[str, int]]],
) -> None:
    tuning_config = _load_databricks_tuning(filename)

    for table_name, expected_columns in expected_by_table.items():
        clustering_columns = {
            column.name: (column.type, column.order)
            for column in tuning_config.table_tunings[table_name].clustering or []
        }
        assert expected_columns.items() <= clustering_columns.items()


def test_databricks_tpcds_tuned_example_excludes_low_evidence_scratchpad_candidates() -> None:
    tuning_config = _load_databricks_tuning("tpcds_tuned.yaml")

    for table_name, dropped_columns in LOW_EVIDENCE_COLUMNS["tpcds_tuned.yaml"].items():
        configured_columns = tuning_config.table_tunings[table_name].get_all_columns()
        assert configured_columns.isdisjoint(dropped_columns)


@pytest.mark.parametrize("filename", EXPECTED_CLUSTERING_COLUMNS)
def test_databricks_tpc_tuned_examples_do_not_use_per_table_z_ordering_columns(filename: str) -> None:
    raw_config = yaml.safe_load((DATABRICKS_TUNING_DIR / filename).read_text(encoding="utf-8"))

    for table_data in raw_config["table_tunings"].values():
        assert "z_ordering_columns" not in table_data
