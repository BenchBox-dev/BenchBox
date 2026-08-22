"""Tests for the deterministic agent-instruction governance audit."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from path_filter_decision import classify_paths, load_rules

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture(autouse=True)
def _isolate_git_identity_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force identity to resolve from config alone.

    `git var` prefers GIT_AUTHOR_* / GIT_COMMITTER_* / EMAIL over any config
    file, so an ambient value in the invoking shell decides these assertions
    instead of the fixture repo. A cloud session that exports GIT_AUTHOR_* to
    satisfy [COMMIT-IDENTITY-001] does exactly that, and it turned the
    negative identity tests green against a repo configured as an agent.
    Tests that want an ambient identity set it themselves, after this runs.
    """
    for name in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL"):
        monkeypatch.delenv(name, raising=False)


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
CANONICAL_COMMIT_SKILL = agent_instruction_audit.CANONICAL_COMMIT_SKILL
audit = agent_instruction_audit.audit
audit_git_identity = agent_instruction_audit.audit_git_identity
audit_identity_overrides = agent_instruction_audit.audit_identity_overrides
audit_commit_range = agent_instruction_audit.audit_commit_range


def _candidate(tmp_path: Path) -> Path:
    for relative in (
        *ACTIVE_TEXT,
        CANONICAL_REVIEW_SKILL,
        CANONICAL_COMMIT_SKILL,
        ".claude/settings.json",
        "pyproject.toml",
    ):
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
        ".claude/skills/SHARED/investigation-framework/SKILL.md",
        "_project/evals/agent-instructions/scenarios.json",
        "docs/agent/review-protocol.md",
        "skill-sync.lock",
    ],
)
def test_governed_paths_route_to_a_required_instruction_lane(path: str) -> None:
    rules = load_rules(ROOT / ".github/path-filters.yml")
    decision = classify_paths([path], rules)

    assert decision["needs_code_ci"] is True or decision["skill_integrity_needed"] is True
    if path.startswith(".claude/skills/") or path == "skill-sync.lock":
        assert decision["skill_integrity_needed"] is True


def test_imposed_identity_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    command = project / ".claude/commands/pr.md"
    command.write_text(command.read_text() + "\nCo-Authored-By: Claude <noreply@example.com>\n")
    _, errors = audit(project, CORPUS)
    assert any("imposed Claude co-author" in error for error in errors)


def test_canonical_commit_coauthor_consent_drift_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    canonical = project / CANONICAL_COMMIT_SKILL
    canonical.write_text(canonical.read_text().replace("Stale requests", "earlier context"))
    _, errors = audit(project, CORPUS)
    assert any("canonical COMMIT-IDENTITY-001 semantics drifted" in error for error in errors)


def test_project_commit_coauthor_consent_drift_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    agents = project / "AGENTS.md"
    agents.write_text(agents.read_text().replace("not authorization", "may be sufficient"))
    _, errors = audit(project, CORPUS)
    assert any("project COMMIT-IDENTITY-001 semantics drifted" in error for error in errors)


def test_project_write_closeout_drift_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    agents = project / "AGENTS.md"
    agents.write_text(
        agents.read_text().replace(
            "required close-out steps of write authorization, not separate permissions",
            "optional suggestions that require separate user approval",
        )
    )
    _, errors = audit(project, CORPUS)
    assert any("AGENTS.md WRITE-CLOSEOUT-001 semantics drifted" in error for error in errors)


@pytest.mark.parametrize(
    "phrase",
    [
        "explicitly forbids publication",
        "authorizes only a local commit",
        "gate fails",
        "do not stop before",
    ],
)
def test_project_write_closeout_exception_drift_fails(tmp_path: Path, phrase: str) -> None:
    project = _candidate(tmp_path)
    agents = project / "AGENTS.md"
    content = agents.read_text()
    pattern = re.compile(r"\s+".join(re.escape(w) for w in phrase.split()))
    new_content, count = pattern.subn("deleted constraint", content)
    assert count > 0, f"Pattern {phrase} was not found in AGENTS.md"
    agents.write_text(new_content)
    _, errors = audit(project, CORPUS)
    assert any("AGENTS.md WRITE-CLOSEOUT-001 semantics drifted" in error for error in errors)


