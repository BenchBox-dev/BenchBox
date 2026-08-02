"""Tests for self-contained browser snapshot gating."""

from pathlib import Path

import pytest

from _project.scripts.results_explorer_snapshot_invariants import check_snapshot

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_rejects_wal_assisted_snapshot_before_opening_database(tmp_path: Path) -> None:
    db_path = tmp_path / "results.duckdb"
    db_path.write_bytes(b"not a complete database")
    db_path.with_name("results.duckdb.wal").write_bytes(b"sidecar")

    errors = check_snapshot(db_path)

    assert errors == ["snapshot is not self-contained: WAL sidecar exists at results.duckdb.wal"]
