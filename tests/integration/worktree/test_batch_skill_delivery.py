"""Integration contracts for the todo-db batch skill rollout."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
CATALOG_REV = "c8473708b5c7809700e8449ecde0dabcdc8e9892"
SOURCE_REV = "74631c83f74b7f184abbd49001f032943b720774"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence() -> dict:
    return json.loads((ROOT / "_project/analysis/batch-rollout-evidence.json").read_text(encoding="utf-8"))


def test_pin_receipt_and_tracked_mirror_bind_catalog_tip() -> None:
    config = (ROOT / "skill-sync.conf").read_text(encoding="utf-8")
    receipt = (ROOT / ".claude/skills/skill-sync.receipt").read_text(encoding="utf-8")
    evidence = _evidence()

    assert f"rev    = {CATALOG_REV}" in config
    assert f"rev = {CATALOG_REV}" in receipt
    assert evidence["catalog"]["merge_revision"] == CATALOG_REV
    assert evidence["source"]["merge_revision"] == SOURCE_REV
    assert evidence["benchbox_pin"]["after"] == CATALOG_REV

    for relative, expected in evidence["mirrors"]["tracked_target"]["files"].items():
        assert _sha256(ROOT / ".claude/skills/todo" / relative) == expected


def test_active_agent_materialization_matches_tracked_snapshot() -> None:
    evidence = _evidence()
    assert evidence["mirrors"]["agents_target"]["materialized"] is True
    for relative in evidence["mirrors"]["tracked_target"]["files"]:
        tracked = ROOT / ".claude/skills/todo" / relative
        active = ROOT / ".agents/skills/todo" / relative
        assert active.is_file()
        assert active.read_bytes() == tracked.read_bytes()


def test_feature_mode_is_capability_gated_and_serial_remains_default() -> None:
    docs = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "AGENTS.md",
            "docs/agent/batch-feature-delivery.md",
            "docs/agent/review-protocol.md",
            "docs/operations/dev-loop-worktrees.md",
        )
    )
    normalized = docs.lower()
    assert "serial mode is the default" in normalized
    assert "active todo-db mcp server" in normalized
    assert "one shared integration branch" in normalized
    assert "one integrator" in normalized
    assert "no feature-base prs" in normalized
    assert "no new ci skips" in normalized
    assert "cannot be used to establish" in normalized or "cannot use feature mode to prove" in normalized


def test_rollout_evidence_records_unsupported_active_runtime() -> None:
    evidence = _evidence()
    runtime = evidence["runtime"]
    assert runtime["compatible_source"]["package_version"] == "0.7.3"
    assert runtime["compatible_source"]["schema_version"] == 3
    assert set(runtime["compatible_source"]["registered_batch_tools"]) == {
        "register_batch",
        "prepare",
        "bind_batch_pr",
        "abort_batch",
    }
    assert runtime["active_benchbox"]["schema_version"] == 1
    assert runtime["active_benchbox"]["registered_batch_tools"] == []
    assert runtime["decision"] == "serial"
