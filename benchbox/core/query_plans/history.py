"""Plan history tracking and analysis.

Provides functionality to track query plan evolution across multiple benchmark
runs and detect plan instability (flapping).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchbox.core.results.loader import iter_query_results

logger = logging.getLogger(__name__)


@dataclass
class PlanHistoryEntry:
    """Single entry in plan history for a query."""

    run_id: str
    timestamp: str  # ISO format
    fingerprint: str
    estimated_cost: float | None
    execution_time_ms: float
    platform: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "fingerprint": self.fingerprint,
            "estimated_cost": self.estimated_cost,
            "execution_time_ms": self.execution_time_ms,
            "platform": self.platform,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanHistoryEntry:
        """Create from dictionary."""
        return cls(
            run_id=data["run_id"],
            timestamp=data["timestamp"],
            fingerprint=data["fingerprint"],
            estimated_cost=data.get("estimated_cost"),
            execution_time_ms=data["execution_time_ms"],
            platform=data["platform"],
        )


class PlanHistory:
    """Track query plan evolution across multiple benchmark runs.

    Stores plan fingerprints and execution times for each run, allowing
    analysis of plan stability and performance correlation over time.
    """

    def __init__(self, storage_path: Path):
        """Initialize plan history storage.

        Args:
            storage_path: Directory to store history files
        """
        self.storage_path = storage_path
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, Any]] = {}

    def add_run(self, results: Any) -> None:
        """
        Add a benchmark run to plan history.

        Args:
            results: BenchmarkResults instance
        """
        run_id = getattr(results, "run_id", None)
        if not run_id:
            logger.warning("Cannot add run without run_id")
            return

        timestamp = getattr(results, "start_time", None)
        if not timestamp:
            timestamp = datetime.now(timezone.utc).isoformat()

        platform = getattr(results, "platform", "unknown")

        history_entry = {
            "run_id": run_id,
            "timestamp": timestamp,
            "platform": platform,
            "plan_fingerprints": {},
        }

        # Extract plan fingerprints from all phases
        for execution in iter_query_results(results):
            plan = execution.get("query_plan")
            if plan and hasattr(plan, "plan_fingerprint") and plan.plan_fingerprint:
                query_id = execution.get("query_id")
                history_entry["plan_fingerprints"][query_id] = {
                    "fingerprint": plan.plan_fingerprint,
                    "estimated_cost": getattr(plan, "estimated_cost", None),
                    "execution_time_ms": execution.get("execution_time_ms", 0.0) or 0.0,
                }

        # Write to storage
        history_file = self.storage_path / f"{run_id}.json"
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history_entry, f, indent=2)

        # Update cache
        self._cache[run_id] = history_entry

    def query_plan_history(self, query_id: str) -> list[PlanHistoryEntry]:
        """
        Get plan history for a specific query.

        Args:
            query_id: Query identifier

        Returns:
            List of PlanHistoryEntry sorted by timestamp (oldest first)
        """
        history: list[PlanHistoryEntry] = []

        for entry_file in sorted(self.storage_path.glob("*.json")):
            try:
                run_id = entry_file.stem
                if run_id in self._cache:
                    entry = self._cache[run_id]
                else:
                    with open(entry_file, encoding="utf-8") as f:
                        entry = json.load(f)
                    self._cache[run_id] = entry

                if query_id in entry.get("plan_fingerprints", {}):
                    plan_data = entry["plan_fingerprints"][query_id]
                    history.append(
                        PlanHistoryEntry(
                            run_id=entry["run_id"],
                            timestamp=entry["timestamp"],
                            fingerprint=plan_data["fingerprint"],
                            estimated_cost=plan_data.get("estimated_cost"),
                            execution_time_ms=plan_data.get("execution_time_ms", 0.0),
                            platform=entry.get("platform", "unknown"),
                        )
                    )
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Error loading history file {entry_file}: {e}")
                continue

        # Sort by timestamp
        history.sort(key=lambda x: x.timestamp)
        return history

    def detect_plan_flapping(
        self,
        query_id: str,
        window_size: int = 10,
        transition_threshold: float = 0.3,
    ) -> bool:
        """
        Detect if a query plan changes back and forth frequently.

        Flapping indicates optimizer instability where the same query gets
        different plans across runs, potentially oscillating between them.

        Args:
            query_id: Query identifier
            window_size: Number of recent runs to analyze
            transition_threshold: Fraction of transitions that indicates flapping

        Returns:
            True if plan flapping is detected
        """
        history = self.query_plan_history(query_id)[-window_size:]

        if len(history) < 3:
            return False

        fingerprints = [h.fingerprint for h in history]
        unique_fps = set(fingerprints)

        # Need at least 2 different fingerprints to have flapping
        if len(unique_fps) < 2:
            return False

        # Count transitions (changes from one fingerprint to another)
        transitions = sum(1 for i in range(len(fingerprints) - 1) if fingerprints[i] != fingerprints[i + 1])

        # Flapping if transitions exceed threshold of possible transitions
        max_transitions = len(fingerprints) - 1
        transition_rate = transitions / max_transitions if max_transitions > 0 else 0

        return transition_rate > transition_threshold

    def get_plan_version_history(self, query_id: str) -> list[tuple[str, int]]:
        """
        Get version history showing when plan changed.

        Args:
            query_id: Query identifier

        Returns:
            List of (fingerprint, version) tuples where version increments
            each time fingerprint changes
        """
        history = self.query_plan_history(query_id)
        versions: list[tuple[str, int]] = []

        current_version = 0
        current_fp = None

        for entry in history:
            if entry.fingerprint != current_fp:
                current_version += 1
                current_fp = entry.fingerprint
            versions.append((entry.fingerprint, current_version))

        return versions

    def get_all_query_ids(self) -> set[str]:
        """Get all query IDs in the history."""
        query_ids: set[str] = set()

        for entry_file in self.storage_path.glob("*.json"):
            try:
                run_id = entry_file.stem
                if run_id in self._cache:
                    entry = self._cache[run_id]
                else:
                    with open(entry_file, encoding="utf-8") as f:
                        entry = json.load(f)
                    self._cache[run_id] = entry

                query_ids.update(entry.get("plan_fingerprints", {}).keys())
            except (json.JSONDecodeError, KeyError):
                continue

        return query_ids

    def get_run_count(self) -> int:
        """Get the number of runs in history."""
        return len(list(self.storage_path.glob("*.json")))

    def clear(self) -> None:
        """Clear all history data."""
        for entry_file in self.storage_path.glob("*.json"):
            entry_file.unlink()
        self._cache.clear()


def create_plan_history(storage_path: str | Path) -> PlanHistory:
    """
    Create a PlanHistory instance.

    Args:
        storage_path: Directory to store history files

    Returns:
        PlanHistory instance
    """
    return PlanHistory(Path(storage_path))
