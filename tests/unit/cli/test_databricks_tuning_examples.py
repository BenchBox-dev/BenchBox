"""Regression tests for checked-in Databricks TPC tuning examples."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from benchbox.cli.config import ConfigManager
from benchbox.core.tuning.profile_validation import validate_tuning_template
from benchbox.core.tuning.workload_profiles import load_tpc_tuning_profile

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
DATABRICKS_TUNING_DIR = REPO_ROOT / "examples" / "tunings" / "databricks"


def _load_databricks_tuning(filename: str):
    return ConfigManager().load_unified_tuning_config(DATABRICKS_TUNING_DIR / filename, platform="databricks")


@pytest.mark.parametrize(("filename", "benchmark_id"), [("tpch_tuned.yaml", "tpch"), ("tpcds_tuned.yaml", "tpcds")])
def test_databricks_tpc_tuned_examples_consume_logical_tpc_profile(filename: str, benchmark_id: str) -> None:
    tuning_config = _load_databricks_tuning(filename)
    result = validate_tuning_template(
        profile=load_tpc_tuning_profile(),
        benchmark=benchmark_id,
        platform="databricks",
        tuning_config=tuning_config,
    )

    assert result.is_valid, [issue.to_dict() for issue in result.issues]
    assert result.mapped_count == result.required_count


@pytest.mark.parametrize("filename", ["tpch_tuned.yaml", "tpcds_tuned.yaml"])
def test_databricks_tpc_tuned_examples_do_not_use_per_table_z_ordering_columns(filename: str) -> None:
    raw_config = yaml.safe_load((DATABRICKS_TUNING_DIR / filename).read_text(encoding="utf-8"))

    for table_data in raw_config["table_tunings"].values():
        assert "z_ordering_columns" not in table_data
