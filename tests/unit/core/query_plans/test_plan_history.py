"""Tests for plan history tracking."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from benchbox.core.query_plans.history import (
    PlanHistory,
    PlanHistoryEntry,
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


@dataclass
class MockQueryExecution:
    """Mock query execution for testing."""

    query_id: str
    execution_time_ms: float = 100.0
    query_plan: QueryPlanDAG | None = None


@dataclass
class MockPhaseResults:
    """Mock phase results for testing."""

    queries: list[MockQueryExecution] = field(default_factory=list)


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
    """Tests for PlanHistory class."""

    def test_add_run(self) -> None:
        """Test adding a benchmark run to history."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            plan = _create_plan_with_fingerprint("q1", "a" * 64)
            results = make_benchmark_results(
                run_id="run1",
                phases={"power": MockPhaseResults(queries=[MockQueryExecution("q1", 100.0, plan)])},
            )

            history.add_run(results)

            # Verify file was created
            assert (Path(tmpdir) / "run1.json").exists()

            # Verify content
            with open(Path(tmpdir) / "run1.json") as f:
                data = json.load(f)
            assert data["run_id"] == "run1"
            assert "q1" in data["plan_fingerprints"]
            assert data["plan_fingerprints"]["q1"]["fingerprint"] == "a" * 64

    def test_query_plan_history(self) -> None:
        """Test retrieving history for a query."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            # Add multiple runs
            for i in range(3):
                plan = _create_plan_with_fingerprint("q1", "a" * 64)
                results = make_benchmark_results(
                    run_id=f"run{i}",
                    start_time=f"2024-01-0{i + 1}T00:00:00Z",
                    phases={"power": MockPhaseResults(queries=[MockQueryExecution("q1", 100.0 + i * 10, plan)])},
                )
                history.add_run(results)

            entries = history.query_plan_history("q1")

            assert len(entries) == 3
            assert entries[0].run_id == "run0"  # Sorted by timestamp
            assert entries[2].run_id == "run2"

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
                    run_id=f"run{i}",
                    start_time=f"2024-01-0{i + 1}T00:00:00Z",
                    phases={"power": MockPhaseResults(queries=[MockQueryExecution("q1", 100.0, plan)])},
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
                    run_id=f"run{i}",
                    start_time=f"2024-01-0{i + 1}T00:00:00Z",
                    phases={"power": MockPhaseResults(queries=[MockQueryExecution("q1", 100.0, plan)])},
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
                    run_id=f"run{i}",
                    start_time=f"2024-01-0{i + 1}T00:00:00Z",
                    phases={"power": MockPhaseResults(queries=[MockQueryExecution("q1", 100.0, plan)])},
                )
                history.add_run(results)

            # 4 transitions = 4/4 = 100%, above 30% threshold
            assert history.detect_plan_flapping("q1") is True

    def test_detect_plan_flapping_few_runs(self) -> None:
        """Test flapping detection with too few runs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            # Only 2 runs - not enough to detect flapping
            for i in range(2):
                fp = "a" * 64 if i == 0 else "b" * 64
                plan = _create_plan_with_fingerprint("q1", fp)
                results = make_benchmark_results(
                    run_id=f"run{i}",
                    start_time=f"2024-01-0{i + 1}T00:00:00Z",
                    phases={"power": MockPhaseResults(queries=[MockQueryExecution("q1", 100.0, plan)])},
                )
                history.add_run(results)

            assert history.detect_plan_flapping("q1") is False

    def test_get_plan_version_history(self) -> None:
        """Test version history tracking."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            fingerprints = ["a" * 64, "a" * 64, "b" * 64, "c" * 64, "c" * 64]
            for i, fp in enumerate(fingerprints):
                plan = _create_plan_with_fingerprint("q1", fp)
                results = make_benchmark_results(
                    run_id=f"run{i}",
                    start_time=f"2024-01-0{i + 1}T00:00:00Z",
                    phases={"power": MockPhaseResults(queries=[MockQueryExecution("q1", 100.0, plan)])},
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

    def test_get_all_query_ids(self) -> None:
        """Test getting all query IDs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            plan1 = _create_plan_with_fingerprint("q1", "a" * 64)
            plan2 = _create_plan_with_fingerprint("q2", "b" * 64)
            results = make_benchmark_results(
                run_id="run1",
                phases={
                    "power": MockPhaseResults(
                        queries=[
                            MockQueryExecution("q1", 100.0, plan1),
                            MockQueryExecution("q2", 200.0, plan2),
                        ]
                    )
                },
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
                    run_id=f"run{i}",
                    phases={"power": MockPhaseResults(queries=[MockQueryExecution("q1", 100.0, plan)])},
                )
                history.add_run(results)

            assert history.get_run_count() == 3

    def test_clear(self) -> None:
        """Test clearing history."""
        with tempfile.TemporaryDirectory() as tmpdir:
            history = PlanHistory(Path(tmpdir))

            plan = _create_plan_with_fingerprint("q1", "a" * 64)
            results = make_benchmark_results(
                run_id="run1",
                phases={"power": MockPhaseResults(queries=[MockQueryExecution("q1", 100.0, plan)])},
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
