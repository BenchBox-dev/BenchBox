from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "_project/scripts/oracle_review_check.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("oracle_review_check", SCRIPT)
assert SPEC and SPEC.loader
oracle_review_check = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = oracle_review_check
SPEC.loader.exec_module(oracle_review_check)

pytestmark = [pytest.mark.unit, pytest.mark.fast]

HEAD = "a" * 40
OLDER = "b" * 40
HEAD_DATE = "2026-10-01T12:00:00Z"
BEFORE_HEAD = "2026-10-01T11:00:00Z"
AFTER_HEAD = "2026-10-01T13:00:00Z"
SOUNDNESS_FILES = ["benchbox/core/equivalence/checker.py", "README.md"]
OTHER_FILES = ["README.md", "docs/index.md"]
CONNECTOR = "chatgpt-codex-connector[bot]"


def _decide(
    files: list[str] = SOUNDNESS_FILES,
    reviews: list[dict[str, Any]] | None = None,
    reactions: list[dict[str, Any]] | None = None,
    threads: list[dict[str, Any]] | None = None,
) -> tuple[int, str]:
    return oracle_review_check.decide(
        HEAD,
        HEAD_DATE,
        files,
        reviews or [],
        reactions or [],
        threads or [],
        oracle_review_check.any_soundness_path,
    )


def _review(login: str = CONNECTOR, commit_id: str = HEAD, state: str = "COMMENTED") -> dict[str, Any]:
    return {"login": login, "commit_id": commit_id, "state": state}


def _reaction(content: str = "+1", created_at: str = AFTER_HEAD, login: str = CONNECTOR) -> dict[str, Any]:
    return {"login": login, "content": content, "created_at": created_at}


def _thread(resolved: bool, author: str = "chatgpt-codex-connector") -> dict[str, Any]:
    return {"resolved": resolved, "author": author}


def test_non_soundness_change_skips() -> None:
    status, message = _decide(files=OTHER_FILES)
    assert status == 0
    assert message == "oracle-review: not a soundness path change"


def test_review_on_head_passes() -> None:
    status, message = _decide(reviews=[_review()])
    assert status == 0
    assert "review" in message
    assert HEAD in message


def test_review_on_older_commit_waits() -> None:
    status, message = _decide(reviews=[_review(commit_id=OLDER)])
    assert status == 1
    assert message == (
        f"oracle-review: waiting for the Codex connector's review of {HEAD}; rerun this check after it lands"
    )


def test_thumbs_up_after_head_passes() -> None:
    status, message = _decide(reactions=[_reaction()])
    assert status == 0
    assert "+1" in message


def test_thumbs_up_before_head_waits() -> None:
    status, _ = _decide(reactions=[_reaction(created_at=BEFORE_HEAD)])
    assert status == 1


def test_eyes_only_waits() -> None:
    status, _ = _decide(reactions=[_reaction(content="eyes")])
    assert status == 1


def test_unresolved_connector_thread_waits_even_with_review() -> None:
    status, message = _decide(reviews=[_review()], threads=[_thread(resolved=False)])
    assert status == 1
    assert "unresolved" in message


def test_resolved_connector_thread_with_review_passes() -> None:
    status, _ = _decide(reviews=[_review()], threads=[_thread(resolved=True)])
    assert status == 0


def test_unresolved_thread_by_another_author_does_not_block() -> None:
    status, _ = _decide(reviews=[_review()], threads=[_thread(resolved=False, author="joeharris76")])
    assert status == 0


def test_owner_review_does_not_count() -> None:
    status, _ = _decide(reviews=[_review(login="joeharris76")])
    assert status == 1


def test_owner_thumbs_up_does_not_count() -> None:
    status, _ = _decide(reactions=[_reaction(login="joeharris76")])
    assert status == 1


def test_pending_review_does_not_count() -> None:
    status, _ = _decide(reviews=[_review(state="PENDING")])
    assert status == 1


def test_rename_out_of_a_soundness_path_is_a_soundness_change() -> None:
    files = oracle_review_check.changed_paths(
        [{"filename": "docs/moved.py", "previous_filename": "benchbox/core/equivalence/checker.py"}]
    )
    assert files == ["docs/moved.py", "benchbox/core/equivalence/checker.py"]
    status, _ = _decide(files=files)
    assert status == 1


def test_changed_paths_without_a_rename_keeps_only_the_filename() -> None:
    assert oracle_review_check.changed_paths([{"filename": "README.md"}]) == ["README.md"]


def test_backdated_head_commit_does_not_make_an_older_thumbs_up_count() -> None:
    backdated_commit = "2026-09-01T00:00:00Z"
    push_run = "2026-10-01T14:00:00Z"
    head_date = oracle_review_check.head_transition_date(backdated_commit, [push_run])
    assert head_date == push_run
    status, _ = oracle_review_check.decide(
        HEAD,
        head_date,
        SOUNDNESS_FILES,
        [],
        [_reaction(created_at=AFTER_HEAD)],
        [],
        oracle_review_check.any_soundness_path,
    )
    assert status == 1


def test_head_transition_date_falls_back_to_the_committer_date_without_runs() -> None:
    assert oracle_review_check.head_transition_date(HEAD_DATE, []) == HEAD_DATE


def test_head_transition_date_keeps_a_later_committer_date() -> None:
    assert oracle_review_check.head_transition_date(AFTER_HEAD, [HEAD_DATE]) == AFTER_HEAD


def test_truncated_file_list_is_treated_as_a_soundness_change() -> None:
    matcher = oracle_review_check.path_matcher(listed_files=3000, changed_files=3001)
    assert matcher(OTHER_FILES) is True
    status, _ = oracle_review_check.decide(HEAD, HEAD_DATE, OTHER_FILES, [], [], [], matcher)
    assert status == 1


def test_complete_file_list_uses_the_soundness_predicate() -> None:
    matcher = oracle_review_check.path_matcher(listed_files=2, changed_files=2)
    assert matcher(OTHER_FILES) is False
    assert matcher(SOUNDNESS_FILES) is True


def test_own_run_dates_match_plain_and_ref_qualified_workflow_paths() -> None:
    runs = [
        {"path": ".github/workflows/oracle-review.yml", "created_at": "2026-10-01T14:00:00Z"},
        {"path": ".github/workflows/oracle-review.yml@refs/pull/7/merge", "created_at": "2026-10-01T15:00:00Z"},
        {"path": ".github/workflows/ci.yml", "created_at": "2026-10-01T16:00:00Z"},
        {"created_at": "2026-10-01T17:00:00Z"},
    ]
    assert oracle_review_check.own_run_dates(runs) == ["2026-10-01T14:00:00Z", "2026-10-01T15:00:00Z"]


def test_latest_run_for_a_restored_head_moves_the_head_transition() -> None:
    first_run = "2026-10-01T12:30:00Z"
    restored_run = "2026-10-01T16:00:00Z"
    head_date = oracle_review_check.head_transition_date(HEAD_DATE, [first_run, restored_run])
    assert head_date == restored_run
    status, _ = oracle_review_check.decide(
        HEAD,
        head_date,
        SOUNDNESS_FILES,
        [],
        [_reaction(created_at=AFTER_HEAD)],
        [],
        oracle_review_check.any_soundness_path,
    )
    assert status == 1
