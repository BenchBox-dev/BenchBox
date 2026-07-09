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
from benchbox.core.results.query_plan_models import LEGACY_FINGERPRINT_VERSION

logger = logging.getLogger(__name__)


def _parse_history_timestamp(timestamp: str) -> datetime:
    """Parse a history entry's ISO-8601 timestamp for chronological ordering.

    Naive and timezone-aware timestamps can both appear across history files
    (e.g. a `datetime.now(timezone.utc).isoformat()` fallback vs. a captured
    `BenchmarkResults.timestamp` that may be naive); comparing a naive and an
    aware `datetime` raises `TypeError`, so a naive result is treated as UTC.
    A malformed/empty timestamp sorts first rather than raising, so one
    corrupt history entry doesn't break ordering for the rest.

    `datetime.fromisoformat` only accepts a trailing "Z" (Zulu/UTC) suffix
    from Python 3.11 onward; on 3.10 (the project's floor - see
    requires-python) it raises ValueError on e.g. "2026-01-01T00:00:00Z",
    which the except branch used to silently swallow into a datetime.min
    sort key. Normalize "Z" to the "+00:00" offset fromisoformat has always
    accepted, on every supported version, before parsing.
    """
    if timestamp:
        normalized = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            logger.warning(f"Could not parse history timestamp {timestamp!r}; sorting it first")
        else:
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


@dataclass
class PlanHistoryEntry:
    """Single entry in plan history for a query."""

    run_id: str
    timestamp: str  # ISO format
    fingerprint: str
    estimated_cost: float | None
    execution_time_ms: float
    platform: str
    # QueryPlanDAG.fingerprint_version the fingerprint was encoded under (qpc-03
    # F2.1). A v1 flat-string and a v2 tree-JSON encoding of the SAME logical
    # plan hash differently, so flapping/version-history detection must never
    # treat a version-boundary crossing as evidence the plan itself changed.
    # Entries from before this field existed default to LEGACY_FINGERPRINT_VERSION.
    fingerprint_version: int = LEGACY_FINGERPRINT_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "fingerprint": self.fingerprint,
            "estimated_cost": self.estimated_cost,
            "execution_time_ms": self.execution_time_ms,
            "platform": self.platform,
            "fingerprint_version": self.fingerprint_version,
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
            fingerprint_version=data.get("fingerprint_version", LEGACY_FINGERPRINT_VERSION),
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
        # BenchmarkResults has no `run_id`/`start_time` attributes -- the real
        # fields are `execution_id`/`timestamp` (qpc-08 / F1.2). Reading the
        # wrong names made this a permanent, silent no-op. Access the required
        # attributes DIRECTLY rather than via `getattr(..., default)`: the
        # original bug was silent precisely because getattr never raised on a
        # missing/renamed attribute, it just returned the default. Direct
        # access makes a future shape drift fail loudly (AttributeError, caught
        # and logged by the single caller) instead of silently no-op'ing again.
        execution_id = results.execution_id
        if not execution_id:
            logger.warning("Cannot add run without execution_id")
            return

        timestamp_value = results.timestamp
        if isinstance(timestamp_value, datetime):
            timestamp = timestamp_value.isoformat()
        elif timestamp_value:
            timestamp = str(timestamp_value)
        else:
            timestamp = datetime.now(timezone.utc).isoformat()

        platform = getattr(results, "platform", "unknown")

        # The on-disk/JSON key stays "run_id" (must_preserve: existing
        # history-file shape stays readable) even though the value now comes
        # from the correctly-named `execution_id` attribute.
        history_entry = {
            "run_id": execution_id,
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
                    "fingerprint_version": getattr(plan, "fingerprint_version", LEGACY_FINGERPRINT_VERSION),
                }

        # Write to storage
        history_file = self.storage_path / f"{execution_id}.json"
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history_entry, f, indent=2)

        # Update cache
        self._cache[execution_id] = history_entry

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
                            fingerprint_version=plan_data.get("fingerprint_version", LEGACY_FINGERPRINT_VERSION),
                        )
                    )
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Error loading history file {entry_file}: {e}")
                continue

        # Sort chronologically. Parsing (rather than a lexicographic string
        # sort) matters once entries mix timestamp representations -- e.g. a
        # naive local ISO string alongside a "+00:00"/"Z" UTC one sort
        # incorrectly as plain strings despite being comparable instants
        # once parsed (qpc-08 / F7.2).
        history.sort(key=lambda x: _parse_history_timestamp(x.timestamp))
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

        History is partitioned by platform before checking for flapping: a
        history directory holding runs from two platforms for the same
        query_id is NOT one interleaved sequence -- each platform has its own
        independent plan lineage, and naively alternating between them would
        report 100% transitions regardless of either platform's actual
        stability (qpc-08 / F3.4-partial). Flapping is reported if any single
        platform's own sequence flaps.

        Args:
            query_id: Query identifier
            window_size: Number of recent runs to analyze (per platform)
            transition_threshold: Fraction of transitions that indicates flapping

        Returns:
            True if plan flapping is detected for any platform
        """
        history = self.query_plan_history(query_id)
        if not history:
            return False

        by_platform: dict[str, list[PlanHistoryEntry]] = {}
        for entry in history:
            by_platform.setdefault(entry.platform, []).append(entry)

        return any(
            self._series_is_flapping(entries[-window_size:], transition_threshold) for entries in by_platform.values()
        )

    @staticmethod
    def _series_is_flapping(history: list[PlanHistoryEntry], transition_threshold: float) -> bool:
        """Flapping check for a single platform's own chronological series."""
        if len(history) < 3:
            return False

        fingerprints = [h.fingerprint for h in history]
        unique_fps = set(fingerprints)

        # Need at least 2 different fingerprints to have flapping
        if len(unique_fps) < 2:
            return False

        # Count transitions (changes from one fingerprint to another). A
        # transition across a fingerprint_version boundary (e.g. a qpc-03
        # v1->v2 encoding bump) is excluded: the two strings differ by
        # encoding alone, not necessarily because the plan changed, and
        # without the full plan tree here there is no way to verify which -
        # counting it would risk a false-positive flapping report on every
        # query for one run, purely from the encoding upgrade.
        transitions = sum(
            1
            for i in range(len(fingerprints) - 1)
            if fingerprints[i] != fingerprints[i + 1]
            and history[i].fingerprint_version == history[i + 1].fingerprint_version
        )

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
        current_fp_version: int | None = None

        for entry in history:
            # A fingerprint_version change from the previous entry means the
            # two strings aren't comparable (qpc-03 anti-pattern) - never
            # treat that boundary alone as a plan change/version bump. Still
            # adopt the new entry as the comparison baseline (current_fp/
            # current_fp_version) so later same-version entries compare
            # correctly against it.
            version_boundary = current_fp_version is not None and entry.fingerprint_version != current_fp_version
            if entry.fingerprint != current_fp and not version_boundary:
                current_version += 1
            current_fp = entry.fingerprint
            current_fp_version = entry.fingerprint_version
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
