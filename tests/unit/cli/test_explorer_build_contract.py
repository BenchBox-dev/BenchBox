"""Contract tests for the explorer build CLI surface."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from benchbox.core.explorer_pipeline.contract import EXPLORER_BUILD_CONTRACT
from benchbox.core.explorer_pipeline.transformer import comparison_artifact_hash

explorer_module = importlib.import_module("benchbox.cli.commands.explorer")

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_explorer_build_contract_command_emits_expected_json() -> None:
    runner = CliRunner()

    result = runner.invoke(explorer_module.explorer_group, ["build-contract"])

    assert result.exit_code == 0
    assert json.loads(result.output) == EXPLORER_BUILD_CONTRACT


def test_explorer_build_flags_match_declared_contract() -> None:
    flag_opts = {opt for param in explorer_module.explorer_build.params for opt in getattr(param, "opts", [])}

    for required_flag in EXPLORER_BUILD_CONTRACT["flags"]:
        assert required_flag in flag_opts


def test_explorer_build_contract_command_matches_registered_click_path() -> None:
    command_tokens = EXPLORER_BUILD_CONTRACT["command"].split()

    assert command_tokens[:2] == ["benchbox", "explorer"]
    assert explorer_module.explorer_group.name == command_tokens[1]

    build_command = explorer_module.explorer_group.commands.get(command_tokens[2])
    assert build_command is explorer_module.explorer_build


def test_build_comparison_writes_artifact_to_correct_path(tmp_path: Path) -> None:
    """build-comparison writes compare/<hash16>.json with schema_version=2."""

    # Build a minimal detail JSON that satisfies DetailResult validation.
    def _detail(result_id: str, platform: str) -> dict:
        return {
            "result_id": result_id,
            "benchmark": "tpch",
            "scale_factor": 0.1,
            "platform": platform,
            "platform_id": platform.lower(),
            "driver_version": None,
            "run_date": "2026-04-01",
            "total_duration_s": 10.0,
            "power_score": None,
            "environment": {},
            "queries": [],
            "display_timings": [{"query_id": "Q1", "display_ms": 100.0, "sample_count": 1}],
            "has_plans": False,
            "has_tuning": False,
            "bundle_download_url": "",
            "trust_label": "maintainer-run",
            "visibility": "public-curated",
        }

    details_dir = tmp_path / "details"
    details_dir.mkdir()
    ids = ["r1", "r2"]
    for rid, plat in zip(ids, ["DuckDB", "SQLite"]):
        (details_dir / f"{rid}.json").write_text(json.dumps(_detail(rid, plat)))

    out_dir = tmp_path / "compare"
    runner = CliRunner()
    result = runner.invoke(
        explorer_module.explorer_group,
        [
            "build-comparison",
            "--data-dir",
            str(tmp_path),
            "--ids",
            ",".join(ids),
            "--out",
            str(out_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    expected_path = out_dir / f"{comparison_artifact_hash(ids)}.json"
    assert expected_path.exists()
    artifact = json.loads(expected_path.read_text())
    assert artifact["schema_version"] == 2
