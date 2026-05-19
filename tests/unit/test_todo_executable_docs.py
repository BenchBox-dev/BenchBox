"""Guardrails for executable TODO/DONE documentation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[2]

if not (REPO_ROOT / "_project").exists():
    pytest.skip("TODO executable documentation checks require _project/", allow_module_level=True)


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _verification_commands(path: Path) -> list[str]:
    data = _load_yaml(path)
    entries = data.get("verification", [])
    assert isinstance(entries, list)
    commands: list[str] = []
    for entry in entries:
        assert isinstance(entry, dict)
        command = entry.get("command")
        if isinstance(command, str):
            commands.append(command)
    return commands


def _todo_or_done_item(worktree: str, phase: str, filename: str) -> Path:
    for root in ("TODO", "DONE"):
        path = REPO_ROOT / "_project" / root / worktree / phase / filename
        if path.exists():
            return path
    raise AssertionError(f"Could not find TODO/DONE item {worktree}/{phase}/{filename}")


def test_completed_codex_followup_validates_current_done_path() -> None:
    path = REPO_ROOT / "_project" / "DONE" / "main" / "active" / "codex-pr-review-followups-week-2026-05-01.yaml"
    text = path.read_text(encoding="utf-8")

    assert "_project/DONE/main/active/codex-pr-review-followups-week-2026-05-01.yaml" in text
    assert "_project/TODO/main/active/codex-pr-review-followups-week-2026-05-01.yaml" not in text


def test_step_3_ruleset_verification_resolves_develop_ruleset_dynamically() -> None:
    path = (
        REPO_ROOT / "_project" / "DONE" / "main" / "planning" / "dev-loop-step-3-ci-rebalance-and-strict-base-off.yaml"
    )
    commands = _verification_commands(path)
    ruleset_command = next(command for command in commands if "required_status_checks" in command)

    assert "rulesets/15611785" not in ruleset_command
    assert "repos/${repo}/rulesets" in ruleset_command
    assert "refs/heads/develop" in ruleset_command


def test_codex_thread_rescan_audit_does_not_claim_present_blind_spots_are_missing() -> None:
    audit = (REPO_ROOT / "_project" / "audits" / "codex-thread-rescan-week-2026-05-01.md").read_text(encoding="utf-8")

    assert "are not present in this worktree" not in audit
    for stem in ("103000", "103001", "103002"):
        assert stem in audit


def test_joinorder_dataframe_followup_path_uses_seeded_yaml() -> None:
    path = _todo_or_done_item("main", "planning", "joinorder-canonical-cutover.yaml")
    text = path.read_text(encoding="utf-8")

    seeded_path = "_project/TODO/main/planning/track2-joinorder-dataframe-coverage.yaml"
    stale_path = "_project/TODO/main/planning/track2-joinorder-dataframe-coverage.md"

    assert f'f"{seeded_path}"' in text
    assert f"grep -c '{seeded_path}'" in text
    assert stale_path not in text
