"""Shared platform-label disambiguation for both the explorer pipeline and CLI visualization."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

_MODE_ABBREV: dict[str, str] = {
    "dataframe": "df",
    "sql": "sql",
    "datagen": "datagen",
    "data_only": "data_only",
}


class _DisambiguatableResult(Protocol):
    """Structural type consumed by disambiguate_platform_labels."""

    platform: str
    platform_id: str
    driver_version: str | None
    execution_mode: str | None
    scale_factor: float
    run_date: str


def _apply_group_suffixes(
    details: Sequence[_DisambiguatableResult],
    labels: list[str],
    indices: list[int],
    suffixes: list[list[str]],
) -> bool:
    """Commit accumulated suffixes to *labels* if they make the group unique.

    Returns True when labels are now unique (caller stops); False when collisions remain.
    """
    candidates = {details[idx].platform + "".join(sfx) for idx, sfx in zip(indices, suffixes)}
    if len(candidates) == len(indices):
        for j, idx in enumerate(indices):
            labels[idx] = details[idx].platform + "".join(suffixes[j])
        return True
    return False


def disambiguate_platform_labels(details: Sequence[_DisambiguatableResult]) -> list[str]:
    """Build unique human-readable display labels for a list of results.

    Each result gets a label equal to its ``platform`` name, with disambiguating
    suffixes appended only when two or more results share the same ``platform_id``:

    1. driver_version  → "DuckDB v1.2.0"
    2. execution_mode  → "DuckDB (sql)" / "DuckDB (df)"
    3. scale_factor    → "DuckDB SF1.0"
    4. run_date        → "DuckDB 2026-01-15"

    Suffixes accumulate progressively until all labels in a collision group are
    unique.  Groups with only one result keep the bare platform name.
    """
    labels = [d.platform for d in details]

    groups: dict[str, list[int]] = {}
    for i, d in enumerate(details):
        groups.setdefault(d.platform_id, []).append(i)

    for indices in groups.values():
        if len(indices) < 2:
            continue

        suffixes: list[list[str]] = [[] for _ in indices]

        # 1. driver_version
        versions = [details[idx].driver_version for idx in indices]
        if len(set(versions)) > 1:
            for j, idx in enumerate(indices):
                v = details[idx].driver_version
                if v:
                    suffixes[j].append(f" v{v}")
        if _apply_group_suffixes(details, labels, indices, suffixes):
            continue

        # 2. execution_mode
        modes = [details[idx].execution_mode for idx in indices]
        if len(set(modes)) > 1:
            for j, idx in enumerate(indices):
                m = details[idx].execution_mode
                if m:
                    suffixes[j].append(f" ({_MODE_ABBREV.get(m, m)})")
        if _apply_group_suffixes(details, labels, indices, suffixes):
            continue

        # 3. scale_factor
        sfs = [details[idx].scale_factor for idx in indices]
        if len(set(sfs)) > 1:
            for j, idx in enumerate(indices):
                suffixes[j].append(f" SF{details[idx].scale_factor:g}")
        if _apply_group_suffixes(details, labels, indices, suffixes):
            continue

        # 4. run_date (last resort - always produces unique labels)
        for j, idx in enumerate(indices):
            suffixes[j].append(f" {details[idx].run_date}")
        _apply_group_suffixes(details, labels, indices, suffixes)

    return labels
