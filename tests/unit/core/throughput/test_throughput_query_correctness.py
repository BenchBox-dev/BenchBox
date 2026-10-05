# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from benchbox.core.expected_results.models import ValidationMode
from benchbox.core.platform_registry import PlatformRegistry
from benchbox.core.tpcds.streams import StreamQuery
from benchbox.core.tpcds.throughput_test import TPCDSThroughputTest, TPCDSThroughputTestConfig
from benchbox.core.tpch.benchmark import TPCHBenchmark
from benchbox.core.tpch.streams import TPCHStreams
from benchbox.core.tpch.throughput_test import TPCHThroughputTest, TPCHThroughputTestConfig
from benchbox.core.validation.query_validation import (
    QueryValidator,
    clear_reference_seed_context,
    set_reference_seed_context,
    set_validation_mode_context,
)
from benchbox.platforms.base.connection_wrappers import PlatformAdapterConnection
from benchbox.platforms.sqlite import SQLiteAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]

_SNAPSHOT = Path(__file__).parents[2] / "platforms" / "throughput_session_capability_snapshot.json"
_SEED = 20260709


def _throughput_capable_platforms() -> list[str]:
    snapshot = json.loads(_SNAPSHOT.read_text())
    return sorted(
        key
        for key, record in snapshot.items()
        if record["status"] == "resolved" and record["capability"] != "unsupported"
    )


def _dialect_of(platform_key: str) -> str:
    adapter_class = PlatformRegistry.get_adapter_class(platform_key)
    return adapter_class.get_target_dialect(adapter_class.__new__(adapter_class))


class _RecordingBenchmark:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get_query(self, query_id: int, **kwargs: Any) -> str:
        self.calls.append({"query_id": query_id, **kwargs})
        return f"SELECT {query_id}"


class TestTPCHThroughputDialect:
    def test_pregenerated_and_inline_queries_receive_the_target_dialect_and_stream_id(self) -> None:
        benchmark = _RecordingBenchmark()
        test = TPCHThroughputTest(benchmark=benchmark, connection_factory=lambda: None, num_streams=2, dialect="sqlite")
        config = TPCHThroughputTestConfig(scale_factor=0.01, num_streams=2, base_seed=_SEED)

        test._pregenerate_stream_queries(config)
        pregenerated_calls = list(benchmark.calls)
        benchmark.calls.clear()
        test._resolve_query_text(None, 0, 1, _SEED, 5, config)

        assert len(pregenerated_calls) == 2 * 22
        for call in pregenerated_calls + benchmark.calls:
            assert call["dialect"] == "sqlite"
            assert call["params"] == {"stream_id": call["params"]["stream_id"]}
            assert call["params"]["stream_id"] in (0, 1)
            assert "stream_id" not in call

    def test_stream_id_beyond_the_permutation_matrix_wraps_like_the_permutation(self) -> None:
        benchmark = _RecordingBenchmark()
        test = TPCHThroughputTest(benchmark=benchmark, connection_factory=lambda: None, dialect="duckdb")
        stream_id = len(TPCHStreams.PERMUTATION_MATRIX) + 3

        test._get_stream_query(1, 7, stream_id, 0.01)

        assert benchmark.calls[0]["params"] == {"stream_id": 3}

    @pytest.mark.parametrize("platform_key", _throughput_capable_platforms())
    def test_stream_sql_equals_power_path_sql_for_the_same_query_seed_and_stream(self, platform_key: str) -> None:
        dialect = _dialect_of(platform_key)
        benchmark = TPCHBenchmark(scale_factor=0.01)
        test = TPCHThroughputTest(benchmark=benchmark, connection_factory=lambda: None, num_streams=2, dialect=dialect)
        config = TPCHThroughputTestConfig(scale_factor=0.01, num_streams=2, base_seed=_SEED)

        streams = test._pregenerate_stream_queries(config)

        for stream_id, stream_sql in streams.items():
            permutation = TPCHStreams.PERMUTATION_MATRIX[stream_id]
            for position, query_id in enumerate(permutation):
                seed = _SEED + stream_id + stream_id * 1000 + position
                power_sql = benchmark.get_query(
                    query_id, seed=seed, stream_id=stream_id, scale_factor=0.01, dialect=dialect
                )
                assert stream_sql[position] == power_sql, f"{platform_key} stream {stream_id} query {query_id}"

    @pytest.mark.parametrize("dialect", ["duckdb", "spark", "mysql", "doris", "sqlite"])
    def test_translation_changes_the_sql_for_dialects_that_need_it(self, dialect: str) -> None:
        benchmark = TPCHBenchmark(scale_factor=0.01)
        test = TPCHThroughputTest(benchmark=benchmark, connection_factory=lambda: None, num_streams=1, dialect=dialect)
        untranslated = TPCHThroughputTest(benchmark=benchmark, connection_factory=lambda: None, num_streams=1)
        config = TPCHThroughputTestConfig(scale_factor=0.01, num_streams=1, base_seed=_SEED)

        assert test._pregenerate_stream_queries(config) != untranslated._pregenerate_stream_queries(config)


