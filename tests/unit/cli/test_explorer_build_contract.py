"""Contract tests for the explorer build CLI surface."""

from __future__ import annotations

import importlib
import json

import pytest
from click.testing import CliRunner

from benchbox.core.explorer_pipeline.contract import EXPLORER_BUILD_CONTRACT

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


def test_explorer_build_contract_matches_duckdb_only_output_contract() -> None:
    outputs = EXPLORER_BUILD_CONTRACT["outputs"]

    assert EXPLORER_BUILD_CONTRACT["version"] == "3"
    assert "results_schema.json" not in outputs["required"]
    assert "results_schema.json" in outputs["removed_legacy"]


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


def test_explorer_group_does_not_register_legacy_comparison_builder() -> None:
    assert "build-comparison" not in explorer_module.explorer_group.commands
