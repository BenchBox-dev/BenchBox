"""Fast tests for the UAT disk-budget estimator."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.uat.config import validate_config
from tests.uat.preflight_budget import (
    DiskBudget,
    DiskRootFreeSpace,
    MemorySnapshot,
    check_disk_headroom,
    check_memory_headroom,
    estimate_largest_scale_peak_disk,
    estimate_peak_disk,
    format_disk_budget,
    format_disk_headroom_failure,
    format_memory_headroom_failure,
    read_memory_snapshot,
)

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


def test_estimate_largest_scale_peak_disk_uses_largest_configured_scale(tmp_path: Path):
    table = tmp_path / "disk_budget.tsv"
    table.write_text(
        "platform\tbenchmark\tscale_factor\tpeak_datagen_gib\tpeak_database_gib\ttransient_growth_gib\n"
        "duckdb\ttpch\t0.01\t1.0\t2.0\t0.5\n"
        "duckdb\ttpch\t1\t10.0\t20.0\t5.0\n"
        "sqlite\ttpch\t1\t12.0\t30.0\t7.0\n",
        encoding="utf-8",
    )
    cfg = validate_config(
        {
            "name": "budget-smoke",
            "platforms": {"include": ["duckdb", "sqlite"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01, 1]},
        }
    )

    budget = estimate_largest_scale_peak_disk(cfg, table_path=table)

    assert budget.cells == 2
    assert budget.est_steady_gib == pytest.approx(12.0 + 20.0 + 30.0)
    assert budget.est_peak_gib == pytest.approx(12.0 + 20.0 + 30.0 + 5.0 + 7.0)
    assert budget.unknown_cells == ()


def test_disk_headroom_gate_reports_short_root(tmp_path: Path):
    budget = DiskBudget(cells=1, est_peak_gib=10.0, est_steady_gib=8.0, unknown_cells=())
    # Render the expectation from the same Path the formatter receives: str(Path) uses
    # the platform separator, so a hardcoded "/tmp" fails on Windows ("\tmp") while
    # asserting nothing extra. Mirrors the idiom already used in test_preflight.py.
    tmp_root = Path("/tmp")
    roots = (
        DiskRootFreeSpace("tmp", tmp_root, 4.0),
        DiskRootFreeSpace("output", tmp_path, 20.0),
    )

    check = check_disk_headroom(budget, roots, min_free_gib=5.0)

    assert check.required_gib == pytest.approx(10.0)
    assert len(check.shortfalls) == 1
    assert check.shortfalls[0].label == "tmp"
    assert f"tmp {tmp_root}: 4.0 GiB free < 10.0 GiB required" in format_disk_headroom_failure(check)


def test_read_memory_snapshot_reports_a_measured_reading_on_this_host():
    """psutil is a hard project dependency (pyproject.toml); on any dev/CI
    host this reads a real, non-negative free-memory figure."""
    snapshot = read_memory_snapshot()
    assert snapshot.free_gib is None or snapshot.free_gib >= 0.0
    assert snapshot.swap_used_percent is None or snapshot.swap_used_percent >= 0.0


def test_read_memory_snapshot_degrades_safely_when_psutil_unavailable(monkeypatch):
    """Must_preserve: an unmeasurable host reports None, never a fabricated 0.0
    or a large number -- the gate must not silently pass OR hard-fail here."""
    monkeypatch.setitem(sys.modules, "psutil", None)
    snapshot = read_memory_snapshot()
    assert snapshot == MemorySnapshot(free_gib=None, swap_used_percent=None)


def test_check_memory_headroom_shortfall_when_measured_below_floor():
    snapshot = MemorySnapshot(free_gib=1.0, swap_used_percent=50.0)
    check = check_memory_headroom(snapshot, min_free_gib=2.0)
    assert check.shortfall is True
    assert check.required_gib == pytest.approx(2.0)


def test_check_memory_headroom_no_shortfall_when_measured_above_floor():
    snapshot = MemorySnapshot(free_gib=4.0, swap_used_percent=0.0)
    check = check_memory_headroom(snapshot, min_free_gib=2.0)
    assert check.shortfall is False


def test_check_memory_headroom_unmeasured_is_never_a_shortfall():
    """Must_preserve: an unmeasured reading (None) never gates -- "unknown" is
    not "failing", the same as it must not silently be "healthy" either."""
    snapshot = MemorySnapshot(free_gib=None, swap_used_percent=None)
    check = check_memory_headroom(snapshot, min_free_gib=100.0)
    assert check.shortfall is False


def test_check_memory_headroom_zero_floor_never_shortfalls():
    """0-disables convention: min_free_gib=0 mirrors free_space_min_gib=0."""
    snapshot = MemorySnapshot(free_gib=0.01, swap_used_percent=99.0)
    check = check_memory_headroom(snapshot, min_free_gib=0.0)
    assert check.shortfall is False


def test_format_memory_headroom_failure_includes_swap_note():
    check = check_memory_headroom(MemorySnapshot(free_gib=0.07, swap_used_percent=88.0), min_free_gib=2.0)
    message = format_memory_headroom_failure(check)
    assert "0.07 GiB free" in message
    assert "2.00 GiB required" in message
    assert "swap 88.0% used" in message


def test_format_memory_headroom_failure_omits_swap_note_when_unmeasured():
    check = check_memory_headroom(MemorySnapshot(free_gib=0.07, swap_used_percent=None), min_free_gib=2.0)
    assert "swap" not in format_memory_headroom_failure(check)
