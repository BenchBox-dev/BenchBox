"""Tests for release canary freshness gating."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scripts.release_readiness_check import _override_active, evaluate_canary_runs

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
