#!/usr/bin/env python3
"""Predicates for live develop-review and v* tag-creation enforcement.

The develop ruleset's ``require_code_owner_review`` parameter is a
repo-admin control for CODEOWNERS-owned soundness paths. It is deliberately
checked without asserting ``required_approving_review_count``: that count is
branch-wide and would gate every develop PR. The same predicate is used by
the standalone CLI and ``scripts/ruleset_drift_check.py``'s canary wiring.

The v* tag-creation predicate remains in this module as the second live
ruleset control. Both predicates fail closed on missing or incomplete live
payloads; the caller decides whether a finding is blocking during an explicit
migration override.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import Any

from auto_merge_soundness_paths import SOUNDNESS_FILES, SOUNDNESS_PREFIXES

# Human-readable globs for the CODEOWNERS-owned soundness surface, derived from
# the shared predicate so this narration cannot drift from auto-merge gating.
SOUNDNESS_PATH_GLOBS: tuple[str, ...] = (
    tuple(f"{prefix}**" if prefix.endswith("/") else prefix for prefix in SOUNDNESS_PREFIXES)
    + SOUNDNESS_FILES
    + ("benchbox/core/**/validation.py",)
)


def extract_rules(payload: Any) -> list[dict[str, Any]]:
    """Normalize either a ``rules/branches`` list or a full ruleset object."""
    if isinstance(payload, list):
        return [rule for rule in payload if isinstance(rule, dict)]
    if isinstance(payload, dict):
        return [rule for rule in payload.get("rules", []) if isinstance(rule, dict)]
    return []


def _pull_request_parameters(rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    for rule in rules:
        if rule.get("type") == "pull_request":
            params = rule.get("parameters")
            return params if isinstance(params, dict) else {}
    return None


def review_enforcement_findings(rules: list[dict[str, Any]]) -> list[str]:
    """Return reasons the develop ruleset lacks a code-owner review rule."""
    params = _pull_request_parameters(rules)
    if params is None:
        return [
            "develop ruleset has no pull_request rule: a soundness-path PR "
            f"({', '.join(SOUNDNESS_PATH_GLOBS)}) can squash-auto-merge with zero reviews"
        ]
    if not params.get("require_code_owner_review", False):
        return [
            f"require_code_owner_review={params.get('require_code_owner_review', False)} (need true) "
            f"for CODEOWNERS-owned soundness paths: {', '.join(SOUNDNESS_PATH_GLOBS)}"
        ]
    return []


def is_review_enforced(rules: list[dict[str, Any]]) -> bool:
    """True when the ruleset requires a code-owner review."""
    return not review_enforcement_findings(rules)


# ---------------------------------------------------------------------------
# v* tag-creation protection (tag-and-pypi-environment-admin-hardening w3)
# ---------------------------------------------------------------------------

# Enforcement flag (blocking after live application).
# The v* tag-creation ruleset was applied by admin on 2026-07-10 (ruleset id
# 18774756 ``v-tag-restricted``; see docs/operations/repo-admin-settings.md,
# "Tag creation restricted to release flow"), so this is flipped to True:
# ``tag_protection_findings`` for a missing/incomplete tag ruleset are now a
# BLOCKING drift finding rather than a non-blocking warning. The bypass list
# was confirmed to be the release-finalize identity only (User:57046) before
# flipping, per the runbook's "CONFIRM before enforcing" gate.
TAG_RULESET_ENFORCED = True

# The ref pattern the release flow tags with (make release-finalize pushes v*).
TAG_REF_PATTERN = "refs/tags/v*"


def _tag_glob_covers(pattern: str) -> bool:
    """True if a ref-name glob ``pattern`` matches every ``refs/tags/v*`` ref.

    GitHub's ``ref_name`` condition patterns are fnmatch-style globs, so
    ``refs/tags/*`` covers (or negates, in an ``exclude``) ``refs/tags/v*``
    just as fully as the literal pattern. Fnmatch-ing ``TAG_REF_PATTERN``
    itself against ``pattern`` answers that without enumerating concrete tag
    names: every character in ``refs/tags/v*`` is literal except the trailing
    ``*``, so a pattern matches it here exactly when that pattern's own
    wildcard structure would match any real ``refs/tags/vX...`` ref too.
    """
    representative_refs = (
        "refs/tags/v",
        "refs/tags/v1",
        "refs/tags/v1.2.3",
        "refs/tags/vnext",
        "refs/tags/vfeature/preview",
    )
    return all(fnmatch.fnmatchcase(ref, pattern) for ref in representative_refs)


def tag_protection_findings(
    rulesets: list[dict[str, Any]], *, require_bypass_actor_visibility: bool = False
) -> list[str]:
    """Reasons the live rulesets fail to restrict ``v*`` tag *creation*.

    Empty list == at least one ACTIVE ruleset with ``target == "tag"`` whose
    ref conditions cover ``refs/tags/v*`` (or ``~ALL``) AND that carries a
    ``creation`` rule. That is the repo-admin layer closing the last
    zero-human path to publish: ``release.yml``'s ``verify-tag-on-release`` only
    stops a tag that does not point at a release-ancestor commit; it does nothing
    to stop a collaborator with push access from creating a ``v*`` tag ON an
    existing release commit out of band. A tag-creation ruleset restricts who may
    mint the tag in the first place.

    Accepts FULL ruleset objects (``GET /repos/{o}/{r}/rulesets/{id}``). The
    list endpoint's summaries omit ``conditions`` / ``rules``, so a
    summary-only payload correctly reports the detail as missing rather than
    passing on absent evidence (never green on unverified input). Rulesets
    that target branches (e.g. ``v-release-branches-minimal`` →
    ``refs/heads/v*``) are ``target != "tag"`` and never count.

    ``include``/``exclude`` ref-name conditions are GitHub fnmatch-style globs,
    not exact strings: an ``include`` of ``refs/tags/*`` covers ``refs/tags/v*``
    just as well as the literal pattern, and an ``exclude`` of ``refs/tags/*``
    negates that coverage even though it is not byte-identical to
    ``TAG_REF_PATTERN``. Coverage is therefore tested by fnmatch-ing
    ``TAG_REF_PATTERN`` itself against each candidate pattern (every character
    in ``refs/tags/v*`` is literal except the trailing ``*``, so this exactly
    answers "does this pattern's wildcard structure swallow the whole
    refs/tags/v* domain" without enumerating concrete tag names). ``~ALL`` is
    GitHub's literal sentinel for "every ref" and is matched by exact string,
    not fnmatch.

    NOTE on ``bypass_actors``: this predicate deliberately does NOT treat a
    non-empty bypass list as a structural failure. This TODO's must_preserve
    REQUIRES a bypass path (``make release-finalize`` must still create ``v*``
    tags), so demanding zero bypass actors would brick the release flow. But an
    explicitly-empty bypass list (``bypass_actors: []``, as returned by the full
    ruleset GET when none are configured) is the OTHER failure mode of the same
    requirement: a structurally-valid ruleset with no exception for the
    release-finalize identity blocks ``make release-finalize``'s own
    ``git push origin v$(VERSION)``, bricking releases outright. That case is a
    finding here, not just an advisory. A MISSING ``bypass_actors`` key (as
    opposed to a present-but-empty list) is left unasserted — it means the
    caller didn't populate that field at all (e.g. a partial/synthetic
    payload), not that GitHub confirmed there are zero bypass actors. A
    non-empty bypass list is still not a structural failure (must_preserve
    requires the bypass path to exist) but its actor list is a real hole if
    too broad, so it is surfaced via :func:`tag_bypass_advisory` (rendered by
    ``main`` and required in the runbook's live-state note) for human
    confirmation before a live enforcement decision — never passed silently.
    """
    tag_rulesets = [rs for rs in rulesets if isinstance(rs, dict) and rs.get("target") == "tag"]
    if not tag_rulesets:
        return [
            "no ruleset with target='tag' exists: any collaborator with push access can "
            f"create a {TAG_REF_PATTERN} tag on a main-ancestor commit and reach release.yml's "
            "publish path with no human gate"
        ]
    problems: list[str] = []
    for ruleset in tag_rulesets:
        name = ruleset.get("name", "(unnamed)")
        issues: list[str] = []
        if ruleset.get("enforcement") != "active":
            issues.append(f"enforcement={ruleset.get('enforcement')!r} (need 'active')")
        ref_name = (ruleset.get("conditions") or {}).get("ref_name") or {}
        include = tuple(ref_name.get("include") or ())
        exclude = tuple(ref_name.get("exclude") or ())
        if not any(pattern == "~ALL" or _tag_glob_covers(pattern) for pattern in include):
            issues.append(f"ref include={include!r} does not cover {TAG_REF_PATTERN}")
        elif any(pattern == "~ALL" or _tag_glob_covers(pattern) for pattern in exclude):
            issues.append(f"ref exclude={exclude!r} negates coverage of {TAG_REF_PATTERN}")
        rule_types = {rule.get("type") for rule in ruleset.get("rules") or [] if isinstance(rule, dict)}
        if "creation" not in rule_types:
            issues.append("no 'creation' rule")
        if require_bypass_actor_visibility and "bypass_actors" not in ruleset:
            issues.append("bypass actors are not visible to this token")
        elif ruleset.get("bypass_actors") == []:
            issues.append(
                "bypass_actors is empty -- `make release-finalize`'s `git push origin "
                "v$(VERSION)` would be blocked with no exception for the release-finalize "
                "identity; add a bypass actor for that identity before enforcing"
            )
        if not issues:
            return []
        problems.append(f"{name}: " + "; ".join(issues))
    return [f"no active tag ruleset covers {TAG_REF_PATTERN} with a creation rule -- " + " | ".join(problems)]


def tag_bypass_advisory(rulesets: list[dict[str, Any]]) -> list[str]:
    """Bypass actors on the covering ``v*`` tag ruleset that a human must confirm.

    Empty list == no protecting tag ruleset, a protecting one with an
    explicitly-empty ``bypass_actors: []`` (both already surfaced as findings
    by :func:`tag_protection_findings`, so not repeated here), or a protecting
    one where ``bypass_actors`` is simply absent from the payload. A non-empty
    result is NOT a failure — it is the list the operator must confirm is
    release-flow-only before flipping ``TAG_RULESET_ENFORCED`` (must_preserve:
    the release identity legitimately needs bypass; a broad role in this list
    is the hole).
    """
    if tag_protection_findings(rulesets):
        return []
    for ruleset in rulesets:
        if not isinstance(ruleset, dict) or ruleset.get("target") != "tag":
            continue
        if tag_protection_findings([ruleset]):
            continue
        actors = ruleset.get("bypass_actors") or []
        if actors:
            rendered = ", ".join(
                f"{a.get('actor_type', '?')}:{a.get('actor_id', '?')}({a.get('bypass_mode', '?')})"
                for a in actors
                if isinstance(a, dict)
            )
            return [
                f"{ruleset.get('name', '(unnamed)')} has bypass_actors [{rendered}] -- confirm these "
                "are the release-finalize identity ONLY (not a broad Write/Admin role) before "
                "enforcing; a wide bypass leaves v* tag creation open"
            ]
        return []
    return []


def is_tag_creation_protected(rulesets: list[dict[str, Any]]) -> bool:
    """True when a ``v*`` tag-creation ruleset restricts out-of-band tagging."""
    return not tag_protection_findings(rulesets)


def _load_rulesets(raw_source: str) -> list[dict[str, Any]]:
    """Load a JSON array of FULL ruleset objects from a file path or '-' (stdin)."""
    raw = sys.stdin.read() if raw_source == "-" else Path(raw_source).read_text(encoding="utf-8")
    payload = json.loads(raw)
    if isinstance(payload, list):
        return [rs for rs in payload if isinstance(rs, dict)]
    if isinstance(payload, dict):
        # Tolerate a single ruleset object as well as a bare list.
        return [payload]
    return []


def _fetch_branch_rules(repo: str, branch: str, token: str) -> list[dict[str, Any]]:
    import urllib.request

    url = f"https://api.github.com/repos/{repo}/rules/branches/{branch}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 (fixed api.github.com host)
        return extract_rules(json.loads(response.read().decode("utf-8")))


def _load_rules(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.rules_file:
        raw = sys.stdin.read() if args.rules_file == "-" else Path(args.rules_file).read_text(encoding="utf-8")
        return extract_rules(json.loads(raw))
    if args.token:
        return _fetch_branch_rules(args.repo, args.branch, args.token)
    raise SystemExit(
        "Provide --rules-file (e.g. `gh api repos/<owner>/<repo>/rules/branches/develop | "
        "ruleset_review_enforcement.py --rules-file -`) or --token to fetch live."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules-file", help="Path to a JSON rules/ruleset payload, or '-' to read stdin.")
    parser.add_argument("--repo", default="joeharris76/BenchBox", help="owner/repo for live fetch.")
    parser.add_argument("--branch", default="develop", help="Branch whose ruleset to check.")
    parser.add_argument("--token", default="", help="Ruleset-read token for live fetch.")
    parser.add_argument(
        "--rulesets-file",
        help=(
            "Path to a JSON array of FULL ruleset objects (or '-' for stdin) to check "
            "v* tag-creation protection; e.g. "
            "`gh api repos/<owner>/<repo>/rulesets --jq '[.[] | .id] | map(...)'` -- see "
            "docs/operations/repo-admin-settings.md for the exact fetch."
        ),
    )
    args = parser.parse_args(argv)

    if args.rulesets_file:
        rulesets = _load_rulesets(args.rulesets_file)
        tag_findings = tag_protection_findings(rulesets)
        if not tag_findings:
            print("# Tag-creation ruleset - OK")
            print(f"- {TAG_REF_PATTERN} creation restricted by an active tag ruleset")
            for advisory in tag_bypass_advisory(rulesets):
                # Not a failure (must_preserve requires a bypass path), but
                # the operator must confirm the actor list remains release-scoped.
                print(f"- CONFIRM before enforcing: {advisory}")
            return 0
        if TAG_RULESET_ENFORCED:
            print("# Tag-creation ruleset - FAILED")
            for finding in tag_findings:
                print(f"- {finding}")
            return 1
        # Retain an explicit warning-only escape hatch for migration callers;
        # the live default is TAG_RULESET_ENFORCED=True above.
        print("# Tag-creation ruleset - WARNING (non-blocking, enforcement override)")
        for finding in tag_findings:
            print(f"- WARNING (non-blocking): {finding}")
        return 0

    rules = _load_rules(args)
    findings = review_enforcement_findings(rules)
    if findings:
        print(f"# Ruleset review enforcement ({args.branch}) - FAILED")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print(f"# Ruleset review enforcement ({args.branch}) - OK")
    print(f"- code-owner review required for {', '.join(SOUNDNESS_PATH_GLOBS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
