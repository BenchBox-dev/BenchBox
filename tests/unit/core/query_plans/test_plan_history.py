"""Tests for plan history tracking."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from benchbox.cli.commands.plan_history import plan_history
from benchbox.core.query_plans.history import (
    PlanHistory,
    PlanHistoryEntry,
    _parse_history_timestamp,
    create_plan_history,
)
from benchbox.core.results.query_plan_models import (
    LogicalOperator,
    LogicalOperatorType,
    QueryPlanDAG,
)
from tests.fixtures.result_dict_fixtures import make_benchmark_results

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _qr(query_id: str, execution_time_ms: float = 100.0, query_plan: QueryPlanDAG | None = None) -> dict:
    """Build a query_results dict matching the real BenchmarkResults.query_results shape."""
    return {"query_id": query_id, "execution_time_ms": execution_time_ms, "query_plan": query_plan}


def _create_plan_with_fingerprint(query_id: str, fingerprint: str) -> QueryPlanDAG:
    """Create a plan with a specific fingerprint."""
    root = LogicalOperator(
        operator_id="1",
        operator_type=LogicalOperatorType.SCAN,
        table_name="test",
        children=[],
    )
    return QueryPlanDAG(
        query_id=query_id,
        platform="test",
        logical_root=root,
        plan_fingerprint=fingerprint,
        raw_explain_output="test",
    )


class TestParseHistoryTimestamp:
    """#1025 review: datetime.fromisoformat only accepts a trailing "Z" from
    Python 3.11 onward; on 3.10 (requires-python floor) it raises ValueError,
    which the except branch silently downgrades to a datetime.min sort key -
    misordering history entries with a "Z"-suffixed timestamp instead of
    raising or logging anything actionable."""

    def test_z_suffix_parses_as_utc(self) -> None:
        parsed = _parse_history_timestamp("2024-03-10T02:30:00Z")

        assert parsed == datetime(2024, 3, 10, 2, 30, 0, tzinfo=timezone.utc)
        assert parsed != datetime.min.replace(tzinfo=timezone.utc)

    def test_z_suffix_sorts_correctly_against_offset_timestamps(self) -> None:
        z_time = _parse_history_timestamp("2024-03-10T02:30:00Z")
        earlier_offset_time = _parse_history_timestamp("2024-03-10T01:00:00+00:00")
        later_offset_time = _parse_history_timestamp("2024-03-10T05:00:00+00:00")

        assert earlier_offset_time < z_time < later_offset_time

    def test_malformed_timestamp_still_sorts_first(self) -> None:
        assert _parse_history_timestamp("not-a-timestamp") == datetime.min.replace(tzinfo=timezone.utc)

    def test_z_suffix_is_stripped_before_fromisoformat_regardless_of_python_version(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Prove the "Z" -> "+00:00" normalization happens unconditionally,
        not just on interpreters new enough to accept "Z" natively. The
        sandbox's own Python (3.11+) already tolerates "Z" in fromisoformat,
        so a plain before/after diff can't distinguish fixed from buggy here
        - assert directly on the string handed to fromisoformat instead."""
        import benchbox.core.query_plans.history as history_module

        seen: list[str] = []
        real_fromisoformat = datetime.fromisoformat

        class _RecordingDatetime:
            @staticmethod
            def fromisoformat(value: str) -> datetime:
                seen.append(value)
                return real_fromisoformat(value)

        # `datetime` is a plain module-level name in history.py (`from datetime
        # import datetime`); datetime.datetime itself is a C type and cannot
        # be monkeypatched directly, so replace the module-level binding.
        monkeypatch.setattr(history_module, "datetime", _RecordingDatetime)

        history_module._parse_history_timestamp("2024-03-10T02:30:00Z")

        assert seen == ["2024-03-10T02:30:00+00:00"]


