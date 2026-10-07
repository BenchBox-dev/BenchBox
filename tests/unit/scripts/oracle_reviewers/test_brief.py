from __future__ import annotations

import stat
from pathlib import Path

import pytest

from _project.scripts.oracle_reviewers.brief import (
    FULL_DIFF_LINE,
    FULL_DIFF_PLACEHOLDER,
    build_brief,
    with_full_diff,
    write_private,
)
from _project.scripts.oracle_reviewers.classifier import ChangedFile

pytestmark = [pytest.mark.unit, pytest.mark.fast]

FILES = [ChangedFile("benchbox/core/equivalence/checker.py", None, 3, 1)]


def _brief(diff: str | None, max_bytes: int = 100_000):
    return build_brief(
        repo="BenchBox-dev/BenchBox",
        pr=7,
        base_sha="b" * 40,
        head_sha="a" * 40,
        tier="medium-high",
        blocking=("Critical", "High"),
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
        blocking=("Critical", "High"),
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
    assert FULL_DIFF_PLACEHOLDER not in _brief("+x = 1\n").text


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
