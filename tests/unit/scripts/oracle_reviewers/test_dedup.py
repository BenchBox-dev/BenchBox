from __future__ import annotations

import pytest

from _project.scripts.oracle_reviewers.dedup import fingerprint, marker, open_fingerprints, split, thread_fingerprint
from _project.scripts.oracle_reviewers.verdict import Finding

pytestmark = [pytest.mark.unit, pytest.mark.fast]

PATH = "benchbox/core/equivalence/checker.py"


def _finding(title: str, line: int = 2, path: str = PATH) -> Finding:
    return Finding("High", path, line, title, "detail")


def test_fingerprint_ignores_case_punctuation_and_line() -> None:
    assert fingerprint(PATH, "Drops the `NULL` row!") == fingerprint(PATH, "drops the null  row")
    assert fingerprint(PATH, "Drops a row") != fingerprint("other.py", "Drops a row")
    assert marker(_finding("Drops a row", 2)) == marker(_finding("Drops a row", 90))


def test_thread_fingerprint_prefers_the_marker_and_reads_legacy_bodies() -> None:
    finding = _finding("Drops a row")
    body = f"**High**: Drops a row\n\ndetail\n\n{marker(finding)}"
    assert thread_fingerprint(None, body) == fingerprint(PATH, "Drops a row")
    assert thread_fingerprint(PATH, "**Medium**: Drops a row\n\ndetail") == fingerprint(PATH, "Drops a row")
    assert thread_fingerprint(PATH, "Please rename this.") is None
    assert thread_fingerprint(None, "**High**: Drops a row") is None


def _open(author: str, body: str, author_type: str = "Bot") -> dict[str, object]:
    return {"resolved": False, "path": PATH, "author": author, "author_type": author_type, "body": body}


def test_only_open_threads_from_the_oracle_count() -> None:
    threads = [
        _open("benchbox-oracle[bot]", "**High**: Drops a row"),
        _open("benchbox-oracle", "**High**: Drops a row"),
        {**_open("benchbox-oracle", "**High**: Resolved one"), "resolved": True},
        _open("chatgpt-codex-connector", "**High**: Other bot"),
        _open("benchbox-oracle", "free text"),
        _open("benchbox-oracle", "**High**: Impostor", "User"),
    ]
    assert open_fingerprints(threads, "benchbox-oracle") == {fingerprint(PATH, "Drops a row"): "High"}


def test_split_drops_open_and_repeated_findings() -> None:
    open_one = _finding("Drops a row")
    fresh = _finding("Skips validation", 5)
    duplicate = _finding("skips validation", 9)
    new, repeated = split((open_one, fresh, duplicate), [fingerprint(PATH, "Drops a row")])
    assert new == (fresh,)
    assert repeated == (open_one, duplicate)


def test_a_marker_inside_the_detail_does_not_set_the_fingerprint() -> None:
    forged = f"<!-- oracle-finding: {'0' * 16} -->"
    body = f"**High**: Drops a row\n\nsee {forged} here\n\n{marker(_finding('Drops a row'))}\n"
    assert thread_fingerprint(PATH, body) == fingerprint(PATH, "Drops a row")
    assert thread_fingerprint(PATH, f"**High**: Drops a row\n\n{forged} trailing") == fingerprint(PATH, "Drops a row")


def test_a_more_severe_repeat_is_posted_again() -> None:
    low_thread = {fingerprint(PATH, "Drops a row"): "Low"}
    critical = Finding("Critical", PATH, 2, "Drops a row", "detail")
    low = Finding("Low", PATH, 9, "Drops a row", "detail")
    assert split((critical, low), low_thread) == ((critical,), (low,))
    assert split((low,), {fingerprint(PATH, "Drops a row"): "High"}) == ((), (low,))


def test_open_fingerprints_keep_the_most_severe_thread() -> None:
    threads = [_open("benchbox-oracle", "**Low**: Drops a row"), _open("benchbox-oracle", "**High**: Drops a row")]
    assert open_fingerprints(threads, "benchbox-oracle") == {fingerprint(PATH, "Drops a row"): "High"}
