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
ORACLE = "benchbox-oracle[bot]"


def _decide(
    files: list[str] = SOUNDNESS_FILES,
    reviews: list[dict[str, Any]] | None = None,
    reactions: list[dict[str, Any]] | None = None,
    threads: list[dict[str, Any]] | None = None,
    base_date: str | None = None,
    comments: list[dict[str, Any]] | None = None,
    signal: str = "connector",
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
        signal,
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
    text = body or f"{prefix}Stand-in oracle review: APPROVE {sha}\n"
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
        _attestation(body=f"see `\nStand-in oracle review: APPROVE {HEAD}\n`\n"),
        _attestation(body=f'[a]: /u "\nStand-in oracle review: APPROVE {HEAD}\n"\n'),
        _attestation(body=f"<details>\nStand-in oracle review: APPROVE {HEAD}\n</details>\n"),
        _attestation(body=f"<code>\nStand-in oracle review: APPROVE {HEAD}\n</code>\n"),
        _attestation(body=f"No P0/P1 findings.\n\nStand-in oracle review: APPROVE {HEAD}\n"),
        _attestation(body=f"I would write Stand-in oracle review: APPROVE {HEAD} here"),
        _attestation(sha=HEAD.upper()),
    ],
    ids=[
        "older-commit",
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
        "inline-code",
        "link-title",
        "details-block",
        "code-block",
        "extra-text",
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


def _oracle_review(**over: Any) -> dict[str, Any]:
    return {**_review(login=ORACLE), "user_type": "Bot", **over}


def _status(state: str = "success", created_at: str = AFTER_HEAD, **over: Any) -> dict[str, Any]:
    status = {
        "context": "oracle-review-shadow",
        "state": state,
        "creator": ORACLE,
        "creator_type": "Bot",
        "created_at": created_at,
    }
    return {**status, **over}


def _oracle(**kwargs: Any) -> tuple[int, str]:
    statuses = kwargs.pop("statuses", [_status()])
    return oracle_review_check.decide(
        HEAD,
        HEAD_DATE,
        SOUNDNESS_FILES,
        kwargs.pop("reviews", [_oracle_review()]),
        kwargs.pop("reactions", []),
        kwargs.pop("threads", []),
        oracle_review_check.any_soundness_path,
        kwargs.pop("base_date", None),
        kwargs.pop("comments", []),
        "oracle",
        statuses,
    )


def test_oracle_review_with_a_success_status_passes_only_under_the_oracle_signal() -> None:
    assert _oracle() == (0, f"oracle-review: pass (oracle review of {HEAD})")
    assert _decide(reviews=[_oracle_review()])[0] == 1


@pytest.mark.parametrize(
    "statuses",
    [
        [],
        [_status("failure")],
        [_status("pending")],
        [_status("success", created_at=BEFORE_HEAD), _status("failure")],
        [_status(context="other")],
        [_status(creator="benchbox-oracle", creator_type="User")],
    ],
    ids=["missing", "failure", "pending", "latest-failure", "other-context", "user-creator"],
)
def test_oracle_review_needs_the_oracles_success_status(statuses: list[dict[str, Any]]) -> None:
    status, message = _oracle(statuses=statuses)
    assert status == 1
    assert "oracle-review-shadow status" in message


def test_latest_oracle_status_wins() -> None:
    statuses = [_status("failure", created_at=BEFORE_HEAD), _status("success")]
    assert _oracle(statuses=statuses)[0] == 0


def test_connector_review_does_not_satisfy_the_oracle_signal() -> None:
    status, message = _oracle(reviews=[_review()], reactions=[_reaction()])
    assert status == 1
    assert "waiting for the oracle's review" in message


@pytest.mark.parametrize(
    "review",
    [
        _oracle_review(commit_id=OLDER),
        _oracle_review(state="PENDING"),
        _oracle_review(state="DISMISSED"),
        _oracle_review(login="benchbox-oracle", user_type="User"),
        _oracle_review(user_type=None),
    ],
    ids=["older-commit", "pending", "dismissed", "user-account", "no-type"],
)
def test_oracle_review_must_be_the_apps_and_on_the_head(review: dict[str, Any]) -> None:
    assert _oracle(reviews=[review])[0] == 1


def test_oracle_review_and_status_before_a_retarget_wait() -> None:
    assert _oracle(reviews=[_oracle_review(submitted_at=BEFORE_HEAD)], base_date=HEAD_DATE)[0] == 1
    assert _oracle(statuses=[_status(created_at=BEFORE_HEAD)], base_date=HEAD_DATE)[0] == 1


def test_open_oracle_threads_block_the_oracle_signal_only() -> None:
    reviews = [_review(), _oracle_review()]
    threads = [{"resolved": False, "author": "benchbox-oracle", "author_type": "Bot"}]
    status, message = _oracle(reviews=reviews, threads=threads)
    assert status == 1
    assert "1 unresolved oracle review thread(s)" in message
    assert _decide(reviews=reviews, threads=threads)[0] == 0
    others = [
        _thread(False),
        {"resolved": True, "author": "benchbox-oracle", "author_type": "Bot"},
        {"resolved": False, "author": "benchbox-oracle", "author_type": "User"},
    ]
    assert _oracle(reviews=reviews, threads=others)[0] == 0


def _standin_comment() -> dict[str, Any]:
    return {
        "login": "joeharris76",
        "user_type": "User",
        "body": f"Stand-in oracle review: APPROVE {HEAD}",
        "created_at": AFTER_HEAD,
        "updated_at": AFTER_HEAD,
    }


def test_standin_attestation_overrides_a_failing_oracle_verdict_but_not_open_threads() -> None:
    assert _oracle(comments=[_standin_comment()], statuses=[_status("failure")])[0] == 0
    assert _oracle(reviews=[], comments=[_standin_comment()], statuses=[])[0] == 0
    threads = [{"resolved": False, "author": "benchbox-oracle", "author_type": "Bot"}]
    assert _oracle(comments=[_standin_comment()], threads=threads)[0] == 1


def test_force_push_back_to_an_attested_head_keeps_the_attestation() -> None:
    comment = {**_standin_comment(), "created_at": BEFORE_HEAD, "updated_at": BEFORE_HEAD}
    assert _decide(comments=[comment])[0] == 0


def _stub_main(monkeypatch: pytest.MonkeyPatch, statuses: Any) -> None:
    check = oracle_review_check
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(check, "fetch_pull", lambda token, repo, pr: {"head": {"sha": HEAD}, "changed_files": 1})
    monkeypatch.setattr(check, "fetch_files", lambda token, repo, pr: [{"filename": SOUNDNESS_FILES[0]}])
    monkeypatch.setattr(check, "fetch_head_date", lambda token, repo, sha: HEAD_DATE)
    monkeypatch.setattr(check, "fetch_reviews", lambda token, repo, pr: [_review(), _oracle_review()])
    monkeypatch.setattr(check, "fetch_reactions", lambda token, repo, pr: [])
    monkeypatch.setattr(check, "fetch_threads", lambda token, repo, pr: [])
    monkeypatch.setattr(check, "fetch_base_change_date", lambda token, repo, pr: None)
    monkeypatch.setattr(check, "fetch_comments", lambda token, repo, pr: [])
    monkeypatch.setattr(check, "fetch_statuses", statuses)


def test_main_reports_the_other_signal_for_parity(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    _stub_main(monkeypatch, lambda token, repo, sha: [_status("failure")])
    assert oracle_review_check.main(["--repo", "o/r", "--pr", "7"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"oracle-review: pass (Codex connector review of {HEAD})"
    assert out[1] == "parity: required=connector pass; oracle waiting"
    assert out[2].startswith("parity: oracle: oracle-review: the oracle's oracle-review-shadow status")
    assert oracle_review_check.main(["--repo", "o/r", "--pr", "7", "--signal", "oracle"]) == 1
    assert capsys.readouterr().out.splitlines()[1] == "parity: required=oracle waiting; connector pass"


def test_a_parity_failure_never_changes_the_required_result(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    def broken(token: str, repo: str, sha: str) -> list[dict[str, Any]]:
        raise oracle_review_check.CheckError("GitHub returned HTTP 403")

    _stub_main(monkeypatch, broken)
    assert oracle_review_check.main(["--repo", "o/r", "--pr", "7"]) == 0
    assert capsys.readouterr().out.splitlines()[1] == "parity: oracle: not evaluated: GitHub returned HTTP 403"
    assert oracle_review_check.main(["--repo", "o/r", "--pr", "7", "--signal", "oracle"]) == 2


def test_fetch_threads_and_reviews_keep_the_author_type(monkeypatch: pytest.MonkeyPatch) -> None:
    node = {"isResolved": False, "comments": {"nodes": [{"author": {"__typename": "Bot", "login": "benchbox-oracle"}}]}}
    page = {
        "data": {
            "repository": {"pullRequest": {"reviewThreads": {"pageInfo": {"hasNextPage": False}, "nodes": [node]}}}
        }
    }
    monkeypatch.setattr(oracle_review_check, "_request", lambda token, url, body=None: page)
    assert oracle_review_check.fetch_threads("t", "o/r", 7) == [
        {"resolved": False, "author": "benchbox-oracle", "author_type": "Bot"}
    ]
    review = {
        "user": {"login": ORACLE, "type": "Bot"},
        "commit_id": HEAD,
        "state": "COMMENTED",
        "submitted_at": AFTER_HEAD,
    }
    monkeypatch.setattr(oracle_review_check, "_paginate", lambda token, path: [review])
    assert oracle_review_check.fetch_reviews("t", "o/r", 7)[0]["user_type"] == "Bot"
