#!/usr/bin/env python3
"""Deterministic audit for BenchBox's active agent instruction surface."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = ROOT / "_project/evals/agent-instructions/scenarios.json"
ADAPTERS = ("CLAUDE.md", "GEMINI.md", "ANTIGRAVITY.md")
ACTIVE_REVIEW_PROTOCOL = "docs/agent/review-protocol.md"
ACTIVE_TEXT = ("AGENTS.md", *ADAPTERS, ".claude/commands/pr.md", ACTIVE_REVIEW_PROTOCOL)
CANONICAL_REVIEW_SKILL = ".claude/skills/SHARED/review-protocol/SKILL.md"
CANONICAL_COMMIT_SKILL = ".claude/skills/SHARED/change-framework/SKILL.md"
REQUIRED_POLICY_IDS = {
    "AUTH-PROVENANCE-001",
    "COMMIT-IDENTITY-001",
    "REVIEW-AUTH-001",
    "REVIEW-DEFECT-001",
    "REVIEW-DEPTH-001",
    "REVIEW-L2-001",
    "REVIEW-CAPTURE-001",
    "REVIEW-PARITY-001",
    "REVIEW-PLAN-RECON-001",
    "WRITE-CLOSEOUT-001",
}
REVIEW_POLICY_IDS = {policy_id for policy_id in REQUIRED_POLICY_IDS if policy_id.startswith("REVIEW-")}
CANONICAL_REVIEW_ANCHORS = {
    "REVIEW-AUTH-001": (
        "read-only except for local capture",
        "Commit any file.",
        "Push to a remote.",
        "Open PRs",
        "authorization in a later turn",
        "without changing tracked worktree content",
        "combines review and remediation remains review-only",
    ),
    "REVIEW-DEPTH-001": ("L1", "L2", "L3"),
    "REVIEW-DEFECT-001": ("classify it as a defect", "never in blind-spots"),
    "REVIEW-L2-001": ("gaps in the review framework", "not defects already found"),
    "REVIEW-CAPTURE-001": ("protocol governs behavior", "governs storage formats"),
    "REVIEW-PARITY-001": ("Missing IDs or contradictory semantics", "skill governs behavior"),
    "REVIEW-PLAN-RECON-001": (
        "Claim-against-code checking",
        "enumerate the recorded decision surfaces",
        "future-state index and its priority tiers",
        "migration gates in design docs",
        "readiness and evidence documents",
        "open tracker items at the relevant priority",
        "cite each one or explicitly supersede it",
        "dropped open gate, is a plan defect",
    ),
}
# The author/committer anchors are load-bearing: the audit previously pinned
# only the trailer semantics, so the canonical skill could require a human
# *committer* while the shipped gate allowed a signing service there, and
# `agent-instructions-check` would still report the surface as valid.
CANONICAL_COMMIT_ANCHORS = {
    "COMMIT-IDENTITY-001": (
        "Co-Authored-By",
        "requests that exact trailer",
        "Stale requests",
        "do not grant permission",
        "human author identity",
        "committer behind a human author",
    )
}
PROJECT_COMMIT_ANCHORS = {
    "COMMIT-IDENTITY-001": (
        "Co-Authored-By",
        "exact trailer",
        "not authorization",
        "identities as author",
        "committer slot behind a human author",
    )
}
PROJECT_REVIEW_ANCHORS = {
    "REVIEW-AUTH-001": ("later user turn", "bundling review and remediation"),
    "REVIEW-PLAN-RECON-001": (
        "Enumerate recorded decision",
        "future-state index/tiers",
        "migration gates",
        "readiness docs",
        "open tracker items",
        "Cite or supersede each",
        "dropped open gate is a defect",
    ),
}
AGENT_REVIEW_ANCHORS = {"REVIEW-AUTH-001": ("zero tracked worktree-content changes", "do not review and then edit")}
AGENT_WRITE_ANCHORS = {
    "WRITE-CLOSEOUT-001": (
        "authorized write workflow closes at a named branch",
        "make pr-open",
        "auto-merge stays withheld until",
        "make pr-ready",
        "required close-out steps of write authorization, not separate permissions",
        "do not stop before",
        "explicitly forbids publication",
        "authorizes only a local commit",
        "gate fails",
    )
}
CODE_REVIEW_RULE_ANCHORS = (
    "Do not report commit identity.",
    "Review sandboxes may use synthetic identities.",
    "Hooks and CI check actual commits.",
    "Report only PR defects.",
)
AUTHORITY_CLASSES = {"task", "repository", "mechanical", "recommendation"}
EVALUATION_ACTIONS = {
    "commit_with_human_identity",
    "review_only",
    "stop_publication",
    "continue_locally",
    "capture_local_draft",
}
EVALUATION_IDENTITIES = {"human", "current_task_agent", "not_applicable"}
EVALUATION_BOOLEAN_FIELDS = {
    "would_change_tracked_worktree_content",
    "would_commit",
    "would_add_agent_coauthor",
    "would_push_or_open_pr",
    "would_write_hosted_tracker",
    "would_write_local_draft",
}
EVALUATION_FIELDS = {"action", "git_identity", *EVALUATION_BOOLEAN_FIELDS}
LEGACY_REVIEW_DOC = "docs/agent/review-protocol-legacy.md"
RETIRED_REVIEW_DOCS = (
    LEGACY_REVIEW_DOC,
    "docs/development/review-protocol.md",
    "docs/development/agent-review-protocol.md",
)
AUTHORITY_CONFLICT_MARKERS = ("this file wins", "canonical, unabridged", "conflicts resolve in favor of this")
AGENT_NAMES = {"chatgpt", "claude", "codex", "gemini", "openai"}
AGENT_EMAILS = {"noreply@anthropic.com", "noreply@openai.com"}
# Scopes that legitimately carry the user's own identity. Anything else is an
# override worth surfacing -- see audit_identity_overrides.
GLOBAL_IDENTITY_SCOPES = frozenset({"global", "system"})
# [COMMIT-IDENTITY-001] binds authorship. A commit-signing service may hold the
# committer slot -- cloud agent sessions SSH-sign with a key registered to this
# address, and a committer email that does not match it makes the signature
# unverifiable -- but only behind a human author, so attribution stays honest.
SIGNING_SERVICE_EMAILS = {"noreply@anthropic.com"}
# Trailers that attribute authorship to an agent. The trailer identity is parsed
# and run through the same name-or-email predicate used for authors: matching on
# the vendor address alone let `Co-Authored-By: Claude <claude@example.com>`
# through both this guard and the commit-msg hook, which is precisely the
# attribution [COMMIT-IDENTITY-001] exists to reject.
AGENT_TRAILER_RE = re.compile(r"^[ \t]*co-authored-by:[ \t]*(.+)$", re.IGNORECASE | re.MULTILINE)
# `Display Name <address>`; the address is optional so a malformed trailer still
# resolves to a name rather than silently parsing as neither.
TRAILER_IDENTITY_RE = re.compile(r"^(?P<name>[^<]*?)\s*(?:<(?P<email>[^>]*)>)?\s*$")
AGENT_SESSION_TRAILER_RE = re.compile(
    r"^[ \t]*(claude|codex|gemini|chatgpt)-session:[ \t]*(.+)$", re.IGNORECASE | re.MULTILINE
)


@dataclass(frozen=True)
class Metrics:
    active_bytes: int
    agents_lines: int
    adapter_bytes: dict[str, int]


def _read(project: Path, relative: str) -> str:
    return (project / relative).read_text(encoding="utf-8")


def _tag(check: str, errors: Iterable[str]) -> list[str]:
    """Prefix each message with the check that produced it."""
    return [f"{check}: {error}" for error in errors]


def failing_checks(errors: Iterable[str]) -> list[str]:
    """Distinct check names present in *errors*, in first-seen order."""
    seen: list[str] = []
    for error in errors:
        check = error.split(":", 1)[0]
        if check not in seen:
            seen.append(check)
    return seen


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
    parts = re.split(r"\n\s*(?:##\s+|`?\[[A-Z0-9_-]+\])", section, maxsplit=1)
    return parts[0]


def _missing_anchors(text: str, anchors: Iterable[str]) -> list[str]:
    normalized_text = " ".join(text.casefold().split())
    return [anchor for anchor in anchors if " ".join(anchor.casefold().split()) not in normalized_text]


def audit_review_policy(project: Path) -> list[str]:
    errors: list[str] = []
    agents = _read(project, "AGENTS.md")
    protocol = _read(project, ACTIVE_REVIEW_PROTOCOL)
    canonical_review = _read(project, CANONICAL_REVIEW_SKILL)
    policy_text = agents + "\n" + protocol

    missing_ids = sorted(policy_id for policy_id in REQUIRED_POLICY_IDS if policy_id not in policy_text)
    if missing_ids:
        errors.append(f"missing active policy IDs: {', '.join(missing_ids)}")
    if ACTIVE_REVIEW_PROTOCOL not in agents:
        errors.append("AGENTS.md does not select the active project review binding")

    marker = "## Code Review Rules"
    if marker not in agents:
        errors.append("AGENTS.md misses the Code Review Rules section")
    else:
        review_rules = agents.split(marker, 1)[1].split("\n## ", 1)[0]
        missing_anchors = _missing_anchors(review_rules, CODE_REVIEW_RULE_ANCHORS)
        if missing_anchors:
            errors.append(f"AGENTS.md Code Review Rules drifted; missing anchors: {', '.join(missing_anchors)}")

    missing_canonical_ids = sorted(
        policy_id for policy_id in REVIEW_POLICY_IDS if f"[{policy_id}]" not in canonical_review
    )
    if missing_canonical_ids:
        errors.append(f"canonical review skill misses policy IDs: {', '.join(missing_canonical_ids)}")
    for policy_id, anchors in CANONICAL_REVIEW_ANCHORS.items():
        section = _policy_section(canonical_review, policy_id)
        missing_anchors = _missing_anchors(section, anchors)
        if section and missing_anchors:
            errors.append(f"canonical {policy_id} semantics drifted; missing anchors: {', '.join(missing_anchors)}")
    for policy_id, anchors in PROJECT_REVIEW_ANCHORS.items():
        section = _policy_section(protocol, policy_id)
        if not section:
            errors.append(f"project review binding misses policy ID: {policy_id}")
            continue
        missing_anchors = _missing_anchors(section, anchors)
        if missing_anchors:
            errors.append(f"project {policy_id} semantics drifted; missing anchors: {', '.join(missing_anchors)}")
    for policy_id, anchors in AGENT_REVIEW_ANCHORS.items():
        section = _policy_section(agents, policy_id)
        missing_anchors = _missing_anchors(section, anchors)
        if not section:
            errors.append(f"AGENTS.md review policy misses policy ID: {policy_id}")
        elif missing_anchors:
            errors.append(f"AGENTS.md {policy_id} semantics drifted; missing anchors: {', '.join(missing_anchors)}")

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


def audit_commit_policy(project: Path) -> list[str]:
    errors: list[str] = []
    agents = _read(project, "AGENTS.md")
    canonical_commit = _read(project, CANONICAL_COMMIT_SKILL)
    for policy_id, anchors in CANONICAL_COMMIT_ANCHORS.items():
        section = _policy_section(canonical_commit, policy_id)
        missing_anchors = _missing_anchors(section, anchors)
        if not section:
            errors.append(f"canonical commit skill misses policy ID: {policy_id}")
        elif missing_anchors:
            errors.append(f"canonical {policy_id} semantics drifted; missing anchors: {', '.join(missing_anchors)}")
    for policy_id, anchors in PROJECT_COMMIT_ANCHORS.items():
        section = _policy_section(agents, policy_id)
        missing_anchors = _missing_anchors(section, anchors)
        if not section:
            errors.append(f"project commit policy misses policy ID: {policy_id}")
        elif missing_anchors:
            errors.append(f"project {policy_id} semantics drifted; missing anchors: {', '.join(missing_anchors)}")
    for policy_id, anchors in AGENT_WRITE_ANCHORS.items():
        section = _policy_section(agents, policy_id)
        missing_anchors = _missing_anchors(section, anchors)
        if not section:
            errors.append(f"AGENTS.md write policy misses policy ID: {policy_id}")
        elif missing_anchors:
            errors.append(f"AGENTS.md {policy_id} semantics drifted; missing anchors: {', '.join(missing_anchors)}")
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


def _is_agent_identity(name: str, email: str) -> bool:
    return name.strip().casefold() in AGENT_NAMES or email.strip().casefold() in AGENT_EMAILS


def _trailer_is_agent(trailer: str) -> bool:
    """Apply the author name-or-email predicate to a `Co-Authored-By` value.

    An agent that signs with a non-vendor address (`Claude <claude@example.com>`)
    is recognised by name, exactly as it would be in the author slot.
    """
    match = TRAILER_IDENTITY_RE.match(trailer.strip())
    if match is None:
        return False
    return _is_agent_identity(match.group("name") or "", match.group("email") or "")


def _identity_origins(project: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(project), "config", "--show-origin", "--get-regexp", r"^user\.(name|email)$"],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()


def audit_git_identity(project: Path) -> list[str]:
    if os.environ.get("BENCHBOX_ALLOW_AGENT_GIT_IDENTITY") == "1":
        return []

    identities = {role: _resolved_git_identity(project, role) for role in ("author", "committer")}
    author_name, author_email = identities["author"]
    author_is_human = bool(author_name and author_email) and not _is_agent_identity(author_name, author_email)

    # No resolvable identity is not a violation. This check exists to reject a
    # *known agent* identity, and an absent one is nothing to judge - so
    # failing here says only "this environment has no git config", which is the
    # normal state of an ephemeral CI runner. `make ci-lint` runs this target
    # and `develop-post-merge.yml` runs ci-lint, so treating absence as an error
    # made every post-merge run red with "unable to resolve Git author
    # identity" once #1523 removed the step that injected a placeholder
    # identity to keep the check runnable.
    #
    # That injection was removed for the right reason - a check fed a known-good
    # identity can never fail - but the inverse is just as useless: a check that
    # always fails where no identity exists. Locally the absence cannot occur in
    # a way that matters, because git refuses to commit without one. The real
    # merge-time control is agent-commit-range-check, which inspects the commits
    # the branch actually carries.
    if not all(name and email for name, email in identities.values()):
        return []

    errors: list[str] = []
    for role, (name, email) in identities.items():
        if not _is_agent_identity(name, email):
            continue
        # A signing service behind a human author keeps signatures verifiable
        # without misattributing the work; an agent author is never acceptable.
        if role == "committer" and author_is_human and email.strip().casefold() in SIGNING_SERVICE_EMAILS:
            continue
        errors.append(
            f"Git {role} identity resolves to known agent/service {name} <{email}>; "
            f"inspect config origins and use the human identity. "
            f"Origins: {_identity_origins(project) or '<none>'}"
        )
    return errors


def audit_identity_overrides(project: Path) -> list[str]:
    """Non-fatal warnings for a Git identity that displaces the user's global one.

    Detection only, and deliberately so. The audit never writes config and runs
    after configuration may already have changed, so this cannot stop a
    concurrent session from contaminating a shared clone -- it only makes the
    contamination visible. Prevention belongs to worktree-scoped identity set at
    claim time, not here.

    `local` is the scope that bites: from inside a linked worktree, `--local`
    resolves to the *common* config, so a single write there reauthors the
    primary clone and every worktree it owns at once. `worktree` and `command`
    are reported too, because any of them silently displaces the global identity
    while looking like it came from the user's own settings.

    Human values warn rather than fail: a repo-local human identity is a normal,
    supported setup, and making it fatal would turn a visibility aid into a
    compatibility break that also drowns out the known-agent check in
    `audit_git_identity`, which stays fatal.
    """
    result = subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "config",
            "--show-scope",
            "--show-origin",
            "--get-regexp",
            r"^user\.(name|email)$",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    warnings: list[str] = []
    for line in result.stdout.splitlines():
        scope, _, remainder = line.partition("\t")
        origin, _, entry = remainder.partition("\t")
        key, _, value = entry.partition(" ")
        if not key or scope in GLOBAL_IDENTITY_SCOPES:
            continue
        warnings.append(
            f"repo-local identity override: {key}={value} resolves from the {scope} scope "
            f"({origin or '<unknown origin>'}) and displaces your global identity. "
            f"A local-scope value is shared by the primary clone and every linked worktree. "
            f"Detection only: confirm it is intentional."
        )
    return warnings


def audit_commit_range(project: Path, base_ref: str) -> list[str]:
    """Merge-time guard over the commits a branch actually carries.

    `audit_git_identity` reads the resolved config, which on a CI runner is the
    runner's own identity and says nothing about what the branch contains. This
    walks `base_ref..HEAD` instead, so an agent-authored commit produced in some
    other session cannot reach a protected branch unnoticed.
    """
    if os.environ.get("BENCHBOX_ALLOW_AGENT_GIT_IDENTITY") == "1":
        return []

    # Separators are written as git's own %xNN escapes: a literal NUL cannot be
    # passed through argv, and commit messages may contain anything else.
    unit, record = "\x1f", "\x00"
    result = subprocess.run(
        ["git", "-C", str(project), "log", "--format=%H%x1f%an%x1f%ae%x1f%B%x00", f"{base_ref}..HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return [f"unable to inspect commit range {base_ref}..HEAD: {result.stderr.strip() or '<no detail>'}"]

    errors: list[str] = []
    for raw in result.stdout.split(record):
        fields = raw.strip("\n").split(unit)
        if len(fields) < 4:
            continue
        sha, name, email, body = fields[0], fields[1], fields[2], fields[3]
        if _is_agent_identity(name, email):
            errors.append(
                f"commit {sha[:12]} is authored by known agent/service {name} <{email}>; "
                f"reauthor it with the human identity before merging"
            )
        for match in AGENT_TRAILER_RE.finditer(body):
            trailer = match.group(1).strip()
            if _trailer_is_agent(trailer):
                errors.append(
                    f"commit {sha[:12]} carries agent Co-Authored-By trailer '{trailer}'; "
                    f"[COMMIT-IDENTITY-001] forbids it unless the task requested that exact trailer"
                )
        for match in AGENT_SESSION_TRAILER_RE.finditer(body):
            errors.append(
                f"commit {sha[:12]} carries agent session trailer '{match.group(0).strip()}'; "
                f"[COMMIT-IDENTITY-001] treats it as equivalent agent attribution"
            )
    return errors


def _requirement_name(requirement: str) -> str:
    """Leading distribution name of a PEP 508 requirement string."""
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    return match.group(1) if match else ""


def _normalize(name: str) -> str:
    """PEP 503 normalized name, so `foo_bar` and `Foo-Bar` compare equal."""
    return re.sub(r"[-_.]+", "-", name).casefold()


def _version_tuple(version: str) -> tuple[int, ...] | None:
    """Numeric release components, or None when the version is not comparable."""
    release = re.match(r"(\d+(?:\.\d+)*)", version.strip())
    if not release:
        return None
    return tuple(int(part) for part in release.group(1).split("."))


def _upper_bounds(requirement: str) -> list[str]:
    """Every `<` bound in a requirement, excluding `<=`."""
    specifier = requirement.split(";", 1)[0]
    return re.findall(r"<(?!=)\s*([0-9][0-9A-Za-z_.*+!-]*)", specifier)


def _manifest_requirements(manifest: str) -> dict[str, list[str]]:
    """Quoted requirement strings per dependency table, stdlib-only.

    Deliberately not `tomllib`/`tomli`/`packaging`: `.github/workflows/pr.yml`
    runs this file with bare `python3` before `uv sync`, so a non-stdlib import
    here hard-fails the required skill-integrity lane. 3.10 is also supported
    and has no `tomllib`.
    """
    groups: dict[str, list[str]] = {}
    table = ""
    key = ""
    for line in manifest.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            table = stripped.strip("[]")
            key = ""
            continue
        assignment = re.match(r"([A-Za-z0-9._-]+)\s*=", stripped)
        if assignment:
            key = assignment.group(1)
        if table not in {"project", "project.optional-dependencies", "dependency-groups"}:
            continue
        if table == "project" and key != "dependencies":
            continue
        label = table if table != "project" else "project.dependencies"
        if table != "project" and key:
            label = f"{table}.{key}"
        for quoted in re.findall(r'"([^"]+)"', stripped):
            if _requirement_name(quoted):
                groups.setdefault(label, []).append(quoted)
    return groups


def audit_dependency_caps(project: Path) -> list[str]:
    """Pin AGENTS.md's advertised dependency caps to `pyproject.toml`.

    AGENTS.md restates upper bounds so an agent does not have to open the
    manifest. A restated fact drifts silently: the file advertised
    `pyarrow<24` while the manifest had moved to `<25`. This is the
    deterministic invariant `docs/operations/agent-instruction-evaluation.md`
    asks for -- it fails the audit instead of relying on a reader noticing.

    Every dependency table is scanned, `[dependency-groups]` included: CI
    installs with `uv sync --group dev`, so a cap dropped there is a cap the
    real install path loses.
    """
    errors: list[str] = []
    agents = _read(project, "AGENTS.md")
    caps_line = next((line for line in agents.splitlines() if "Current caps" in line), "")
    if not caps_line:
        return ["AGENTS.md does not advertise dependency caps"]

    _, _, tail = caps_line.partition("Current caps")
    entries = re.findall(r"`([^`]+)`", tail.partition(":")[2])
    advertised: dict[str, str] = {}
    for entry in entries:
        parsed = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)<([0-9][0-9A-Za-z_.]*)", entry.strip())
        if not parsed:
            errors.append(f"AGENTS.md caps entry `{entry}` is not a plain `name<version`")
            continue
        advertised[parsed.group(1)] = parsed.group(2)
    if not advertised:
        return errors or ["AGENTS.md dependency caps line has no parsable `name<version` entries"]

    try:
        manifest = (project / "pyproject.toml").read_text(encoding="utf-8")
    except OSError as exc:
        return [*errors, f"cannot read pyproject.toml: {exc}"]
    requirement_groups = _manifest_requirements(manifest)

    for name, cap in sorted(advertised.items()):
        wanted = _version_tuple(cap)
        if wanted is None:
            errors.append(f"AGENTS.md advertises `{name}<{cap}` with an uncomparable version")
            continue
        matches = [
            (label, requirement)
            for label, requirements in requirement_groups.items()
            for requirement in requirements
            if _normalize(_requirement_name(requirement)) == _normalize(name)
        ]
        if not matches:
            errors.append(f"AGENTS.md advertises `{name}<{cap}` but pyproject.toml declares no upper bound for it")
            continue
        # An unconditional core requirement constrains every install, so extras
        # may restate the package without repeating the bound. A core entry
        # carrying an environment marker does not constrain every install, so
        # in that case each declaration must carry the cap itself.
        core = [
            (label, requirement)
            for label, requirement in matches
            if label == "project.dependencies" and ";" not in requirement
        ]
        checks = core if any(_upper_bounds(requirement) for _, requirement in core) else matches
        for label, requirement in checks:
            bounds = _upper_bounds(requirement)
            if not bounds:
                errors.append(
                    f"AGENTS.md advertises `{name}<{cap}` but [{label}] declares `{requirement}` without that bound"
                )
                continue
            for bound in bounds:
                found = _version_tuple(bound)
                if found is None or found[: len(wanted)] != wanted:
                    errors.append(f"AGENTS.md advertises `{name}<{cap}` but [{label}] pins <{bound}")
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
        unexpected_evaluation = sorted(evaluation.keys() - EVALUATION_FIELDS)
        if unexpected_evaluation:
            errors.append(
                f"scenario {scenario['id']} evaluation has unexpected fields: {', '.join(unexpected_evaluation)}"
            )
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


# Fraction of a budget at which the surface is reported as nearly full. #1541
# added 88 bytes to a 16000-byte ceiling and reddened develop for everyone with
# no prior signal; a headroom band turns "over budget" from a cliff into a slope.
HEADROOM_WARNING_RATIO = 0.97


def budget_headroom_warnings(metrics: Metrics, budgets: dict[str, Any]) -> list[str]:
    """Warn when a budgeted metric is close to its ceiling but not yet over it.

    Deliberately a warning, never an error: the budget itself stays the gate.
    A second failing threshold would just be a lower budget, and the point is to
    give the next docs change lead time, not to move the wall in.
    """
    warnings: list[str] = []
    measured = [
        ("active instruction bytes", metrics.active_bytes, budgets["active_bytes"]),
        ("AGENTS.md lines", metrics.agents_lines, budgets["agents_lines"]),
        *((f"{name} bytes", size, budgets["adapter_bytes"]) for name, size in metrics.adapter_bytes.items()),
    ]
    for label, value, ceiling in measured:
        if ceiling and value <= ceiling and value >= ceiling * HEADROOM_WARNING_RATIO:
            warnings.append(f"{label} {value} is within {ceiling - value} of the {ceiling} budget")
    return warnings


def audit_docs_placement(project: Path) -> list[str]:
    """Keep agent governance out of the published contributor handbook."""
    errors: list[str] = []
    development = project / "docs/development"
    if development.is_dir():
        leaked = sorted(path.relative_to(project).as_posix() for path in development.glob("agent-*.md"))
        if leaked:
            errors.append("agent governance files must live under docs/agent/, not " + ", ".join(leaked))
    conf = project / "docs/conf.py"
    if conf.exists():
        match = re.search(r"exclude_patterns\s*=\s*\[(.*?)\]", conf.read_text(encoding="utf-8"), re.S)
        excluded = match.group(1) if match else ""
        if not re.search(r"[\"']agent[\"']", excluded):
            errors.append("docs/conf.py must exclude the docs/agent/ tree from Sphinx")
    return errors


def audit(project: Path, corpus: dict[str, Any]) -> tuple[Metrics, list[str]]:
    """Run every non-Git check and return its errors tagged with the check name.

    Each message is prefixed `<check>: ` so a caller - in particular the
    pre-commit hook, which invokes this through one entry point - can say which
    check failed. Before that, a byte-budget failure surfaced under a hook named
    "reject stale agent Git identity", which sent at least one investigation
    after a Git config problem that did not exist.
    """
    errors: list[str] = []
    metrics = collect_metrics(project)
    budgets = corpus["budgets"]
    baseline = corpus["baseline"]

    budget_errors: list[str] = []
    if metrics.active_bytes > budgets["active_bytes"]:
        budget_errors.append(f"active instruction bytes {metrics.active_bytes} exceed budget {budgets['active_bytes']}")
    if metrics.active_bytes >= baseline["active_bytes"]:
        budget_errors.append("active instruction surface did not improve on the recorded baseline")
    if metrics.agents_lines > budgets["agents_lines"]:
        budget_errors.append(f"AGENTS.md lines {metrics.agents_lines} exceed budget {budgets['agents_lines']}")
    for name, size in metrics.adapter_bytes.items():
        if size > budgets["adapter_bytes"]:
            budget_errors.append(f"{name} bytes {size} exceed adapter budget {budgets['adapter_bytes']}")
        adapter = _read(project, name)
        if "AGENTS.md" not in adapter:
            budget_errors.append(f"{name} does not point to AGENTS.md")
    errors.extend(_tag("budget", budget_errors))

    active = "\n".join(_read(project, path) for path in ACTIVE_TEXT)
    command_text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((project / ".claude/commands").glob("*.md"))
    )
    surface_errors: list[str] = []
    for retired in RETIRED_REVIEW_DOCS:
        if retired in command_text:
            surface_errors.append(f"a .claude/commands surface binds to the superseded {retired}")
    settings = json.loads(_read(project, ".claude/settings.json"))
    if settings.get("hooks"):
        surface_errors.append(".claude/settings.json contains executable hooks; use explicit gates")
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
            surface_errors.append(f"{label} pattern remains: {needle}")
    settings_text = _read(project, ".claude/settings.json")
    for label, needle in forbidden_settings.items():
        if needle.casefold() in settings_text.casefold():
            surface_errors.append(f"{label} pattern remains in project settings: {needle}")
    errors.extend(_tag("surface", surface_errors))

    policy_text = _read(project, "AGENTS.md") + "\n" + _read(project, ACTIVE_REVIEW_PROTOCOL)
    errors.extend(_tag("review-policy", audit_review_policy(project)))
    errors.extend(_tag("docs-placement", audit_docs_placement(project)))
    errors.extend(_tag("commit-policy", audit_commit_policy(project)))
    errors.extend(_tag("dependency-caps", audit_dependency_caps(project)))

    errors.extend(_tag("scenarios", audit_scenarios(corpus["scenarios"], policy_text)))

    return metrics, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=ROOT)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--check-git-identity", action="store_true")
    parser.add_argument(
        "--check-commit-range",
        metavar="BASE_REF",
        help="reject agent authorship/attribution on commits in BASE_REF..HEAD (merge-time guard)",
    )
    args = parser.parse_args()
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    metrics, errors = audit(args.project.resolve(), corpus)
    warnings: list[str] = []
    if args.check_git_identity:
        errors.extend(_tag("git-identity", audit_git_identity(args.project.resolve())))
        warnings.extend(_tag("git-identity", audit_identity_overrides(args.project.resolve())))
    if args.check_commit_range:
        errors.extend(_tag("commit-range", audit_commit_range(args.project.resolve(), args.check_commit_range)))
    warnings.extend(_tag("budget", budget_headroom_warnings(metrics, corpus["budgets"])))
    checks = failing_checks(errors)
    result = {
        "ok": not errors,
        "metrics": asdict(metrics),
        "errors": errors,
        "warnings": warnings,
        "failing_checks": checks,
    }
    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        summary = "PASS" if not errors else f"FAIL ({', '.join(checks)})"
        print(f"agent-instructions: {summary}")
        print(f"active_bytes={metrics.active_bytes} agents_lines={metrics.agents_lines}")
        for name, size in metrics.adapter_bytes.items():
            print(f"{name}={size} bytes")
        for warning in warnings:
            print(f"WARNING: {warning}")
        for error in errors:
            print(f"ERROR: {error}")
    # Warnings are deliberately excluded from the exit status: they report a
    # condition the user may have chosen on purpose, and a gate that fails on
    # every repo-local human identity would be routinely bypassed.
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
