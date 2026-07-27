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
REQUIRED_POLICY_IDS = {
    "AUTH-PROVENANCE-001",
    "COMMIT-IDENTITY-001",
    "REVIEW-AUTH-001",
    "REVIEW-DEFECT-001",
    "REVIEW-L2-001",
    "REVIEW-CAPTURE-001",
    "REVIEW-PARITY-001",
}
AUTHORITY_CLASSES = {"task", "repository", "mechanical", "recommendation"}
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

    agents = _read(project, "AGENTS.md")
    protocol = _read(project, "docs/development/agent-review-protocol.md")
    policy_text = agents + "\n" + protocol
    missing_ids = sorted(policy_id for policy_id in REQUIRED_POLICY_IDS if policy_id not in policy_text)
    if missing_ids:
        errors.append(f"missing active policy IDs: {', '.join(missing_ids)}")
    if "docs/development/agent-review-protocol.md" not in agents:
        errors.append("AGENTS.md does not select the active project review binding")

    scenarios = corpus["scenarios"]
    covered_authorities = {scenario.get("authority") for scenario in scenarios}
    missing_authorities = sorted(AUTHORITY_CLASSES - covered_authorities)
    if missing_authorities:
        errors.append(f"scenario corpus misses authority classes: {', '.join(missing_authorities)}")
    for scenario in scenarios:
        missing = sorted({"id", "prompt", "authority", "policy_id", "expected"} - scenario.keys())
        if missing:
            errors.append(f"scenario {scenario.get('id', '<unknown>')} misses fields: {', '.join(missing)}")
        elif scenario["policy_id"] not in policy_text:
            errors.append(f"scenario {scenario['id']} references inactive policy {scenario['policy_id']}")

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
