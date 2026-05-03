from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

import benchbox.utils.printing as printing
from benchbox.cli.commands.results import results

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


def test_results_group_without_subcommand_shows_summary(cli_runner, monkeypatch):
    results_module = import_module("benchbox.cli.commands.results")
    exporter = MagicMock()
    monkeypatch.setattr(results_module, "ResultExporter", lambda: exporter)

    result = cli_runner.invoke(results, [])
    assert result.exit_code == 0
    exporter.show_results_summary.assert_called_once_with()


def test_results_paths_prints_copyable_result_paths(cli_runner, monkeypatch, tmp_path):
    results_module = import_module("benchbox.cli.commands.results")
    result_a = tmp_path / "tpch_duckdb.json"
    result_b = tmp_path / "tpch_clickhouse.json"
    exporter = SimpleNamespace(
        show_results_summary=MagicMock(),
        list_results=MagicMock(
            return_value=[
                {"file": result_a, "timestamp": "2026-05-03T12:00:00"},
                {"file": result_b, "timestamp": "2026-05-03T11:00:00"},
            ]
        ),
    )
    prints = []
    monkeypatch.setattr(results_module, "ResultExporter", lambda: exporter)
    monkeypatch.setattr(
        results_module,
        "console",
        SimpleNamespace(print=lambda *args, **_kwargs: prints.extend(str(arg) for arg in args)),
    )

    result = cli_runner.invoke(results, ["--paths", "--limit", "1"])

    assert result.exit_code == 0
    exporter.show_results_summary.assert_called_once_with()
    exporter.list_results.assert_called_once_with()
    printed = "\n".join(prints)
    assert "Result Paths (1 shown)" in printed
    assert str(result_a) in printed
    assert str(result_b) not in printed
    assert "benchbox submit <path> --output ./submission" in printed


def test_results_group_with_submitted_shows_submission_history(cli_runner, monkeypatch, tmp_path):
    results_module = import_module("benchbox.cli.commands.results")
    prints = []
    sidecar = tmp_path / "tpch_duckdb.submission.json"
    sidecar.write_text(
        json.dumps(
            {
                "submitted_at": "2026-05-01T12:00:00+00:00",
                "benchmark": "tpch",
                "platform": "duckdb",
                "scale_factor": 0.01,
                "status": "published",
                "public_url": "https://benchbox.dev/results/r/r1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(results_module, "ResultExporter", lambda: SimpleNamespace(output_dir=Path(tmp_path)))

    def fake_print(*args, **_kwargs):
        for arg in args:
            if hasattr(arg, "columns"):
                for column in arg.columns:
                    prints.extend(str(cell) for cell in column._cells)
            else:
                prints.append(str(arg))

    monkeypatch.setattr(results_module, "console", SimpleNamespace(print=fake_print))

    result = cli_runner.invoke(results, ["--submitted"])

    assert result.exit_code == 0
    printed = "\n".join(prints)
    assert "Hosted Submissions" in printed
    assert "https://benchbox.dev/results/r/r1" in printed


def test_results_group_with_submitted_reports_empty(cli_runner, monkeypatch, tmp_path):
    results_module = import_module("benchbox.cli.commands.results")
    prints = []
    monkeypatch.setattr(results_module, "ResultExporter", lambda: SimpleNamespace(output_dir=Path(tmp_path)))
    monkeypatch.setattr(results_module, "console", SimpleNamespace(print=lambda *args, **_kwargs: prints.append(args)))

    result = cli_runner.invoke(results, ["--submitted"])

    assert result.exit_code == 0
    assert any("No hosted submissions found" in str(args) for args in prints)


def test_show_cli_reconstructs_legacy_command(cli_runner, tmp_path, monkeypatch):
    # Reset Rich console singleton so it binds to CliRunner's captured stdout,
    # and ensure quiet mode is off so output is not suppressed.
    # Use a wide console width to prevent Rich from truncating text inside Panels.
    from rich.console import Console

    monkeypatch.setattr(printing, "_STD_CONSOLE", Console(width=200))
    monkeypatch.setattr(printing, "_QUIET", False)

    result_file = tmp_path / "result.json"
    result_file.write_text(
        json.dumps(
            {
                "platform": "duckdb",
                "benchmark_name": "tpch",
                "scale_factor": 0.01,
                "run": {"query_subset": ["Q1", "Q2"]},
            }
        )
    )

    result = cli_runner.invoke(results, ["show-cli", str(result_file)])
    assert result.exit_code == 0
    assert "benchbox run --platform duckdb --benchmark tpch --scale 0.01" in result.output
    assert "--queries Q1,Q2" in result.output


def test_show_cli_reports_missing_fields(cli_runner, tmp_path, monkeypatch):
    monkeypatch.setattr(printing, "_STD_CONSOLE", None)
    monkeypatch.setattr(printing, "_QUIET", False)

    result_file = tmp_path / "bad.json"
    result_file.write_text(json.dumps({"platform": "duckdb"}))

    result = cli_runner.invoke(results, ["show-cli", str(result_file)])
    assert result.exit_code == 0
    assert "Could not extract required fields" in result.output


def test_show_cli_reports_invalid_json(cli_runner, tmp_path, monkeypatch):
    monkeypatch.setattr(printing, "_STD_CONSOLE", None)
    monkeypatch.setattr(printing, "_QUIET", False)

    result_file = tmp_path / "invalid.json"
    result_file.write_text("{not valid json")

    result = cli_runner.invoke(results, ["show-cli", str(result_file)])
    assert result.exit_code == 0
    assert "Invalid JSON file" in result.output
