"""Multi-client concurrent-writer stress test ("multiplayer DuckDB" story).

Spawns N writer threads issuing INSERTs against one DuckDB table while M
reader threads run SELECTs, then asserts every write landed and no stream
errored. DuckDB serializes concurrent writers internally, so the scenario
proves the client-side fan-out works rather than asserting any particular
isolation level.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

pytest.importorskip("duckdb", reason="DuckDB not installed")

import duckdb

from benchbox.experimental.load_testing.patterns import MultiWriterPattern

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


def test_multi_writer_pattern_drives_duckdb_writers_and_readers(tmp_path: Path) -> None:
    pattern = MultiWriterPattern(writers=3, readers=2, duration_seconds=10, drain_seconds=0)
    assert pattern.max_concurrency == 5

    db_path = str(tmp_path / "mw.duckdb")
    with duckdb.connect(db_path) as con:
        con.execute("CREATE TABLE t (id INTEGER, v VARCHAR)")

    errors: list[str] = []

    def writer(n: int) -> None:
        try:
            with duckdb.connect(db_path) as con:
                for i in range(20):
                    con.execute(f"INSERT INTO t VALUES ({n * 100 + i}, 'w{n}')")
        except Exception as exc:  # noqa: BLE001 - collected as test failure below
            errors.append(f"writer {n}: {exc}")

    def reader() -> None:
        try:
            with duckdb.connect(db_path) as con:
                for _ in range(20):
                    con.execute("SELECT COUNT(*) FROM t").fetchone()
        except Exception as exc:  # noqa: BLE001 - collected as test failure below
            errors.append(f"reader: {exc}")

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(pattern.writer_count)]
    threads += [threading.Thread(target=reader) for _ in range(pattern.reader_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert not [t for t in threads if t.is_alive()], "writer/reader threads hung"
    assert not errors, f"concurrent writer/reader errors: {errors}"
    with duckdb.connect(db_path, read_only=True) as con:
        (rows,) = con.execute("SELECT COUNT(*) FROM t").fetchone()
    assert rows == pattern.writer_count * 20
