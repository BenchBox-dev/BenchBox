from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.medium]
ROOT = Path(__file__).resolve().parents[3]


def _workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/trunk.yml").read_text(encoding="utf-8"))


def _triggers() -> dict:
    return _workflow()[True]


def test_runs_after_each_push_to_develop_and_on_demand() -> None:
    triggers = _triggers()
    assert triggers["push"] == {"branches": ["develop"]}
    assert "workflow_dispatch" in triggers
    assert "pull_request" not in triggers and "merge_group" not in triggers


def test_runs_queue_per_ref_without_cancelling() -> None:
    concurrency = _workflow()["concurrency"]
    assert "github.ref" in concurrency["group"], "a manual run on another ref would replace the pending run for develop"
    assert concurrency["cancel-in-progress"] is False


def test_is_read_only() -> None:
    assert _workflow()["permissions"] == {"contents": "read"}