class TestTPCDSStreamSeedValidationPolicy:
    @pytest.fixture(autouse=True)
    def _exact_mode(self) -> Any:
        set_validation_mode_context(ValidationMode.EXACT)
        yield
        set_validation_mode_context(None)
        clear_reference_seed_context()

    def test_exact_mode_row_count_mismatch_fails_without_a_stream_seed_context(self) -> None:
        result = QueryValidator().validate_query_result("tpcds", "3", 70, scale_factor=1.0, stream_id=0)

        assert result.is_valid is False
        assert result.validation_mode is ValidationMode.EXACT

    def test_stream_seeded_queries_are_excluded_from_answer_set_row_counts(self) -> None:
        set_reference_seed_context(False)

        result = QueryValidator().validate_query_result("tpcds", "3", 70, scale_factor=1.0, stream_id=0)

        assert result.is_valid is True
        assert result.validation_mode is ValidationMode.SKIP
        assert "excluded" in result.warning_message

    def test_tpch_non_reference_seed_policy_is_unchanged(self) -> None:
        set_reference_seed_context(False)

        result = QueryValidator().validate_query_result("tpch", "1", 0, scale_factor=1.0, stream_id=0)

        assert result.is_valid is False


class TestTPCDSFailedPlatformResult:
    @staticmethod
    def _connection_factory() -> Any:
        adapter = SQLiteAdapter(database_path=":memory:")

        def factory() -> PlatformAdapterConnection:
            return PlatformAdapterConnection(sqlite3.connect(":memory:", check_same_thread=False), adapter)

        return factory

    @staticmethod
    def _benchmark_with_sql(monkeypatch: pytest.MonkeyPatch, *statements: str) -> Any:
        class _Benchmark:
            def translate_query_text(self, query: str, source_dialect: str, target_dialect: str) -> str:
                return query

        monkeypatch.setattr(
            "benchbox.core.tpcds.streams.generate_dsqgen_streams",
            lambda **_kwargs: {
                0: [StreamQuery(stream_id=0, position=i, query_id=i + 1, sql=sql) for i, sql in enumerate(statements)]
            },
        )
        return _Benchmark()

    def _run(self, benchmark: Any) -> Any:
        test = TPCDSThroughputTest(
            benchmark=benchmark,
            connection_factory=self._connection_factory(),
            scale_factor=1.0,
            num_streams=1,
            dialect="sqlite",
        )
        return test.run(TPCDSThroughputTestConfig(scale_factor=1.0, num_streams=1, base_seed=7))

    def test_invalid_query_on_a_real_adapter_connection_fails_the_stream(self, monkeypatch: pytest.MonkeyPatch) -> None:
        benchmark = self._benchmark_with_sql(monkeypatch, "SELECT * FROM no_such_table")

        result = self._run(benchmark)

        stream = result.stream_results[0]
        assert stream.queries_failed == 1
        assert stream.queries_successful == 0
        assert stream.success is False
        assert "no_such_table" in stream.query_results[0]["error"]
        assert result.success is False
        assert result.throughput_at_size == 0.0

    def test_one_failed_query_makes_the_stream_unsuccessful_even_with_many_successes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        benchmark = self._benchmark_with_sql(monkeypatch, *(["SELECT 1"] * 9 + ["SELECT * FROM no_such_table"]))

        result = self._run(benchmark)

        stream = result.stream_results[0]
        assert (stream.queries_successful, stream.queries_failed) == (9, 1)
        assert stream.success is False
        assert result.success is False
        assert result.throughput_at_size == 0.0

    def test_valid_query_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        benchmark = self._benchmark_with_sql(monkeypatch, "SELECT 1")

        result = self._run(benchmark)

        assert result.stream_results[0].success is True
        assert result.success is True
        assert result.throughput_at_size > 0


class TestSQLiteStreamConnections:
    def test_each_stream_gets_its_own_connection_to_the_database_file(self, tmp_path: Path) -> None:
        adapter = SQLiteAdapter(database_path=str(tmp_path / "streams.sqlite"))
        shared = adapter.create_connection()
        shared.execute("CREATE TABLE t (id INTEGER)")
        shared.execute("INSERT INTO t VALUES (1)")
        shared.commit()

        first = adapter.new_stream_connection(shared, benchmark_type="olap")
        second = adapter.new_stream_connection(shared, benchmark_type="olap")
        try:
            assert len({id(shared), id(first), id(second)}) == 3
            assert first.execute("SELECT id FROM t").fetchall() == [(1,)]
            first.close()
            assert second.execute("SELECT id FROM t").fetchall() == [(1,)]
            assert shared.execute("SELECT id FROM t").fetchall() == [(1,)]
        finally:
            second.close()
            shared.close()

    def test_in_memory_database_cannot_serve_independent_streams(self) -> None:
        adapter = SQLiteAdapter(database_path=":memory:")
        shared = adapter.create_connection()
        try:
            with pytest.raises(RuntimeError, match="file-backed"):
                adapter.new_stream_connection(shared, benchmark_type="olap")
            with pytest.raises(RuntimeError, match="file-backed"):
                adapter.ensure_stream_sessions_supported()
        finally:
            shared.close()
