"""Unit tests for the operator-run DuckDB version-matrix helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import run_duckdb_version_matrix as matrix

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_prerelease_detection_covers_dev_and_stable_versions() -> None:
    assert matrix._is_prerelease("1.6.0.dev365") is True
    assert matrix._is_prerelease("1.5.5") is False


def test_matrix_uses_sf10_for_all_four_workloads() -> None:
    assert matrix.BENCHMARKS == (("tpch", 10.0), ("tpcds", 10.0), ("clickbench", 10.0), ("ssb", 10.0))


def test_benchbox_command_uses_package_option_for_stable_versions() -> None:
    command = matrix._benchbox_command(phase="power", benchmark="tpch", scale=10.0, version="1.5.5")

    assert command[command.index("--platform") + 1] == "duckdb"
    assert command[-2:] == ["--platform-option", "driver_version=1.5.5"]


def test_benchbox_command_omits_driver_option_for_dev_versions() -> None:
    command = matrix._benchbox_command(phase="power", benchmark="tpch", scale=10.0, version="1.6.0.dev365")

    assert "--platform-option" not in command


def test_dry_run_does_not_require_a_log_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    status, output, elapsed = matrix._run_command(
        ["command-that-is-not-run"],
        cwd=tmp_path,
        env={},
        log_path=tmp_path / "missing" / "matrix.log",
        dry_run=True,
    )

    assert (status, output, elapsed) == (0, "", 0.0)
    assert "$ command-that-is-not-run" in capsys.readouterr().out


def test_find_result_path_accepts_relative_path(tmp_path: Path) -> None:
    result = tmp_path / "results" / "run.json"
    result.parent.mkdir()
    result.write_text("{}", encoding="utf-8")

    assert matrix._find_result_path("ignored\nresults/run.json\n", cwd=tmp_path) == result.resolve()