def test_project_commit_anchor_reflow_passes(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    agents = project / "AGENTS.md"
    agents.write_text(
        agents.read_text().replace("agent work are not authorization\n(", "agent work are not\nauthorization (")
    )
    _, errors = audit(project, CORPUS)
    assert errors == []


@pytest.mark.parametrize(
    "anchor",
    [
        "## Code Review Rules",
        "Do not report commit identity.",
        "Review sandboxes may use synthetic identities.",
        "Hooks and CI check actual commits.",
        "Report only PR defects.",
    ],
)
def test_code_review_identity_noise_guard_drift_fails(tmp_path: Path, anchor: str) -> None:
    project = _candidate(tmp_path)
    agents = project / "AGENTS.md"
    agents.write_text(agents.read_text().replace(anchor, "removed review guard", 1))
    _, errors = audit(project, CORPUS)
    assert any("Code Review Rules" in error for error in errors)


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


def test_unexpected_evaluation_field_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    corpus = json.loads(json.dumps(CORPUS))
    corpus["scenarios"][0]["evaluation"]["would_modify_repository"] = False
    _, errors = audit(project, corpus)
    assert any("evaluation has unexpected fields: would_modify_repository" in error for error in errors)


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
    legacy = project / "docs/agent/review-protocol-legacy.md"
    legacy.write_text(
        "# Review Protocol\n\n> Canonical, unabridged form.\n\nIf a wrapper conflicts with this file, this file wins.\n"
    )
    _, errors = audit(project, CORPUS)
    assert any("lacks a leading non-authoritative banner" in error for error in errors)
    assert any("still claims authority: 'this file wins'" in error for error in errors)
    assert any("still claims authority: 'canonical, unabridged'" in error for error in errors)


def test_superseded_review_doc_with_banner_passes(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    legacy = project / "docs/agent/review-protocol-legacy.md"
    legacy.write_text(
        "# Review Protocol (historical)\n\n"
        "> Historical, non-authoritative. The active behavioral authority is\n"
        "> docs/agent/review-protocol.md.\n\nRetained rationale.\n"
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
    canonical.write_text(
        canonical.read_text().replace("read-only except for local capture", "may modify reviewed code")
    )
    _, errors = audit(project, CORPUS)
    assert any("canonical REVIEW-AUTH-001 semantics drifted" in error for error in errors)


def test_project_review_policy_separate_turn_drift_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    protocol = project / "docs/agent/review-protocol.md"
    protocol.write_text(protocol.read_text().replace("in a\n  later user turn", "separately"))
    _, errors = audit(project, CORPUS)
    assert any("project REVIEW-AUTH-001 semantics drifted" in error for error in errors)


def test_agents_bundled_review_zero_mutation_drift_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    agents = project / "AGENTS.md"
    agents.write_text(agents.read_text().replace("zero tracked worktree-content changes", "some local changes"))
    _, errors = audit(project, CORPUS)
    assert any("AGENTS.md REVIEW-AUTH-001 semantics drifted" in error for error in errors)


def test_project_review_policy_id_missing_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    protocol = project / "docs/agent/review-protocol.md"
    protocol.write_text(protocol.read_text().replace("[REVIEW-AUTH-001]", "[REMOVED-AUTH-ID]"))
    _, errors = audit(project, CORPUS)
    assert any("project review binding misses policy ID: REVIEW-AUTH-001" in error for error in errors)


def test_missing_canonical_review_policy_id_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    canonical = project / CANONICAL_REVIEW_SKILL
    canonical.write_text(canonical.read_text().replace("[REVIEW-L2-001]", "[REMOVED-L2-ID]"))
    _, errors = audit(project, CORPUS)
    assert any("canonical review skill misses policy IDs: REVIEW-L2-001" in error for error in errors)


def test_canonical_plan_reconciliation_policy_drift_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    canonical = project / CANONICAL_REVIEW_SKILL
    canonical.write_text(canonical.read_text().replace("Claim-against-code checking", "Casual code checking"))
    _, errors = audit(project, CORPUS)
    assert any("canonical REVIEW-PLAN-RECON-001 semantics drifted" in error for error in errors)


def test_project_plan_reconciliation_policy_drift_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    protocol = project / "docs/agent/review-protocol.md"
    protocol.write_text(protocol.read_text().replace("Enumerate recorded decision", "Skim prior decision"))
    _, errors = audit(project, CORPUS)
    assert any("project REVIEW-PLAN-RECON-001 semantics drifted" in error for error in errors)


def test_development_agent_doc_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    leaked = project / "docs/development/agent-extra.md"
    leaked.parent.mkdir(parents=True, exist_ok=True)
    leaked.write_text("# stray agent note\n")
    _, errors = audit(project, CORPUS)
    assert any("must live under docs/agent/" in error for error in errors)
    assert any("docs/development/agent-extra.md" in error for error in errors)


def test_missing_sphinx_agent_exclude_fails(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    conf = project / "docs/conf.py"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text('exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]\n')
    _, errors = audit(project, CORPUS)
    assert any("must exclude the docs/agent/ tree from Sphinx" in error for error in errors)


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


def test_signing_service_committer_behind_human_author_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A signing service may hold the committer slot when the author is human."""
    project = _git_configured_repo(tmp_path, "Claude", "noreply@anthropic.com")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Joe Harris")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "joeharris76@gmail.com")
    assert audit_git_identity(project) == []


def test_signing_service_committer_without_human_author_fails(tmp_path: Path) -> None:
    """The allowance is conditional: an agent author is never acceptable."""
    project = _git_configured_repo(tmp_path, "Claude", "noreply@anthropic.com")
    errors = audit_git_identity(project)
    assert any("author identity resolves to known agent/service" in error for error in errors)


def test_repo_local_human_identity_warns_without_failing(tmp_path: Path) -> None:
    """The drift a human identity causes is real but not an error.

    A repo-local human identity is a supported setup, so it must stay
    non-fatal -- but it is still inherited by every linked worktree, which is
    the property worth surfacing.
    """
    project = _git_configured_repo(tmp_path, "Some Human", "human@example.invalid")
    warnings = audit_identity_overrides(project)
    assert len(warnings) == 2
    assert all("repo-local identity override" in warning for warning in warnings)
    assert all("local scope" in warning for warning in warnings)
    assert all(".git/config" in warning for warning in warnings)
    assert audit_git_identity(project) == []


def test_global_only_identity_produces_no_override_warning(tmp_path: Path) -> None:
    """Nothing displaces the global identity, so there is nothing to report."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert audit_identity_overrides(tmp_path) == []


def test_agent_identity_both_warns_and_stays_fatal(tmp_path: Path) -> None:
    """The warning is additive; it must not soften the known-agent rejection."""
    project = _git_configured_repo(tmp_path, "Claude", "noreply@anthropic.com")
    assert len(audit_identity_overrides(project)) == 2
    errors = audit_git_identity(project)
    assert len(errors) == 2
    assert all("known agent/service" in error for error in errors)


def test_worktree_scoped_identity_is_reported_as_an_override(tmp_path: Path) -> None:
    """Worktree scope is an override too, even though it is the safe one.

    Worktree-scoped identity is the prevention mechanism for shared-clone
    contamination, so it must still be *visible* rather than silently trusted.
    """
    project = _git_configured_repo(tmp_path, "Some Human", "human@example.invalid")
    subprocess.run(["git", "-C", str(project), "config", "extensions.worktreeConfig", "true"], check=True)
    subprocess.run(
        ["git", "-C", str(project), "config", "--worktree", "user.email", "scoped@example.invalid"],
        check=True,
    )
    warnings = audit_identity_overrides(project)
    assert any("worktree scope" in warning and "scoped@example.invalid" in warning for warning in warnings)


def test_identity_override_warning_does_not_change_exit_status(tmp_path: Path) -> None:
    """A warning that failed the gate would be bypassed, not heeded.

    Drives the real CLI rather than the function, because the exit status and
    the JSON contract are what callers depend on.
    """
    project = _candidate(tmp_path)
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "Some Human"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "human@example.invalid"], check=True)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "_project/scripts/agent_instruction_audit.py"),
            "--project",
            str(project),
            "--check-git-identity",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["warnings"], payload
    assert any("repo-local identity override" in warning for warning in payload["warnings"])
    assert payload["ok"] is True
    assert result.returncode == 0


def _git_commit(project: Path, message: str, name: str, email: str) -> None:
    (project / "file.txt").write_text(message, encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "file.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(project), "commit", "-q", "-m", message],
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        },
    )


