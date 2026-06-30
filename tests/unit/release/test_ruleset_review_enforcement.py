"""The develop ruleset must enforce a review before a soundness-path PR can merge.

Pins the predicate behind ``auto-merge-review-gate-admin-enforcement``: a ``develop``
ruleset whose ``pull_request`` rule allows zero approvals (or no code-owner review)
fails the check, so the soundness exception from #912 is enforceable at the repo
layer rather than only withheld in code. The narrated soundness paths are read from
``auto_merge_soundness_paths`` so this check and the auto-merge withholding cannot
drift apart.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ROOT / "_project" / "scripts"


def _load(name: str):
    # Ensure the sibling source-of-truth module resolves when loaded out of tree.
    sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rre = _load("ruleset_review_enforcement")
soundness = _load("auto_merge_soundness_paths")

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _pr_rule(count: int, code_owner: bool) -> list[dict]:
    return [
        {"type": "required_status_checks", "parameters": {"required_status_checks": []}},
        {
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": count,
                "require_code_owner_review": code_owner,
            },
        },
    ]


def test_enforced_ruleset_passes() -> None:
    rules = _pr_rule(count=1, code_owner=True)
    assert rre.is_review_enforced(rules) is True
    assert rre.review_enforcement_findings(rules) == []


def test_unenforced_ruleset_fails_on_both_axes() -> None:
    # The live develop state at authoring time: zero approvals, no code-owner review.
    findings = rre.review_enforcement_findings(_pr_rule(count=0, code_owner=False))
    assert findings, "an unenforced ruleset must produce findings (it currently does not)"
    blob = " ".join(findings)
    assert "required_approving_review_count=0" in blob
    assert "require_code_owner_review=False" in blob


def test_zero_count_alone_fails() -> None:
    findings = rre.review_enforcement_findings(_pr_rule(count=0, code_owner=True))
    assert any("required_approving_review_count" in f for f in findings)
    assert not any("require_code_owner_review" in f for f in findings)


def test_missing_code_owner_alone_fails() -> None:
    findings = rre.review_enforcement_findings(_pr_rule(count=2, code_owner=False))
    assert any("require_code_owner_review" in f for f in findings)
    assert not any("required_approving_review_count" in f for f in findings)


def test_missing_pull_request_rule_fails() -> None:
    rules = [{"type": "required_status_checks", "parameters": {"required_status_checks": []}}]
    findings = rre.review_enforcement_findings(rules)
    assert findings and "no pull_request rule" in findings[0]


def test_narrated_soundness_paths_come_from_shared_predicate() -> None:
    # Single source of truth: every auto-merge soundness prefix is narrated here.
    for prefix in soundness.SOUNDNESS_PREFIXES:
        assert any(prefix in glob for glob in rre.SOUNDNESS_PATH_GLOBS)
    assert "benchbox/core/**/validation.py" in rre.SOUNDNESS_PATH_GLOBS


def test_extract_rules_accepts_both_payload_shapes() -> None:
    flat = _pr_rule(count=1, code_owner=True)
    assert rre.extract_rules(flat) == flat
    assert rre.extract_rules({"rules": flat}) == flat
    assert rre.extract_rules({"name": "develop-squash-only", "rules": flat}) == flat


def test_cli_exit_codes(tmp_path: Path) -> None:
    import json

    enforced = tmp_path / "enforced.json"
    enforced.write_text(json.dumps(_pr_rule(count=1, code_owner=True)), encoding="utf-8")
    unenforced = tmp_path / "unenforced.json"
    unenforced.write_text(json.dumps(_pr_rule(count=0, code_owner=False)), encoding="utf-8")

    assert rre.main(["--rules-file", str(enforced)]) == 0
    assert rre.main(["--rules-file", str(unenforced)]) == 1
