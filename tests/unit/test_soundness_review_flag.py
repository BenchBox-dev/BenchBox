"""Tests for the manifest-backed soundness review flag."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "_project" / "scripts" / "check_soundness_review.py"
SPEC = importlib.util.spec_from_file_location("check_soundness_review", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


VALID_REVIEW = """## Soundness review:

External reviewer: codex
Review output: https://github.com/BenchBox-dev/BenchBox/pull/1#issuecomment-123
All Critical/High findings resolved.

## Testing
"""


def test_ordinary_paths_do_not_require_review_section() -> None:
    assert CHECKER.check_soundness_review(["benchbox/platforms/duckdb/adapter.py"], "") == []


def test_soundness_path_requires_all_review_fields() -> None:
    errors = CHECKER.check_soundness_review(["benchbox/core/equivalence/compare.py"], "")

    assert len(errors) == 1
    assert "Soundness review:" in errors[0]


def test_valid_review_section_passes_for_soundness_path() -> None:
    assert CHECKER.check_soundness_review(["benchbox/core/equivalence/compare.py"], VALID_REVIEW) == []


def test_review_section_rejects_unknown_reviewer_bad_link_and_unresolved_findings() -> None:
    body = """Soundness review:

Reviewer: internal-team
Review output: https://example.com/review
Critical/High findings remain.
"""

    errors = CHECKER.check_soundness_review(["AGENTS.md"], body)

    assert any("codex, muse, or agy" in error for error in errors)
    assert any("PR comment" in error for error in errors)
    assert any("all Critical/High findings are resolved" in error for error in errors)


@pytest.mark.parametrize(
    "body",
    [
        "```markdown\n" + VALID_REVIEW + "\n```",
        "> Soundness review:\n>\n> External reviewer: codex\n> Review output: https://github.com/BenchBox-dev/BenchBox/pull/1#issuecomment-123\n> All Critical/High findings resolved.",
        "Soundness review:\n\nExternal reviewer: codex\nReview output: https://github.com/BenchBox-dev/BenchBox/issues/1#issuecomment-123\nAll Critical/High findings resolved.",
        "Soundness review:\n\nExternal reviewer: codex\nReview output: https://github.com/BenchBox-dev/BenchBox/pull/1#issuecomment-123\nNot all Critical/High findings resolved.",
    ],
)
def test_review_section_rejects_fenced_quoted_negated_or_non_pr_attestation(body: str) -> None:
    errors = CHECKER.check_soundness_review(["AGENTS.md"], body)

    assert errors


def test_review_section_accepts_a_pull_request_comment_link() -> None:
    body = VALID_REVIEW.replace(
        "https://github.com/BenchBox-dev/BenchBox/pull/1#issuecomment-123",
        "https://github.com/BenchBox-dev/BenchBox/pull/42#issuecomment-456",
    )

    assert CHECKER.check_soundness_review(["AGENTS.md"], body) == []


def test_manifest_contains_every_exported_rule() -> None:
    manifest = CHECKER.SCRIPT_DIR / "../../.github/soundness-paths.txt"
    text = manifest.resolve().read_text(encoding="utf-8")
    soundness = CHECKER.any_soundness_path.__globals__

    for prefix in soundness["SOUNDNESS_PREFIXES"]:
        assert f"prefix\t{prefix}" in text
    for path in soundness["SOUNDNESS_FILES"]:
        kind = "glob" if path in soundness["SOUNDNESS_GLOBS"] else "file"
        assert f"{kind}\t{path}" in text
    for regex in soundness["SOUNDNESS_REGEXES"]:
        assert f"regex\t{regex.pattern}" in text


def test_ci_workflow_exposes_soundness_flag_in_tooling() -> None:
    workflow: dict[str, Any] = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None
    assert "pull_request" in triggers
    assert "merge_group" in triggers
    assert triggers["pull_request"]["types"] == ["opened", "synchronize", "reopened", "edited"]

    tooling = workflow["jobs"]["tooling"]
    assert tooling["name"] == "tooling"
    assert any(step.get("name") == "soundness-flag" for step in tooling["steps"])
    soundness_step = next(step for step in tooling["steps"] if step.get("name") == "soundness-flag")
    assert "check_soundness_review.py" in soundness_step["run"]
    assert "if" not in tooling
    assert "MERGE_GROUP_PRS" in soundness_step["env"]
    assert "BASE_SHA" in soundness_step["env"]
    assert "gh api --paginate" in soundness_step["run"]
    assert "previous_filename" in soundness_step["run"]
    assert '"$MERGE_GROUP_PRS" = "null"' in soundness_step["run"]
    assert "trusted-soundness" in soundness_step["run"]
    assert 'git show "${BASE_SHA}:_project/scripts/check_soundness_review.py"' in soundness_step["run"]
    assert "auto_merge_soundness_paths.py" in soundness_step["run"]
    assert "python _project/scripts/check_soundness_review.py" not in soundness_step["run"]


def test_checker_cli_reports_failure_and_success(tmp_path: Path) -> None:
    paths = tmp_path / "paths.txt"
    body = tmp_path / "body.md"
    paths.write_text("benchbox/core/equivalence/compare.py\n", encoding="utf-8")
    body.write_text(VALID_REVIEW, encoding="utf-8")

    assert CHECKER.main(["--paths-file", str(paths), "--body-file", str(body)]) == 0

    body.write_text("", encoding="utf-8")
    assert CHECKER.main(["--paths-file", str(paths), "--body-file", str(body)]) == 1