def _git_range_repo(tmp_path: Path) -> Path:
    project = _git_configured_repo(tmp_path, "Joe Harris", "joeharris76@gmail.com")
    _git_commit(project, "base", "Joe Harris", "joeharris76@gmail.com")
    subprocess.run(["git", "-C", str(project), "branch", "-q", "base-ref"], check=True)
    return project


def test_commit_range_accepts_human_authorship(tmp_path: Path) -> None:
    project = _git_range_repo(tmp_path)
    _git_commit(project, "feat: human work", "Joe Harris", "joeharris76@gmail.com")
    assert audit_commit_range(project, "base-ref") == []


def test_commit_range_rejects_agent_authorship(tmp_path: Path) -> None:
    project = _git_range_repo(tmp_path)
    _git_commit(project, "feat: agent work", "Claude", "noreply@anthropic.com")
    errors = audit_commit_range(project, "base-ref")
    assert any("authored by known agent/service Claude <noreply@anthropic.com>" in error for error in errors)


def test_commit_range_rejects_agent_coauthor_trailer(tmp_path: Path) -> None:
    project = _git_range_repo(tmp_path)
    _git_commit(
        project,
        "feat: work\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>",
        "Joe Harris",
        "joeharris76@gmail.com",
    )
    errors = audit_commit_range(project, "base-ref")
    assert any("carries agent Co-Authored-By trailer" in error for error in errors)


