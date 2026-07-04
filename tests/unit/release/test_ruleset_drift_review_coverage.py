"""compare_ruleset must surface the develop review-enforcement gap.

Follow-up to ``auto-merge-review-gate-admin-enforcement``:
``scripts/ruleset_drift_check.py``'s ``compare_ruleset`` already compares
required status checks, strict-check policy, linear history,
non-fast-forward, deletion, and bypass actors for both rulesets, but never
inspected the ``pull_request`` rule's review-enforcement settings. This
pins the merged behaviour: ``compare_ruleset`` now imports
``review_enforcement_findings`` from
``_project/scripts/ruleset_review_enforcement.py`` (the single source of
truth for that predicate - not reimplemented here) and applies it only to
``develop-squash-only`` (``main-release-only`` has no equivalent
documented requirement).

Decision (ruleset-drift-check-review-rule-coverage, w1): WARN-until-enforced.
The live develop ruleset does not yet require a code-owner review, so a
missing review-enforcement rule is surfaced as a ``WARNING_PREFIX``-prefixed
finding - visible in the same findings list / JSON output as any other
drift finding - without flipping the exit code, until
``DEVELOP_REVIEW_RULE_ENFORCED`` is switched to ``True`` (a one-line change,
gated on the admin PUT from ``auto-merge-review-gate-admin-enforcement``
actually landing).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ruleset_drift_check import (
    WARNING_PREFIX,
    blocking_findings,
    compare_ruleset,
    parse_expected_rulesets,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _develop_expected():
    return parse_expected_rulesets((REPO_ROOT / "docs" / "operations" / "repo-admin-settings.md").read_text())[
        "develop-squash-only"
    ]


def _live_develop_ruleset(*, review_count: int, code_owner_review: bool) -> dict:
    return {
        "name": "develop-squash-only",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["refs/heads/develop"], "exclude": []}},
        "bypass_actors": [],
        "rules": [
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": review_count,
                    "require_code_owner_review": code_owner_review,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "required_status_checks": [{"context": "ci-required-result"}],
                },
            },
            {"type": "required_linear_history"},
            {"type": "non_fast_forward"},
            {"type": "deletion"},
        ],
    }


def test_missing_review_enforcement_is_a_non_blocking_warning_by_default():
    live = _live_develop_ruleset(review_count=0, code_owner_review=False)

    findings = compare_ruleset(_develop_expected(), live)

    assert any(f.startswith(WARNING_PREFIX) for f in findings), findings
    assert any("require_code_owner_review" in f for f in findings)
    # WARN-until-enforced: the missing rule must not be a blocking finding.
    assert blocking_findings(findings) == []


def test_review_enforcement_produces_no_findings_once_ruleset_enforces_it():
    live = _live_develop_ruleset(review_count=0, code_owner_review=True)

    findings = compare_ruleset(_develop_expected(), live)

    assert findings == []


def test_review_enforcement_can_be_switched_to_blocking_explicitly():
    """The one-line enforce switch: passing enforce_review_rule=True (what
    DEVELOP_REVIEW_RULE_ENFORCED=True will do once flipped) makes the same
    gap a blocking finding instead of a warning."""
    live = _live_develop_ruleset(review_count=0, code_owner_review=False)

    findings = compare_ruleset(_develop_expected(), live, enforce_review_rule=True)

    assert findings, "expected a blocking finding once enforcement is on"
    assert not any(f.startswith(WARNING_PREFIX) for f in findings)
    assert blocking_findings(findings) == findings


def test_main_release_only_is_not_subject_to_the_review_rule_check():
    """main-release-only has no documented review-enforcement requirement;
    compare_ruleset must not apply the develop-only check to it."""
    expected = parse_expected_rulesets((REPO_ROOT / "docs" / "operations" / "repo-admin-settings.md").read_text())[
        "main-release-only"
    ]
    live = {
        "name": "main-release-only",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "bypass_actors": [],
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "required_status_checks": [
                        {"context": "validate-base"},
                        {"context": "release-required-result"},
                    ],
                },
            },
            {"type": "required_linear_history"},
            {"type": "non_fast_forward"},
            {"type": "deletion"},
        ],
    }

    assert compare_ruleset(expected, live) == []
