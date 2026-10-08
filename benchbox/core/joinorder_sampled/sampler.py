from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Collection, Container, Iterable, Mapping
from dataclasses import KW_ONLY, dataclass, field
from fractions import Fraction
from typing import Any

TITLE_CHILD_TABLES: dict[str, tuple[str, ...]] = {
    "aka_title": ("movie_id",),
    "cast_info": ("movie_id",),
    "movie_companies": ("movie_id",),
    "movie_info": ("movie_id",),
    "movie_info_idx": ("movie_id",),
    "movie_keyword": ("movie_id",),
    "complete_cast": ("movie_id",),
}

MOVIE_LINK_TABLE = "movie_link"
MOVIE_LINK_ENDPOINTS: tuple[str, str] = ("movie_id", "linked_movie_id")

PERSON_CHILD_TABLES: dict[str, tuple[str, ...]] = {
    "aka_name": ("person_id",),
    "person_info": ("person_id",),
}

VERBATIM_TABLES: tuple[str, ...] = (
    "char_name",
    "company_name",
    "company_type",
    "comp_cast_type",
    "info_type",
    "keyword",
    "kind_type",
    "link_type",
    "name",
    "role_type",
)

SAMPLING_MODULUS = 1000

StratumKey = tuple["int | None", "int | None"]


@dataclass
class SampledManifest:
    scale_factor: float
    kept_title_ids: int
    total_title_ids: int
    seed_note: str = (
        "seeded-hash stratified: uniform within (kind_id, production_year) strata "
        "via sha256(seed, stratum, title_id) rank"
    )
    per_table_rows: dict[str, int] = field(default_factory=dict)
    _: KW_ONLY
    seed: int = 0
    source_dataset_version: str = ""
    source_manifest_hash: str = ""
    source_data_archive_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "derived_identity": "joinorder_sampled",
            "source_identity": "canonical_imdb",
            "source_dataset_version": self.source_dataset_version,
            "source_manifest_hash": self.source_manifest_hash,
            "source_data_archive_hash": self.source_data_archive_hash,
            "scale_factor": self.scale_factor,
            "kept_title_ids": self.kept_title_ids,
            "total_title_ids": self.total_title_ids,
            "seed": self.seed,
            "seed_note": self.seed_note,
            "per_table_rows": self.per_table_rows,
        }


def scale_to_fraction(scale_factor: float | Fraction) -> Fraction:
    if isinstance(scale_factor, bool):
        raise TypeError(f"sampled scale_factor must be a number in (0, 1], got bool {scale_factor!r}")
    if isinstance(scale_factor, Fraction):
        requested = scale_factor
        if requested <= 0 or requested > 1:
            raise ValueError(f"sampled scale_factor must be in (0, 1], got {scale_factor}")
    else:
        requested_float = float(scale_factor)
        if not math.isfinite(requested_float) or requested_float <= 0 or requested_float > 1:
            raise ValueError(f"sampled scale_factor must be in (0, 1], got {scale_factor}")
        requested = Fraction(requested_float)
    if requested < Fraction(1, SAMPLING_MODULUS):
        raise ValueError(f"sampled scale_factor {scale_factor} is below the supported 1/{SAMPLING_MODULUS} resolution")
    fraction = requested.limit_denominator(SAMPLING_MODULUS)
    if fraction <= 0 or fraction > 1:
        raise ValueError(f"sampled scale_factor must be in (0, 1], got {scale_factor}")
    return fraction


def stratum_key(kind_id: int | None, production_year: int | None) -> StratumKey:
    return (kind_id, production_year)


def title_hash_rank(title_id: int, stratum: StratumKey, seed: int) -> float:
    digest = hashlib.sha256(f"{seed}\x00{stratum[0]}\x00{stratum[1]}\x00{int(title_id)}".encode()).digest()
    return int.from_bytes(digest, "big") / 2**256


def keep_title_id(
    title_id: int,
    fraction: Fraction,
    *,
    seed: int = 0,
    kind_id: int | None = None,
    production_year: int | None = None,
) -> bool:
    rank = title_hash_rank(title_id, stratum_key(kind_id, production_year), seed)
    return rank < float(fraction)


def sample_title_ids(
    records: Iterable[Mapping[str, int | None]],
    fraction: Fraction,
    *,
    seed: int = 0,
) -> set[int]:
    rows = list(records)
    total = len(rows)
    if total == 0:
        return set()
    target = min(max(int(round(float(fraction) * total)), 0), total)
    strata: dict[StratumKey, list[Mapping[str, int | None]]] = {}
    for row in rows:
        key = stratum_key(row.get("kind_id"), row.get("production_year"))
        strata.setdefault(key, []).append(row)
    quotas = {key: float(fraction) * len(members) for key, members in strata.items()}
    alloc = {key: math.floor(quota) for key, quota in quotas.items()}
    remainder = target - sum(alloc.values())
    by_fraction = sorted(quotas, key=lambda key: (quotas[key] - alloc[key], repr(key)), reverse=True)
    for key in by_fraction[: max(remainder, 0)]:
        alloc[key] += 1
    kept: set[int] = set()
    for key, members in strata.items():
        ordered = sorted(members, key=lambda row: (title_hash_rank(int(row["id"]), key, seed), int(row["id"])))
        kept.update(int(row["id"]) for row in ordered[: alloc[key]])
    return kept


