from __future__ import annotations

from pathlib import Path

import pytest

from benchbox.cli.config import ConfigManager
from benchbox.core.tuning.interface import TuningType

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[4]
TEMPLATE_DIRS = (
    REPO_ROOT / "examples" / "tunings" / "duckdb",
    REPO_ROOT / "benchbox" / "core" / "tuning" / "templates" / "duckdb",
)
TUNED_TEMPLATES = sorted(path for directory in TEMPLATE_DIRS for path in directory.glob("*_tuned.yaml"))


def _template_id(path: Path) -> str:
    return f"{'examples' if 'examples' in path.parts else 'packaged'}/{path.name}"


def _load(path: Path):
    return ConfigManager().load_unified_tuning_config(path, platform="duckdb")


def test_every_duckdb_tuned_template_is_discovered() -> None:
    for directory in TEMPLATE_DIRS:
        assert sorted(directory.glob("*_tuned.yaml")), directory


@pytest.mark.parametrize("template", TUNED_TEMPLATES, ids=_template_id)
def test_duckdb_tuned_template_requests_no_partitioning(template: Path) -> None:
    config = _load(template)

    partitioned = {
        name: [column.name for column in tuning.get_columns_by_type(TuningType.PARTITIONING)]
        for name, tuning in config.table_tunings.items()
        if tuning.get_columns_by_type(TuningType.PARTITIONING)
    }

    assert partitioned == {}


@pytest.mark.parametrize("template", TUNED_TEMPLATES, ids=_template_id)
def test_duckdb_tuned_template_disables_check_constraints(template: Path) -> None:
    assert _load(template).check_constraints.enabled is False
