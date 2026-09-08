"""Contract tests for the publication soak monitor workflow."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
MONITOR_PATH = ROOT / ".github" / "workflows" / "publication-soak-monitor.yml"


def _load_yaml(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"Workflow file missing at {path}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_soak_monitor_samples_every_five_minutes() -> None:
    wf = _load_yaml(MONITOR_PATH)
    triggers = wf.get("on") or wf.get(True) or {}

    assert "push" not in triggers
    assert "pull_request" not in triggers
    assert "workflow_dispatch" in triggers
    crons = [entry.get("cron") for entry in triggers.get("schedule", [])]
    assert "*/5 * * * *" in crons


def test_soak_monitor_never_cancels_a_sample() -> None:
    wf = _load_yaml(MONITOR_PATH)
    # Every scheduled sample must execute: GitHub replaces a queued run in a
    # fixed concurrency group even with cancel-in-progress: false, and a
    # replaced sample would be indistinguishable from a missed required sample.
    assert "concurrency" not in wf, "a queued sample replaced by a later tick would restart the soak window"


def test_soak_monitor_compares_live_against_durable_head() -> None:
    wf = _load_yaml(MONITOR_PATH)
    steps = wf["jobs"]["sample"]["steps"]
    text = "\n".join(str(step.get("run", "")) for step in steps)

    assert "read_journal_state" in text
    assert "durable_transaction_id" in text
    assert "no durable head" in text
    assert "no usable route checksums" in text
    assert "--manifest soak-monitor/expected-manifest.json" in text
    assert "--require-receipt" in text


def test_soak_monitor_defers_while_transaction_in_flight() -> None:
    wf = _load_yaml(MONITOR_PATH)
    steps = wf["jobs"]["sample"]["steps"]
    text = "\n".join(str(step.get("run", "")) for step in steps)

    # The live site may already serve the new bytes after Pages activation
    # while the durable head still attests the previous transaction; comparing
    # in that window would record a false digest mismatch.
    assert "active_transaction_id" in text
    assert "deferred" in text
    assert "live publication and durable head may disagree" in text


def test_soak_monitor_records_heartbeat_and_fails_closed() -> None:
    wf = _load_yaml(MONITOR_PATH)
    steps = wf["jobs"]["sample"]["steps"]
    text = "\n".join(str(step.get("run", "")) for step in steps)

    assert "heartbeat.json" in text
    assert "window restarts per runbook" in text
    assert 'heartbeat["deferred"]' in text
    upload_step = next(
        (
            s
            for s in steps
            if "heartbeat" in str(s.get("name", "")).lower() and "upload" in str(s.get("name", "")).lower()
        ),
        None,
    )
    assert upload_step is not None, "heartbeat receipt must be uploaded as a retained artifact"
    assert upload_step["with"]["retention-days"] == 7


def test_soak_monitor_pins_all_actions() -> None:
    text = MONITOR_PATH.read_text(encoding="utf-8")
    action_refs = re.findall(r"uses:\s+([^\s#]+)", text)

    assert action_refs, "expected pinned actions in soak monitor workflow"
    for ref in action_refs:
        assert "@" in ref, f"Action reference '{ref}' is missing version tag or commit SHA"
        name, sha = ref.split("@", 1)
        assert re.fullmatch(r"[0-9a-f]{40}", sha), (
            f"Action '{name}' in publication-soak-monitor.yml must be pinned by a 40-character commit SHA, got: {sha}"
        )


def test_soak_monitor_permissions_follow_least_privilege() -> None:
    wf = _load_yaml(MONITOR_PATH)
    assert wf.get("permissions") == {"contents": "read"}
    assert wf["jobs"]["sample"]["permissions"] == {"contents": "read"}
    assert wf["jobs"]["sample"]["timeout-minutes"] == 10
