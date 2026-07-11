"""Tests for PlatformAdapterCursor row extraction.

#1100 review (Codex, landed after merge): ``_extract_rows()`` fabricated an
all-``None`` placeholder list from ``rows_returned`` even when the platform
result also carried a real sampled ``first_row``, silently discarding that
value. This is the root cause of the ``develop`` CI failure in
``tests/integration/test_throughput_session_isolation.py::
TestSharedCursorCapabilityIsDuckDBDefault::
test_streams_share_one_connection_no_new_connections_opened``
(``assert [(None,)] == [(7,)]``), which the auto-revert bot twice
misattributed to unrelated PRs (#1112 blamed #1100 itself; #1115 blamed the
next unrelated merge, #1113) because the real cursor is populated with
exactly this ``rows_returned``+``first_row`` shape.

``placeholder-rows-fetch-safety`` (builds on #1117): adds ``has_real_rows``
and a one-time-per-cursor ``logger.warning`` when fetchall()/fetchone()/
``.rows`` actually materializes a list containing fabricated ``(None,)``
placeholders, so a future incident like the one above is loud instead of
silent. ``row_count()``/``count_query_rows()`` and bare ``has_real_rows``
access must stay silent and never trigger the warning.
"""

from __future__ import annotations

import logging

import pytest

from benchbox.platforms.base.connection_wrappers import PlatformAdapterCursor, count_query_rows

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

_LOGGER_NAME = "benchbox.platforms.base.connection_wrappers"


def test_preserves_first_row_when_padding_from_rows_returned():
    cursor = PlatformAdapterCursor({"rows_returned": 1, "first_row": (7,)})
    assert cursor.fetchall() == [(7,)]
    assert cursor.fetchone() == (7,)


def test_pads_remaining_cardinality_with_none_after_first_row():
    cursor = PlatformAdapterCursor({"rows_returned": 3, "first_row": (7,)})
    assert cursor.fetchall() == [(7,), (None,), (None,)]


def test_falls_back_to_none_placeholders_without_first_row():
    cursor = PlatformAdapterCursor({"rows_returned": 2})
    assert cursor.fetchall() == [(None,), (None,)]


def test_rows_returned_zero_is_empty_regardless_of_first_row():
    # A stale/mismatched first_row alongside rows_returned=0 must not
    # fabricate a phantom row.
    cursor = PlatformAdapterCursor({"rows_returned": 0, "first_row": (7,)})
    assert cursor.fetchall() == []
    assert cursor.fetchone() is None


def test_explicit_rows_list_takes_priority_over_first_row():
    cursor = PlatformAdapterCursor({"rows": [(1,), (2,)], "rows_returned": 1, "first_row": (99,)})
    assert cursor.fetchall() == [(1,), (2,)]


def test_first_row_alone_without_rows_returned():
    cursor = PlatformAdapterCursor({"first_row": (7,)})
    assert cursor.fetchall() == [(7,)]


# --- has_real_rows / one-time placeholder-materialization warning matrix ---


def test_placeholder_only_fetch_warns_once_and_has_real_rows_is_false(caplog):
    cursor = PlatformAdapterCursor({"query_id": "q_placeholder", "rows_returned": 2})
    assert cursor.has_real_rows is False

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        assert cursor.fetchall() == [(None,), (None,)]
        # A second materializing access must not log a second warning.
        assert cursor.fetchall() == [(None,), (None,)]
        assert cursor.rows == [(None,), (None,)]

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "q_placeholder" in message
    assert "rows_returned_only" in message


def test_explicit_rows_fetch_never_warns_and_has_real_rows_is_true(caplog):
    cursor = PlatformAdapterCursor({"query_id": "q_explicit", "rows": [(1,), (2,)]})
    assert cursor.has_real_rows is True

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        assert cursor.fetchall() == [(1,), (2,)]
        assert cursor.fetchone() == (1,)
        assert cursor.rows == [(1,), (2,)]

    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


def test_count_only_paths_never_warn_even_with_placeholder_cardinality(caplog):
    # row_count()/count_query_rows() read platform_result directly and must
    # never materialize the placeholder list or log the warning, even though
    # this same platform_result would warn if fetched via fetchall()/.rows.
    cursor = PlatformAdapterCursor({"query_id": "q_count_only", "rows_returned": 5})

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        assert cursor.row_count() == 5
        assert count_query_rows(cursor) == 5

    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []
    # The count-only path must not have materialized anything either.
    assert cursor._rows is None


def test_has_real_rows_access_alone_does_not_warn(caplog):
    cursor = PlatformAdapterCursor({"query_id": "q_inspect", "rows_returned": 3, "first_row": (7,)})

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        assert cursor.has_real_rows is False

    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []

    # A later real fetch must still warn exactly once - has_real_rows access
    # is a safe inspection, not a substitute for the materialization warning.
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        assert cursor.fetchall() == [(7,), (None,), (None,)]

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_fetchone_on_placeholder_cursor_warns_once_and_shares_budget_with_fetchall(caplog):
    # fetchone() routes through the same lazy `rows` property, so it must
    # trigger the one-time placeholder warning itself - and consume the same
    # once-per-cursor budget as fetchall(), not a separate one.
    cursor = PlatformAdapterCursor({"query_id": "q_fetchone", "rows_returned": 2})

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        assert cursor.fetchone() == (None,)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        assert cursor.fetchall() == [(None,), (None,)]

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1  # still exactly one - shared budget


def test_first_row_present_case_element_zero_real_but_still_warns_on_padding(caplog):
    # #1117 nuance: element 0 is the real first_row, but the remaining
    # cardinality is fabricated padding - has_real_rows is False and the
    # one-time warning still fires because real padding was fabricated.
    cursor = PlatformAdapterCursor({"query_id": "q_padded", "rows_returned": 3, "first_row": (7,)})
    assert cursor.has_real_rows is False

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        rows = cursor.fetchall()

    assert rows == [(7,), (None,), (None,)]
    assert rows[0] == (7,)  # element 0 is genuinely real
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "q_padded" in message
    assert "first_row+padding" in message


def test_first_row_only_single_real_row_does_not_warn_no_padding_fabricated(caplog):
    # Branch 3 (first_row alone, no rows_returned): the single element is
    # genuinely real and nothing is padded, so no warning fires even though
    # has_real_rows is conservatively False (no confirmed cardinality).
    cursor = PlatformAdapterCursor({"query_id": "q_first_row_only", "first_row": (7,)})
    assert cursor.has_real_rows is False

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        assert cursor.fetchall() == [(7,)]

    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []
    assert cursor._has_placeholder_padding is False
    assert cursor._warned_placeholder_materialization is False


def test_no_padding_when_rows_returned_equals_one_with_first_row(caplog):
    # rows_returned=1 with first_row present pads zero elements - no
    # fabrication occurred, so no warning should fire.
    cursor = PlatformAdapterCursor({"query_id": "q_exact_one", "rows_returned": 1, "first_row": (7,)})

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        assert cursor.fetchall() == [(7,)]

    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []
    assert cursor._has_placeholder_padding is False
    assert cursor._warned_placeholder_materialization is False
