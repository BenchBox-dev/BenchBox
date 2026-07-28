"""Tests for the deterministic agent-instruction governance audit."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from path_filter_decision import classify_paths, load_rules

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
CORPUS = json.loads((ROOT / "_project/evals/agent-instructions/scenarios.json").read_text())


def _load_audit():
    path = ROOT / "_project/scripts/agent_instruction_audit.py"
    spec = importlib.util.spec_from_file_location("agent_instruction_audit", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


agent_instruction_audit = _load_audit()
ACTIVE_TEXT = agent_instruction_audit.ACTIVE_TEXT
CANONICAL_REVIEW_SKILL = agent_instruction_audit.CANONICAL_REVIEW_SKILL
audit = agent_instruction_audit.audit
audit_git_identity = agent_instruction_audit.audit_git_identity


def _candidate(tmp_path: Path) -> Path:
    for relative in (*ACTIVE_TEXT, CANONICAL_REVIEW_SKILL, ".claude/settings.json"):
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return tmp_path


def test_repository_candidate_passes() -> None:
    metrics, errors = audit(ROOT, CORPUS)
    assert errors == []
    assert metrics.active_bytes < CORPUS["baseline"]["active_bytes"]


@pytest.mark.parametrize(
    "path",
    [
        "AGENTS.md",
        ".claude/settings.json",
        ".claude/skills/SHARED/context-guide/SKILL.md",
        "_project/evals/agent-instructions/scenarios.json",
        "docs/development/agent-review-protocol.md",
        "skill-sync.lock",
    ],
)
def test_governed_paths_route_to_required_code_ci(path: str) -> None:
    rules = load_rules(ROOT / ".github/path-filters.yml")
    assert classify_paths([path], rules)["needs_code_ci"] is True


def test_imposed_identity_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    command = project / ".claude/commands/pr.md"
    command.write_text(command.read_text() + "\nCo-Authored-By: Claude <noreply@example.com>\n")
    _, errors = audit(project, CORPUS)
    assert any("imposed Claude co-author" in error for error in errors)


def test_executable_hook_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    settings = project / ".claude/settings.json"
    data = json.loads(settings.read_text())
    data["hooks"] = {"PostToolUse": [{"command": "uv run ruff --fix"}]}
    settings.write_text(json.dumps(data))
    _, errors = audit(project, CORPUS)
    assert any("contains executable hooks" in error for error in errors)


def test_missing_authority_scenario_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    corpus = dict(CORPUS)
    corpus["scenarios"] = [item for item in CORPUS["scenarios"] if item["authority"] != "mechanical"]
    _, errors = audit(project, corpus)
    assert any("misses authority classes: mechanical" in error for error in errors)


def test_duplicate_scenario_id_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    corpus = json.loads(json.dumps(CORPUS))
    corpus["scenarios"].append(dict(corpus["scenarios"][0]))
    _, errors = audit(project, corpus)
    assert any("duplicate IDs: task-specific-identity" in error for error in errors)


def test_missing_evaluation_field_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    corpus = json.loads(json.dumps(CORPUS))
    del corpus["scenarios"][0]["evaluation"]["would_commit"]
    _, errors = audit(project, corpus)
    assert any("evaluation misses fields: would_commit" in error for error in errors)


def test_non_object_evaluation_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    corpus = json.loads(json.dumps(CORPUS))
    corpus["scenarios"][0]["evaluation"] = "commit"
    _, errors = audit(project, corpus)
    assert any("evaluation must be an object" in error for error in errors)


def test_invalid_evaluation_values_fail(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    corpus = json.loads(json.dumps(CORPUS))
    evaluation = corpus["scenarios"][0]["evaluation"]
    evaluation["action"] = "invent_policy"
    evaluation["git_identity"] = "claude"
    evaluation["would_commit"] = "yes"
    _, errors = audit(project, corpus)
    assert any("invalid evaluation action: 'invent_policy'" in error for error in errors)
    assert any("invalid evaluation git_identity: 'claude'" in error for error in errors)
    assert any("evaluation fields must be boolean: would_commit" in error for error in errors)


def test_superseded_review_doc_claiming_authority_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    legacy = project / "docs/development/review-protocol.md"
    legacy.write_text(
        "# Review Protocol\n\n> Canonical, unabridged form.\n\nIf a wrapper conflicts with this file, this file wins.\n"
    )
    _, errors = audit(project, CORPUS)
    assert any("lacks a leading non-authoritative banner" in error for error in errors)
    assert any("still claims authority: 'this file wins'" in error for error in errors)
    assert any("still claims authority: 'canonical, unabridged'" in error for error in errors)


def test_superseded_review_doc_with_banner_passes(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    legacy = project / "docs/development/review-protocol.md"
    legacy.write_text(
        "# Review Protocol (historical)\n\n"
        "> Historical, non-authoritative. The active behavioral authority is\n"
        "> docs/development/agent-review-protocol.md.\n\nRetained rationale.\n"
    )
    _, errors = audit(project, CORPUS)
    assert errors == []


def test_command_bound_to_superseded_review_doc_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    command = project / ".claude/commands/pr.md"
    command.write_text(command.read_text() + "\nFollow docs/development/review-protocol.md exactly.\n")
    _, errors = audit(project, CORPUS)
    assert any("binds to the superseded docs/development/review-protocol.md" in error for error in errors)


def test_canonical_review_policy_semantic_drift_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    canonical = project / CANONICAL_REVIEW_SKILL
    canonical.write_text(canonical.read_text().replace("read-only plus local capture", "may modify reviewed code"))
    _, errors = audit(project, CORPUS)
    assert any("canonical REVIEW-AUTH-001 semantics drifted" in error for error in errors)


def test_missing_canonical_review_policy_id_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    canonical = project / CANONICAL_REVIEW_SKILL
    canonical.write_text(canonical.read_text().replace("[REVIEW-L2-001]", "[REMOVED-L2-ID]"))
    _, errors = audit(project, CORPUS)
    assert any("canonical review skill misses policy IDs: REVIEW-L2-001" in error for error in errors)


def _git_configured_repo(tmp_path: Path, name: str, email: str) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", name], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", email], check=True)
    return tmp_path


def test_human_git_identity_passes(tmp_path: Path) -> None:
    project = _git_configured_repo(tmp_path, "Joe Harris", "joeharris76@gmail.com")
    assert audit_git_identity(project) == []


def test_repository_local_agent_identity_fails(tmp_path: Path) -> None:
    project = _git_configured_repo(tmp_path, "Claude", "noreply@anthropic.com")
    errors = audit_git_identity(project)
    assert len(errors) == 2
    assert all("known agent/service Claude <noreply@anthropic.com>" in error for error in errors)
    assert all(".git/config" in error for error in errors)


def test_explicit_task_local_agent_identity_override_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _git_configured_repo(tmp_path, "Claude", "noreply@anthropic.com")
    monkeypatch.setenv("BENCHBOX_ALLOW_AGENT_GIT_IDENTITY", "1")
    assert audit_git_identity(project) == []
