"""Regression tests for develop PR metric collection and timeout alignment."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.medium]

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "_project" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

spec = importlib.util.spec_from_file_location("dev_loop_pr_metrics", SCRIPTS / "dev_loop_pr_metrics.py")
assert spec is not None and spec.loader is not None
metrics = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = metrics
spec.loader.exec_module(metrics)


class _NoRunsClient:
    repo = "owner/repo"

    def get_paginated(self, *_args, **_kwargs):
        return []


def test_empty_first_pass_run_returns_all_metric_slots() -> None:
    assert metrics.first_pass_green_and_job_seconds(_NoRunsClient(), "branch") == (None, None, None)


def test_medium_budget_reads_workflow_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workflow = tmp_path / "pr.yml"
    workflow.write_text("jobs:\n  medium-test:\n    timeout-minutes: 55\n", encoding="utf-8")
    monkeypatch.setattr(metrics, "MEDIUM_TEST_WORKFLOW_PATH", workflow)

    warning = metrics._medium_budget_warning(55 * 60)

    assert warning is not None
    assert "55 min timeout" in warning
