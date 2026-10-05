from __future__ import annotations

import stat
from pathlib import Path

import pytest

from _project.scripts.oracle_reviewers.brief import build_brief, write_private
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
