"""Candidate identity: only trunk commits with a green merge-queue ci.yml run are eligible."""

from __future__ import annotations

import pytest

from scripts.site_deploy import candidate as c
from tests.unit.scripts.site_deploy.helpers import sha

pytestmark = [pytest.mark.unit, pytest.mark.fast]

NEWEST, MIDDLE, OLDEST = sha("3"), sha("2"), sha("1")
HISTORY = [NEWEST, MIDDLE, OLDEST]  # newest first


def run(head_sha: str, *, conclusion: str | None = "success", status: str = "completed", **overrides) -> dict:
    data = {
        "id": int(head_sha[0]) * 100,
        "head_sha": head_sha,
        "head_branch": f"gh-readonly-queue/develop/pr-1-{head_sha}",
        "event": "merge_group",
        "path": ".github/workflows/ci.yml",
        "status": status,
        "conclusion": conclusion,
        "created_at": "2026-09-29T10:00:00Z",
        "html_url": f"https://example.invalid/runs/{head_sha[0]}",
    }
    data.update(overrides)
    return data


def test_green_merge_group_run_on_trunk_is_eligible() -> None:
    verdict = c.check_candidate(NEWEST, [run(NEWEST)], HISTORY)
    assert verdict.eligible and verdict.run_id == 300


def test_commit_without_a_merge_group_run_is_not_eligible() -> None:
    verdict = c.check_candidate(NEWEST, [run(OLDEST)], HISTORY)
    assert not verdict.eligible
    assert "no ci.yml merge_group run" in verdict.reasons[0]


def test_commit_off_trunk_is_not_eligible_even_with_a_green_run() -> None:
    stranger = sha("9")
    verdict = c.check_candidate(stranger, [run(stranger)], HISTORY)
    assert not verdict.eligible
    assert "first-parent history" in verdict.reasons[0]


@pytest.mark.parametrize(
    "overrides",
    [
        {"conclusion": "failure"},
        {"conclusion": "cancelled"},
        {"conclusion": None, "status": "in_progress"},
        {"conclusion": "skipped"},
    ],
)
def test_run_that_did_not_succeed_is_not_eligible(overrides: dict) -> None:
    assert not c.check_candidate(NEWEST, [run(NEWEST, **overrides)], HISTORY).eligible


@pytest.mark.parametrize(
    "overrides",
    [
        {"event": "pull_request"},
        {"event": "push"},
        {"path": ".github/workflows/docs.yml"},
        {"head_branch": "feature/x"},
        {"head_branch": "gh-readonly-queue/release/pr-1-abc"},
    ],
)
def test_runs_of_other_events_workflows_or_branches_do_not_count(overrides: dict) -> None:
    assert not c.check_candidate(NEWEST, [run(NEWEST, **overrides)], HISTORY).eligible


def test_workflow_path_with_a_ref_suffix_is_recognized() -> None:
    runs = [run(NEWEST, path=".github/workflows/ci.yml@refs/heads/gh-readonly-queue/develop/pr-1-x")]
    assert c.check_candidate(NEWEST, runs, HISTORY).eligible


def test_newest_run_decides_when_a_commit_was_rerun() -> None:
    green_then_red = [
        run(NEWEST, id=1, created_at="2026-09-29T10:00:00Z"),
        run(NEWEST, id=2, created_at="2026-09-29T11:00:00Z", conclusion="failure"),
    ]
    assert not c.check_candidate(NEWEST, green_then_red, HISTORY).eligible
    red_then_green = [
        run(NEWEST, id=1, created_at="2026-09-29T10:00:00Z", conclusion="failure"),
        run(NEWEST, id=2, created_at="2026-09-29T11:00:00Z"),
    ]
    assert c.check_candidate(NEWEST, red_then_green, HISTORY).eligible


def test_latest_eligible_skips_newer_commits_without_a_green_run() -> None:
    runs = [run(NEWEST, conclusion="failure"), run(MIDDLE)]
    chosen = c.select_latest_eligible(runs, HISTORY)
    assert chosen is not None and chosen.sha == MIDDLE


def test_latest_eligible_is_none_when_nothing_qualifies() -> None:
    assert c.select_latest_eligible([], HISTORY) is None


def test_fetch_merge_group_runs_pages_until_a_short_page() -> None:
    calls: list[str] = []

    def api(path: str):
        calls.append(path)
        page = int(path.rsplit("page=", 1)[1])
        size = 100 if page == 1 else 3
        return {"workflow_runs": [run(NEWEST)] * size}

    runs = c.fetch_merge_group_runs("o/r", api)
    assert len(runs) == 103
    assert len(calls) == 2
    assert "workflows/ci.yml/runs?event=merge_group" in calls[0]


def test_fetch_runs_for_sha_filters_by_head_sha() -> None:
    seen: list[str] = []

    def api(path: str):
        seen.append(path)
        return {"workflow_runs": [run(NEWEST)]}

    assert c.fetch_runs_for_sha("o/r", NEWEST, api)[0]["head_sha"] == NEWEST
    assert f"head_sha={NEWEST}" in seen[0]
