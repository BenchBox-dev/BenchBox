#!/usr/bin/env python3
"""Predicate: does the ``develop`` ruleset enforce a review before squash-auto-merge?

Follow-up guard for ``auto-merge-review-gate-soundness-paths`` (#912). The auto-merge
*code* side is correct: ``make pr-open`` and ``auto-merge-on-open.yml`` share
``auto_merge_soundness_paths.py`` (``--no-renames``) and WITHHOLD auto-merge
enablement for PRs touching the soundness paths in
``auto_merge_soundness_paths.SOUNDNESS_PREFIXES``. But withholding auto-merge is only
a precondition: a soundness-path PR can still be squash-merged with zero approvals
(manually, or by re-enabling auto-merge) unless the ``develop`` branch ruleset itself
requires a review. This module pins that repo-layer rule -- the ``develop`` ruleset's
``pull_request`` rule must require at least one approving review AND code-owner
review -- so the soundness exception is enforceable at the repo layer, not just in
code.

The soundness path set is read from ``auto_merge_soundness_paths`` (single source of
truth), so the narration here and the auto-merge withholding cannot drift apart.

Token note: the develop-PR CI cannot read the live ruleset -- the default Actions
``GITHUB_TOKEN`` has no ``administration`` scope, and the ruleset-read
``RULESET_DRIFT_TOKEN`` is wired only into ``release-canary.yml``. So this module is
exercised two ways:

  * as a pinned-logic guard in ``tests/unit/release/`` (runs in the required fast
    lane); and
  * as the predicate behind the manual / canary live-ruleset check documented in
    ``docs/operations/repo-admin-settings.md`` -- an operator pipes
    ``gh api repos/<owner>/<repo>/rules/branches/develop`` into ``--rules-file -``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Make the sibling source-of-truth importable whether this file is run as a script
# (sys.path[0] is already this dir) or loaded via importlib from a test.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from auto_merge_soundness_paths import SOUNDNESS_PREFIXES  # noqa: E402

# Human-readable globs for the CODEOWNERS-owned soundness surface, derived from the
# shared predicate so this narration tracks the auto-merge withholding set exactly.
SOUNDNESS_PATH_GLOBS: tuple[str, ...] = tuple(f"{prefix}**" for prefix in SOUNDNESS_PREFIXES) + (
    "benchbox/core/**/validation.py",
)


def extract_rules(payload: Any) -> list[dict[str, Any]]:
    """Normalize either a ``rules/branches`` list or a ``rulesets/<id>`` object.

    ``gh api repos/<owner>/<repo>/rules/branches/develop`` returns the flat list of
    effective rules; ``gh api repos/<owner>/<repo>/rulesets/<id>`` returns a ruleset
    object carrying ``rules``. Accept both so the operator can pipe either.
    """
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
    """Return human-readable reasons the ruleset fails to enforce a review.

    Empty list == the ruleset enforces an approving + code-owner review, so a
    soundness-path PR cannot be squash-merged with zero approvals.
    """
    params = _pull_request_parameters(rules)
    if params is None:
        return [
            "develop ruleset has no pull_request rule: a soundness-path PR "
            f"({', '.join(SOUNDNESS_PATH_GLOBS)}) can squash-auto-merge with zero reviews"
        ]
    findings: list[str] = []
    count = params.get("required_approving_review_count") or 0
    if count < 1:
        findings.append(f"required_approving_review_count={count} (need >= 1)")
    if not params.get("require_code_owner_review", False):
        findings.append(
            f"require_code_owner_review={params.get('require_code_owner_review', False)} (need true) "
            f"for CODEOWNERS-owned soundness paths: {', '.join(SOUNDNESS_PATH_GLOBS)}"
        )
    return findings


def is_review_enforced(rules: list[dict[str, Any]]) -> bool:
    """True when the ruleset requires an approving + code-owner review."""
    return not review_enforcement_findings(rules)


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
    parser.add_argument(
        "--rules-file",
        help="Path to a JSON rules/ruleset payload, or '-' to read it from stdin.",
    )
    parser.add_argument("--repo", default="joeharris76/BenchBox", help="owner/repo for live fetch.")
    parser.add_argument("--branch", default="develop", help="Branch whose ruleset to check.")
    parser.add_argument("--token", default="", help="Ruleset-read token for live fetch (e.g. RULESET_DRIFT_TOKEN).")
    args = parser.parse_args(argv)

    rules = _load_rules(args)
    findings = review_enforcement_findings(rules)
    if findings:
        print(f"# Ruleset review enforcement ({args.branch}) - FAILED")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print(f"# Ruleset review enforcement ({args.branch}) - OK")
    print(f"- approving + code-owner review required for {', '.join(SOUNDNESS_PATH_GLOBS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
