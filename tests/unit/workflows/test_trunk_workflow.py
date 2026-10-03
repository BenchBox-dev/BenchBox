"""Pin how the post-merge workflow is triggered and queued.

``trunk.yml`` is the only test of ``develop`` in its merged state, so a run for a
merged commit must not be dropped, and a run on another ref must not replace it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.medium]
ROOT = Path(__file__).resolve().parents[3]


def _workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/trunk.yml").read_text(encoding="utf-8"))


def test_runs_after_each_push_to_develop_and_on_demand() -> None:
    triggers = _workflow()[True]  # YAML reads the bare key `on` as True
    assert triggers["push"] == {"branches": ["develop"]}
    assert "workflow_dispatch" in triggers
    assert "pull_request" not in triggers and "merge_group" not in triggers


def test_runs_queue_per_ref_without_cancelling() -> None:
    concurrency = _workflow()["concurrency"]
    assert "github.ref" in concurrency["group"], "a manual run on another ref would replace the pending run for develop"
    assert concurrency["cancel-in-progress"] is False


def test_is_read_only() -> None:
    assert _workflow()["permissions"] == {"contents": "read"}
