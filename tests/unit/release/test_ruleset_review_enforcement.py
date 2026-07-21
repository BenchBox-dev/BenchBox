"""The live develop ruleset must require a code-owner review.

The predicate is intentionally scoped to ``require_code_owner_review``. The
branch-wide ``required_approving_review_count`` setting is not asserted here,
because requiring it would gate every develop PR rather than only
CODEOWNERS-owned soundness paths.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ROOT / "_project" / "scripts"


def _load(name: str):
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
    rules = _pr_rule(count=0, code_owner=True)
    assert rre.is_review_enforced(rules) is True
    assert rre.review_enforcement_findings(rules) == []


def test_unenforced_ruleset_fails() -> None:
    findings = rre.review_enforcement_findings(_pr_rule(count=0, code_owner=False))
    assert findings
    assert "require_code_owner_review=False" in " ".join(findings)


def test_required_approving_review_count_is_not_checked() -> None:
    for count in (0, 1, 5):
        assert rre.review_enforcement_findings(_pr_rule(count=count, code_owner=True)) == []


def test_missing_pull_request_rule_fails() -> None:
    rules = [{"type": "required_status_checks", "parameters": {"required_status_checks": []}}]
    findings = rre.review_enforcement_findings(rules)
    assert findings and "no pull_request rule" in findings[0]


def test_narrated_soundness_paths_come_from_shared_predicate() -> None:
    for prefix in soundness.SOUNDNESS_PREFIXES:
        assert any(prefix in glob for glob in rre.SOUNDNESS_PATH_GLOBS)
    assert "benchbox/core/**/validation.py" in rre.SOUNDNESS_PATH_GLOBS


def test_extract_rules_accepts_both_payload_shapes() -> None:
    flat = _pr_rule(count=0, code_owner=True)
    assert rre.extract_rules(flat) == flat
    assert rre.extract_rules({"rules": flat}) == flat
    assert rre.extract_rules({"name": "develop-squash-only", "rules": flat}) == flat


def test_cli_exit_codes(tmp_path: Path) -> None:
    import json

    enforced = tmp_path / "enforced.json"
    enforced.write_text(json.dumps(_pr_rule(count=0, code_owner=True)), encoding="utf-8")
    unenforced = tmp_path / "unenforced.json"
    unenforced.write_text(json.dumps(_pr_rule(count=0, code_owner=False)), encoding="utf-8")

    assert rre.main(["--rules-file", str(enforced)]) == 0
    assert rre.main(["--rules-file", str(unenforced)]) == 1
