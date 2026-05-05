"""Fast-test coverage for tests/uat/phases/report.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.uat.phases import report
from tests.uat.runner import CellResult

pytestmark = pytest.mark.fast


def _cell(platform, benchmark, scale, status="passed", elapsed=1.0, result=None):
    return CellResult(
        platform=platform,
        benchmark=benchmark,
        scale=scale,
        status=status,
        exit_code=0 if status == "passed" else 1,
        elapsed_s=elapsed,
        log_path=Path(f"/tmp/{platform}_{benchmark}_{scale}.log"),
        result_path=Path(result) if result else None,
    )


def test_render_row_matches_header_columns():
    cell = _cell("duckdb", "tpch", 0.01, status="passed", result="/tmp/r.json")
    row = report.render_row(cell, validator_status="clean")
    fields = row.split("\t")
    expected_cols = report.REPORT_HEADER.split("\t")
    assert len(fields) == len(expected_cols)


def test_write_report_counts(tmp_path: Path):
    cells = [
        _cell("duckdb", "tpch", 0.01, status="passed"),
        _cell("duckdb", "tpch", 0.1, status="failed"),
        _cell("duckdb", "tpch", 1.0, status="timed-out"),
    ]
    summary = report.write_report(cells, output_path=tmp_path / "out.tsv")
    assert summary.rows == 3
    assert summary.pass_count == 1
    assert summary.fail_count == 1
    assert summary.timeout_count == 1
    text = (tmp_path / "out.tsv").read_text()
    assert text.startswith(report.REPORT_HEADER)


def test_cross_scale_clean_counts_full_ladder():
    cells = [
        _cell("duckdb", "tpch", 0.01, status="passed"),
        _cell("duckdb", "tpch", 0.1, status="passed"),
        _cell("duckdb", "tpch", 1.0, status="passed"),
        _cell("sqlite", "tpch", 0.01, status="passed"),  # missing 0.1 and 1.0
    ]
    n = report.cross_scale_clean_pair_count(cells, rungs=[0.01, 0.1, 1.0])
    assert n == 1


def test_cross_scale_clean_excludes_failed_rung():
    cells = [
        _cell("duckdb", "tpch", 0.01, status="passed"),
        _cell("duckdb", "tpch", 0.1, status="failed"),
        _cell("duckdb", "tpch", 1.0, status="passed"),
    ]
    n = report.cross_scale_clean_pair_count(cells, rungs=[0.01, 0.1, 1.0])
    assert n == 0


def test_cross_scale_floor_breach_sets_exit_code(tmp_path: Path):
    cells = [
        _cell("duckdb", "tpch", 0.01, status="passed"),
    ]
    summary = report.write_report(
        cells,
        output_path=tmp_path / "out.tsv",
        rungs=[0.01, 0.1, 1.0],
        cross_scale_floor=1,
    )
    assert summary.cross_scale_clean_pairs == 0
    assert summary.cross_scale_floor_breached is True
    assert summary.exit_code() == 1


def test_cross_scale_floor_default_off(tmp_path: Path):
    cells = [_cell("duckdb", "tpch", 0.01, status="passed")]
    summary = report.write_report(cells, output_path=tmp_path / "out.tsv")
    assert summary.cross_scale_floor_breached is False
    assert summary.exit_code() == 0


def test_cross_scale_validator_status_blocks_clean_pair():
    cells = [
        _cell("duckdb", "tpch", 0.01, status="passed", result="/tmp/r1.json"),
        _cell("duckdb", "tpch", 0.1, status="passed", result="/tmp/r2.json"),
    ]
    n = report.cross_scale_clean_pair_count(
        cells,
        rungs=[0.01, 0.1],
        validator_status_by_path={Path("/tmp/r1.json"): "clean", Path("/tmp/r2.json"): "error"},
    )
    assert n == 0
