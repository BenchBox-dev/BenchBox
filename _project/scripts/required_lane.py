#!/usr/bin/env python3
"""Shared required-lane classifier for develop PR observers.

Both ``green_unmerged_sweep.py`` and ``soundness_drain_report.py`` classify
the same lane — every required status context in the ``develop-squash-only``
ruleset (``docs/operations/repo-admin-settings.md``, live id ``15611785``).
This module is the single source of truth for that set and its predicates so
the two observers cannot drift.

Prior art: ``auto_merge_soundness_paths.py`` already provides a precedent for
``sys.path.insert(SCRIPT_DIR)`` + ``from <helper> import …`` consumption.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

# Develop ruleset `develop-squash-only` required status contexts.
# Pin must match docs/operations/repo-admin-settings.md and the live
# ruleset (id 15611785). Partial membership is incomplete green.
REQUIRED_CHECK_NAMES: tuple[str, ...] = (
    "ci-required-result",
    "Results Explorer browser gate",
)


def _parse_iso(value: str) -> dt.datetime:
    # GitHub timestamps are RFC3339 with a trailing "Z". Fractions and offsets
    # are accepted via the replace so fractional seconds compare correctly.
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _started_at_key(run: dict[str, Any]) -> dt.datetime | None:
    raw = run.get("started_at")
    if not raw:
        return None
    try:
        return _parse_iso(str(raw))
    except (ValueError, TypeError):
        return None


def latest_check_run(check_runs: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Return the latest check run for *name*, if present.

    A re-run can leave multiple same-named runs on one SHA; pick the most
    recently started so a stale conclusion never wins. Comparison is by
    parsed datetime so fractional seconds and offset forms are ordered
    correctly; unparsable or missing stamps sort as oldest.
    """
    matches = [run for run in check_runs if run.get("name") == name]
    if not matches:
        return None

    def _key(run: dict[str, Any]) -> tuple[int, dt.datetime]:
        parsed = _started_at_key(run)
        if parsed is None:
            # Missing/unparsable stamp is oldest. Use min datetime.
            return (0, dt.datetime.min.replace(tzinfo=dt.timezone.utc))
        return (1, parsed)

    return max(matches, key=_key)


def is_check_run_success(run: dict[str, Any] | None) -> bool:
    """True when *run* completed with conclusion ``success`` (not skipped/neutral)."""
    if run is None:
        return False
    return run.get("status") == "completed" and run.get("conclusion") == "success"


def is_required_lane_green(check_runs: list[dict[str, Any]]) -> bool:
    """True when every develop-ruleset required context is latest-success.

    Partial green (e.g. ``ci-required-result`` success but browser gate
    missing or red) returns False. Missing runs are fail-closed not-green;
    the browser gate always reports on develop PRs (success when the explorer
    suite is not needed).
    """
    if not REQUIRED_CHECK_NAMES:
        return False
    for name in REQUIRED_CHECK_NAMES:
        if not is_check_run_success(latest_check_run(check_runs, name)):
            return False
    return True
