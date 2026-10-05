from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from _project.scripts.oracle_reviewers import absence
from _project.scripts.oracle_reviewers.absence import classify, parse_reset

pytestmark = [pytest.mark.unit, pytest.mark.fast]

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _classify(harness: str, exit_code: int | None, stdout: str = "", stderr: str = "", timed_out: bool = False):
    return classify(harness, exit_code, stdout, stderr, timed_out=timed_out, now=NOW)


def test_agy_resource_exhausted_is_quota_with_a_reset_time() -> None:
    stderr = "Error: RESOURCE_EXHAUSTED (code 429): quota exceeded. Resets in 4h12m30s."
    result = _classify("agy", 1, stderr=stderr)
    assert result.kind == absence.QUOTA
    assert result.reset_at == NOW + timedelta(hours=4, minutes=12, seconds=30)


def test_agy_quota_without_a_reset_time_has_none() -> None:
    result = _classify("agy", 1, stderr="RESOURCE_EXHAUSTED (code 429)")
    assert result.kind == absence.QUOTA
    assert result.reset_at is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Resets in 45m", timedelta(minutes=45)),
        ("resets in 1d 2h", timedelta(days=1, hours=2)),
        ("Resets in 3h 5m 10s", timedelta(hours=3, minutes=5, seconds=10)),
    ],
)
def test_reset_durations(text: str, expected: timedelta) -> None:
    assert parse_reset(text, NOW) == NOW + expected


def test_no_reset_phrase_means_no_reset() -> None:
    assert parse_reset("try again later", NOW) is None


def test_agy_auto_denied_headless_run_is_empty() -> None:
    message = "No output produced: tool use was auto-denied in --print mode"
    assert _classify("agy", 0, stdout="", stderr=message).kind == absence.EMPTY


def test_exit_zero_without_output_is_empty_for_every_harness() -> None:
    for harness in ("agy", "claude", "codex", "muse"):
        result = _classify(harness, 0, stdout="  \n")
        assert result.kind == absence.EMPTY
        assert result.absent


def test_timeout_wins() -> None:
    assert _classify("claude", None, timed_out=True).kind == absence.TIMEOUT


def test_uncalibrated_quota_messages_are_errors_never_passes() -> None:
    for harness in ("claude", "codex", "muse"):
        result = _classify(
            harness, 1, stderr="429 Too Many Requests: usage limit reached, RESOURCE_EXHAUSTED (code 429)"
        )
        assert result.kind == absence.ERROR
        assert result.absent


def test_unstartable_reviewer_is_an_error() -> None:
    assert _classify("codex", None).kind == absence.ERROR


def test_output_with_exit_zero_is_ok() -> None:
    result = _classify("codex", 0, stdout='{"summary": "", "findings": []}')
    assert result.kind == absence.OK
    assert not result.absent


def test_calibration_tables_cover_every_harness() -> None:
    for table in (
        absence.CALIBRATED_QUOTA_PATTERNS,
        absence.CALIBRATED_AUTH_PATTERNS,
        absence.CALIBRATED_EMPTY_PATTERNS,
    ):
        assert set(table) == {"agy", "claude", "codex", "muse"}
    assert not any(absence.CALIBRATED_QUOTA_PATTERNS[name] for name in ("claude", "codex", "muse"))
