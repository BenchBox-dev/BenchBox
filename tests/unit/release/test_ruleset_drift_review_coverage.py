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
``develop-squash-only`` (``release-only`` has no equivalent
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

import importlib.util
import sys
from pathlib import Path

import pytest

from scripts.ruleset_drift_check import (
    WARNING_PREFIX,
    blocking_findings,
    compare_ruleset,
    parse_expected_rulesets,
    tag_creation_findings,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_review_enforcement():
    """Load _project/scripts/ruleset_review_enforcement.py out of tree.

    The v* tag-creation predicate lives beside the review-rule predicate in
    the same single-source-of-truth module (this TODO's scope_limit); load it
    the same way tests/unit/release/test_ruleset_review_enforcement.py does.
    """
    scripts_dir = REPO_ROOT / "_project" / "scripts"
    sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "ruleset_review_enforcement", scripts_dir / "ruleset_review_enforcement.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_rre = _load_review_enforcement()


def _tag_ruleset(*, name="v-tag-restricted", enforcement="active", include=("refs/tags/v*",), rule_types=("creation",)):
    return {
        "name": name,
        "target": "tag",
        "enforcement": enforcement,
        "conditions": {"ref_name": {"include": list(include), "exclude": []}},
        "rules": [{"type": t} for t in rule_types],
    }


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


def test_release_only_is_not_subject_to_the_review_rule_check():
    """release-only has no documented review-enforcement requirement;
    compare_ruleset must not apply the develop-only check to it."""
    expected = parse_expected_rulesets((REPO_ROOT / "docs" / "operations" / "repo-admin-settings.md").read_text())[
        "release-only"
    ]
    live = {
        "name": "release-only",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["refs/heads/release"], "exclude": []}},
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


# ---------------------------------------------------------------------------
# v* tag-creation ruleset coverage (tag-and-pypi-environment-admin-hardening w3)
# ---------------------------------------------------------------------------


def test_tag_protection_missing_when_no_tag_ruleset_exists():
    # Live state 2026-07-03: only v-release-branches-minimal exists, which
    # targets refs/heads/v* (branches), not tags -- must NOT count.
    branch_ruleset = {
        "name": "v-release-branches-minimal",
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["refs/heads/v*"], "exclude": []}},
        "rules": [{"type": "creation"}],
    }
    findings = _rre.tag_protection_findings([branch_ruleset])
    assert findings, "a branch ruleset must not satisfy the tag-creation requirement"
    assert "target='tag'" in findings[0]
    assert not _rre.is_tag_creation_protected([branch_ruleset])


def test_tag_protection_satisfied_by_active_v_tag_creation_ruleset():
    findings = _rre.tag_protection_findings([_tag_ruleset()])
    assert findings == []
    assert _rre.is_tag_creation_protected([_tag_ruleset()])


def test_tag_protection_satisfied_when_ref_is_all_tags():
    # A ~ALL tag ruleset covers refs/tags/v* too.
    findings = _rre.tag_protection_findings([_tag_ruleset(include=("~ALL",))])
    assert findings == []


def test_tag_protection_flags_inactive_or_incomplete_tag_ruleset():
    # Present but not active.
    inactive = _rre.tag_protection_findings([_tag_ruleset(enforcement="evaluate")])
    assert inactive and "enforcement='evaluate'" in inactive[0]
    # Present and active but no creation rule (e.g. only update/deletion).
    no_creation = _rre.tag_protection_findings([_tag_ruleset(rule_types=("deletion",))])
    assert no_creation and "no 'creation' rule" in no_creation[0]
    # Active with a creation rule but ref does not cover v*.
    wrong_ref = _rre.tag_protection_findings([_tag_ruleset(include=("refs/tags/rc*",))])
    assert wrong_ref and "does not cover refs/tags/v*" in wrong_ref[0]


