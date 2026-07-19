#!/usr/bin/env python3
"""Predicates for the ``v*`` tag-creation ruleset (release-flow hardening).

History note: until 2026-07-18 this module also carried the ``develop``
review-rule predicate (``review_enforcement_findings``), which pinned the
then-pending admin target ``require_code_owner_review: true`` on the
``develop-squash-only`` ruleset. That target was RETIRED without being
applied: every PR in this repository is authored by the sole code owner
(agent sessions open PRs under the owner's account), GitHub does not let a
PR author approve their own PR, and the ruleset has no bypass actors -- so
enabling the rule would have deadlocked every soundness-path PR instead of
gating it. The operative soundness control is auto-merge withholding plus a
manual owner merge; see docs/operations/repo-admin-settings.md,
"Soundness-path review enforcement (RETIRED 2026-07-18)".

What remains here is the tag-creation protection predicate
(tag-and-pypi-environment-admin-hardening w3), shared between the standalone
``--rulesets-file`` CLI documented in ``docs/operations/repo-admin-settings.md``
and ``scripts/ruleset_drift_check.py``'s canary wiring.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# v* tag-creation protection (tag-and-pypi-environment-admin-hardening w3)
# ---------------------------------------------------------------------------

# Enforcement flag (WARN-until-applied pattern).
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
    return fnmatch.fnmatchcase(TAG_REF_PATTERN, pattern)


def tag_protection_findings(rulesets: list[dict[str, Any]]) -> list[str]:
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
    confirmation before ``TAG_RULESET_ENFORCED`` is flipped — never passed
    silently.
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
        if ruleset.get("bypass_actors") == []:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rulesets-file",
        required=True,
        help=(
            "Path to a JSON array of FULL ruleset objects (or '-' for stdin) to check "
            "v* tag-creation protection; e.g. "
            "`gh api repos/<owner>/<repo>/rulesets --jq '[.[] | .id] | map(...)'` -- see "
            "docs/operations/repo-admin-settings.md for the exact fetch."
        ),
    )
    args = parser.parse_args(argv)

    rulesets = _load_rulesets(args.rulesets_file)
    tag_findings = tag_protection_findings(rulesets)
    if not tag_findings:
        print("# Tag-creation ruleset - OK")
        print(f"- {TAG_REF_PATTERN} creation restricted by an active tag ruleset")
        for advisory in tag_bypass_advisory(rulesets):
            # Not a failure (must_preserve requires a bypass path), but the
            # operator must confirm the actor list before enforcing.
            print(f"- CONFIRM before enforcing: {advisory}")
        return 0
    if TAG_RULESET_ENFORCED:
        print("# Tag-creation ruleset - FAILED")
        for finding in tag_findings:
            print(f"- {finding}")
        return 1
    # WARN-until-applied: surface the gap without failing while the admin
    # POST is still pending.
    print("# Tag-creation ruleset - WARNING (non-blocking, pending admin action)")
    for finding in tag_findings:
        print(f"- WARNING (non-blocking): {finding}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
