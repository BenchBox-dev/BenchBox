#!/usr/bin/env python3
"""Compare live GitHub rulesets with the repository admin runbook."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNBOOK = REPO_ROOT / "docs" / "operations" / "repo-admin-settings.md"

# Make the sibling _project/scripts source-of-truth importable regardless of
# how this module is loaded (script, package import, or out-of-tree test).
sys.path.insert(0, str(REPO_ROOT / "_project" / "scripts"))

from ruleset_review_enforcement import (  # noqa: E402
    TAG_RULESET_ENFORCED,
    extract_rules,
    review_enforcement_findings,
    tag_bypass_advisory,
    tag_protection_findings,
)

# Findings with this prefix are surfaced (rendered, included in the JSON
# `findings` list) exactly like any other drift finding, but do NOT flip the
# exit code / `status` field to failed. Used for the develop review-rule gap
# below while it is still a pending admin action.
WARNING_PREFIX = "WARNING (non-blocking): "

# Decision (ruleset-drift-check-review-rule-coverage, w1): WARN-until-enforced.
# The live develop ruleset does not yet require a code-owner review
# (docs/operations/repo-admin-settings.md's "Soundness-path review
# enforcement" section - deferred admin action tracked by
# auto-merge-review-gate-admin-enforcement). Flipping this straight to a
# blocking check would make the daily release-canary.yml run (and the
# validate-main-pr.yml bootstrap invocation) permanently red until that
# admin PUT lands. Flip this constant to True once that TODO's w3 confirms
# the PUT has landed - this is the one-line change referenced by that
# decision; no other code here needs to change.
DEVELOP_REVIEW_RULE_ENFORCED = False


@dataclass(frozen=True)
class ExpectedRuleset:
    name: str
    ref: str
    required_checks: tuple[str, ...]
    strict_required_status_checks_policy: bool
    required_linear_history: bool
    non_fast_forward: bool
    deletion: bool
    bypass_actors_none: bool


def _api_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _bool_from_text(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise ValueError(f"expected boolean text, got {value!r}")


def _section_for_ruleset(text: str, name: str) -> str:
    marker = f"Ruleset name: `{name}`"
    start = text.find(marker)
    if start < 0:
        raise ValueError(f"could not find ruleset section for {name!r}")
    next_heading = text.find("\n## ", start + len(marker))
    return text[start:] if next_heading < 0 else text[start:next_heading]


def _required_checks(section: str, name: str) -> tuple[str, ...]:
    match = re.search(r"Required status checks:\n\n```text\n(.*?)\n```", section, re.DOTALL)
    if not match:
        raise ValueError(f"could not find required checks block for {name!r}")
    checks = tuple(line.removeprefix("- ").strip() for line in match.group(1).splitlines() if line.strip())
    if not checks:
        raise ValueError(f"required checks block for {name!r} is empty")
    return checks


def _other_properties(section: str, name: str) -> dict[str, str]:
    match = re.search(r"Other ruleset properties to preserve:\n\n```text\n(.*?)\n```", section, re.DOTALL)
    if not match:
        raise ValueError(f"could not find other-properties block for {name!r}")
    props: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        props[key.strip()] = value.strip()
    return props


def parse_expected_rulesets(runbook_text: str) -> dict[str, ExpectedRuleset]:
    """Extract expected ruleset state from docs/operations/repo-admin-settings.md."""
    expected: dict[str, ExpectedRuleset] = {}
    for name in ("develop-squash-only", "main-release-only"):
        section = _section_for_ruleset(runbook_text, name)
        ref_match = re.search(r"targets?\s+`([^`]+)`", section)
        if not ref_match:
            raise ValueError(f"could not find target ref for {name!r}")
        props = _other_properties(section, name)
        expected[name] = ExpectedRuleset(
            name=name,
            ref=ref_match.group(1),
            required_checks=_required_checks(section, name),
            strict_required_status_checks_policy=_bool_from_text(props["strict_required_status_checks_policy"]),
            required_linear_history=_bool_from_text(props["required_linear_history"]),
            non_fast_forward=_bool_from_text(props["non_fast_forward"]),
            deletion=props["deletion"].lower() == "blocked",
            bypass_actors_none=props["bypass_actors"].lower() == "(none)",
        )
    return expected


def _rule_by_type(ruleset: dict[str, Any], rule_type: str) -> dict[str, Any] | None:
    for rule in ruleset.get("rules", []):
        if rule.get("type") == rule_type:
            return rule
    return None


def _required_status_contexts(ruleset: dict[str, Any]) -> tuple[str, ...]:
    rule = _rule_by_type(ruleset, "required_status_checks")
    if not rule:
        return ()
    checks = rule.get("parameters", {}).get("required_status_checks", [])
    return tuple(check.get("context", "") for check in checks if check.get("context"))


def _strict_required_status_checks_policy(ruleset: dict[str, Any]) -> bool | None:
    rule = _rule_by_type(ruleset, "required_status_checks")
    if not rule:
        return None
    return rule.get("parameters", {}).get("strict_required_status_checks_policy")


def _ref_includes(ruleset: dict[str, Any]) -> tuple[str, ...]:
    ref_name = ruleset.get("conditions", {}).get("ref_name", {})
    return tuple(ref_name.get("include", []) or ())


def compare_ruleset(
    expected: ExpectedRuleset,
    live: dict[str, Any],
    *,
    require_bypass_actor_visibility: bool = False,
    enforce_review_rule: bool = DEVELOP_REVIEW_RULE_ENFORCED,
) -> list[str]:
    """Return human-readable drift findings for one ruleset.

    For ``develop-squash-only`` only (``main-release-only`` has no equivalent
    documented requirement), also runs the shared
    ``ruleset_review_enforcement.review_enforcement_findings`` predicate
    against the already-fetched live payload (via ``extract_rules`` - no
    second API fetch) so a missing code-owner-review rule surfaces here too.
    While ``enforce_review_rule`` is ``False`` (the default, driven by
    ``DEVELOP_REVIEW_RULE_ENFORCED``), those findings are prefixed with
    ``WARNING_PREFIX``: they render in the same findings list / JSON output
    as any other drift finding, but the caller (``main``) excludes
    ``WARNING_PREFIX``-prefixed entries when deciding the exit code, so the
    canary does not go red for a gap that is still a pending admin action.
    """
    findings: list[str] = []
    if live.get("enforcement") != "active":
        findings.append(f"{expected.name}: enforcement is {live.get('enforcement')!r}, expected 'active'")
    if expected.ref not in _ref_includes(live):
        findings.append(f"{expected.name}: target refs {_ref_includes(live)!r}, expected {expected.ref!r}")

    live_checks = _required_status_contexts(live)
    if set(live_checks) != set(expected.required_checks):
        findings.append(
            f"{expected.name}: required checks {sorted(live_checks)!r}, expected {sorted(expected.required_checks)!r}"
        )
    live_strict = _strict_required_status_checks_policy(live)
    if live_strict != expected.strict_required_status_checks_policy:
        findings.append(
            f"{expected.name}: strict_required_status_checks_policy is {live_strict!r}, "
            f"expected {expected.strict_required_status_checks_policy!r}"
        )

    for rule_type, expected_present in [
        ("required_linear_history", expected.required_linear_history),
        ("non_fast_forward", expected.non_fast_forward),
        ("deletion", expected.deletion),
    ]:
        live_present = _rule_by_type(live, rule_type) is not None
        if live_present != expected_present:
            findings.append(f"{expected.name}: {rule_type} present={live_present!r}, expected {expected_present!r}")

    if expected.bypass_actors_none:
        if require_bypass_actor_visibility and "bypass_actors" not in live:
            findings.append(
                f"{expected.name}: bypass actors are not visible to this token; "
                "use RULESET_DRIFT_TOKEN with ruleset write/admin visibility"
            )
        else:
            bypass_actors = live.get("bypass_actors", []) or []
            if bypass_actors:
                actor_types = [actor.get("actor_type", "(unknown)") for actor in bypass_actors]
                findings.append(f"{expected.name}: bypass actors {actor_types!r}, expected none")

    if expected.name == "develop-squash-only":
        review_findings = review_enforcement_findings(extract_rules(live))
        if review_findings:
            if enforce_review_rule:
                findings.extend(review_findings)
            else:
                findings.extend(f"{WARNING_PREFIX}{finding}" for finding in review_findings)

    return findings


def tag_creation_findings(
    all_live_rulesets: list[dict[str, Any]],
    *,
    enforce_tag_rule: bool = TAG_RULESET_ENFORCED,
) -> list[str]:
    """Findings for the ``v*`` tag-creation ruleset (release-flow hardening).

    Delegates entirely to ``ruleset_review_enforcement.tag_protection_findings``/
    ``tag_bypass_advisory`` (single source of truth, shared with the standalone
    ``--rulesets-file`` CLI documented in ``docs/operations/repo-admin-settings.md``).
    Unlike the per-name ``compare_ruleset`` checks above, this scans ALL fetched
    rulesets (not one by expected name) because the tag-creation ruleset has no
    fixed expected name — any ruleset with ``target: "tag"`` that covers
    ``refs/tags/v*`` with a ``creation`` rule counts.

    Mirrors the ``DEVELOP_REVIEW_RULE_ENFORCED`` WARN-until-applied pattern:
    while ``enforce_tag_rule`` is ``False`` (the default, driven by
    ``TAG_RULESET_ENFORCED``), a missing/incomplete tag ruleset is a
    ``WARNING_PREFIX``-prefixed finding — visible, non-blocking — until the
    admin POST lands and the flag is flipped.
    """
    findings: list[str] = []
    protection_findings = tag_protection_findings(all_live_rulesets)
    if protection_findings:
        if enforce_tag_rule:
            findings.extend(protection_findings)
        else:
            findings.extend(f"{WARNING_PREFIX}{finding}" for finding in protection_findings)
    else:
        findings.extend(
            f"{WARNING_PREFIX}CONFIRM before enforcing: {advisory}"
            for advisory in tag_bypass_advisory(all_live_rulesets)
        )
    return findings


def _override_active(env: dict[str, str]) -> tuple[bool, str]:
    sha = env.get("RELEASE_READINESS_OVERRIDE_SHA", "").strip()
    reason = env.get("RELEASE_READINESS_OVERRIDE_REASON", "").strip()
    current_sha = env.get("GITHUB_SHA", "").strip()
    if sha and reason and sha == current_sha:
        return True, reason
    return False, ""


def _fetch_live_rulesets(repo: str, token: str) -> dict[str, dict[str, Any]]:
    base_url = f"https://api.github.com/repos/{repo}/rulesets"
    listing = _api_json(base_url, token)
    by_name: dict[str, dict[str, Any]] = {}
    for entry in listing:
        name = entry.get("name")
        ruleset_id = entry.get("id")
        if name and ruleset_id:
            by_name[name] = _api_json(f"{base_url}/{ruleset_id}", token)
    return by_name


def blocking_findings(findings: list[str]) -> list[str]:
    """Findings that should fail the check (excludes WARNING_PREFIX entries)."""
    return [finding for finding in findings if not finding.startswith(WARNING_PREFIX)]


def render_summary(findings: list[str], expected: dict[str, ExpectedRuleset]) -> str:
    blocking = blocking_findings(findings)
    warnings = [finding for finding in findings if finding.startswith(WARNING_PREFIX)]
    if blocking:
        lines = ["# Ruleset Drift - FAILED", "", *[f"- {finding}" for finding in blocking]]
    else:
        lines = ["# Ruleset Drift - OK", ""]
        for ruleset in expected.values():
            lines.append(f"- {ruleset.name}: required checks {', '.join(ruleset.required_checks)}")
    if warnings:
        lines += ["", "## Non-blocking warnings", "", *[f"- {finding}" for finding in warnings]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runbook", type=Path, default=DEFAULT_RUNBOOK)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "joeharris76/BenchBox"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--require-bypass-actor-visibility",
        action="store_true",
        help="Fail if the GitHub API response does not expose bypass_actors.",
    )
    args = parser.parse_args(argv)

    override, reason = _override_active(os.environ)
    try:
        expected = parse_expected_rulesets(args.runbook.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ERROR: failed to parse ruleset runbook: {exc}", file=sys.stderr)
        return 1
    if override:
        payload = {"status": "override", "reason": reason, "rulesets": sorted(expected)}
        if args.output:
            args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Ruleset drift override active: {reason}")
        return 0
    if not args.token:
        print("ERROR: ruleset drift check requires RULESET_DRIFT_TOKEN or --token.", file=sys.stderr)
        return 1

    try:
        live_by_name = _fetch_live_rulesets(args.repo, args.token)
    except Exception as exc:
        if args.output:
            args.output.write_text(
                json.dumps({"status": "error", "error": str(exc)}, indent=2) + "\n",
                encoding="utf-8",
            )
        print(f"ERROR: ruleset drift check failed while querying GitHub: {exc}", file=sys.stderr)
        return 1

    findings: list[str] = []
    for name, expected_ruleset in expected.items():
        live = live_by_name.get(name)
        if live is None:
            findings.append(f"{name}: live ruleset is missing")
            continue
        findings.extend(
            compare_ruleset(
                expected_ruleset,
                live,
                require_bypass_actor_visibility=args.require_bypass_actor_visibility,
            )
        )
    findings.extend(tag_creation_findings(list(live_by_name.values())))

    blocking = blocking_findings(findings)
    summary = render_summary(findings, expected)
    if args.output:
        args.output.write_text(
            json.dumps(
                {"status": "failed" if blocking else "ok", "findings": findings, "blocking_findings": blocking},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print(summary)
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
