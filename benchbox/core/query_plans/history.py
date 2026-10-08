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
    run_id: str
    timestamp: str
    fingerprint: str
    estimated_cost: float | None
    execution_time_ms: float
    platform: str
    fingerprint_version: int = LEGACY_FINGERPRINT_VERSION

    def to_dict(self) -> dict[str, Any]:
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
    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, Any]] = {}

    def add_run(self, results: Any) -> None:
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

        history_entry = {
            "run_id": execution_id,
            "timestamp": timestamp,
            "platform": platform,
            "plan_fingerprints": {},
        }

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

        history_file = self.storage_path / f"{execution_id}.json"
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history_entry, f, indent=2)

        self._cache[execution_id] = history_entry

    def query_plan_history(self, query_id: str, platform: str | None = None) -> list[PlanHistoryEntry]:
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

                run_platform = entry.get("platform", "unknown")
                if platform is not None and run_platform != platform:
                    continue
                if query_id in entry.get("plan_fingerprints", {}):
                    plan_data = entry["plan_fingerprints"][query_id]
                    history.append(
                        PlanHistoryEntry(
                            run_id=entry["run_id"],
                            timestamp=entry["timestamp"],
                            fingerprint=plan_data["fingerprint"],
                            estimated_cost=plan_data.get("estimated_cost"),
                            execution_time_ms=plan_data.get("execution_time_ms", 0.0),
                            platform=run_platform,
                            fingerprint_version=plan_data.get("fingerprint_version", LEGACY_FINGERPRINT_VERSION),
                        )
                    )
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Error loading history file {entry_file}: {e}")
                continue

        history.sort(key=lambda x: _parse_history_timestamp(x.timestamp))
        return history

    def detect_plan_flapping(
        self,
        query_id: str,
        window_size: int = 10,
        transition_threshold: float = 0.3,
        platform: str | None = None,
    ) -> bool:
        history = self.query_plan_history(query_id, platform=platform)
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
        if len(history) < 3:
            return False

        fingerprints = [h.fingerprint for h in history]
        unique_fps = set(fingerprints)

        if len(unique_fps) < 2:
            return False

        transitions = sum(
            1
            for i in range(len(fingerprints) - 1)
            if fingerprints[i] != fingerprints[i + 1]
            and history[i].fingerprint_version == history[i + 1].fingerprint_version
        )

        max_transitions = len(fingerprints) - 1
        transition_rate = transitions / max_transitions if max_transitions > 0 else 0

        return transition_rate > transition_threshold

    def get_plan_version_history(self, query_id: str, platform: str | None = None) -> list[tuple[str, int]]:
        history = self.query_plan_history(query_id, platform=platform)
        versions: list[tuple[str, int]] = []

        current_version = 0
        current_fp = None
        current_fp_version: int | None = None

        for entry in history:
            version_boundary = current_fp_version is not None and entry.fingerprint_version != current_fp_version
            if entry.fingerprint != current_fp and not version_boundary:
                current_version += 1
            current_fp = entry.fingerprint
            current_fp_version = entry.fingerprint_version
            versions.append((entry.fingerprint, current_version))

        return versions

    def count_unique_plans(self, query_id: str, platform: str | None = None) -> int:
        history = self.query_plan_history(query_id, platform=platform)
        plan_of: list[int] = []
        seen: dict[tuple[str, int], int] = {}
        next_plan = 0
        for i, entry in enumerate(history):
            key = (entry.fingerprint, entry.fingerprint_version)
            if key in seen:
                plan_of.append(seen[key])
                continue
            if i > 0 and entry.fingerprint_version != history[i - 1].fingerprint_version:
                plan_id = plan_of[i - 1]
            else:
                plan_id = next_plan
                next_plan += 1
            seen[key] = plan_id
            plan_of.append(plan_id)
        return len(set(plan_of))

    def get_all_query_ids(self) -> set[str]:
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
        return len(list(self.storage_path.glob("*.json")))

    def clear(self) -> None:
        for entry_file in self.storage_path.glob("*.json"):
            entry_file.unlink()
        self._cache.clear()


def create_plan_history(storage_path: str | Path) -> PlanHistory:
    return PlanHistory(Path(storage_path))
