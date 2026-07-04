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
    "benchbox/platforms/base/result_capture.py",
    # benchbox/sql_compat/ as a whole is high-churn (routine per-platform
    # DDL/query-rewrite rule additions), so only its rule-dispatch core is
    # in scope, not the whole tree -- see soundness-surface-widening's
    # decision. These three files decide WHICH rewrite rules apply to a
    # given query/platform; a bug here silently changes what SQL actually
    # executes without touching the comparator itself.
    "benchbox/sql_compat/resolver.py",
    "benchbox/sql_compat/decision.py",
    "benchbox/sql_compat/rules/_registration.py",
    # Self-protection: the review-gate machinery itself. The in-workflow
    # base-ref execution + self-touch override in auto-merge-on-open.yml is
    # best-effort only for same-repo PRs (GitHub runs the PR's OWN copy of a
    # pull_request-triggered workflow file, so a PR editing that workflow can
    # delete those checks in the same commit). The durable control is this
    # prefix list mirrored into .github/CODEOWNERS plus the develop ruleset's
    # require_code_owner_review (pending admin action; see
    # docs/operations/repo-admin-settings.md). release.yml is included
    # because it publishes to PyPI. .github/workflows/pr.yml is deliberately
    # NOT included: it is high-churn (routine CI-lane edits), and the
    # required-check contract it feeds (ci-required-result) is pinned by the
    # develop ruleset + the daily ruleset-drift canary rather than by owner
    # review -- see soundness-surface-widening's recorded decision.
    "_project/scripts/auto_merge_soundness_paths.py",
    ".github/workflows/auto-merge-on-open.yml",
    ".github/workflows/release.yml",
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
    return _VALIDATION_RE.match(normalized) is not None or normalized.startswith(SOUNDNESS_PREFIXES)


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
