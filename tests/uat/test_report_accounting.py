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

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rows"] == 5
    assert payload["attempted"] == 3
    assert payload["skipped"] == 1
    assert payload["unreachable"] == 1
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

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["unreachable"] == 3
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

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["unreachable"] == 0
    assert payload["total_defined"] == 1
