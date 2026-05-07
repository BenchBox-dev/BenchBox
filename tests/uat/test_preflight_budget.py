"""Fast tests for the UAT disk-budget estimator."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.uat.config import validate_config
from tests.uat.preflight_budget import estimate_peak_disk, format_disk_budget

pytestmark = pytest.mark.fast


def test_estimate_peak_disk_counts_datagen_once_and_reports_unknown(tmp_path: Path):
    table = tmp_path / "disk_budget.tsv"
    table.write_text(
        "platform\tbenchmark\tscale_factor\tpeak_datagen_gib\tpeak_database_gib\ttransient_growth_gib\n"
        "duckdb\ttpch\t0.01\t1.0\t2.0\t0.5\n"
        "sqlite\ttpch\t0.01\t1.5\t3.0\t0.25\n",
        encoding="utf-8",
    )
    cfg = validate_config(
        {
            "name": "budget-smoke",
            "platforms": {"include": ["duckdb", "sqlite", "datafusion"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )

    budget = estimate_peak_disk(cfg, table_path=table)

    assert budget.cells == 3
    assert budget.est_steady_gib == pytest.approx(1.5 + 2.0 + 3.0)
    assert budget.est_peak_gib == pytest.approx(1.5 + 2.0 + 3.0 + 0.5 + 0.25)
    assert [cell.key for cell in budget.unknown_cells] == ["datafusion|tpch|0.01"]


def test_format_disk_budget_includes_operator_fields(tmp_path: Path):
    table = tmp_path / "disk_budget.tsv"
    table.write_text(
        "platform\tbenchmark\tscale_factor\tpeak_datagen_gib\tpeak_database_gib\ttransient_growth_gib\n"
        "duckdb\ttpch\t0.01\t1.0\t2.0\t0.5\n",
        encoding="utf-8",
    )
    cfg = validate_config(
        {
            "name": "budget-smoke",
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )

    line = format_disk_budget(estimate_peak_disk(cfg, table_path=table))

    assert line.startswith("Disk budget estimate: ")
    assert "GiB peak" in line
    assert "cells=1" in line
    assert "unknown=0" in line
