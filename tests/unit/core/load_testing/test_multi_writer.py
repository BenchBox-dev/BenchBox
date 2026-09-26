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
from typing import Any

import pytest

pytest.importorskip("duckdb", reason="DuckDB not installed")

import duckdb

from benchbox.experimental.load_testing.executor import ConcurrentLoadConfig, ConcurrentLoadExecutor
from benchbox.experimental.load_testing.patterns import MultiWriterPattern

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


class _MockConnection:
    def close(self) -> None:
        pass


def _role_config(
    pattern: MultiWriterPattern,
    executed: list[tuple[str, str]],
    queries_per_stream: int = 1,
) -> ConcurrentLoadConfig:
    def make_factory(role: str, sql: str):
        def factory(index: int) -> tuple[str, str]:
            executed.append((role, sql))
            return (f"{role}_{index}", sql)

        return factory

    return ConcurrentLoadConfig(
        query_factory=make_factory("default", "SELECT 1"),
        connection_factory=_MockConnection,
        execute_query=lambda _conn, _sql: (True, 1, None),
        pattern=pattern,
        queries_per_stream=queries_per_stream,
        collect_resource_metrics=False,
        role_factories={
            "writer": make_factory("writer", "INSERT INTO t VALUES (1)"),
            "reader": make_factory("reader", "SELECT * FROM t"),
        },
    )


def test_multi_writer_executor_routes_roles() -> None:
    executed: list[tuple[str, str]] = []
    pattern = MultiWriterPattern(writers=2, readers=1, duration_seconds=0.6, drain_seconds=0)
    result = ConcurrentLoadExecutor(_role_config(pattern, executed)).run()

    assert result.total_queries_executed > 0
    roles = {role for role, _ in executed}
    assert "writer" in roles
    assert "reader" in roles
    assert "default" not in roles
    assert {sql for role, sql in executed if role == "writer"} == {"INSERT INTO t VALUES (1)"}
    assert {sql for role, sql in executed if role == "reader"} == {"SELECT * FROM t"}


def test_multi_writer_executor_rejects_missing_role_factories() -> None:
    pattern = MultiWriterPattern(writers=1, readers=1, duration_seconds=0.5, drain_seconds=0)
    config = ConcurrentLoadConfig(
        query_factory=lambda index: (f"q{index}", "SELECT 1"),
        connection_factory=_MockConnection,
        execute_query=lambda _conn, _sql: (True, 1, None),
        pattern=pattern,
        queries_per_stream=1,
        collect_resource_metrics=False,
    )
    with pytest.raises(ValueError, match="role_factories"):
        ConcurrentLoadExecutor(config).run()


def test_multi_writer_drain_launches_writers_only() -> None:
    executed: list[tuple[str, str]] = []
    pattern = MultiWriterPattern(writers=2, readers=2, duration_seconds=0.3, drain_seconds=3.0)
    executor = ConcurrentLoadExecutor(_role_config(pattern, executed, queries_per_stream=50))

    drain = next(phase for phase in pattern.get_phases() if phase.phase_name == "write-drain")
    executor._active_roles = {"writer": 1, "reader": 2}
    assert executor._role_targets(drain) == {"writer": 1}

    executor._active_roles = {"writer": 2, "reader": 0}
    assert executor._role_targets(drain) == {"writer": 0}


def test_undifferentiated_phase_keeps_default_factory(mock_connection_factory: Any, mock_execute_query: Any) -> None:
    from benchbox.experimental.load_testing.patterns import SteadyPattern

    executed: list[tuple[str, str]] = []
    config = _role_config(
        SteadyPattern(concurrency=1, duration_seconds=0.4),
        executed,
    )
    config.connection_factory = mock_connection_factory
    config.execute_query = mock_execute_query
    result = ConcurrentLoadExecutor(config).run()

    assert result.total_queries_executed > 0
    assert {role for role, _ in executed} == {"default"}


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
