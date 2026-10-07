from __future__ import annotations

import fnmatch
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .policy import TIERS, ClassifierRules, Policy


@dataclass(frozen=True)
class ChangedFile:
    path: str
    previous_path: str | None
    additions: int
    deletions: int
    sha: str = ""
    status: str = ""

    @property
    def removed(self) -> bool:
        return self.status == "removed"

    @property
    def lines(self) -> int:
        return self.additions + self.deletions

    @property
    def paths(self) -> tuple[str, ...]:
        return (self.path,) if not self.previous_path else (self.path, self.previous_path)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> ChangedFile:
        return cls(
            path=str(data["filename"]),
            previous_path=data.get("previous_filename") or None,
            additions=int(data.get("additions") or 0),
            deletions=int(data.get("deletions") or 0),
            sha=str(data.get("sha") or ""),
            status=str(data.get("status") or ""),
        )


@dataclass(frozen=True)
class Classification:
    soundness: bool
    tier: str | None
    computed_tier: str | None
    reasons: tuple[str, ...]
    soundness_paths: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "soundness": self.soundness,
            "tier": self.tier,
            "computed_tier": self.computed_tier,
            "reasons": list(self.reasons),
            "soundness_paths": list(self.soundness_paths),
        }


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _area(path: str, depth: int) -> str:
    parts = path.split("/")[:-1]
    return "/".join(parts[:depth]) or "."


def _rank(tier: str) -> int:
    return TIERS.index(tier)


def label_tier(labels: Iterable[str], tier_labels: Mapping[str, str]) -> str | None:
    tiers = [tier_labels[label] for label in labels if label in tier_labels]
    return max(tiers, key=_rank) if tiers else None


def computed_tier(files: list[ChangedFile], rules: ClassifierRules) -> tuple[str, list[str]]:
    reasons: list[str] = []
    gate = sorted({path for item in files for path in item.paths if _matches(path, rules.gate_paths)})
    code = [item for item in files if not all(_matches(path, rules.data_paths) for path in item.paths)]
    logic = sorted({path for item in code for path in item.paths if _matches(path, rules.logic_paths)})
    lines = sum(item.lines for item in code)
    areas = {_area(path, rules.area_depth) for item in code for path in item.paths}
    if gate:
        reasons.append("changes the gate: " + ", ".join(gate))
    if len(areas) >= rules.large_min_areas and lines >= rules.large_min_lines:
        reasons.append(f"large multi-area diff: {lines} code lines across {len(areas)} areas")
    if reasons:
        return "very-high", reasons
    if logic:
        reasons.append("changes comparison, validation or result logic: " + ", ".join(logic))
    if lines > rules.small_max_lines:
        reasons.append(f"{lines} code lines exceed {rules.small_max_lines}")
    if len(areas) > 1:
        reasons.append(f"touches {len(areas)} areas")
    if reasons:
        return "medium-high", reasons
    return "low-medium", ["data-only or small single-area change"]


def classify(
    files: list[ChangedFile],
    labels: Iterable[str],
    policy: Policy,
    is_soundness_path: Callable[[str], bool],
) -> Classification:
    rules = policy.classifier
    in_scope = [
        item
        for item in files
        if any(is_soundness_path(path) or _matches(path, rules.gate_paths) for path in item.paths)
    ]
    if not in_scope:
        return Classification(False, None, None, ("no soundness path changed",), ())
    tier, reasons = computed_tier(in_scope, rules)
    raised = label_tier(labels, policy.tier_labels)
    final = tier
    if raised is not None and _rank(raised) > _rank(tier):
        final = raised
        reasons.append(f"label raised the tier from {tier} to {raised}")
    paths = tuple(sorted({path for item in in_scope for path in item.paths}))
    return Classification(True, final, tier, tuple(reasons), paths)