class TestPlanHistoryEntry:
    """Tests for PlanHistoryEntry dataclass."""

    def test_to_dict(self) -> None:
        """Test to_dict conversion."""
        entry = PlanHistoryEntry(
            run_id="run1",
            timestamp="2024-01-01T00:00:00Z",
            fingerprint="a" * 64,
            estimated_cost=100.0,
            execution_time_ms=50.0,
            platform="duckdb",
        )

        result = entry.to_dict()

        assert result["run_id"] == "run1"
        assert result["fingerprint"] == "a" * 64
        assert result["execution_time_ms"] == 50.0

    def test_from_dict(self) -> None:
        """Test from_dict creation."""
        data = {
            "run_id": "run1",
            "timestamp": "2024-01-01T00:00:00Z",
            "fingerprint": "a" * 64,
            "estimated_cost": 100.0,
            "execution_time_ms": 50.0,
            "platform": "duckdb",
        }

        entry = PlanHistoryEntry.from_dict(data)

        assert entry.run_id == "run1"
        assert entry.fingerprint == "a" * 64


class TestPlanHistory:
    """Tests for PlanHistory class.

    Constructs real ``BenchmarkResults`` via ``make_benchmark_results`` using
    its REAL attribute names (``execution_id``/``timestamp``), not the
    ``run_id``/``start_time`` names ``PlanHistory.add_run`` used to read
    (qpc-08 / F1.2): those attributes don't exist on ``BenchmarkResults``, so
    a fixture that bolted them on as loose attributes masked `add_run` being
    permanently unreachable from any real caller.
    """

    def test_add_run(self) -> None:
        """Test adding a benchmark run to history."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            plan = _create_plan_with_fingerprint("q1", "a" * 64)
            results = make_benchmark_results(
                execution_id="run1",
                query_results=[_qr("q1", 100.0, plan)],
            )

            history.add_run(results)

            # Verify file was created
            assert (Path(tmpdir) / "run1.json").exists()

            # Verify content
            with open(Path(tmpdir) / "run1.json", encoding="utf-8") as f:
                data = json.load(f)
            assert data["run_id"] == "run1"
            assert "q1" in data["plan_fingerprints"]
            assert data["plan_fingerprints"]["q1"]["fingerprint"] == "a" * 64

    def test_add_run_without_execution_id_is_a_noop(self) -> None:
        """A result with no execution_id cannot be filed under any run name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            plan = _create_plan_with_fingerprint("q1", "a" * 64)
            results = make_benchmark_results(
                execution_id="",
                query_results=[_qr("q1", 100.0, plan)],
            )

            history.add_run(results)

            assert history.get_run_count() == 0

    def test_query_plan_history(self) -> None:
        """Test retrieving history for a query."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            # Add multiple runs
            for i in range(3):
                plan = _create_plan_with_fingerprint("q1", "a" * 64)
                results = make_benchmark_results(
                    execution_id=f"run{i}",
                    timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
                    query_results=[_qr("q1", 100.0 + i * 10, plan)],
                )
                history.add_run(results)

            entries = history.query_plan_history("q1")

            assert len(entries) == 3
            assert entries[0].run_id == "run0"  # Sorted by timestamp
            assert entries[2].run_id == "run2"

    def test_query_plan_history_sorts_mixed_offset_timestamps_chronologically(self) -> None:
        """qpc-08 / F7.2: mixed-offset timestamps must be ordered by the instant
        they denote, not by lexicographic string comparison.

        The earlier instant here is deliberately arranged to sort LATER by both
        of the axes a naive implementation might rely on -- filename/glob order
        and raw-string order -- so only a parse-based sort recovers the true
        chronological order. A regression to ``history.sort(key=lambda x:
        x.timestamp)`` (lexicographic) turns this test red.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            # run-a: 2024-03-10 02:30 UTC.
            # run-b: 2024-03-10 06:30 +08:00 == 2024-03-09 22:30 UTC -- the
            # EARLIER instant. Yet its filename ("run-b" > "run-a") AND its raw
            # timestamp string ("06:30" > "02:30") both sort it AFTER run-a, so
            # a lexicographic (or glob-order) sort yields the wrong [run-a,
            # run-b]; only parsing yields the correct [run-b, run-a]. Explicit
            # offsets (not "Z") keep this valid on every supported Python,
            # including 3.10 where ``fromisoformat`` rejects a trailing "Z".
            stored_timestamps = (
                ("run-a", "2024-03-10T02:30:00+00:00"),
                ("run-b", "2024-03-10T06:30:00+08:00"),
            )
            for exec_id, iso_timestamp in stored_timestamps:
                plan = _create_plan_with_fingerprint("q1", "a" * 64)
                history.add_run(
                    make_benchmark_results(
                        execution_id=exec_id,
                        query_results=[_qr("q1", 100.0, plan)],
                    )
                )
                # Overwrite the stored timestamp with the exact mixed-offset
                # representation under test (add_run would otherwise write the
                # fixture's naive now()).
                entry_file = Path(tmpdir) / f"{exec_id}.json"
                with open(entry_file, encoding="utf-8") as f:
                    data = json.load(f)
                data["timestamp"] = iso_timestamp
                with open(entry_file, "w", encoding="utf-8") as f:
                    json.dump(data, f)
            history._cache.clear()

            entries = history.query_plan_history("q1")

            assert [e.run_id for e in entries] == ["run-b", "run-a"]

    def test_query_plan_history_empty(self) -> None:
        """Test history for non-existent query."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))
            entries = history.query_plan_history("nonexistent")
            assert entries == []

    def test_detect_plan_flapping_no_flapping(self) -> None:
        """Test flapping detection with stable plan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            # All runs have same fingerprint - no flapping
            for i in range(5):
                plan = _create_plan_with_fingerprint("q1", "a" * 64)
                results = make_benchmark_results(
                    execution_id=f"run{i}",
                    timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
                    query_results=[_qr("q1", 100.0, plan)],
                )
                history.add_run(results)

            assert history.detect_plan_flapping("q1") is False

    def test_detect_plan_flapping_single_change(self) -> None:
        """Test flapping detection with single plan change."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            # Plan changes once - not flapping
            fingerprints = ["a" * 64, "a" * 64, "b" * 64, "b" * 64, "b" * 64]
            for i, fp in enumerate(fingerprints):
                plan = _create_plan_with_fingerprint("q1", fp)
                results = make_benchmark_results(
                    execution_id=f"run{i}",
                    timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
                    query_results=[_qr("q1", 100.0, plan)],
                )
                history.add_run(results)

            # Single transition = 1/4 = 25%, below 30% threshold
            assert history.detect_plan_flapping("q1") is False

    def test_detect_plan_flapping_detected(self) -> None:
        """Test flapping detection with frequent changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            # Plan oscillates - flapping
            fingerprints = ["a" * 64, "b" * 64, "a" * 64, "b" * 64, "a" * 64]
            for i, fp in enumerate(fingerprints):
                plan = _create_plan_with_fingerprint("q1", fp)
                results = make_benchmark_results(
                    execution_id=f"run{i}",
                    timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
                    query_results=[_qr("q1", 100.0, plan)],
                )
                history.add_run(results)

            # 4 transitions = 4/4 = 100%, above 30% threshold
            assert history.detect_plan_flapping("q1") is True

    def test_detect_plan_flapping_ignores_fingerprint_version_boundary(self) -> None:
        """A pure fingerprint-encoding-version bump (qpc-03 v1 -> v2) makes
        the fingerprint string change even for an unchanged plan (#1028
        review). Every consecutive pair here crosses a fingerprint_version
        boundary; without the fix that reads as 100% transitions (flapping),
        but none of it reflects a real plan change, so it must not flap."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            # Alternating fingerprint_version on every run, same logical plan
            # re-encoded each time - an artificial worst case that isolates
            # the version-boundary-exclusion mechanism (same technique as
            # test_detect_plan_flapping_ignores_cross_platform_alternation).
            specs = [("v1-a" * 16, 1), ("v2-a" * 16, 2), ("v1-a" * 16, 1), ("v2-a" * 16, 2), ("v1-a" * 16, 1)]
            for i, (fp, version) in enumerate(specs):
                plan = _create_plan_with_fingerprint("q1", fp)
                plan.fingerprint_version = version
                results = make_benchmark_results(
                    execution_id=f"run{i}",
                    timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
                    query_results=[_qr("q1", 100.0, plan)],
                )
                history.add_run(results)

            assert history.detect_plan_flapping("q1") is False

    def test_detect_plan_flapping_few_runs(self) -> None:
        """Test flapping detection with too few runs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            # Only 2 runs - not enough to detect flapping
            for i in range(2):
                fp = "a" * 64 if i == 0 else "b" * 64
                plan = _create_plan_with_fingerprint("q1", fp)
                results = make_benchmark_results(
                    execution_id=f"run{i}",
                    timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
                    query_results=[_qr("q1", 100.0, plan)],
                )
                history.add_run(results)

            assert history.detect_plan_flapping("q1") is False

    def test_detect_plan_flapping_ignores_cross_platform_alternation(self) -> None:
        """qpc-08 / F3.4-partial: two platforms alternating for the same
        query_id is NOT one flapping sequence -- each platform has its own
        independent, stable plan lineage. Naive interleaved comparison would
        report 100% transitions; partitioned by platform, neither platform
        actually flaps.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            # duckdb: always "a". postgres: always "b". Interleaved by
            # timestamp they alternate a/b/a/b/a -- 100% naive transition rate.
            for i in range(5):
                platform = "duckdb" if i % 2 == 0 else "postgres"
                fingerprint = "a" * 64 if platform == "duckdb" else "b" * 64
                plan = _create_plan_with_fingerprint("q1", fingerprint)
                results = make_benchmark_results(
                    execution_id=f"run{i}",
                    timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
                    platform=platform,
                    query_results=[_qr("q1", 100.0, plan)],
                )
                history.add_run(results)

            assert history.detect_plan_flapping("q1") is False

    def test_detect_plan_flapping_detects_real_flap_within_one_platform(self) -> None:
        """A genuine flap on ONE platform is still detected even when a
        second, stable platform's runs are interleaved in the same history."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            duckdb_fingerprints = ["a" * 64, "c" * 64, "a" * 64, "c" * 64, "a" * 64]
            for i, fp in enumerate(duckdb_fingerprints):
                plan = _create_plan_with_fingerprint("q1", fp)
                history.add_run(
                    make_benchmark_results(
                        execution_id=f"duckdb-run{i}",
                        timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
                        platform="duckdb",
                        query_results=[_qr("q1", 100.0, plan)],
                    )
                )
            # A stable postgres lineage interleaved in the same history dir.
            for i in range(5):
                plan = _create_plan_with_fingerprint("q1", "b" * 64)
                history.add_run(
                    make_benchmark_results(
                        execution_id=f"postgres-run{i}",
                        timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
                        platform="postgres",
                        query_results=[_qr("q1", 100.0, plan)],
                    )
                )

            assert history.detect_plan_flapping("q1") is True

    def test_get_plan_version_history(self) -> None:
        """Test version history tracking."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            fingerprints = ["a" * 64, "a" * 64, "b" * 64, "c" * 64, "c" * 64]
            for i, fp in enumerate(fingerprints):
                plan = _create_plan_with_fingerprint("q1", fp)
                results = make_benchmark_results(
                    execution_id=f"run{i}",
                    timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
                    query_results=[_qr("q1", 100.0, plan)],
                )
                history.add_run(results)

            versions = history.get_plan_version_history("q1")

            assert len(versions) == 5
            # Same fingerprint keeps same version
            assert versions[0] == ("a" * 64, 1)
            assert versions[1] == ("a" * 64, 1)
            # New fingerprint increments version
            assert versions[2] == ("b" * 64, 2)
            assert versions[3] == ("c" * 64, 3)
            assert versions[4] == ("c" * 64, 3)

    def test_get_plan_version_history_ignores_fingerprint_version_boundary(self) -> None:
        """A fingerprint_version change alone (qpc-03 encoding bump) must not
        bump the reported plan version - only a genuine content change within
        the same encoding version should (#1028 review)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            specs = [
                ("a" * 64, 1),  # v1 baseline
                ("a2" * 32, 2),  # same logical plan, re-encoded as v2 - NOT a change
                ("a2" * 32, 2),  # stable under v2
                ("b" * 64, 2),  # genuine change, same (v2) encoding
            ]
            for i, (fp, version) in enumerate(specs):
                plan = _create_plan_with_fingerprint("q1", fp)
                plan.fingerprint_version = version
                results = make_benchmark_results(
                    execution_id=f"run{i}",
                    timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
                    query_results=[_qr("q1", 100.0, plan)],
                )
                history.add_run(results)

            versions = history.get_plan_version_history("q1")

            assert len(versions) == 4
            assert versions[0] == ("a" * 64, 1)
            assert versions[1] == ("a2" * 32, 1)  # encoding bump alone: no version bump
            assert versions[2] == ("a2" * 32, 1)
            assert versions[3] == ("b" * 64, 2)  # genuine change: version bumps

    def test_get_all_query_ids(self) -> None:
        """Test getting all query IDs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            plan1 = _create_plan_with_fingerprint("q1", "a" * 64)
            plan2 = _create_plan_with_fingerprint("q2", "b" * 64)
            results = make_benchmark_results(
                execution_id="run1",
                query_results=[
                    _qr("q1", 100.0, plan1),
                    _qr("q2", 200.0, plan2),
                ],
            )
            history.add_run(results)

            query_ids = history.get_all_query_ids()

            assert query_ids == {"q1", "q2"}

    def test_get_run_count(self) -> None:
        """Test run count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            assert history.get_run_count() == 0

            for i in range(3):
                plan = _create_plan_with_fingerprint("q1", "a" * 64)
                results = make_benchmark_results(
                    execution_id=f"run{i}",
                    query_results=[_qr("q1", 100.0, plan)],
                )
                history.add_run(results)

            assert history.get_run_count() == 3

    def test_clear(self) -> None:
        """Test clearing history."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            plan = _create_plan_with_fingerprint("q1", "a" * 64)
            results = make_benchmark_results(
                execution_id="run1",
                query_results=[_qr("q1", 100.0, plan)],
            )
            history.add_run(results)

            assert history.get_run_count() == 1

            history.clear()

            assert history.get_run_count() == 0


class TestCreatePlanHistory:
    """Tests for create_plan_history factory function."""

    def test_creates_history_instance(self) -> None:
        """Test factory function creates PlanHistory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = create_plan_history(tmpdir)
            assert isinstance(history, PlanHistory)

    def test_creates_directory_if_not_exists(self) -> None:
        """Test factory creates storage directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "subdir" / "history"
            create_plan_history(new_dir)
            assert new_dir.exists()


class TestAddRunEndToEndViaCLI:
    """qpc-08 w3: exercise the real (un-mocked) `add_run` -> `PlanHistory` ->
    `benchbox plan-history` CLI path end to end, proving the wiring actually
    reaches a real ``BenchmarkResults`` rather than only a fixture that
    happens to define the attributes `add_run` reads.
    """

    def test_real_benchmark_results_recorded_and_shown_by_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = Path(tmpdir)
            history = PlanHistory(history_dir)

            for i, fp in enumerate(["a" * 64, "a" * 64, "b" * 64]):
                plan = _create_plan_with_fingerprint("1", fp)
                results = make_benchmark_results(
                    execution_id=f"run{i}",
                    timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
                    platform="duckdb",
                    query_results=[_qr("1", 100.0 + i, plan)],
                )
                history.add_run(results)

            result = CliRunner().invoke(
                plan_history,
                ["--query-id", "1", "--history-dir", str(history_dir)],
            )

            assert result.exit_code == 0, result.output
            assert "Plan History for 1" in result.output
            assert "run0" in result.output
            assert "run2" in result.output
            assert "Unique plans: 2" in result.output