def test_commit_range_rejects_agent_coauthor_by_name_with_non_vendor_address(tmp_path: Path) -> None:
    """An agent that signs with its own address is still an agent.

    Matching only the vendor address let this exact trailer through both the
    merge-time guard and the commit-msg hook, which is the attribution
    [COMMIT-IDENTITY-001] exists to reject.
    """
    project = _git_range_repo(tmp_path)
    _git_commit(
        project,
        "feat: work\n\nCo-Authored-By: Claude <claude@example.com>",
        "Joe Harris",
        "joeharris76@gmail.com",
    )
    errors = audit_commit_range(project, "base-ref")
    assert any("carries agent Co-Authored-By trailer" in error for error in errors)


def test_commit_range_accepts_human_coauthor_named_like_a_vendor(tmp_path: Path) -> None:
    """The name arm matches the whole display name, not a substring of it."""
    project = _git_range_repo(tmp_path)
    _git_commit(
        project,
        "feat: work\n\nCo-Authored-By: Claudia Gemini-Lopez <claudia@example.com>",
        "Joe Harris",
        "joeharris76@gmail.com",
    )
    assert audit_commit_range(project, "base-ref") == []


def test_commit_range_rejects_agent_session_trailer(tmp_path: Path) -> None:
    project = _git_range_repo(tmp_path)
    _git_commit(
        project,
        "feat: work\n\nClaude-Session: https://claude.ai/code/session_abc",
        "Joe Harris",
        "joeharris76@gmail.com",
    )
    errors = audit_commit_range(project, "base-ref")
    assert any("carries agent session trailer" in error for error in errors)


def test_commit_range_reports_unresolvable_base_ref(tmp_path: Path) -> None:
    """A missing base ref must surface, never silently pass as 'no findings'."""
    project = _git_range_repo(tmp_path)
    errors = audit_commit_range(project, "origin/does-not-exist")
    assert any("unable to inspect commit range" in error for error in errors)


def test_unresolvable_git_identity_is_not_a_violation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An environment where git resolves no identity must not fail this guard.

    `git var GIT_AUTHOR_IDENT` exits non-zero when it can neither read a
    configured identity nor auto-detect one, and `_resolved_git_identity` then
    returns ("", ""). That is the state of an ephemeral CI runner, and it cannot
    be reproduced by clearing config locally because git synthesises an implicit
    user@host identity instead - so drive the resolver directly.

    The check exists to reject a *known agent* identity; an absent one is
    nothing to judge. `make ci-lint` runs this target and develop-post-merge
    runs ci-lint, so treating absence as an error turned every post-merge run
    red with "unable to resolve Git author identity" once #1523 removed the step
    that injected a placeholder identity to keep the check runnable. Removing
    that injection was right - a check fed a known-good identity can never fail
    - but a check that always fails where no identity exists is as
    uninformative. agent-commit-range-check remains the merge-time control.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(agent_instruction_audit, "_resolved_git_identity", lambda _project, _role: ("", ""))
    assert audit_git_identity(tmp_path) == []


def test_unresolvable_identity_skip_does_not_weaken_the_agent_check(tmp_path: Path) -> None:
    """The skip must not become a blanket pass.

    A guard that returns [] for the absent case is only safe while the populated
    case still fails, so pin both halves together: this is the assertion that
    would catch the skip being widened into "always return []".
    """
    project = _git_configured_repo(tmp_path, "Codex", "codex@openai.com")
    errors = audit_git_identity(project)
    assert len(errors) == 2
    assert all("known agent/service Codex <codex@openai.com>" in error for error in errors)


