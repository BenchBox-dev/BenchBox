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
    base_date: str | None = None,
    comments: list[dict[str, Any]] | None = None,
) -> tuple[int, str]:
    return oracle_review_check.decide(
        HEAD,
        HEAD_DATE,
        files,
        reviews or [],
        reactions or [],
        threads or [],
        oracle_review_check.any_soundness_path,
        base_date,
        comments or [],
    )


def _review(
    login: str = CONNECTOR, commit_id: str = HEAD, state: str = "COMMENTED", submitted_at: str = AFTER_HEAD
) -> dict[str, Any]:
    return {"login": login, "commit_id": commit_id, "state": state, "submitted_at": submitted_at}


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
        f"oracle-review: waiting for the Codex connector's review of {HEAD}, or a stand-in attestation "
        f"'Stand-in oracle review: APPROVE {HEAD}' from a listed attester; rerun this check after it lands"
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


def _run(created_at: str, action: str, path: str = ".github/workflows/oracle-review.yml") -> dict[str, Any]:
    return {"path": path, "created_at": created_at, "display_title": f"oracle-review ({action})"}


def test_own_run_dates_match_plain_and_ref_qualified_workflow_paths() -> None:
    runs = [
        _run("2026-10-01T14:00:00Z", "opened"),
        _run("2026-10-01T15:00:00Z", "synchronize", ".github/workflows/oracle-review.yml@refs/pull/7/merge"),
        _run("2026-10-01T16:00:00Z", "synchronize", ".github/workflows/ci.yml"),
        {"created_at": "2026-10-01T17:00:00Z"},
    ]
    assert oracle_review_check.own_run_dates(runs) == [
        "2026-10-01T14:00:00Z",
        "2026-10-01T14:00:00Z",
        "2026-10-01T15:00:00Z",
    ]


def test_reopened_and_ready_runs_do_not_move_the_head_transition() -> None:
    runs = [
        _run("2026-10-01T12:30:00Z", "opened"),
        _run("2026-10-01T15:00:00Z", "reopened"),
        _run("2026-10-01T15:30:00Z", "ready_for_review"),
    ]
    dates = oracle_review_check.own_run_dates(runs)
    assert oracle_review_check.head_transition_date(HEAD_DATE, dates) == "2026-10-01T12:30:00Z"


def test_first_run_for_a_head_that_advanced_while_closed_is_a_transition() -> None:
    dates = oracle_review_check.own_run_dates([_run("2026-10-01T15:00:00Z", "reopened")])
    assert oracle_review_check.head_transition_date(HEAD_DATE, dates) == "2026-10-01T15:00:00Z"


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


RETARGETED = "2026-10-01T14:00:00Z"
AFTER_RETARGET = "2026-10-01T15:00:00Z"


def test_review_before_a_retarget_waits() -> None:
    status, _ = _decide(reviews=[_review()], base_date=RETARGETED)
    assert status == oracle_review_check.WAITING


def test_review_after_a_retarget_passes() -> None:
    status, _ = _decide(reviews=[_review(submitted_at=AFTER_RETARGET)], base_date=RETARGETED)
    assert status == oracle_review_check.PASS


def test_thumbs_up_before_a_retarget_waits() -> None:
    status, _ = _decide(reactions=[_reaction()], base_date=RETARGETED)
    assert status == oracle_review_check.WAITING


def test_thumbs_up_after_a_retarget_passes() -> None:
    status, _ = _decide(reactions=[_reaction(created_at=AFTER_RETARGET)], base_date=RETARGETED)
    assert status == oracle_review_check.PASS


def test_latest_base_change_picks_the_newest_retarget() -> None:
    events = [
        {"event": "base_ref_changed", "created_at": "2026-10-01T10:00:00Z"},
        {"event": "commented", "created_at": "2026-10-01T16:00:00Z"},
        {"event": "base_ref_changed", "created_at": RETARGETED},
    ]
    assert oracle_review_check.latest_base_change(events) == RETARGETED
    assert oracle_review_check.latest_base_change([{"event": "commented", "created_at": RETARGETED}]) is None


