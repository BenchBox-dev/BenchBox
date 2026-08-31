#!/usr/bin/env python3
"""Shared soundness-path predicate for auto-merge gating."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable

SOUNDNESS_PREFIXES = (
    "benchbox/core/equivalence/",
    "benchbox/core/query_plans/parsers/",
    # Oracle-adjacent widening (soundness-surface-widening): these define or
    # feed "correct" for the same soundness checks the comparator/parser
    # paths above already gate, so a PR touching them should get the same
    # review requirement.
    #
    # The reference-value loader, registry, and hash-pinned digest fixtures
    # (e.g. reference_digests/tpch_value_digests_sf1.json) all live here.
    # Editing any of them silently redefines what counts as a "correct"
    # benchmark result.
    "benchbox/core/expected_results/",
    # validate_loaded_data / validate_row_counts (delegate to
    # ValidationService / DataValidator) and the plan-capture pipeline
    # (get_query_plan_parser, capture_query_plan) that feeds
    # benchbox/core/query_plans/parsers/ live in this single file.
    # benchbox/sql_compat/ as a whole is high-churn (routine per-platform
    # DDL/query-rewrite rule additions), so only its rule-dispatch core is
    # in scope, not the whole tree -- see soundness-surface-widening's
    # decision. These three files decide WHICH rewrite rules apply to a
    # given query/platform; a bug here silently changes what SQL actually
    # executes without touching the comparator itself.
    # Publication privacy. This is a deliberate widening beyond "what defines a
    # correct result": the anonymizer decides every byte that leaves the
    # project and the public pseudonym identity that groups results by machine.
    # Both of its failure modes are silent -- a missed key publishes a private
    # path, and a changed hashing rule repartitions public identity without
    # anything raising. PR #1512 was exactly that: it changed every published
    # byte and every public result_id, and auto-merged with no review because
    # this list did not cover it. Same rationale as release.yml above (that one
    # is here for publishing to PyPI, not for soundness) -- is_soundness_path
    # means "needs owner review before auto-merge", which is broader than
    # soundness alone. anonymization_specs.yaml is listed with it because it
    # DEFINES which keys get hashed -- dropping one entry there silently stops
    # anonymizing that field, with no code change to review.
    # Self-protection: the review-gate machinery itself. The in-workflow
    # base-ref execution + self-touch override in auto-merge-on-open.yml is
    # best-effort only for same-repo PRs (GitHub runs the PR's OWN copy of a
    # pull_request-triggered workflow file, so a PR editing that workflow can
    # delete those checks in the same commit). The repo-layer backstop is the
    # develop ruleset's require_code_owner_review rule, re-enabled 2026-07-21
    # with required approvals 0 (it was retired 2026-07-18 over a
    # self-approval deadlock, then restored -- see
    # docs/operations/repo-admin-settings.md, "Soundness-path review
    # enforcement"). CODEOWNERS mirrors SOUNDNESS_PREFIXES 1:1, lockstep-
    # pinned by tests/unit/test_auto_merge_soundness_paths.py. GitHub forbids
    # self-approval, so the operative effect is that soundness PRs never
    # merge hands-free: the owner reviews the diff and merges manually.
    # Listing these files here still matters: it revokes/withholds auto-merge
    # so that manual step is reached at all.
    # release.yml is included
    # because it publishes to PyPI. .github/workflows/pr.yml is deliberately
    # NOT included: it is high-churn (routine CI-lane edits), and the
    # required-check contract it feeds (ci-required-result) is pinned by the
    # develop ruleset + the daily ruleset-drift canary rather than by owner
    # review -- see soundness-surface-widening's recorded decision.
)
SOUNDNESS_FILES = (
    "benchbox/platforms/base/result_capture.py",
    "benchbox/sql_compat/resolver.py",
    "benchbox/sql_compat/decision.py",
    "benchbox/sql_compat/rules/_registration.py",
    "benchbox/core/results/anonymization.py",
    "benchbox/core/results/anonymization_specs.yaml",
    "_project/scripts/auto_merge_soundness_paths.py",
    ".github/workflows/auto-merge-on-open.yml",
    ".github/workflows/release.yml",
    # Independent-publication authority and trust-policy surfaces. The accepted
    # A1 contract requires manual maintainer review and forbids auto-merge for
    # changes that redefine archive authority, live-state evidence, withdrawal,
    # ranking/trust policy, or their enforcement checker.
    "_project/decisions/independent-publication-a0-freeze-2026-08-31.md",
    "docs/development/adr/adr-independent-publication-authorities.md",
    "docs/development/adr/adr-public-result-id-permanence.md",
    "docs/development/adr/adr-published-results-slim-corpus-branch.md",
    "docs/development/independent-publication-threat-model.md",
    "docs/operations/independent-publication-contract.md",
    "docs/operations/results-phase-2-runbook.md",
    "docs/reference/hosted-results-contract.md",
    "docs/reference/threat-model.md",
    "scripts/check_decision_records.py",
)
_VALIDATION_RE = re.compile(r"^benchbox/core/(?:.+/)?validation\.py$")


def normalize_path(path: str) -> str:
    """Normalize a git path for predicate checks."""
    return path.strip().replace("\\", "/")


def is_soundness_path(path: str) -> bool:
    """Return True when *path* needs review before auto-merge."""
    normalized = normalize_path(path)
    if not normalized:
        return False
    return (
        _VALIDATION_RE.match(normalized) is not None
        or normalized in SOUNDNESS_FILES
        or normalized.startswith(SOUNDNESS_PREFIXES)
    )


def any_soundness_path(paths: Iterable[str]) -> bool:
    """Return True if any path intersects the review-required soundness surface."""
    return any(is_soundness_path(path) for path in paths)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdin", action="store_true", help="Read newline-delimited paths from stdin.")
    parser.add_argument("--paths-file", help="Read newline-delimited paths from a file.")
    parser.add_argument(
        "--format",
        choices=("plain", "shell", "github-output"),
        default="plain",
        help="Output format. Default prints true/false.",
    )
    return parser.parse_args(argv)


def _read_paths(args: argparse.Namespace) -> list[str]:
    if args.stdin:
        return list(sys.stdin)
    if args.paths_file:
        with open(args.paths_file, encoding="utf-8") as fh:
            return list(fh)
    raise SystemExit("Provide --stdin or --paths-file.")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    result = any_soundness_path(_read_paths(args))
    value = "true" if result else "false"
    if args.format == "github-output":
        print(f"soundness_path={value}")
    elif args.format == "shell":
        print(f"SOUNDNESS_PATH={value}")
    else:
        print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
