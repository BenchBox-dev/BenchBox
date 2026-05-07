"""Fast regression checks for the checked-in tuned-template coverage matrix."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchbox.core.tuning.coverage import (
    BASIC_CONSTRAINTS,
    DECISION_AUTHOR,
    DECISION_DONE,
    DECISION_WAIVED,
    TUNED_TEMPLATE,
    VALID_DECISIONS,
    TuningCoverageRow,
    build_tuning_coverage_rows,
    parse_runtime_tuning_logs,
    read_tuning_coverage_tsv,
    runtime_mismatches,
    static_matrix_drift,
)
from tests.uat import _cli
from tests.uat.matrix import PLATFORM_GROUPS, load_benchmarks, resolve_benchmarks

pytestmark = pytest.mark.fast

MATRIX_PATH = Path(__file__).resolve().parent / "data" / "tuning_coverage.tsv"


def test_tuning_coverage_matrix_is_checked_in_and_has_decisions():
    rows = read_tuning_coverage_tsv(MATRIX_PATH)
    assert rows
    assert all(row.decision in VALID_DECISIONS for row in rows)
    assert all(row.reason for row in rows)
    assert any(row.status == TUNED_TEMPLATE and row.decision == DECISION_DONE for row in rows)
    assert any(row.status == BASIC_CONSTRAINTS and row.decision == DECISION_AUTHOR for row in rows)


def test_checked_in_tuning_coverage_has_no_static_drift():
    recorded = read_tuning_coverage_tsv(MATRIX_PATH)
    current = build_tuning_coverage_rows(_uat_platforms(), _uat_benchmarks())
    assert static_matrix_drift(recorded, current) == []


def test_static_matrix_drift_flags_new_current_rows_missing_from_matrix():
    recorded = [
        TuningCoverageRow(
            platform="duckdb",
            benchmark="tpch",
            status=TUNED_TEMPLATE,
            decision=DECISION_DONE,
            reason="template exists",
        )
    ]
    current = [
        *recorded,
        TuningCoverageRow(
            platform="duckdb",
            benchmark="newbench",
            status=BASIC_CONSTRAINTS,
            decision=DECISION_WAIVED,
            reason="new coverage gap",
        ),
    ]

    assert static_matrix_drift(recorded, current) == ["new current row missing from matrix for duckdb/newbench"]


def test_static_regressions_reports_current_rows_missing_from_checked_in_matrix():
    recorded = [
        TuningCoverageRow("duckdb", "tpch", TUNED_TEMPLATE, DECISION_DONE, "benchmark-specific tuned template exists")
    ]
    current = [
        *recorded,
        TuningCoverageRow("duckdb", "newbench", BASIC_CONSTRAINTS, DECISION_WAIVED, "needs checked-in triage"),
    ]

    assert static_regressions(recorded, current) == ["missing checked-in matrix row for duckdb/newbench"]


def test_runtime_log_parser_matches_matrix_rows(tmp_path: Path):
    log_path = tmp_path / "duckdb_tpch_0.01_20260505_010203.log"
    log_path.write_text("Tuning: auto-discovered template at examples/tunings/duckdb/tpch_tuned.yaml\n")

    rows = [
        row for row in read_tuning_coverage_tsv(MATRIX_PATH) if row.platform == "duckdb" and row.benchmark == "tpch"
    ]
    observations = parse_runtime_tuning_logs(tmp_path, platforms=_uat_platforms(), benchmarks=_uat_benchmarks())

    assert len(observations) == 1
    assert observations[0].status == TUNED_TEMPLATE
    assert runtime_mismatches(rows, observations) == []


def test_runtime_log_mismatch_reports_context(tmp_path: Path):
    log_path = tmp_path / "duckdb_tpch_0.01_20260505_010203.log"
    log_path.write_text("Tuning: using basic constraints (no optimized template available)\n")
    rows = [
        row for row in read_tuning_coverage_tsv(MATRIX_PATH) if row.platform == "duckdb" and row.benchmark == "tpch"
    ]

    observations = parse_runtime_tuning_logs(tmp_path, platforms=_uat_platforms(), benchmarks=_uat_benchmarks())
    mismatches = runtime_mismatches(rows, observations)

    assert len(mismatches) == 1
    assert "duckdb/tpch" in mismatches[0]
    assert str(log_path) in mismatches[0]


def test_verify_tuning_matrix_rejects_empty_observations(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    rc = _cli.verify_tuning_matrix_main(["--logs", str(tmp_path)])

    captured = capsys.readouterr()
    assert rc == 1
    assert "No tuning observations parsed" in captured.err
    assert str(tmp_path) in captured.err


def _uat_platforms() -> list[str]:
    return list(PLATFORM_GROUPS["all"])


def _uat_benchmarks() -> list[str]:
    benchmarks = load_benchmarks()
    return resolve_benchmarks(groups=["all"], benchmarks=benchmarks)
