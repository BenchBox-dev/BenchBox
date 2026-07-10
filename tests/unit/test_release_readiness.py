"""Tests for release canary freshness gating."""

from __future__ import annotations

import io
import json
import urllib.error
import zipfile
from datetime import UTC, datetime, timedelta

import pytest

from scripts import release_readiness_check
from scripts.release_readiness_check import BOOTSTRAP_REQUIRED_EXIT_CODE, _override_active, evaluate_canary_runs

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _run(*, conclusion: str, updated_at: datetime, sha: str = "abc123") -> dict[str, str]:
    return {
        "status": "completed",
        "conclusion": conclusion,
        "updated_at": updated_at.isoformat().replace("+00:00", "Z"),
        "head_sha": sha,
        "html_url": f"https://example.test/{sha}",
        "display_title": "Release Canary",
    }


def test_latest_red_canary_blocks_even_with_older_success() -> None:
    now = datetime(2026, 5, 25, 12, tzinfo=UTC)
    result = evaluate_canary_runs(
        [
            _run(conclusion="success", updated_at=now - timedelta(hours=2), sha="oldgreen"),
            _run(conclusion="failure", updated_at=now - timedelta(minutes=30), sha="latestred"),
        ],
        now=now,
        max_age_hours=48,
        head_sha="release-head",
        is_ancestor=lambda _ancestor, _head: True,
    )

    assert not result.ok
    assert "Latest release canary is failure" in result.message
    assert any("latestred" in line for line in result.summary)


def test_stale_canary_blocks_release_readiness() -> None:
    now = datetime(2026, 5, 25, 12, tzinfo=UTC)
    result = evaluate_canary_runs(
        [_run(conclusion="success", updated_at=now - timedelta(hours=49), sha="stalesha")],
        now=now,
        max_age_hours=48,
        head_sha="release-head",
        is_ancestor=lambda _ancestor, _head: True,
    )

    assert not result.ok
    assert "stale" in result.message


def test_non_ancestor_canary_blocks_release_readiness() -> None:
    now = datetime(2026, 5, 25, 12, tzinfo=UTC)
    result = evaluate_canary_runs(
        [_run(conclusion="success", updated_at=now - timedelta(hours=1), sha="not-ancestor")],
        now=now,
        max_age_hours=48,
        head_sha="release-head",
        is_ancestor=lambda _ancestor, _head: False,
    )

    assert not result.ok
    assert "not an ancestor" in result.message


def test_green_fresh_ancestor_canary_passes() -> None:
    now = datetime(2026, 5, 25, 12, tzinfo=UTC)
    result = evaluate_canary_runs(
        [_run(conclusion="success", updated_at=now - timedelta(hours=1), sha="goodsha")],
        now=now,
        max_age_hours=48,
        head_sha="release-head",
        is_ancestor=lambda ancestor, head: ancestor == "goodsha" and head == "release-head",
    )

    assert result.ok
    assert "green, fresh, and applicable" in result.message


def test_canary_artifact_sha_is_used_for_ancestor_check() -> None:
    now = datetime(2026, 5, 25, 12, tzinfo=UTC)
    checked: list[tuple[str, str]] = []

    def _is_ancestor(ancestor: str, head: str) -> bool:
        checked.append((ancestor, head))
        return ancestor == "develop-tested-sha" and head == "release-head"

    result = evaluate_canary_runs(
        [_run(conclusion="success", updated_at=now - timedelta(hours=1), sha="default-branch-sha")],
        now=now,
        max_age_hours=48,
        head_sha="release-head",
        canary_commit_sha=lambda _run: "develop-tested-sha",
        is_ancestor=_is_ancestor,
    )

    assert result.ok
    assert checked == [("develop-tested-sha", "release-head")]
    assert any("checked_sha: develop-tested-sha" in line for line in result.summary)


def test_release_canary_commit_sha_reads_summary_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_api_json(url: str, _token: str) -> dict:
        assert url == "https://api.github.test/artifacts"
        return {
            "artifacts": [
                {
                    "name": "release-canary-summary",
                    "expired": False,
                    "created_at": "2026-05-25T12:00:00Z",
                    "archive_download_url": "https://api.github.test/artifact.zip",
                }
            ]
        }

    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr(
            "release-canary-summary.json",
            json.dumps({"checked_ref": "develop", "commit_sha": "develop-tested-sha"}),
        )

    monkeypatch.setattr(release_readiness_check, "_api_json", _fake_api_json)
    monkeypatch.setattr(release_readiness_check, "_api_bytes", lambda _url, _token: archive_buffer.getvalue())

    assert (
        release_readiness_check._release_canary_commit_sha(
            {"id": 123, "artifacts_url": "https://api.github.test/artifacts", "head_sha": "default-branch-sha"},
            "token",
        )
        == "develop-tested-sha"
    )


