"""Tests for GitHub ruleset drift detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import ruleset_drift_check
from scripts.ruleset_drift_check import compare_ruleset, parse_expected_rulesets

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).parent.parent.parent


def _live_ruleset(ref: str, checks: list[str], *, strict: bool = False, bypass: list[dict] | None = None) -> dict:
    return {
        "name": "main-release-only",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": [ref], "exclude": []}},
        "bypass_actors": bypass or [],
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": strict,
                    "required_status_checks": [{"context": check} for check in checks],
                },
            },
            {"type": "required_linear_history"},
            {"type": "non_fast_forward"},
            {"type": "deletion"},
        ],
    }


def test_parse_expected_rulesets_from_admin_runbook() -> None:
    expected = parse_expected_rulesets((REPO_ROOT / "docs" / "operations" / "repo-admin-settings.md").read_text())

    assert expected["develop-squash-only"].ref == "refs/heads/develop"
    assert expected["develop-squash-only"].required_checks == ("ci-required-result",)
    assert expected["main-release-only"].ref == "refs/heads/main"
    assert expected["main-release-only"].required_checks == ("validate-base", "release-required-result")
    assert expected["main-release-only"].strict_required_status_checks_policy is False
    assert expected["main-release-only"].bypass_actors_none is True


def test_matching_ruleset_has_no_drift_findings() -> None:
    expected = parse_expected_rulesets((REPO_ROOT / "docs" / "operations" / "repo-admin-settings.md").read_text())[
        "main-release-only"
    ]
    live = _live_ruleset("refs/heads/main", ["validate-base", "release-required-result"])

    assert compare_ruleset(expected, live) == []


def test_required_context_drift_is_reported() -> None:
    expected = parse_expected_rulesets((REPO_ROOT / "docs" / "operations" / "repo-admin-settings.md").read_text())[
        "main-release-only"
    ]
    live = _live_ruleset("refs/heads/main", ["validate-base"])

    findings = compare_ruleset(expected, live)

    assert findings
    assert "required checks" in findings[0]
    assert "release-required-result" in findings[0]


def test_ruleset_policy_drift_is_reported() -> None:
    expected = parse_expected_rulesets((REPO_ROOT / "docs" / "operations" / "repo-admin-settings.md").read_text())[
        "main-release-only"
    ]
    live = _live_ruleset(
        "refs/heads/main",
        ["validate-base", "release-required-result"],
        strict=True,
        bypass=[{"actor_type": "RepositoryRole"}],
    )
    live["rules"] = [rule for rule in live["rules"] if rule["type"] != "deletion"]

    findings = compare_ruleset(expected, live)

    assert any("strict_required_status_checks_policy" in finding for finding in findings)
    assert any("deletion" in finding for finding in findings)
    assert any("bypass actors" in finding for finding in findings)


def test_bypass_actor_visibility_can_be_required() -> None:
    expected = parse_expected_rulesets((REPO_ROOT / "docs" / "operations" / "repo-admin-settings.md").read_text())[
        "main-release-only"
    ]
    live = _live_ruleset("refs/heads/main", ["validate-base", "release-required-result"])
    del live["bypass_actors"]

    findings = compare_ruleset(expected, live, require_bypass_actor_visibility=True)

    assert any("bypass actors are not visible" in finding for finding in findings)


def test_github_api_failure_is_reported_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _raise_api_error(_repo: str, _token: str) -> dict:
        raise RuntimeError("api unavailable")

    output = tmp_path / "ruleset-drift.json"
    monkeypatch.setattr(ruleset_drift_check, "_fetch_live_rulesets", _raise_api_error)
    monkeypatch.delenv("RELEASE_READINESS_OVERRIDE_SHA", raising=False)
    monkeypatch.delenv("RELEASE_READINESS_OVERRIDE_REASON", raising=False)

    rc = ruleset_drift_check.main(["--token", "token", "--output", str(output)])

    assert rc == 1
    assert json.loads(output.read_text()) == {"status": "error", "error": "api unavailable"}