# ---------------------------------------------------------------------------
# Check attribution and budget headroom.
#
# The pre-commit hook runs the whole audit through one entry point, so before
# these landed a byte-budget failure was reported under a hook named "reject
# stale agent Git identity" and sent an investigation after a Git config problem
# that did not exist.
# ---------------------------------------------------------------------------


def test_every_error_names_the_check_that_produced_it(tmp_path: Path) -> None:
    """A caller must be able to say which check failed, not just that one did."""
    project = _candidate(tmp_path)
    (project / "AGENTS.md").write_text("Co-Authored-By: Claude\n", encoding="utf-8")
    _, errors = audit(project, CORPUS)
    assert errors, "the mutated candidate must fail, or this asserts nothing"
    known = {
        "budget",
        "surface",
        "review-policy",
        "commit-policy",
        "dependency-caps",
        "scenarios",
        "git-identity",
        "commit-range",
    }
    unattributed = [error for error in errors if error.split(":", 1)[0] not in known]
    assert not unattributed, f"errors with no check name: {unattributed}"


def test_a_budget_failure_is_attributed_to_budget_not_identity(tmp_path: Path) -> None:
    """The exact misreport this guards: over-budget must not read as identity."""
    project = _candidate(tmp_path)
    corpus = json.loads(json.dumps(CORPUS))
    corpus["budgets"]["active_bytes"] = 1
    _, errors = audit(project, corpus)
    over = [error for error in errors if "exceed budget" in error]
    assert over, "shrinking the budget must produce an over-budget error"
    assert all(error.startswith("budget: ") for error in over)
    assert agent_instruction_audit.failing_checks(errors)[0] == "budget"


def test_failing_checks_lists_each_check_once_in_first_seen_order() -> None:
    assert agent_instruction_audit.failing_checks(["budget: a", "scenarios: b", "budget: c"]) == [
        "budget",
        "scenarios",
    ]


def test_headroom_warns_near_the_ceiling_and_stays_a_warning() -> None:
    """A near-full surface warns; only exceeding the ceiling is an error."""
    metrics, _ = audit(ROOT, CORPUS)
    budgets = dict(CORPUS["budgets"], active_bytes=metrics.active_bytes + 1)
    warnings = agent_instruction_audit.budget_headroom_warnings(metrics, budgets)
    assert any("active instruction bytes" in warning for warning in warnings)
    # The same near-full state must not be an error - the budget is the gate.
    _, errors = audit(ROOT, dict(CORPUS, budgets=budgets))
    assert not [error for error in errors if "exceed budget" in error]


def test_headroom_is_silent_with_room_to_spare() -> None:
    metrics, _ = audit(ROOT, CORPUS)
    budgets = dict(CORPUS["budgets"], active_bytes=metrics.active_bytes * 10)
    warnings = agent_instruction_audit.budget_headroom_warnings(metrics, budgets)
    assert not [warning for warning in warnings if "active instruction bytes" in warning]


def test_the_precommit_hook_name_does_not_claim_a_single_check() -> None:
    """The hook runs the full audit, so its name must not promise only identity.

    Pinning the name is the only mechanical guard available here: pre-commit
    prints the hook name, not the command, when a hook fails.
    """
    import yaml

    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = [hook for repo in config["repos"] for hook in repo.get("hooks", [])]
    hook = next(hook for hook in hooks if hook["id"] == "agent-git-identity")
    assert "agent-identity-check" in hook["entry"], "this test tracks the full-audit entry point"
    assert "instruction" in hook["name"].casefold(), (
        f"hook name {hook['name']!r} names only the identity check while running the whole audit"
    )


def test_advertised_dependency_cap_behind_the_manifest_fails(tmp_path: Path) -> None:
    """The exact drift that shipped: AGENTS.md said `pyarrow<24`, manifest said <25."""
    project = _candidate(tmp_path)
    agents = project / "AGENTS.md"
    agents.write_text(agents.read_text().replace("`pyarrow<25`", "`pyarrow<24`"))
    _, errors = audit(project, CORPUS)
    assert any("pyarrow" in error and "dependency-caps" in error for error in errors)


def test_advertised_cap_without_a_manifest_bound_fails(tmp_path: Path) -> None:
    """An advertised cap for a dependency the manifest never bounds is drift too."""
    project = _candidate(tmp_path)
    agents = project / "AGENTS.md"
    agents.write_text(agents.read_text().replace("`duckdb<2`", "`nonexistentpkg<9`"))
    _, errors = audit(project, CORPUS)
    assert any("nonexistentpkg" in error and "declares no upper bound" in error for error in errors)