def test_release_canary_commit_sha_requires_expected_checked_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr(
            "release-canary-summary.json",
            json.dumps({"checked_ref": "feature/demo", "commit_sha": "feature-sha"}),
        )

    monkeypatch.setattr(
        release_readiness_check,
        "_api_json",
        lambda _url, _token: {
            "artifacts": [
                {
                    "name": "release-canary-summary",
                    "expired": False,
                    "created_at": "2026-05-25T12:00:00Z",
                    "archive_download_url": "https://api.github.test/artifact.zip",
                }
            ]
        },
    )
    monkeypatch.setattr(release_readiness_check, "_api_bytes", lambda _url, _token: archive_buffer.getvalue())

    with pytest.raises(RuntimeError, match="expected 'develop'"):
        release_readiness_check._release_canary_commit_sha(
            {"id": 123, "artifacts_url": "https://api.github.test/artifacts"},
            "token",
        )


def test_workflow_runs_url_requires_trusted_branch_filter() -> None:
    with pytest.raises(ValueError, match="trusted branch"):
        release_readiness_check._workflow_runs_url("owner/repo", "release-canary.yml", "")


def test_workflow_runs_url_filters_to_trusted_branch() -> None:
    url = release_readiness_check._workflow_runs_url("owner/repo", "release-canary.yml", "main")

    assert "branch=main" in url
    assert "status=completed" in url


def test_main_queries_trusted_default_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_urls: list[str] = []

    def _fake_api_json(url: str, _token: str) -> dict:
        captured_urls.append(url)
        return {"workflow_runs": []}

    monkeypatch.setattr(release_readiness_check, "_api_json", _fake_api_json)
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("RELEASE_CANARY_BRANCH", raising=False)
    monkeypatch.delenv("RELEASE_READINESS_OVERRIDE_SHA", raising=False)
    monkeypatch.delenv("RELEASE_READINESS_OVERRIDE_REASON", raising=False)

    rc = release_readiness_check.main(["--head-sha", "release-head"])

    assert rc == 1
    assert captured_urls == [
        "https://api.github.com/repos/joeharris76/BenchBox/actions/workflows/release-canary.yml/runs?"
        "branch=develop&status=completed&per_page=20"
    ]


def test_override_requires_exact_head_sha_and_reason() -> None:
    assert _override_active(
        {
            "RELEASE_READINESS_OVERRIDE_SHA": "head",
            "RELEASE_READINESS_OVERRIDE_REASON": "INC-123 approved by admin",
        },
        "head",
    ) == (True, "INC-123 approved by admin")
    assert _override_active(
        {
            "RELEASE_READINESS_OVERRIDE_SHA": "old-head",
            "RELEASE_READINESS_OVERRIDE_REASON": "INC-123 approved by admin",
        },
        "head",
    ) == (False, "")
    assert _override_active({"RELEASE_READINESS_OVERRIDE_SHA": "head"}, "head") == (False, "")


def test_missing_workflow_can_request_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_404(_url: str, _token: str) -> dict:
        raise urllib.error.HTTPError(
            url="https://api.github.test/workflows/release-canary.yml/runs",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(release_readiness_check, "_api_json", _raise_404)
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("RELEASE_READINESS_OVERRIDE_SHA", raising=False)
    monkeypatch.delenv("RELEASE_READINESS_OVERRIDE_REASON", raising=False)

    rc = release_readiness_check.main(["--head-sha", "release-head", "--bootstrap-on-missing-workflow"])

    assert rc == BOOTSTRAP_REQUIRED_EXIT_CODE


def test_artifact_lookup_404_does_not_request_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 5, 25, 12, tzinfo=UTC)

    def _fake_api_json(url: str, _token: str) -> dict:
        if url.startswith("https://api.github.com/repos/"):
            return {
                "workflow_runs": [
                    _run(conclusion="success", updated_at=now, sha="default-branch-sha")
                    | {"artifacts_url": "https://api.github.test/artifacts"}
                ]
            }
        raise urllib.error.HTTPError(
            url=url,
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(release_readiness_check, "_api_json", _fake_api_json)
    monkeypatch.setattr(release_readiness_check, "_is_ancestor_with_git", lambda _ancestor, _head: True)
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("RELEASE_READINESS_OVERRIDE_SHA", raising=False)
    monkeypatch.delenv("RELEASE_READINESS_OVERRIDE_REASON", raising=False)

    rc = release_readiness_check.main(["--head-sha", "release-head", "--bootstrap-on-missing-workflow"])

    assert rc == 1
