from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

OK = "ok"
QUOTA = "quota"
AUTH = "auth"
TIMEOUT = "timeout"
INVALID = "invalid"
EMPTY = "empty"
ERROR = "error"
KINDS = (OK, QUOTA, AUTH, TIMEOUT, INVALID, EMPTY, ERROR)

CALIBRATED_QUOTA_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "agy": (re.compile(r"RESOURCE_EXHAUSTED \(code 429\)"),),
    "claude": (),
    "codex": (),
    "muse": (),
}
CALIBRATED_AUTH_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "agy": (),
    "claude": (),
    "codex": (),
    "muse": (),
}
CALIBRATED_EMPTY_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "agy": (re.compile(r"no output (?:was )?produced.*auto-denied", re.IGNORECASE | re.DOTALL),),
    "claude": (),
    "codex": (),
    "muse": (),
}

_RESET = re.compile(r"Resets in\s+(?P<duration>(?:\d+\s*[dhms]\s*)+)", re.IGNORECASE)
_DURATION_PART = re.compile(r"(\d+)\s*([dhms])", re.IGNORECASE)
_UNITS = {"d": "days", "h": "hours", "m": "minutes", "s": "seconds"}


@dataclass(frozen=True)
class Absence:
    kind: str
    detail: str = ""
    reset_at: datetime | None = None

    @property
    def absent(self) -> bool:
        return self.kind != OK


def parse_reset(text: str, now: datetime) -> datetime | None:
    match = _RESET.search(text)
    if match is None:
        return None
    delta = timedelta()
    for amount, unit in _DURATION_PART.findall(match.group("duration")):
        delta += timedelta(**{_UNITS[unit.lower()]: int(amount)})
    return now + delta if delta else None


def _first(patterns: tuple[re.Pattern[str], ...], text: str) -> re.Match[str] | None:
    return next((match for pattern in patterns if (match := pattern.search(text)) is not None), None)


def classify(
    harness: str,
    exit_code: int | None,
    stdout: str,
    stderr: str,
    *,
    timed_out: bool,
    now: datetime,
) -> Absence:
    combined = f"{stdout}\n{stderr}"
    if timed_out:
        return Absence(TIMEOUT, "the reviewer did not finish within its timeout")
    if _first(CALIBRATED_EMPTY_PATTERNS.get(harness, ()), combined) is not None:
        return Absence(EMPTY, "the reviewer produced no output because tool use was denied")
    quota = _first(CALIBRATED_QUOTA_PATTERNS.get(harness, ()), combined)
    if quota is not None:
        return Absence(QUOTA, quota.group(0), parse_reset(combined, now))
    auth = _first(CALIBRATED_AUTH_PATTERNS.get(harness, ()), combined)
    if auth is not None:
        return Absence(AUTH, auth.group(0))
    if exit_code is None:
        return Absence(ERROR, "the reviewer could not be started")
    if exit_code != 0:
        return Absence(ERROR, f"exit code {exit_code}")
    if not stdout.strip():
        return Absence(EMPTY, "exit code 0 with no output")
    return Absence(OK)
