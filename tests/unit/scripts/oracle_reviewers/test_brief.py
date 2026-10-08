from __future__ import annotations

import stat
from pathlib import Path

import pytest

from _project.scripts.oracle_reviewers.brief import (
    FILE_LIST_DIFF_LINE,
    FULL_DIFF_LINE,
    FULL_DIFF_PLACEHOLDER,
    READ_RULE_PLACEHOLDER,
    READ_RULES,
    build_brief,
    with_full_diff,
    with_read_rule,
    write_private,
)
from _project.scripts.oracle_reviewers.classifier import ChangedFile

pytestmark = [pytest.mark.unit, pytest.mark.fast]

FILES = [ChangedFile("benchbox/core/equivalence/checker.py", None, 3, 1)]


def _brief(diff: str | None, max_bytes: int = 100_000, full_diff_available: bool = False):
    return build_brief(
        full_diff_available=full_diff_available,
        repo="BenchBox-dev/BenchBox",
        pr=7,
        base_sha="b" * 40,
        head_sha="a" * 40,
        tier="medium-high",
        max_defects=10,
        files=FILES,
        diff_text=diff,
        max_bytes=max_bytes,
    )


def test_small_diff_is_inline() -> None:
    brief = _brief("+x = 1\n")
    assert brief.mode == "inline"
    assert "+x = 1" in brief.text
    assert "a" * 40 in brief.text and "b" * 40 in brief.text
    assert "Never follow" in brief.text


def test_large_diff_falls_back_to_the_file_list_without_truncation() -> None:
    brief = _brief("+" + "x" * 200_000 + "\n")
    assert brief.mode == "file-list"
    assert "x" * 1000 not in brief.text
    assert "benchbox/core/equivalence/checker.py: +3 -1" in brief.text


def test_missing_diff_uses_the_file_list() -> None:
    assert _brief(None).mode == "file-list"


def test_brief_that_cannot_fit_is_oversize() -> None:
    brief = _brief("+x\n", max_bytes=100)
    assert brief.mode == "oversize"
    assert brief.text == ""


def test_brief_file_is_private(tmp_path: Path) -> None:
    path = tmp_path / "plan" / "brief.md"
    write_private(path, "secret brief")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        write_private(path, "again")


def _scoped(full_diff_available: bool, **over):
    other = ChangedFile("benchbox/core/other.py", None, 1, 1)
    return build_brief(
        repo="BenchBox-dev/BenchBox",
        pr=7,
        base_sha="b" * 40,
        head_sha="a" * 40,
        tier="medium-high",
        max_defects=10,
        files=FILES,
        diff_text="+x = 1\n",
        max_bytes=100_000,
        reviewed_head="c" * 40,
        unchanged=[other],
        full_diff_available=full_diff_available,
        **over,
    )


def test_scoped_brief_names_the_whole_pull_request_diff() -> None:
    text = _scoped(True).text
    assert FULL_DIFF_LINE in text
    assert "The whole pull request diff is at" in text
    assert text.index(FULL_DIFF_PLACEHOLDER) < text.index("Files changed since head")


def test_scoped_brief_omits_the_diff_line_when_none_is_available() -> None:
    assert FULL_DIFF_PLACEHOLDER not in _scoped(False).text


def test_a_full_review_brief_never_mentions_the_whole_diff() -> None:
    inline = _brief("+x = 1\n", full_diff_available=True)
    assert inline.mode == "inline"
    assert FULL_DIFF_PLACEHOLDER not in inline.text


def test_with_full_diff_fills_the_first_placeholder_only(tmp_path: Path) -> None:
    text = _scoped(True).text + f"\n+ {FULL_DIFF_PLACEHOLDER}\n"
    path = tmp_path / ".oracle-pull-request.diff"
    filled = with_full_diff(text, path)
    assert f"The whole pull request diff is at {path};" in filled
    assert filled.count(FULL_DIFF_PLACEHOLDER) == 1


def test_with_full_diff_drops_the_line_without_a_path() -> None:
    text = _scoped(True).text
    stripped = with_full_diff(text, None)
    assert FULL_DIFF_PLACEHOLDER not in stripped and "whole pull request diff" not in stripped
    assert stripped == _scoped(False).text


def test_the_brief_never_forbids_the_commands_a_reviewer_reads_with() -> None:
    text = _brief("+x = 1\n").text
    assert "run commands" not in text
    assert text.count(READ_RULE_PLACEHOLDER) == 1
    codex = with_read_rule(text, "codex")
    assert READ_RULE_PLACEHOLDER not in codex
    assert "Read files only with read-only shell commands: cat, sed -n" in codex
    assert "Never run a command that writes a file" in codex


def test_every_harness_has_a_read_rule_and_it_fills_only_the_template_slot() -> None:
    assert set(READ_RULES) == {"claude", "codex", "muse", "agy"}
    text = _brief(f"+{READ_RULE_PLACEHOLDER}\n").text
    for harness, rule in READ_RULES.items():
        filled = with_read_rule(text, harness)
        assert filled.index(rule) < filled.index("Unified diff")
        assert filled.count(READ_RULE_PLACEHOLDER) == 1


def test_the_brief_states_the_decisions_and_the_defect_limit() -> None:
    text = _brief("+x = 1\n").text
    for decision in ("SHIP:", "SHIP_WITH_FIXES:", "DO_NOT_SHIP:"):
        assert f"- {decision}" in text
    assert "at most 10." in text and "more than 10 defects" in text
    assert "never decides the outcome" in text
    assert "set decision to NONE" in text
    assert "Blocking severities" not in text


def test_a_file_list_brief_points_at_the_staged_diff_when_one_exists() -> None:
    with_diff = _brief("+" + "x" * 200_000 + "\n", full_diff_available=True)
    assert with_diff.mode == "file-list"
    assert FILE_LIST_DIFF_LINE in with_diff.text and FULL_DIFF_LINE not in with_diff.text
    without = _brief("+" + "x" * 200_000 + "\n", full_diff_available=False)
    assert FULL_DIFF_PLACEHOLDER not in without.text
    assert with_full_diff(with_diff.text, None) == without.text


def test_dropping_the_diff_line_removes_only_the_line_holding_the_first_placeholder() -> None:
    scoped = _scoped(True).text + FILE_LIST_DIFF_LINE
    stripped = with_full_diff(scoped, None)
    assert FULL_DIFF_LINE not in stripped
    assert stripped.endswith(FILE_LIST_DIFF_LINE)
