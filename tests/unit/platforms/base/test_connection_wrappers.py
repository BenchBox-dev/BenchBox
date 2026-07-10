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
"""

from __future__ import annotations

import pytest

from benchbox.platforms.base.connection_wrappers import PlatformAdapterCursor

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


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