def test_optional_dependency_caps_are_honoured(tmp_path: Path) -> None:
    """`duckdb` is bounded only under optional-dependencies; that must still count."""
    project = _candidate(tmp_path)
    _, errors = audit(project, CORPUS)
    assert not [error for error in errors if "duckdb" in error]


def test_advertised_cap_is_not_accepted_as_a_version_prefix(tmp_path: Path) -> None:
    """`sqlglot<3` must not pass merely because the manifest says `<31.0.0`."""
    project = _candidate(tmp_path)
    agents = project / "AGENTS.md"
    agents.write_text(agents.read_text().replace("`sqlglot<31`", "`sqlglot<3`"))
    _, errors = audit(project, CORPUS)
    assert any("sqlglot<3" in error and "<31.0.0" in error for error in errors)


def test_each_independent_optional_dependency_keeps_the_advertised_cap(tmp_path: Path) -> None:
    """A bound in `dev` must not hide a missing bound in the `duckdb` extra."""
    project = _candidate(tmp_path)
    manifest = project / "pyproject.toml"
    manifest.write_text(manifest.read_text().replace('duckdb = ["duckdb>=1.0.0,<2.0.0"]', 'duckdb = ["duckdb>=1.0.0"]'))
    _, errors = audit(project, CORPUS)
    assert any("project.optional-dependencies.duckdb" in error and "without that bound" in error for error in errors)


def test_audit_entry_point_imports_without_third_party_packages() -> None:
    """`.github/workflows/pr.yml` runs this file with bare `python3` before `uv sync`.

    A non-stdlib import at module scope hard-fails the required skill-integrity
    lane. That lane is path-filtered, so the PR that introduced `packaging` and
    `tomli` never exercised it.
    """
    source = (ROOT / "_project/scripts/agent_instruction_audit.py").read_text(encoding="utf-8")
    forbidden = ("import packaging", "from packaging", "import tomli", "import tomllib")
    offenders = [needle for needle in forbidden if needle in source]
    assert not offenders, f"audit entry point imports non-stdlib modules: {offenders}"


def test_dependency_group_cap_drift_is_caught(tmp_path: Path) -> None:
    """CI installs with `uv sync --group dev`, so a cap dropped there is real drift."""
    project = _candidate(tmp_path)
    manifest = project / "pyproject.toml"
    text = manifest.read_text(encoding="utf-8")
    head, marker, tail = text.partition("[dependency-groups]")
    manifest.write_text(head + marker + tail.replace('"duckdb>=1.0.0,<2.0.0"', '"duckdb>=1.0.0"', 1))
    _, errors = audit(project, CORPUS)
    assert any("duckdb" in error and "without that bound" in error for error in errors)


def test_a_shorter_advertised_cap_does_not_prefix_match(tmp_path: Path) -> None:
    """`sqlglot<3` must not pass against a manifest bound of `<31.0.0`."""
    project = _candidate(tmp_path)
    agents = project / "AGENTS.md"
    agents.write_text(agents.read_text().replace("`sqlglot<31`", "`sqlglot<3`"))
    _, errors = audit(project, CORPUS)
    assert any("sqlglot" in error and "pins <31" in error for error in errors)


def test_a_non_plain_advertised_cap_is_rejected_not_ignored(tmp_path: Path) -> None:
    """An advertised `<=` used to be dropped by the parser and silently pass."""
    project = _candidate(tmp_path)
    agents = project / "AGENTS.md"
    agents.write_text(agents.read_text().replace("`pyarrow<25`", "`pyarrow<=25`"))
    _, errors = audit(project, CORPUS)
    assert any("pyarrow<=25" in error and "not a plain" in error for error in errors)


def test_missing_review_depth_binding_fails_the_parity_audit(tmp_path: Path) -> None:
    """REVIEW-PARITY-001 requires REVIEW-DEPTH-001; the audit must enforce it."""
    project = _candidate(tmp_path)
    protocol = project / "docs/agent/review-protocol.md"
    protocol.write_text(re.sub(r"- `\[REVIEW-DEPTH-001\]`.*?\n(?=- )", "", protocol.read_text(), flags=re.S))
    _, errors = audit(project, CORPUS)
    assert any("REVIEW-DEPTH-001" in error for error in errors)