def _attestation(
    sha: str = HEAD,
    login: str = "joeharris76",
    created_at: str = AFTER_HEAD,
    prefix: str = "",
    updated_at: str | None = None,
    user_type: str = "User",
    body: str | None = None,
) -> dict[str, Any]:
    text = body or f"Stand-in review by agy: no P0/P1 findings.\n\n{prefix}Stand-in oracle review: APPROVE {sha}\n"
    return {
        "login": login,
        "user_type": user_type,
        "body": text,
        "created_at": created_at,
        "updated_at": updated_at or created_at,
    }


def test_standin_attestation_for_the_head_passes() -> None:
    status, message = _decide(comments=[_attestation()])
    assert status == oracle_review_check.PASS
    assert "stand-in review attested by joeharris76" in message


@pytest.mark.parametrize(
    "comment",
    [
        _attestation(sha=OLDER),
        _attestation(created_at=BEFORE_HEAD),
        _attestation(login="someone-else"),
        _attestation(prefix="> "),
        _attestation(body="Looks good to me"),
        _attestation(updated_at="2026-10-01T14:00:00Z"),
        _attestation(login="joeharris76[bot]", user_type="Bot"),
        _attestation(user_type="Bot"),
        _attestation(body=f"```\nStand-in oracle review: APPROVE {HEAD}\n```\n"),
        _attestation(body=f"- draft:\n  ```\nStand-in oracle review: APPROVE {HEAD}\n  ```\n"),
        _attestation(body=f"```\nStand-in oracle review: APPROVE {HEAD}\n"),
        _attestation(body=f"~~~\nStand-in oracle review: APPROVE {HEAD}\n~~~\n"),
        _attestation(body=f"<!--\nStand-in oracle review: APPROVE {HEAD}\n-->\n"),
        _attestation(body=f"<PRE>\nStand-in oracle review: APPROVE {HEAD}\n</PRE>\n"),
        _attestation(body=f"I would write Stand-in oracle review: APPROVE {HEAD} here"),
        _attestation(sha=HEAD.upper()),
    ],
    ids=[
        "older-commit",
        "before-head",
        "not-an-attester",
        "quoted",
        "no-marker",
        "edited",
        "bot-suffix",
        "bot-account",
        "fenced",
        "indented-fence",
        "unclosed-fence",
        "tilde-fence",
        "html-comment",
        "pre-block",
        "mid-line",
        "uppercase-sha",
    ],
)
def test_standin_attestation_must_be_exact_current_and_authorized(comment: dict[str, Any]) -> None:
    status, _ = _decide(comments=[comment])
    assert status == oracle_review_check.WAITING


def test_standin_attestation_does_not_override_open_connector_threads() -> None:
    status, message = _decide(comments=[_attestation()], threads=[_thread(resolved=False)])
    assert status == oracle_review_check.WAITING
    assert "unresolved Codex connector review thread" in message


def test_standin_attestation_before_a_retarget_waits() -> None:
    status, _ = _decide(comments=[_attestation(created_at=AFTER_HEAD)], base_date="2026-10-01T14:00:00Z")
    assert status == oracle_review_check.WAITING


def test_a_later_valid_attestation_counts_after_an_earlier_invalid_one() -> None:
    status, _ = _decide(comments=[_attestation(sha=OLDER), _attestation()])
    assert status == oracle_review_check.PASS


def test_connector_review_message_wins_over_a_standin() -> None:
    status, message = _decide(reviews=[_review()], comments=[_attestation()])
    assert status == oracle_review_check.PASS
    assert "Codex connector review" in message


def test_waiting_message_names_the_standin_marker() -> None:
    _, message = _decide()
    assert f"Stand-in oracle review: APPROVE {HEAD}" in message


def test_fetch_comments_maps_author_type_and_edit_time(monkeypatch: pytest.MonkeyPatch) -> None:
    item = {
        "user": {"login": "joeharris76", "type": "User"},
        "body": "x",
        "created_at": AFTER_HEAD,
        "updated_at": AFTER_HEAD,
    }
    monkeypatch.setattr(oracle_review_check, "_paginate", lambda _token, _path: [item])
    assert oracle_review_check.fetch_comments("t", "o/r", 1) == [
        {"login": "joeharris76", "user_type": "User", "body": "x", "created_at": AFTER_HEAD, "updated_at": AFTER_HEAD}
    ]