def merge_episode_parents(
    title_parents: Mapping[int, int | None],
    aka_title_parents: Mapping[int, int | None],
) -> dict[int, int | None]:
    merged: dict[int, int | None] = {}
    for title_id in set(title_parents) | set(aka_title_parents):
        parent = title_parents.get(title_id)
        aka_parent = aka_title_parents.get(title_id)
        merged[title_id] = parent if parent is not None else aka_parent
    return merged


def close_title_set_over_episode_parents(
    kept_title_ids: Collection[int],
    episode_parents: Mapping[int, int | None],
) -> set[int]:
    closed = set(kept_title_ids)
    stack = list(kept_title_ids)
    while stack:
        parent_id = episode_parents.get(stack.pop())
        if parent_id is not None and parent_id not in closed:
            closed.add(parent_id)
            stack.append(parent_id)
    return closed


def _cluster_roots(
    title_ids: Collection[int],
    episode_parents: Mapping[int, int | None],
) -> dict[int, set[int]]:
    parent_of = {int(child): int(parent) for child, parent in episode_parents.items() if parent is not None}

    def root(title_id: int) -> int:
        seen: set[int] = set()
        while title_id in parent_of and title_id not in seen:
            seen.add(title_id)
            title_id = parent_of[title_id]
        return title_id

    clusters: dict[int, set[int]] = {}
    for title_id in list(title_ids) + [parent for parent in parent_of.values() if parent not in set(title_ids)]:
        clusters.setdefault(root(int(title_id)), set()).add(int(title_id))
    return clusters


def sample_title_ids_with_episode_closure(
    records: Iterable[Mapping[str, int | None]],
    episode_parents: Mapping[int, int | None],
    fraction: Fraction,
    *,
    seed: int = 0,
) -> set[int]:
    rows = list(records)
    if not rows:
        return set()
    total = len(rows)
    target = min(max(int(round(float(fraction) * total)), 0), total)
    meta = {int(row["id"]): stratum_key(row.get("kind_id"), row.get("production_year")) for row in rows}
    clusters = _cluster_roots([int(row["id"]) for row in rows], episode_parents)
    by_stratum: dict[StratumKey, list[tuple[float, int]]] = {}
    for cluster_root, members in clusters.items():
        key = meta.get(cluster_root, (None, None))
        rank = title_hash_rank(cluster_root, key, seed)
        by_stratum.setdefault(key, []).append((rank, cluster_root))
    weights = {key: sum(len(clusters[root]) for _, root in ranked) for key, ranked in by_stratum.items()}
    quotas = {key: float(fraction) * weight for key, weight in weights.items()}
    budgets = {key: math.floor(quota) for key, quota in quotas.items()}
    remainder = target - sum(budgets.values())
    by_fraction = sorted(quotas, key=lambda key: (quotas[key] - budgets[key], repr(key)), reverse=True)
    for key in by_fraction[: max(remainder, 0)]:
        budgets[key] += 1
    kept: set[int] = set()
    for key, ranked in by_stratum.items():
        budget = budgets[key]
        stratum_kept = 0
        for _, cluster_root in sorted(ranked):
            members = clusters[cluster_root]
            if stratum_kept + len(members) <= budget:
                kept.update(members)
                stratum_kept += len(members)
        if stratum_kept == 0 and budget > 0 and ranked:
            smallest = min(ranked, key=lambda item: (len(clusters[item[1]]), item[0]))[1]
            kept.update(clusters[smallest])
    return kept


def keep_title_child_row(
    row: Mapping[str, int | None],
    kept_title_ids: Container[int],
    key_columns: Iterable[str],
) -> bool:
    return all(row.get(column) is not None and row[column] in kept_title_ids for column in key_columns)


def keep_movie_link_row(
    row: Mapping[str, int | None],
    kept_title_ids: Container[int],
) -> bool:
    return all(row.get(column) is not None and row[column] in kept_title_ids for column in MOVIE_LINK_ENDPOINTS)


def surviving_person_ids(
    cast_rows: Iterable[Mapping[str, int | None]],
    kept_title_ids: Container[int],
) -> set[int]:
    persons: set[int] = set()
    for row in cast_rows:
        person_id = row.get("person_id")
        if row.get("movie_id") in kept_title_ids and person_id is not None:
            persons.add(person_id)
    return persons


def keep_person_child_row(
    row: Mapping[str, int | None],
    surviving: Container[int],
    key_columns: Iterable[str] = ("person_id",),
) -> bool:
    return all(row.get(column) is not None and row[column] in surviving for column in key_columns)


def manifest_hash(manifest: SampledManifest) -> str:
    body = json.dumps(manifest.to_dict(), sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
