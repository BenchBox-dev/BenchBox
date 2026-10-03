from __future__ import annotations

import pytest

from scripts.site_deploy import candidate
from tests.unit.scripts.site_deploy.site_deploy_fakes import SHA_A, SHA_B, SHA_C, FakeGitHub

pytestmark = [pytest.mark.unit, pytest.mark.fast]


TRUNK_PATH = ".github/workflows/trunk.yml"


def _run(
    sha: str,
    conclusion: str = "success",
    event: str = "push",
    run_id: int = 1,
    branch: str = "develop",
    path: str = TRUNK_PATH,
) -> dict[str, object]:
    return {
        "id": run_id,
        "head_sha": sha,
        "head_branch": branch,
        "event": event,
        "conclusion": conclusion,
        "path": path,
        "created_at": f"2026-01-01T00:00:0{run_id}Z",
    }


def test_latest_release_tag_uses_semver_not_lexical_order() -> None:
    assert candidate.latest_release_tag(["v0.2.1", "v0.10.0", "v0.9.9", "v1.0.0-rc1", "nightly"]) == "v0.10.0"


def test_latest_release_tag_fails_closed_without_release_tags() -> None:
    with pytest.raises(candidate.CandidateError):
        candidate.latest_release_tag(["nightly", "v1"])


def test_newest_certified_sha_wins_and_uncertified_newer_sha_is_skipped() -> None:
    api = FakeGitHub(runs=[_run(SHA_B, run_id=7)])
    found = candidate.find_candidate(api.client(), [SHA_A, SHA_B, SHA_C], "v0.4.1")
    assert (found.trunk_sha, found.certifying_run_id, found.release_tag) == (SHA_B, 7, "v0.4.1")


@pytest.mark.parametrize(
    "run",
    [
        _run(SHA_A, conclusion="failure"),
        _run(SHA_A, conclusion="cancelled"),
        _run(SHA_A, event="merge_group"),
        _run(SHA_A, event="pull_request"),
        _run(SHA_A, branch="feature"),
        _run(SHA_A, path=".github/workflows/ci.yml"),
        _run(SHA_B),
    ],
)
def test_refuses_when_no_successful_trunk_push_run_matches_the_exact_sha(run: dict[str, object]) -> None:
    api = FakeGitHub(runs=[run])
    with pytest.raises(candidate.CandidateError, match="successful push run of trunk.yml"):
        candidate.find_candidate(api.client(), [SHA_A], "v0.4.1")


def test_run_conclusion_decides_even_if_the_server_filter_returns_a_failed_run() -> None:
    api = FakeGitHub(
        runs=[_run(SHA_A, conclusion="failure"), _run(SHA_A, conclusion="success", run_id=2)],
        ignore_status_filter=True,
    )
    assert candidate.find_candidate(api.client(), [SHA_A], "v0.4.1").certifying_run_id == 2


def test_lookup_requests_develop_push_runs_of_trunk_for_the_head_sha() -> None:
    api = FakeGitHub(runs=[_run(SHA_A)])
    candidate.find_candidate(api.client(), [SHA_A], "v0.4.1")
    method, path = api.requests[0]
    assert method == "GET"
    assert "/actions/workflows/trunk.yml/runs" in path
    assert "event=push" in path
    assert "branch=develop" in path
    assert f"head_sha={SHA_A}" in path
    assert "status=success" in path


def test_pagination_overflow_fails_closed() -> None:
    api = FakeGitHub(runs=[_run(SHA_A, run_id=1) for _ in range(1100)])
    with pytest.raises(candidate.CandidateError, match="lookup failed"):
        candidate.find_candidate(api.client(), [SHA_A], "v0.4.1")


def test_a_later_page_is_followed() -> None:
    noise = [_run(SHA_A, conclusion="failure", run_id=1) for _ in range(100)]
    api = FakeGitHub(runs=noise + [_run(SHA_A, run_id=2)], ignore_status_filter=True)
    assert candidate.find_candidate(api.client(), [SHA_A], "v0.4.1").certifying_run_id == 2


def test_api_failure_fails_closed() -> None:
    api = FakeGitHub(fail=True)
    with pytest.raises(candidate.CandidateError, match="lookup failed"):
        candidate.find_candidate(api.client(), [SHA_A], "v0.4.1")


def test_rejects_abbreviated_shas_and_empty_walks() -> None:
    api = FakeGitHub()
    with pytest.raises(candidate.CandidateError):
        candidate.find_candidate(api.client(), ["abc123"], "v0.4.1")
    with pytest.raises(candidate.CandidateError):
        candidate.find_candidate(api.client(), [], "v0.4.1")
