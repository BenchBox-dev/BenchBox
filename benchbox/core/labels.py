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
    candidates = {details[idx].platform + "".join(sfx) for idx, sfx in zip(indices, suffixes)}
    if len(candidates) == len(indices):
        for j, idx in enumerate(indices):
            labels[idx] = details[idx].platform + "".join(suffixes[j])
        return True
    return False


def disambiguate_platform_labels(details: Sequence[_DisambiguatableResult]) -> list[str]:
    labels = [d.platform for d in details]

    groups: dict[str, list[int]] = {}
    for i, d in enumerate(details):
        groups.setdefault(d.platform_id, []).append(i)

    for indices in groups.values():
        if len(indices) < 2:
            continue

        suffixes: list[list[str]] = [[] for _ in indices]

        versions = [details[idx].driver_version for idx in indices]
        if len(set(versions)) > 1:
            for j, idx in enumerate(indices):
                v = details[idx].driver_version
                if v:
                    suffixes[j].append(f" v{v}")
        if _apply_group_suffixes(details, labels, indices, suffixes):
            continue

        modes = [details[idx].execution_mode for idx in indices]
        if len(set(modes)) > 1:
            for j, idx in enumerate(indices):
                m = details[idx].execution_mode
                if m:
                    suffixes[j].append(f" ({_MODE_ABBREV.get(m, m)})")
        if _apply_group_suffixes(details, labels, indices, suffixes):
            continue

        sfs = [details[idx].scale_factor for idx in indices]
        if len(set(sfs)) > 1:
            for j, idx in enumerate(indices):
                suffixes[j].append(f" SF{details[idx].scale_factor:g}")
        if _apply_group_suffixes(details, labels, indices, suffixes):
            continue

        for j, idx in enumerate(indices):
            suffixes[j].append(f" {details[idx].run_date}")
        _apply_group_suffixes(details, labels, indices, suffixes)

    return labels
