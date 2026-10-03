"""Pin how the post-merge workflow is triggered and queued.

``trunk.yml`` is the only test of ``develop`` in its merged state. Runs on one ref
queue and GitHub keeps a single pending run, so a burst of merges is batched: a
replaced run is covered by the next one, which tests the newer tree. A run on
another ref must not replace the pending run for develop.
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
