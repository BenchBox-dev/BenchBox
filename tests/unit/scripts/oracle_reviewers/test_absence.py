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


META_KEY = "mta" + "Q7x9Lk2Pz8Rw4Tn6Yb1Vc3Hd5Jf0Gs7Ma2Ne"
OPENAI_KEY = "sk-" + "proj-" + "Zx8Cv7Bn6Mq5Wr4Ty3Ui2Op1As0Df9Gh8"
CLAUDE_OAUTH = "sk-ant-" + "oat01-" + "Kj7Hg6Fd5Sa4Lp3Oi2Uy1Tr0Ew9Qz8Xc7Vb6"


@pytest.mark.parametrize(
    "secret",
    [META_KEY, OPENAI_KEY, CLAUDE_OAUTH, f"META_API_KEY={META_KEY}", f"OPENAI_API_KEY: {OPENAI_KEY}"],
)
def test_excerpt_redacts_credentials(secret: str) -> None:
    text = absence.excerpt("", f"error: request with {secret} was rejected\n")
    assert "Q7x9Lk2Pz8" not in text
    assert "Zx8Cv7Bn6" not in text
    assert "Kj7Hg6Fd5" not in text
    assert "[redacted]" in text


def test_excerpt_redacts_the_exact_credential_values() -> None:
    short_but_secret = "abc12345xyz"
    text = absence.excerpt("", f"bad key {short_but_secret}", [short_but_secret])
    assert short_but_secret not in text


def test_excerpt_is_one_capped_line() -> None:
    stderr = "first line with detail\n" + "x " * 1000 + "\n\n"
    text = absence.excerpt("raw review output", stderr)
    assert "first line" not in text
    assert len(text) <= absence.EXCERPT_LIMIT
    assert absence.excerpt("only stdout line\n", "") == "only stdout line"
    assert absence.excerpt("", "") == ""
