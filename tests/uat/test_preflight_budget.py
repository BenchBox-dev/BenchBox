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


def test_largest_scale_cells_selects_the_largest_rung_through_the_live_path(tmp_path: Path):
    """Pin `largest_scale_cells` -- the LIVE cell-selection path the preflight gate
    actually runs (`estimate_disk_budget_summary_and_gate` and `assess_budget_coverage`
    in `phases/preflight.py` both consume it) -- against a MULTI-rung config.

    Every other test in this module uses a single-rung config (`rungs: [0.01]`), which
    cannot distinguish "select the largest rung" from "select any rung" or "select every
    rung": with one rung, `max`, `min`, and "all cells" all return the same set. That gap
    let two mutations survive the full suite:

    - M15: `max(cells_by_scale)` -> `min(cells_by_scale)` -- rung selection silently
      flips to the SMALLEST configured scale. With `rungs: [0.01, 1, 100]` this is the
      exact mid-sweep disk death the gate exists to prevent: preflight budgets the
      tiny-scale figure while the sweep runs the largest.
    - M13: returning cells from every rung instead of only the largest -- the gate would
      then estimate/report coverage over a mixed population instead of "the largest
      configured scale's estimated peak" (the module's own docstring, and
      docs/operations/uat-framework.md's "Disk-budget estimate" section).

    This test uses three rungs specifically so `min` and `max` disagree AND "all cells"
    (6, across 3 rungs x 2 platforms) disagrees with "largest only" (2).
    """
    cfg = validate_config(
        {
            "name": "multi-rung-live-path-smoke",
            "platforms": {"include": ["duckdb", "sqlite"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01, 1, 100]},
        }
    )

    cells = largest_scale_cells(cfg)

    assert cells, "expected cells at the largest configured scale rung"
    assert {cell.scale for cell in cells} == {100.0}
    assert {cell.platform for cell in cells} == {"duckdb", "sqlite"}
    assert len(cells) == 2

    # Same assertion through the estimator that consumes `largest_scale_cells`'
    # output, so a regression in either the selection or its consumption is caught.
    table = tmp_path / "disk_budget.tsv"
    table.write_text(
        "platform\tbenchmark\tscale_factor\tpeak_datagen_gib\tpeak_database_gib\ttransient_growth_gib\n"
        "duckdb\ttpch\t0.01\t1.0\t2.0\t0.5\n"
        "duckdb\ttpch\t1\t10.0\t20.0\t5.0\n"
        "duckdb\ttpch\t100\t100.0\t200.0\t50.0\n"
        "sqlite\ttpch\t100\t120.0\t300.0\t70.0\n",
        encoding="utf-8",
    )
    from tests.uat.preflight_budget import estimate_cells

    budget = estimate_cells(cells, table=load_budget_table(table))

    assert budget.cells == 2
    assert budget.est_steady_gib == pytest.approx(120.0 + 200.0 + 300.0)
    assert budget.est_peak_gib == pytest.approx(120.0 + 200.0 + 300.0 + 50.0 + 70.0)
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
    """A genuine fully-measured single-cell coverage, not a hand-substituted one.

    Previously this test built its "complete" coverage by calling
    `assess_budget_coverage((), table={})` (`cells_total=0`) and then
    hand-substituting `cells_total=1` on the result -- which sidestepped the
    real `cells_total == 0` case entirely (see
    `test_format_budget_verdict_zero_cells_never_claims_a_fit` for that case)
    and never actually exercised `assess_budget_coverage` computing a
    genuine complete rung.
    """
    table = tmp_path / "disk_budget.tsv"
    table.write_text(
        "platform\tbenchmark\tscale_factor\tpeak_datagen_gib\tpeak_database_gib\t"
        "peak_database_gib_status\ttransient_growth_gib\n"
        "duckdb\ttpch\t0.01\t1.0\t2.0\tmeasured\t0.5\n",
        encoding="utf-8",
    )
    cfg = validate_config(
        {
            "name": "verdict-complete-smoke",
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )

    coverage = assess_budget_coverage(largest_scale_cells(cfg), table=load_budget_table(table))
    check = check_disk_headroom(
        DiskBudget(cells=1, est_peak_gib=4.0, est_steady_gib=3.5, unknown_cells=()),
        (DiskRootFreeSpace("output", tmp_path, 100.0),),
        min_free_gib=5.0,
    )

    assert coverage.cells_total == 1
    assert coverage.is_lower_bound is False
    assert "fits" in format_budget_verdict(check, coverage)


def test_format_budget_verdict_zero_cells_never_claims_a_fit(tmp_path: Path):
    """A zero-cell config (e.g. `platforms: {include: [duckdb], exclude:
    [duckdb]}`) must not read as a MEASURED fit.

    `coverage.is_lower_bound` evaluates `(0 < 0) or (0 < 0)` = False for a
    zero-cell coverage, which used to fall through to the "fits" branch and
    print `Disk budget verdict: measured requirement of 5.00 GiB fits every
    required root` for a config that measured nothing at all --
    self-contradicting alongside `format_budget_coverage`'s own "nothing
    measured and nothing gated" line for the same coverage.
    """
    coverage = assess_budget_coverage((), table={})
    check = check_disk_headroom(
        DiskBudget(cells=0, est_peak_gib=0.0, est_steady_gib=0.0, unknown_cells=()),
        (DiskRootFreeSpace("output", tmp_path, 500.0),),
        min_free_gib=5.0,
    )

    assert coverage.cells_total == 0

    verdict = format_budget_verdict(check, coverage)

    assert "no cells enumerated" in verdict
    assert "fits" not in verdict
    assert "measured requirement" not in verdict


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
