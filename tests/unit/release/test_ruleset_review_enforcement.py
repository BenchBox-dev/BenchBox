"""The live develop ruleset must require review thread resolution.

The branch-wide ``required_approving_review_count`` setting is not asserted
here, because requiring it would gate every develop PR.
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

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _pr_rule(count: int, thread_resolution: bool | None = True) -> list[dict]:
    parameters: dict[str, object] = {
        "required_approving_review_count": count,
    }
    if thread_resolution is not None:
        parameters["required_review_thread_resolution"] = thread_resolution
    return [
        {"type": "required_status_checks", "parameters": {"required_status_checks": []}},
        {
            "type": "pull_request",
            "parameters": parameters,
        },
    ]


def test_enforced_ruleset_passes() -> None:
    rules = _pr_rule(count=0, thread_resolution=True)
    assert rre.is_review_enforced(rules) is True
    assert rre.review_enforcement_findings(rules) == []


def test_unenforced_thread_resolution_fails() -> None:
    findings = rre.review_enforcement_findings(_pr_rule(count=0, thread_resolution=False))
    assert findings
    assert "required_review_thread_resolution=False" in " ".join(findings)


def test_missing_thread_resolution_fails() -> None:
    findings = rre.review_enforcement_findings(_pr_rule(count=0, thread_resolution=None))
    assert findings
    assert "required_review_thread_resolution=False" in " ".join(findings)


def test_required_approving_review_count_is_not_checked() -> None:
    for count in (0, 1, 5):
        assert rre.review_enforcement_findings(_pr_rule(count=count, thread_resolution=True)) == []


def test_missing_pull_request_rule_fails() -> None:
    rules = [{"type": "required_status_checks", "parameters": {"required_status_checks": []}}]
    findings = rre.review_enforcement_findings(rules)
    assert findings and "no pull_request rule" in findings[0]


def test_extract_rules_accepts_both_payload_shapes() -> None:
    flat = _pr_rule(count=0)
    assert rre.extract_rules(flat) == flat
    assert rre.extract_rules({"rules": flat}) == flat
    assert rre.extract_rules({"name": "develop-squash-only", "rules": flat}) == flat


def test_cli_exit_codes(tmp_path: Path) -> None:
    import json

    enforced = tmp_path / "enforced.json"
    enforced.write_text(json.dumps(_pr_rule(count=0)), encoding="utf-8")
    unenforced = tmp_path / "unenforced.json"
    unenforced.write_text(json.dumps(_pr_rule(count=0, thread_resolution=False)), encoding="utf-8")

    assert rre.main(["--rules-file", str(enforced)]) == 0
    assert rre.main(["--rules-file", str(unenforced)]) == 1
