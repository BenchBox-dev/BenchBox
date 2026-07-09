"""Tests for the --normalize-plan-literals CLI flag.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.

Covers the flag end-to-end:
- the flag is a recognized CLI option and is reproduced by the dry-run command
  generator, and
- when set on a real run, a literal-normalized fingerprint is recorded in the
  exported plans companion file under a separate key.
"""

from __future__ import annotations

import glob
import json

import pytest
from click.testing import CliRunner

from benchbox.cli.commands.run import run
from benchbox.cli.config import ConfigManager
from benchbox.cli.dryrun import generate_cli_command

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


def _load_plans_companion(results_dir):
    """Return the parsed plans companion payload from a results directory."""
    matches = glob.glob(str(results_dir / "*.plans.json"))
    assert matches, f"No plans companion file written in {results_dir}"
    with open(matches[0], encoding="utf-8") as handle:
        return json.load(handle)


class TestNormalizePlanLiteralsFlagAccepted:
    """The flag is wired into the CLI surface and dry-run reproduction."""

    def test_flag_is_a_recognized_option(self):
        param_names = {p.name for p in run.params}
        assert "normalize_plan_literals" in param_names

    def test_dry_run_command_generator_reproduces_flag(self):
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=0.01,
            capture_plans=True,
            normalize_plan_literals=True,
        )
        assert "--normalize-plan-literals" in cmd

    def test_dry_run_command_generator_omits_flag_when_unset(self):
        cmd = generate_cli_command(
            platform="duckdb",
            benchmark="tpch",
            scale=0.01,
            capture_plans=True,
            normalize_plan_literals=False,
        )
        assert "--normalize-plan-literals" not in cmd


class TestNormalizePlanLiteralsFingerprintInResults:
    """A real run records the normalized fingerprint only when the flag is set."""

    def _run(self, monkeypatch, tmp_path, extra_args):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            run,
            [
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--phases",
                "power",
                "--queries",
                "1",
                "--capture-plans",
                "--non-interactive",
                "--quiet",
                *extra_args,
            ],
            obj={"config": ConfigManager()},
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
        return tmp_path / "benchmark_runs" / "results"

    def test_normalized_fingerprint_present_when_flag_set(self, monkeypatch, tmp_path):
        results_dir = self._run(monkeypatch, tmp_path, ["--normalize-plan-literals"])
        payload = _load_plans_companion(results_dir)

        plans = payload["queries"]
        assert plans, "Expected at least one captured plan"
        for entry in plans.values():
            assert "fingerprint" in entry
            assert "fingerprint_normalized" in entry
            # Normalized fingerprint is still a valid SHA256 hash.
            assert len(entry["fingerprint_normalized"]) == 64

    def test_normalized_fingerprint_absent_without_flag(self, monkeypatch, tmp_path):
        results_dir = self._run(monkeypatch, tmp_path, [])
        payload = _load_plans_companion(results_dir)

        plans = payload["queries"]
        assert plans, "Expected at least one captured plan"
        for entry in plans.values():
            assert "fingerprint" in entry
            assert "fingerprint_normalized" not in entry
