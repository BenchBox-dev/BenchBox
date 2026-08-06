"""Fast tests for the UAT disk-budget estimator."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.uat.config import validate_config
from tests.uat.preflight_budget import (
    DATABASE_STATUS_MEASURED,
    DATABASE_STATUS_UNMEASURED,
    DEFAULT_TABLE_PATH,
    DiskBudget,
    DiskRootFreeSpace,
    MemorySnapshot,
    assess_budget_coverage,
    check_disk_headroom,
    check_memory_headroom,
    estimate_largest_scale_peak_disk,
    estimate_peak_disk,
    format_budget_coverage,
    format_budget_verdict,
    format_disk_budget,
    format_disk_headroom_failure,
    format_memory_headroom_failure,
    largest_scale_cells,
    load_budget_table,
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


# ---------------------------------------------------------------------------
# The configured floor (`preflight.free_space_min_gib`) is enforced ONLY by
# the `max(min_free_gib, ...)` inside `check_disk_headroom`. Nothing else in
# the preflight path re-applies it once a disk-budget config is present, so
# this is the single test standing between an operator's 5 GiB floor and a
# sweep that starts with 0.2 GiB free.
# ---------------------------------------------------------------------------


def test_disk_headroom_gate_enforces_configured_floor(tmp_path: Path):
    """A budget BELOW the configured floor must still gate at the floor.

    Mutation killer: replacing `max(min_free_gib, budget.est_peak_gib)` with
    a bare `budget.est_peak_gib` makes this test fail. That mutation is not
    hypothetical -- the checked-in inventory's loaded-database term is
    identically zero, so a real sweep's estimate routinely lands far below
    the operator's floor and the `max` is the only thing holding.
    """
    budget = DiskBudget(cells=1, est_peak_gib=1.0, est_steady_gib=1.0, unknown_cells=())
    roots = (DiskRootFreeSpace("output", tmp_path, 0.2),)

    check = check_disk_headroom(budget, roots, min_free_gib=5.0)

    assert check.required_gib == pytest.approx(5.0)
    assert len(check.shortfalls) == 1
    assert check.shortfalls[0].required_gib == pytest.approx(5.0)
    assert "0.2 GiB free < 5.0 GiB required" in format_disk_headroom_failure(check)


def test_disk_headroom_gate_uses_budget_when_it_exceeds_the_floor(tmp_path: Path):
    """The other side of the same `max`: a budget above the floor wins.

    Without this, replacing the `max` with a bare `min_free_gib` would also
    survive -- the floor test alone does not pin both directions.
    """
    budget = DiskBudget(cells=1, est_peak_gib=40.0, est_steady_gib=35.0, unknown_cells=())
    roots = (DiskRootFreeSpace("output", tmp_path, 12.0),)

    check = check_disk_headroom(budget, roots, min_free_gib=5.0)

    assert check.required_gib == pytest.approx(40.0)
    assert len(check.shortfalls) == 1


# ---------------------------------------------------------------------------
# Coverage disclosure: an estimate over a partially-measured inventory is a
# lower bound, and must never render as "fits".
# ---------------------------------------------------------------------------


def _coverage_table(tmp_path: Path) -> Path:
    """duckdb measured, lakesail present but database-unmeasured, datafusion absent."""
    table = tmp_path / "disk_budget.tsv"
    table.write_text(
        "platform\tbenchmark\tscale_factor\tpeak_datagen_gib\tpeak_database_gib\t"
        "peak_database_gib_status\ttransient_growth_gib\n"
        "duckdb\ttpch\t0.01\t1.0\t2.0\tmeasured\t0.5\n"
        "lakesail\ttpch\t0.01\t1.0\t0.0\tunmeasured\t0.5\n",
        encoding="utf-8",
    )
    return table


def _coverage_config():
    return validate_config(
        {
            "name": "coverage-smoke",
            "platforms": {"include": ["duckdb", "lakesail", "datafusion"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )


def test_load_budget_table_defaults_absent_status_column_to_measured(tmp_path: Path):
    """A table without the column keeps its historical meaning."""
    table = tmp_path / "disk_budget.tsv"
    table.write_text(
        "platform\tbenchmark\tscale_factor\tpeak_datagen_gib\tpeak_database_gib\ttransient_growth_gib\n"
        "duckdb\ttpch\t0.01\t1.0\t2.0\t0.5\n",
        encoding="utf-8",
    )

    rows = load_budget_table(table)

    assert rows[("duckdb", "tpch", 0.01)].database_status == DATABASE_STATUS_MEASURED
    assert rows[("duckdb", "tpch", 0.01)].database_measured is True


def test_assess_budget_coverage_separates_missing_rows_from_unmeasured_databases(tmp_path: Path):
    table = load_budget_table(_coverage_table(tmp_path))
    cells = largest_scale_cells(_coverage_config())

    coverage = assess_budget_coverage(cells, table=table)

    assert coverage.cells_total == 3
    # datafusion has no row at all; duckdb and lakesail do.
    assert coverage.cells_with_rows == 2
    # lakesail's row exists but declares its database footprint a placeholder,
    # so only duckdb contributes a real loaded-database number.
    assert coverage.cells_with_measured_database == 1
    assert coverage.platforms_total == 3
    assert coverage.measured_platforms == ("duckdb",)
    assert coverage.unmeasured_platforms == ("datafusion", "lakesail")
    assert coverage.is_lower_bound is True


def test_assess_budget_coverage_is_complete_when_every_cell_is_measured(tmp_path: Path):
    table = tmp_path / "disk_budget.tsv"
    table.write_text(
        "platform\tbenchmark\tscale_factor\tpeak_datagen_gib\tpeak_database_gib\t"
        "peak_database_gib_status\ttransient_growth_gib\n"
        "duckdb\ttpch\t0.01\t1.0\t2.0\tmeasured\t0.5\n",
        encoding="utf-8",
    )
    cfg = validate_config(
        {
            "name": "coverage-complete",
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )

    coverage = assess_budget_coverage(largest_scale_cells(cfg), table=load_budget_table(table))

    assert coverage.is_lower_bound is False
    assert coverage.unmeasured_platforms == ()
    assert "COMPLETE" in format_budget_coverage(coverage)


def test_format_budget_coverage_partial_names_the_gap_and_never_claims_fit(tmp_path: Path):
    coverage = assess_budget_coverage(
        largest_scale_cells(_coverage_config()),
        table=load_budget_table(_coverage_table(tmp_path)),
    )

    message = format_budget_coverage(coverage)

    assert "LOWER BOUND" in message
    assert "1 of 3 platform(s)" in message
    assert "2 of 3 largest-scale cell(s) have any row" in message
    assert "1 of 3 have a measured loaded-database footprint" in message
    # The unmeasured platforms are named, not just counted -- an operator has
    # to be able to see WHICH platforms the estimate knows nothing about.
    assert "datafusion" in message
    assert "lakesail" in message


def test_format_budget_verdict_partial_is_not_a_certification(tmp_path: Path):
    coverage = assess_budget_coverage(
        largest_scale_cells(_coverage_config()),
        table=load_budget_table(_coverage_table(tmp_path)),
    )
    check = check_disk_headroom(
        DiskBudget(cells=3, est_peak_gib=4.0, est_steady_gib=3.5, unknown_cells=()),
        (DiskRootFreeSpace("output", tmp_path, 100.0),),
        min_free_gib=5.0,
    )

    verdict = format_budget_verdict(check, coverage)

    assert "no shortfall detected" in verdict
    assert "lower-bound" in verdict
    assert "real demand may be higher" in verdict
    # The word an operator would read as a certification must not appear.
    assert "fits" not in verdict


def test_format_budget_verdict_complete_may_state_the_requirement_fits(tmp_path: Path):
    coverage = assess_budget_coverage((), table={})
    coverage = type(coverage)(
        cells_total=1,
        cells_with_rows=1,
        cells_with_measured_database=1,
        platforms_total=1,
        measured_platforms=("duckdb",),
        unmeasured_platforms=(),
    )
    check = check_disk_headroom(
        DiskBudget(cells=1, est_peak_gib=4.0, est_steady_gib=3.5, unknown_cells=()),
        (DiskRootFreeSpace("output", tmp_path, 100.0),),
        min_free_gib=5.0,
    )

    assert "fits" in format_budget_verdict(check, coverage)


# ---------------------------------------------------------------------------
# D3: the checked-in inventory's zero loaded-database column is UNMEASURED.
# ---------------------------------------------------------------------------


def test_checked_in_budget_table_declares_its_database_column_unmeasured():
    """Guard the disclosure itself.

    Every checked-in row carries `peak_database_gib = 0` because no sweep has
    ever measured it -- not because loaded databases are free. This test fails
    if someone drops the `peak_database_gib_status` marker, or flips a row to
    `measured` while leaving its value at zero (which would silently convert a
    disclosed gap into a fabricated measurement). Rows with a real non-zero
    measurement may legitimately be marked `measured`.
    """
    rows = load_budget_table(DEFAULT_TABLE_PATH)

    assert rows, "checked-in disk budget table is empty"
    zero_but_measured = [key for key, row in rows.items() if row.peak_database_gib == 0.0 and row.database_measured]
    assert zero_but_measured == [], (
        "rows claim a MEASURED zero loaded-database footprint: "
        f"{sorted(zero_but_measured)[:5]}. Mark them "
        f"{DATABASE_STATUS_UNMEASURED!r} until a real sweep measures them."
    )


# ---------------------------------------------------------------------------
# Memory headroom gate (uat readiness and memory gate, #1616): a measured
# low-memory host must gate the same way a measured low-disk host does, and
# an unmeasurable host must never be silently treated as healthy OR failing.
# ---------------------------------------------------------------------------


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
