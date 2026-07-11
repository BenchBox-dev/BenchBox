"""Regression coverage for UAT release-accounting denominators."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.uat import _cli as uat_cli
from tests.uat.phases import report
from tests.uat.runner import CellResult

pytestmark = pytest.mark.fast

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "report-accounting-skipped-unreachable-cells.jsonl"


def _cell(platform: str, benchmark: str, scale: float, status: str = "passed") -> CellResult:
    return CellResult(
        platform=platform,
        benchmark=benchmark,
        scale=scale,
        status=status,
        exit_code=0 if status in {"passed", "skipped", "skipped-unreachable"} else 1,
        elapsed_s=1.0 if status in {"passed", "failed", "timed-out"} else 0.0,
        log_path=Path(f"/tmp/{platform}_{benchmark}_{scale}.log"),
        result_path=Path(f"/tmp/{platform}_{benchmark}_{scale}.json") if status == "passed" else None,
    )


def test_report_cli_reconciles_skipped_and_unreachable_fixture(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    output_tsv = tmp_path / "matrix_summary.tsv"

    exit_code = uat_cli.main(["report", "--cells-jsonl", str(FIXTURE), "--output-tsv", str(output_tsv)])

    # Default-strict exit-code policy (uat-accounting-hardening w1/w4): the
    # fixture has a failed cell and an unreachable cell, so a report exit
    # code of 0 would no longer mean "everything attempted actually passed."
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["rows"] == 5
    assert payload["attempted"] == 3
    assert payload["skipped"] == 1
    assert payload["unreachable"] == 1
    # The fixture has no `.accounting.json` sidecar, so the unreachable count
    # is not confirmed (it happens to be right here because the fixture also
    # carries a `skipped-unreachable` row directly, but the sidecar-derived
    # portion of it is still an assumption, not a confirmation).
    assert payload["unreachable_is_estimated"] is True
    assert payload["total_defined"] == 5
    assert payload["passed"] + payload["failed"] + payload["timed_out"] == payload["attempted"]
    assert payload["attempted"] + payload["skipped"] + payload["unreachable"] == payload["total_defined"]

    text = output_tsv.read_text(encoding="utf-8")
    assert "attempted=3 skipped=1 unreachable=1 total_defined=5" in text
    assert "# UNREACHABLE_CELLS=1 release_gate_attention=required" in text


def test_report_counts_execute_unreachable_cells_outside_rows(tmp_path: Path):
    summary = report.write_report(
        [
            _cell("duckdb", "tpch", 0.01, status="passed"),
            _cell("duckdb", "tpch", 0.1, status="failed"),
            _cell("duckdb", "tpch", 1.0, status="timed-out"),
        ],
        output_path=tmp_path / "matrix_summary.tsv",
        compatibility_pruned_count=2,
        early_stop_pruned_count=1,
        skipped_unreachable_count=4,
    )

    assert summary.attempted_count == 3
    assert summary.skipped_count == 3
    assert summary.unreachable_count == 4
    assert summary.total_defined_count == 10
    assert summary.candidate_count == 10

    text = (tmp_path / "matrix_summary.tsv").read_text(encoding="utf-8")
    assert "compatibility_pruned=2 early_stop_pruned=1 attempted=3 skipped=3 unreachable=4 total_defined=10" in text
    assert "# UNREACHABLE_CELLS=4 release_gate_attention=required" in text


def test_report_cli_reads_skipped_unreachable_sidecar(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """A report regenerated from cells.jsonl must read skipped-unreachable
    cells back from the durable sidecar instead of printing unreachable: 0."""
    cells_jsonl = tmp_path / "cells.jsonl"
    cells_jsonl.write_text(
        "\n".join(
            json.dumps(
                {
                    "platform": "duckdb",
                    "benchmark": "tpch",
                    "scale": 0.01,
                    "status": "passed",
                    "exit_code": 0,
                    "elapsed_s": 1.0,
                    "log_path": "/tmp/a.log",
                    "result_path": "/tmp/a.json",
                }
            )
            for _ in range(2)
        )
        + "\n",
        encoding="utf-8",
    )
    # The durable sweep writes this sidecar next to cells.jsonl.
    cells_jsonl.with_name("cells.jsonl.accounting.json").write_text(
        json.dumps({"skipped_unreachable_count": 3}), encoding="utf-8"
    )
    output_tsv = tmp_path / "matrix_summary.tsv"

    exit_code = uat_cli.main(["report", "--cells-jsonl", str(cells_jsonl), "--output-tsv", str(output_tsv)])

    # Default-strict exit-code policy: a confirmed nonzero unreachable count
    # is itself grounds for a nonzero exit code, independent of pass/fail.
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["unreachable"] == 3
    # The sidecar was present and read successfully, so this is a confirmed
    # count, not an estimate.
    assert payload["unreachable_is_estimated"] is False
    assert payload["attempted"] == 2
    assert payload["total_defined"] == 5
    text = output_tsv.read_text(encoding="utf-8")
    assert "# UNREACHABLE_CELLS=3 release_gate_attention=required" in text


def test_report_cli_without_sidecar_defaults_unreachable_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """Older artifacts predate the sidecar; the report must still regenerate."""
    cells_jsonl = tmp_path / "cells.jsonl"
    cells_jsonl.write_text(
        json.dumps(
            {
                "platform": "duckdb",
                "benchmark": "tpch",
                "scale": 0.01,
                "status": "passed",
                "exit_code": 0,
                "elapsed_s": 1.0,
                "log_path": "/tmp/a.log",
                "result_path": "/tmp/a.json",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output_tsv = tmp_path / "matrix_summary.tsv"

    exit_code = uat_cli.main(["report", "--cells-jsonl", str(cells_jsonl), "--output-tsv", str(output_tsv)])

    # must_preserve: the pinned unreachable=0-without-sidecar default and its
    # exit code stay exactly as before - w5 only adds visibility that this 0
    # is an assumption, not a confirmation (see the estimated-flag assertion
    # below), it does not change the default itself.
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["unreachable"] == 0
    assert payload["unreachable_is_estimated"] is True
    assert payload["total_defined"] == 1


# ---------------------------------------------------------------------------
# w1/w4: default-strict exit-code policy.
# ---------------------------------------------------------------------------


def test_write_report_exit_code_zero_when_everything_attempted_passed(tmp_path: Path):
    summary = report.write_report(
        [_cell("duckdb", "tpch", 0.01, status="passed")],
        output_path=tmp_path / "matrix_summary.tsv",
    )
    assert summary.exit_code() == 0


def test_write_report_exit_code_nonzero_on_fail_count(tmp_path: Path):
    summary = report.write_report(
        [
            _cell("duckdb", "tpch", 0.01, status="passed"),
            _cell("duckdb", "tpch", 0.1, status="failed"),
        ],
        output_path=tmp_path / "matrix_summary.tsv",
    )
    assert summary.fail_count == 1
    assert summary.exit_code() == 1


def test_write_report_exit_code_nonzero_on_timeout_count(tmp_path: Path):
    summary = report.write_report(
        [_cell("duckdb", "tpch", 0.01, status="timed-out")],
        output_path=tmp_path / "matrix_summary.tsv",
    )
    assert summary.timeout_count == 1
    assert summary.exit_code() == 1


def test_write_report_exit_code_nonzero_on_unreachable_count(tmp_path: Path):
    summary = report.write_report(
        [_cell("duckdb", "tpch", 0.01, status="passed")],
        output_path=tmp_path / "matrix_summary.tsv",
        skipped_unreachable_count=2,
    )
    assert summary.unreachable_count == 2
    assert summary.fail_count == 0
    assert summary.timeout_count == 0
    assert summary.exit_code() == 1


def test_write_report_exit_code_aborted_still_wins_over_clean_run(tmp_path: Path):
    """`aborted` (exit 2) must still take priority over the fail/timeout/unreachable check."""
    summary = report.write_report(
        [_cell("duckdb", "tpch", 0.01, status="passed")],
        output_path=tmp_path / "matrix_summary.tsv",
        run_status="ABORTED",
    )
    assert summary.exit_code() == 2


# ---------------------------------------------------------------------------
# w3: registry_pruned_count threading into total_defined_count.
# ---------------------------------------------------------------------------


def test_write_report_threads_registry_pruned_count_into_total_defined(tmp_path: Path):
    summary = report.write_report(
        [_cell("duckdb", "tpch", 0.01, status="passed")],
        output_path=tmp_path / "matrix_summary.tsv",
        compatibility_pruned_count=2,
        registry_pruned_count=3,
    )

    assert summary.registry_pruned_count == 3
    assert summary.skipped_count == 5  # 0 row-skipped + 2 compatibility + 3 registry
    assert summary.total_defined_count == 6  # 1 attempted + 5 skipped + 0 unreachable

    text = (tmp_path / "matrix_summary.tsv").read_text(encoding="utf-8")
    assert "registry_pruned=3" in text


# ---------------------------------------------------------------------------
# uat-status-taxonomy-exit-code-fixes w3: failed cells with a resolved result
# JSON must not read as submission-ready when a report is regenerated from
# cells.jsonl via `make uat-report`.
# ---------------------------------------------------------------------------


def test_report_cli_marks_failed_cell_with_result_path_not_submittable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    cells_jsonl = tmp_path / "cells.jsonl"
    cells_jsonl.write_text(
        json.dumps(
            {
                "platform": "duckdb",
                "benchmark": "tpch",
                "scale": 0.01,
                "status": "failed",
                "exit_code": 1,
                "elapsed_s": 2.0,
                "log_path": "/tmp/a.log",
                "result_path": "/tmp/a.json",
                "submit_terminal_state": "submittable",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output_tsv = tmp_path / "matrix_summary.tsv"

    exit_code = uat_cli.main(["report", "--cells-jsonl", str(cells_jsonl), "--output-tsv", str(output_tsv)])

    assert exit_code == 1
    text = output_tsv.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert "failed\tfailed:submittable\t" in lines[1]
    capsys.readouterr()  # drain stdout to keep this test quiet in -s runs
