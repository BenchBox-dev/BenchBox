"""Fast-test coverage for tests/uat/phases/explorer_smoke.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from tests.uat.phases import explorer_smoke

pytestmark = pytest.mark.fast


def test_skipped_when_node_missing(tmp_path: Path):
    with patch.object(explorer_smoke, "has_node", return_value=False):
        result = explorer_smoke.run_explorer_smoke(
            bundles_dir=tmp_path / "b",
            output_dir=tmp_path / "out",
            log_dir=tmp_path / "logs",
        )
    assert result.skipped is True
    assert result.exit_code() == 0


def test_runs_build_then_smoke(tmp_path: Path):
    invocations: list[list[str]] = []

    def fake_runner(argv, stdout=None, stderr=None, check=False):
        invocations.append(argv)
        return Mock(returncode=0, args=argv)

    with (
        patch.object(explorer_smoke, "has_node", return_value=True),
        patch.object(explorer_smoke, "playwright_entry_exists", return_value=True),
    ):
        result = explorer_smoke.run_explorer_smoke(
            bundles_dir=tmp_path / "b",
            output_dir=tmp_path / "out",
            log_dir=tmp_path / "logs",
            runner=fake_runner,
        )
    assert result.skipped is False
    assert result.exit_code() == 0
    assert len(invocations) == 2
    # Build first, smoke second.
    assert invocations[0][:3] == ["benchbox", "explorer", "build"]
    assert "--data-dir" in invocations[0]
    assert "explorer" in invocations[0]
    assert "node" in invocations[1][0]


def test_short_circuits_on_build_failure(tmp_path: Path):
    invocations: list[list[str]] = []

    def fake_runner(argv, stdout=None, stderr=None, check=False):
        invocations.append(argv)
        return Mock(returncode=2, args=argv)

    with (
        patch.object(explorer_smoke, "has_node", return_value=True),
        patch.object(explorer_smoke, "playwright_entry_exists", return_value=True),
    ):
        result = explorer_smoke.run_explorer_smoke(
            bundles_dir=tmp_path / "b",
            output_dir=tmp_path / "out",
            log_dir=tmp_path / "logs",
            runner=fake_runner,
        )
    assert result.exit_code() == 2
    # Smoke should not have run.
    assert len(invocations) == 1


def test_skipped_when_playwright_entry_missing(tmp_path: Path, monkeypatch):
    with (
        patch.object(explorer_smoke, "has_node", return_value=True),
        patch.object(explorer_smoke, "playwright_entry_exists", return_value=False),
    ):
        result = explorer_smoke.run_explorer_smoke(
            bundles_dir=tmp_path / "b",
            output_dir=tmp_path / "out",
            log_dir=tmp_path / "logs",
        )
    assert result.skipped is True