def test_tag_protection_summary_only_payload_does_not_pass():
    # The list endpoint omits conditions/rules; a summary must not read as
    # protected (never green on absent evidence).
    summary = {"name": "v-tag-restricted", "target": "tag", "enforcement": "active"}
    findings = _rre.tag_protection_findings([summary])
    assert findings, "summary-only ruleset lacks a creation rule and must be flagged"


def test_tag_check_is_warn_until_applied_by_default():
    # Mirror DEVELOP_REVIEW_RULE_ENFORCED: the flag is False until the admin
    # POST lands, so the check lands non-blocking.
    assert _rre.TAG_RULESET_ENFORCED is False


def test_tag_check_main_warns_non_blocking_when_missing(tmp_path, capsys):
    import json as _json

    payload = tmp_path / "rulesets.json"
    payload.write_text(_json.dumps([]), encoding="utf-8")
    rc = _rre.main(["--rulesets-file", str(payload)])
    out = capsys.readouterr().out
    assert rc == 0, "missing tag ruleset must be non-blocking while WARN-until-applied"
    assert "WARNING (non-blocking):" in out
    assert "target='tag'" in out


def test_tag_check_main_passes_when_ruleset_present(tmp_path, capsys):
    import json as _json

    payload = tmp_path / "rulesets.json"
    payload.write_text(_json.dumps([_tag_ruleset()]), encoding="utf-8")
    rc = _rre.main(["--rulesets-file", str(payload)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Tag-creation ruleset - OK" in out


def test_tag_protection_flags_exclude_that_negates_v_coverage():
    # include covers v* (or ~ALL) but exclude removes it -> not protected.
    negated = _rre.tag_protection_findings(
        [
            _tag_ruleset(include=("~ALL",))
            | {"conditions": {"ref_name": {"include": ["~ALL"], "exclude": ["refs/tags/v*"]}}}
        ]
    )
    assert negated and "negates coverage" in negated[0]


def test_tag_bypass_advisory_surfaces_actors_without_failing_structure():
    # A structurally-valid ruleset with bypass actors is still "protected"
    # (must_preserve: the release identity needs bypass), but the advisory
    # forces the operator to confirm the actor list before enforcing.
    ruleset = _tag_ruleset() | {
        "bypass_actors": [{"actor_type": "Integration", "actor_id": 42, "bypass_mode": "always"}]
    }
    assert _rre.is_tag_creation_protected([ruleset])  # structure OK
    advisory = _rre.tag_bypass_advisory([ruleset])
    assert advisory and "bypass_actors" in advisory[0]
    assert "Integration:42" in advisory[0]


def test_tag_bypass_advisory_empty_when_no_bypass_or_no_ruleset():
    assert _rre.tag_bypass_advisory([_tag_ruleset()]) == []  # protected, no bypass
    assert _rre.tag_bypass_advisory([]) == []  # nothing protecting


def test_tag_check_main_prints_bypass_confirmation_on_ok(tmp_path, capsys):
    import json as _json

    ruleset = _tag_ruleset() | {"bypass_actors": [{"actor_type": "Team", "actor_id": 7, "bypass_mode": "pull_request"}]}
    payload = tmp_path / "rulesets.json"
    payload.write_text(_json.dumps([ruleset]), encoding="utf-8")
    rc = _rre.main(["--rulesets-file", str(payload)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Tag-creation ruleset - OK" in out
    assert "CONFIRM before enforcing:" in out


# ---------------------------------------------------------------------------
# Review-followup hardening: empty bypass_actors + fnmatch ref-glob matching
# ---------------------------------------------------------------------------


def test_tag_protection_flags_explicitly_empty_bypass_actors():
    # A structurally-valid ruleset with bypass_actors: [] (GitHub's shape for
    # "none configured") would itself block make release-finalize's own tag
    # push, so it must NOT read as protected.
    ruleset = _tag_ruleset() | {"bypass_actors": []}
    findings = _rre.tag_protection_findings([ruleset])
    assert findings and "bypass_actors is empty" in findings[0]
    assert not _rre.is_tag_creation_protected([ruleset])
    # No redundant advisory: the empty-bypass gap is already a finding above.
    assert _rre.tag_bypass_advisory([ruleset]) == []


def test_tag_protection_does_not_flag_missing_bypass_actors_key():
    # A caller that never populated bypass_actors at all (vs. GitHub
    # confirming zero via an explicit []) is left unasserted -- unlike a
    # confirmed-empty list, absence isn't evidence of anything.
    ruleset = _tag_ruleset()
    assert "bypass_actors" not in ruleset
    assert _rre.tag_protection_findings([ruleset]) == []


def test_tag_protection_include_covers_via_broader_fnmatch_glob():
    # refs/tags/* is a broader GitHub fnmatch glob that covers refs/tags/v*
    # just as fully as the literal pattern -- not just an exact string match.
    findings = _rre.tag_protection_findings([_tag_ruleset(include=("refs/tags/*",))])
    assert findings == []


def test_tag_protection_flags_exclude_that_negates_v_coverage_via_broader_glob():
    # The bug this regression pins: a prior exact-string exclude check missed
    # a broader-but-still-covering exclude glob like refs/tags/* (as opposed
    # to the byte-identical refs/tags/v* already covered by the older test
    # above), so an admin who wrote refs/tags/* saw a false "protected" OK.
    negated = _rre.tag_protection_findings(
        [
            _tag_ruleset(include=("~ALL",))
            | {"conditions": {"ref_name": {"include": ["~ALL"], "exclude": ["refs/tags/*"]}}}
        ]
    )
    assert negated and "negates coverage" in negated[0]


def test_tag_protection_narrower_exclude_does_not_negate_coverage():
    # refs/tags/rc* (a disjoint, narrower glob) does not overlap refs/tags/v*
    # at all, so it must not be treated as a negating exclude.
    findings = _rre.tag_protection_findings(
        [_tag_ruleset() | {"conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": ["refs/tags/rc*"]}}}]
    )
    assert findings == []


# ---------------------------------------------------------------------------
# scripts/ruleset_drift_check.py wiring (release-canary.yml's ruleset-drift
# job) -- the tag predicate must actually run in CI, not just via the
# standalone --rulesets-file CLI documented in the runbook.
# ---------------------------------------------------------------------------


def test_tag_creation_findings_warns_non_blocking_when_no_tag_ruleset_exists():
    # Live state: only develop/main-release rulesets exist, no target='tag'
    # ruleset yet -- must surface as a non-blocking warning by default
    # (TAG_RULESET_ENFORCED is False), same WARN-until-applied pattern as the
    # develop review rule.
    all_live = [
        _live_develop_ruleset(review_count=0, code_owner_review=False),
    ]
    findings = tag_creation_findings(all_live)
    assert findings and all(f.startswith(WARNING_PREFIX) for f in findings)
    assert blocking_findings(findings) == []
    assert any("target='tag'" in f for f in findings)


def test_tag_creation_findings_empty_when_ruleset_present_and_no_bypass_gap():
    all_live = [
        _tag_ruleset() | {"bypass_actors": [{"actor_type": "Integration", "actor_id": 1, "bypass_mode": "always"}]}
    ]
    findings = tag_creation_findings(all_live)
    # A non-empty bypass list is an advisory, not a failure -- still non-blocking.
    assert blocking_findings(findings) == []


def test_tag_creation_findings_can_be_switched_to_blocking_explicitly():
    # The one-line enforce switch: TAG_RULESET_ENFORCED=True would make this
    # call with enforce_tag_rule=True instead, turning the same gap blocking.
    findings = tag_creation_findings([], enforce_tag_rule=True)
    assert findings, "expected a blocking finding once tag-rule enforcement is on"
    assert not any(f.startswith(WARNING_PREFIX) for f in findings)
    assert blocking_findings(findings) == findings
