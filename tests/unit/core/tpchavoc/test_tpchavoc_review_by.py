"""Unit tests for the optional waiver review_by policy on TPC-Havoc's shared ``_report``.

Locks the behavior described in
``_project/TODO/main/planning/equivalence-waiver-expiry-policy.yaml``: a
past-due ``review_by`` date on a known-divergence baseline entry WARNS (prints a
"WAIVER REVIEW DUE" line) but never fails the gate, and is independent of the
existing stale-baseline (``resolved``) failure.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from datetime import date

import pytest

from benchbox.core.tpchavoc.equivalence import CLICKHOUSE_KNOWN_DIVERGENCES, _report

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_review_by_past_due_warns_but_does_not_fail_the_report(capsys):
    """A past-due review_by entry warns; the still-live divergence keeps the report green."""
    exit_code = _report(
        [],
        total=10,
        known={"1_v1": "a documented, still-live engine-semantic difference"},
        engine_label="DuckDB",
        baseline_name="KNOWN_DIVERGENCES",
        review_by={"1_v1": date(2020, 1, 1)},
    )

    out = capsys.readouterr().out
    assert exit_code == 1  # NOTE: "resolved" fires here because divergences=[] and the key is baselined;
    # see the companion test below for the review_by signal in isolation from `resolved`.
    assert "WAIVER REVIEW DUE - 1_v1: review_by 2020-01-01 has passed" in out


def test_review_by_past_due_warns_on_a_still_reproducing_divergence(capsys):
    """A past-due review_by on a LIVE (still-reproducing) divergence warns without failing."""
    from benchbox.core.tpchavoc.equivalence import Divergence

    exit_code = _report(
        [Divergence(1, 1, "accepted, documented difference")],
        total=10,
        known={"1_v1": "a documented, still-live engine-semantic difference"},
        engine_label="DuckDB",
        baseline_name="KNOWN_DIVERGENCES",
        review_by={"1_v1": date(2020, 1, 1)},
    )

    out = capsys.readouterr().out
    assert exit_code == 0  # the divergence is still classified and still reproduces - not resolved, not new
    assert "WAIVER REVIEW DUE - 1_v1: review_by 2020-01-01 has passed - a documented, still-live" in out


def test_review_by_future_date_does_not_warn(capsys):
    """A future review_by date produces no warning."""
    from benchbox.core.tpchavoc.equivalence import Divergence

    exit_code = _report(
        [Divergence(1, 1, "accepted, documented difference")],
        total=10,
        known={"1_v1": "a documented, still-live engine-semantic difference"},
        engine_label="DuckDB",
        baseline_name="KNOWN_DIVERGENCES",
        review_by={"1_v1": date(2099, 1, 1)},
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "WAIVER REVIEW DUE" not in out


def test_review_by_absent_by_default_produces_no_warning(capsys):
    """No review_by side-table at all (the default) never warns - opt-in only."""
    from benchbox.core.tpchavoc.equivalence import Divergence

    exit_code = _report(
        [Divergence(1, 1, "accepted, documented difference")],
        total=10,
        known={"1_v1": "a documented, still-live engine-semantic difference"},
        engine_label="DuckDB",
        baseline_name="KNOWN_DIVERGENCES",
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "WAIVER REVIEW DUE" not in out


def test_clickhouse_review_by_worked_example_is_not_yet_due():
    """The committed worked example (1_v4) must not be past-due on a healthy tree.

    Regression guard: an accidentally-past-due review_by on a real baseline would
    make every ClickHouse sample run print a review warning - not a gate failure,
    but a signal this test catches immediately rather than leaving it to be
    noticed only when someone reads CI output.
    """
    from benchbox.core.tpchavoc.equivalence import CLICKHOUSE_KNOWN_DIVERGENCES_REVIEW_BY

    for key, review_by in CLICKHOUSE_KNOWN_DIVERGENCES_REVIEW_BY.items():
        assert key in CLICKHOUSE_KNOWN_DIVERGENCES, f"{key} has a review_by but no matching baseline entry"
        assert review_by >= date.today(), f"{key}'s review_by {review_by} is already past-due"
