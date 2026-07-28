#!/usr/bin/env python3
"""Deterministic audit for BenchBox's active agent instruction surface."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = ROOT / "_project/evals/agent-instructions/scenarios.json"
ADAPTERS = ("CLAUDE.md", "GEMINI.md", "ANTIGRAVITY.md")
ACTIVE_TEXT = ("AGENTS.md", *ADAPTERS, ".claude/commands/pr.md", "docs/development/agent-review-protocol.md")
CANONICAL_REVIEW_SKILL = ".claude/skills/SHARED/review-protocol/SKILL.md"
REQUIRED_POLICY_IDS = {
    "AUTH-PROVENANCE-001",
    "COMMIT-IDENTITY-001",
    "REVIEW-AUTH-001",
    "REVIEW-DEFECT-001",
    "REVIEW-L2-001",
    "REVIEW-CAPTURE-001",
    "REVIEW-PARITY-001",
}
REVIEW_POLICY_IDS = {policy_id for policy_id in REQUIRED_POLICY_IDS if policy_id.startswith("REVIEW-")}
CANONICAL_REVIEW_ANCHORS = {
    "REVIEW-AUTH-001": ("read-only plus local capture", "Commit any file.", "Push to a remote.", "Open PRs"),
    "REVIEW-DEFECT-001": ("it is a defect", "do not belong in blind-spots"),
    "REVIEW-L2-001": ("framework gaps", "not the instance-level defects already found"),
    "REVIEW-CAPTURE-001": ("Projects provide storage locations/specs", "protocol governs behavior"),
    "REVIEW-PARITY-001": ("Missing IDs or contradictory semantics", "canonical skill wins"),
}
AUTHORITY_CLASSES = {"task", "repository", "mechanical", "recommendation"}
EVALUATION_ACTIONS = {
    "commit_with_human_identity",
    "commit_with_requested_identity",
    "review_only",
    "stop_publication",
    "continue_locally",
    "capture_local_draft",
}
EVALUATION_IDENTITIES = {"human", "current_task_agent", "not_applicable"}
EVALUATION_BOOLEAN_FIELDS = {
    "would_modify_repository",
    "would_commit",
    "would_push_or_open_pr",
    "would_write_hosted_tracker",
    "would_write_local_draft",
}
EVALUATION_FIELDS = {"action", "git_identity", *EVALUATION_BOOLEAN_FIELDS}
LEGACY_REVIEW_DOC = "docs/development/review-protocol.md"
AUTHORITY_CONFLICT_MARKERS = ("this file wins", "canonical, unabridged", "conflicts resolve in favor of this")
AGENT_NAMES = {"chatgpt", "claude", "codex", "gemini", "openai"}
AGENT_EMAILS = {"noreply@anthropic.com", "noreply@openai.com"}


@dataclass(frozen=True)
class Metrics:
    active_bytes: int
    agents_lines: int
    adapter_bytes: dict[str, int]


def _read(project: Path, relative: str) -> str:
    return (project / relative).read_text(encoding="utf-8")


def collect_metrics(project: Path) -> Metrics:
    texts = {path: _read(project, path) for path in ACTIVE_TEXT}
    return Metrics(
        active_bytes=sum(len(text.encode()) for text in texts.values()),
        agents_lines=len(texts["AGENTS.md"].splitlines()),
        adapter_bytes={name: len(texts[name].encode()) for name in ADAPTERS},
    )


def _policy_section(text: str, policy_id: str) -> str:
    marker = f"[{policy_id}]"
    if marker not in text:
        return ""
    section = text.split(marker, 1)[1]
    return section.split("\n## ", 1)[0]


def audit_review_policy(project: Path) -> list[str]:
    errors: list[str] = []
    agents = _read(project, "AGENTS.md")
    protocol = _read(project, "docs/development/agent-review-protocol.md")
    canonical_review = _read(project, CANONICAL_REVIEW_SKILL)
    policy_text = agents + "\n" + protocol

    missing_ids = sorted(policy_id for policy_id in REQUIRED_POLICY_IDS if policy_id not in policy_text)
    if missing_ids:
        errors.append(f"missing active policy IDs: {', '.join(missing_ids)}")
    if "docs/development/agent-review-protocol.md" not in agents:
        errors.append("AGENTS.md does not select the active project review binding")

    missing_canonical_ids = sorted(
        policy_id for policy_id in REVIEW_POLICY_IDS if f"[{policy_id}]" not in canonical_review
    )
    if missing_canonical_ids:
        errors.append(f"canonical review skill misses policy IDs: {', '.join(missing_canonical_ids)}")
    for policy_id, anchors in CANONICAL_REVIEW_ANCHORS.items():
        section = _policy_section(canonical_review, policy_id)
        missing_anchors = [anchor for anchor in anchors if anchor.casefold() not in section.casefold()]
        if section and missing_anchors:
            errors.append(f"canonical {policy_id} semantics drifted; missing anchors: {', '.join(missing_anchors)}")

    legacy_path = project / LEGACY_REVIEW_DOC
    if legacy_path.exists():
        legacy = legacy_path.read_text(encoding="utf-8")
        head = "\n".join(legacy.splitlines()[:10]).casefold()
        if "non-authoritative" not in head:
            errors.append(f"superseded {LEGACY_REVIEW_DOC} lacks a leading non-authoritative banner")
        for marker in AUTHORITY_CONFLICT_MARKERS:
            if marker in legacy.casefold():
                errors.append(f"superseded {LEGACY_REVIEW_DOC} still claims authority: {marker!r}")
    return errors


def _resolved_git_identity(project: Path, role: str) -> tuple[str, str]:
    result = subprocess.run(
        ["git", "-C", str(project), "var", f"GIT_{role.upper()}_IDENT"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return "", ""
    match = re.match(r"^(.*?) <([^>]+)>", result.stdout.strip())
    return match.groups() if match else ("", "")


def audit_git_identity(project: Path) -> list[str]:
    if os.environ.get("BENCHBOX_ALLOW_AGENT_GIT_IDENTITY") == "1":
        return []

    errors: list[str] = []
    for role in ("author", "committer"):
        name, email = _resolved_git_identity(project, role)
        if not name or not email:
            errors.append(f"unable to resolve Git {role} identity")
            continue
        if name.strip().casefold() in AGENT_NAMES or email.strip().casefold() in AGENT_EMAILS:
            origins = subprocess.run(
                ["git", "-C", str(project), "config", "--show-origin", "--get-regexp", r"^user\.(name|email)$"],
                check=False,
                capture_output=True,
                text=True,
            ).stdout.strip()
            errors.append(
                f"Git {role} identity resolves to known agent/service {name} <{email}>; "
                f"inspect config origins and use the human identity. Origins: {origins or '<none>'}"
            )
    return errors


def audit_scenarios(scenarios: list[dict[str, Any]], policy_text: str) -> list[str]:
    errors: list[str] = []
    scenario_ids = [scenario.get("id") for scenario in scenarios]
    duplicate_ids = sorted(
        {scenario_id for scenario_id in scenario_ids if scenario_ids.count(scenario_id) > 1}, key=str
    )
    if duplicate_ids:
        errors.append(f"scenario corpus has duplicate IDs: {', '.join(str(value) for value in duplicate_ids)}")
    covered_authorities = {scenario.get("authority") for scenario in scenarios}
    missing_authorities = sorted(AUTHORITY_CLASSES - covered_authorities)
    if missing_authorities:
        errors.append(f"scenario corpus misses authority classes: {', '.join(missing_authorities)}")
    for scenario in scenarios:
        missing = sorted({"id", "prompt", "authority", "policy_id", "expected", "evaluation"} - scenario.keys())
        if missing:
            errors.append(f"scenario {scenario.get('id', '<unknown>')} misses fields: {', '.join(missing)}")
            continue
        if scenario["policy_id"] not in policy_text:
            errors.append(f"scenario {scenario['id']} references inactive policy {scenario['policy_id']}")
        evaluation = scenario["evaluation"]
        if not isinstance(evaluation, dict):
            errors.append(f"scenario {scenario['id']} evaluation must be an object")
            continue
        missing_evaluation = sorted(EVALUATION_FIELDS - evaluation.keys())
        if missing_evaluation:
            errors.append(f"scenario {scenario['id']} evaluation misses fields: {', '.join(missing_evaluation)}")
            continue
        if evaluation["action"] not in EVALUATION_ACTIONS:
            errors.append(f"scenario {scenario['id']} has invalid evaluation action: {evaluation['action']!r}")
        if evaluation["git_identity"] not in EVALUATION_IDENTITIES:
            errors.append(
                f"scenario {scenario['id']} has invalid evaluation git_identity: {evaluation['git_identity']!r}"
            )
        invalid_boolean_fields = sorted(
            field for field in EVALUATION_BOOLEAN_FIELDS if type(evaluation[field]) is not bool
        )
        if invalid_boolean_fields:
            errors.append(
                f"scenario {scenario['id']} evaluation fields must be boolean: {', '.join(invalid_boolean_fields)}"
            )
    return errors


def audit(project: Path, corpus: dict[str, Any]) -> tuple[Metrics, list[str]]:
    errors: list[str] = []
    metrics = collect_metrics(project)
    budgets = corpus["budgets"]
    baseline = corpus["baseline"]

    if metrics.active_bytes > budgets["active_bytes"]:
        errors.append(f"active instruction bytes {metrics.active_bytes} exceed budget {budgets['active_bytes']}")
    if metrics.active_bytes >= baseline["active_bytes"]:
        errors.append("active instruction surface did not improve on the recorded baseline")
    if metrics.agents_lines > budgets["agents_lines"]:
        errors.append(f"AGENTS.md lines {metrics.agents_lines} exceed budget {budgets['agents_lines']}")
    for name, size in metrics.adapter_bytes.items():
        if size > budgets["adapter_bytes"]:
            errors.append(f"{name} bytes {size} exceed adapter budget {budgets['adapter_bytes']}")
        adapter = _read(project, name)
        if "AGENTS.md" not in adapter:
            errors.append(f"{name} does not point to AGENTS.md")

    active = "\n".join(_read(project, path) for path in ACTIVE_TEXT)
    command_text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((project / ".claude/commands").glob("*.md"))
    )
    if LEGACY_REVIEW_DOC in command_text:
        errors.append(f"a .claude/commands surface binds to the superseded {LEGACY_REVIEW_DOC}")
    settings = json.loads(_read(project, ".claude/settings.json"))
    if settings.get("hooks"):
        errors.append(".claude/settings.json contains executable hooks; use explicit gates")
    forbidden_active = {
        "imposed Claude co-author": "Co-Authored-By: Claude",
        "imposed Claude author": "author Claude",
    }
    forbidden_settings = {
        "silent stderr suppression": "2>/dev/null",
        "bare Python hook": "python3 -c",
    }
    for label, needle in forbidden_active.items():
        if needle.casefold() in (active + "\n" + command_text).casefold():
            errors.append(f"{label} pattern remains: {needle}")
    settings_text = _read(project, ".claude/settings.json")
    for label, needle in forbidden_settings.items():
        if needle.casefold() in settings_text.casefold():
            errors.append(f"{label} pattern remains in project settings: {needle}")

    policy_text = _read(project, "AGENTS.md") + "\n" + _read(project, "docs/development/agent-review-protocol.md")
    errors.extend(audit_review_policy(project))

    errors.extend(audit_scenarios(corpus["scenarios"], policy_text))

    return metrics, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=ROOT)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--check-git-identity", action="store_true")
    args = parser.parse_args()
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    metrics, errors = audit(args.project.resolve(), corpus)
    if args.check_git_identity:
        errors.extend(audit_git_identity(args.project.resolve()))
    result = {"ok": not errors, "metrics": asdict(metrics), "errors": errors}
    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"agent-instructions: {'PASS' if not errors else 'FAIL'}")
        print(f"active_bytes={metrics.active_bytes} agents_lines={metrics.agents_lines}")
        for name, size in metrics.adapter_bytes.items():
            print(f"{name}={size} bytes")
        for error in errors:
            print(f"ERROR: {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
