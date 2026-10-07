from __future__ import annotations

import json
from typing import Any

import pytest

from _project.scripts.oracle_reviewers.diff import commentable_lines, select_files
from _project.scripts.oracle_reviewers.verdict import (
    LINK_REMOVED,
    REDACTED,
    VERDICT_SCHEMA,
    VerdictError,
    parse_output,
    place,
    sanitize,
    validate,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]

DIFF = """diff --git a/benchbox/core/equivalence/checker.py b/benchbox/core/equivalence/checker.py
index 1111111..2222222 100644
--- a/benchbox/core/equivalence/checker.py
+++ b/benchbox/core/equivalence/checker.py
@@ -10,3 +10,4 @@ def compare(left, right):
     a = 1
-    b = 2
+    b = 3
+    c = 4
     return a
@@ -40,0 +42,2 @@
+x = 1
+y = 2
diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-gone = 1
-gone = 2
diff --git a/new.txt b/new.txt
new file mode 100644
--- /dev/null
+++ b/new.txt
@@ -0,0 +1 @@
+++ looks like a header
\\ No newline at end of file
"""


def _finding(**overrides: Any) -> dict[str, Any]:
    finding = {
        "severity": "High",
        "file": "benchbox/core/equivalence/checker.py",
        "line": 11,
        "title": "Wrong constant",
        "detail": "b changed",
    }
    finding.update(overrides)
    return finding


def _verdict(*findings: dict[str, Any], summary: str = "Reviewed.") -> dict[str, Any]:
    return {"summary": summary, "findings": list(findings)}


def test_schema_is_strict() -> None:
    assert VERDICT_SCHEMA["additionalProperties"] is False
    item = VERDICT_SCHEMA["properties"]["findings"]["items"]
    assert item["additionalProperties"] is False
    assert item["required"] == ["severity", "file", "line", "title", "detail"]
    assert item["properties"]["severity"]["enum"] == ["Critical", "High", "Medium", "Low"]
    assert "head_sha" not in VERDICT_SCHEMA["properties"]


def test_valid_verdict_round_trips() -> None:
    verdict = validate(_verdict(_finding(), _finding(severity="Low", line=99)))
    assert [finding.severity for finding in verdict.findings] == ["High", "Low"]
    assert [finding.severity for finding in verdict.blocking(("Critical", "High"))] == ["High"]
    assert validate(verdict.to_json()) == verdict


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"summary": "x"},
        {"summary": "x", "findings": [], "head_sha": "a" * 40},
        _verdict(_finding(severity="critical")),
        _verdict(_finding(severity="Blocker")),
        _verdict(_finding(line=0)),
        _verdict(_finding(line=True)),
        _verdict(_finding(line="12")),
        _verdict(_finding(file="/etc/passwd")),
        _verdict(_finding(file="../outside.py")),
        _verdict(_finding(file="")),
        _verdict(_finding(title=" ")),
        _verdict({**_finding(), "extra": 1}),
        _verdict({key: value for key, value in _finding().items() if key != "detail"}),
        {"summary": 3, "findings": []},
        {"summary": "x", "findings": [_finding()] * 51},
    ],
)
def test_invalid_verdicts_are_rejected(payload: Any) -> None:
    with pytest.raises(VerdictError):
        validate(payload)


def test_head_sha_comes_from_the_run_not_the_model() -> None:
    with pytest.raises(VerdictError):
        validate({**_verdict(), "head_sha": "b" * 40})


def test_sanitize_redacts_secrets() -> None:
    samples = [
        "sk-ant-oat01-" + "A" * 40,
        "sk-proj-" + "B" * 40,
        "ghp_" + "C" * 36,
        "github_pat_" + "D" * 40,
        "AKIA" + "E" * 16,
        "-----BEGIN RSA " + "PRIVATE KEY-----\nabc\n-----END RSA " + "PRIVATE KEY-----",
        "api_key = supersecretvalue123",
        "xoxb-" + "1" * 20,
    ]
    for sample in samples:
        cleaned = sanitize(f"leak {sample} end", 5000)
        assert REDACTED in cleaned, sample
        assert sample not in cleaned


def test_sanitize_strips_mentions_and_links() -> None:
    cleaned = sanitize("ping @owner and see [docs](https://evil.example/x) or http://a.b/c and www.x.y", 5000)
    assert "@owner" not in cleaned and "owner" in cleaned
    assert "evil.example" not in cleaned and "docs" in cleaned
    assert "http://" not in cleaned and "www.x.y" not in cleaned
    assert LINK_REMOVED in cleaned
    assert sanitize("a@b.com", 50) == "a@b.com"


def test_validation_sanitizes_and_truncates_text() -> None:
    verdict = validate(_verdict(_finding(title="@team " + "x" * 300, detail="token: " + "Z" * 30)))
    finding = verdict.findings[0]
    assert len(finding.title) <= 200
    assert "@team" not in finding.title
    assert REDACTED in finding.detail


def test_parse_claude_envelope_prefers_structured_output() -> None:
    envelope = {"type": "result", "is_error": False, "result": "text", "structured_output": _verdict()}
    assert parse_output("claude", json.dumps(envelope)) == _verdict()
    envelope = {"type": "result", "is_error": False, "result": json.dumps(_verdict())}
    assert parse_output("claude", json.dumps(envelope)) == _verdict()
    with pytest.raises(VerdictError):
        parse_output("claude", json.dumps({"is_error": True, "result": "limit"}))


def test_parse_plain_and_fenced_output() -> None:
    assert parse_output("muse", json.dumps(_verdict())) == _verdict()
    assert parse_output("muse", "```json\n" + json.dumps(_verdict()) + "\n```") == _verdict()
    with pytest.raises(VerdictError):
        parse_output("muse", "Here is my review: " + json.dumps(_verdict()))


def test_commentable_lines_follow_the_right_side_of_hunks() -> None:
    lines = commentable_lines(DIFF)
    assert lines["benchbox/core/equivalence/checker.py"] == {10, 11, 12, 13, 42, 43}
    assert "old.py" not in lines
    assert lines["new.txt"] == {1}


def test_findings_split_into_inline_and_summary() -> None:
    verdict = validate(
        _verdict(
            _finding(line=12),
            _finding(line=30),
            _finding(file="benchbox/other.py", line=1),
        )
    )
    placement = place(verdict.findings, commentable_lines(DIFF))
    assert [finding.line for finding in placement.inline] == [12]
    assert [(finding.file, finding.line) for finding in placement.summary] == [
        ("benchbox/core/equivalence/checker.py", 30),
        ("benchbox/other.py", 1),
    ]


def test_select_files_keeps_only_the_named_file_sections() -> None:
    diff = (
        "diff --git a/one.py b/one.py\n--- a/one.py\n+++ b/one.py\n@@ -1 +1 @@\n-a\n+b\n"
        "diff --git a/old.py b/new.py\nsimilarity index 90%\nrename from old.py\nrename to new.py\n"
        "diff --git a/two.py b/two.py\n--- a/two.py\n+++ b/two.py\n@@ -1 +1 @@\n-c\n+d\n"
    )
    assert select_files(diff, frozenset({"two.py"})) == (
        "diff --git a/two.py b/two.py\n--- a/two.py\n+++ b/two.py\n@@ -1 +1 @@\n-c\n+d\n"
    )
    assert select_files(diff, frozenset({"old.py"})).startswith("diff --git a/old.py b/new.py\n")
    assert select_files(diff, frozenset()) == ""
