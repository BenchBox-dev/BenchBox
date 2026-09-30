"""Sampled-from-real JOB scaling (Track-2, Option B).

Title-stratified downsampling of the canonical IMDb-2013 archive with
referential-integrity preservation. The sampler keeps a deterministic
fraction of ``title`` rows via seeded-hash stratified sampling (uniform
selection within each ``(kind_id, production_year)`` stratum, ranked by
``sha256(seed, stratum, title_id)``), closes the retained set
transitively over episode parents merged from both ``title.episode_of_id``
and ``aka_title.episode_of_id``, and then keeps dependent rows: every row
in a title-referencing table whose ``movie_id`` survives, every
``movie_link`` row whose ``movie_id`` and ``linked_movie_id`` both survive,
the person rows referenced by the surviving cast (``name`` carried
verbatim, ``aka_name``/``person_info`` filtered to surviving persons),
plus small dimension tables carried verbatim.

Derived identity is explicit: output archives are labeled
``joinorder_sampled``, never ``canonical_imdb``. Scale-factor semantics:
``scale_factor`` is the kept title fraction (1.0 = canonical). Only
fractional factors in (0, 1] are accepted; bools are rejected outright.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Collection, Container, Iterable, Mapping
from dataclasses import KW_ONLY, dataclass, field
from fractions import Fraction
from typing import Any

# Tables keyed by a single title id: a row survives when its movie_id is
# retained. movie_link has two title ends and is handled separately: a
# row survives only when both movie_id and linked_movie_id are retained,
# so neither foreign key can dangle. cast_info is the title/person bridge:
# its movie_id side is filtered here; its person_id side feeds
# surviving_person_ids() below.
TITLE_CHILD_TABLES: dict[str, tuple[str, ...]] = {
    "aka_title": ("movie_id",),
    "cast_info": ("movie_id",),
    "movie_companies": ("movie_id",),
    "movie_info": ("movie_id",),
    "movie_info_idx": ("movie_id",),
    "movie_keyword": ("movie_id",),
    "complete_cast": ("movie_id",),
}

# movie_link has two title ends: a row survives only when both movie_id
# and linked_movie_id are retained, so neither foreign key can dangle.
MOVIE_LINK_TABLE = "movie_link"
MOVIE_LINK_ENDPOINTS: tuple[str, str] = ("movie_id", "linked_movie_id")

# Person-side tables filtered to persons referenced by the surviving cast.
# The base ``name`` table is carried verbatim (see VERBATIM_TABLES), so a
# surviving cast row's person_id never dangles; these child tables close
# over the same surviving person set.
PERSON_CHILD_TABLES: dict[str, tuple[str, ...]] = {
    "aka_name": ("person_id",),
    "person_info": ("person_id",),
}

# Small dimension tables carried verbatim (no title/person key). ``name``
# is verbatim: every person referenced by surviving cast rows keeps a base
# row, while aka_name/person_info are filtered to surviving persons.
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
    """Provenance for one sampled archive."""

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
    """Express a (0, 1] scale factor as an exact kept fraction.

    The raw requested value is validated before rounding: non-finite
    values and values outside (0, 1] are rejected even when
    ``limit_denominator`` would round them back into range. A requested
    value below the supported 1/1000 resolution (whose best rational
    approximation rounds to zero) is likewise rejected. Bools are
    rejected with TypeError: ``True`` would otherwise silently mean 1.0.
    """
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
    """Normalize a title's stratification key (None marks unknown)."""
    return (kind_id, production_year)


def title_hash_rank(title_id: int, stratum: StratumKey, seed: int) -> float:
    """Uniform rank in [0, 1) for one title within its stratum.

    Ranks are decorrelated across strata and seeds: titles sharing a
    numeric id range (IMDb ids cluster by kind/era) do not share keep
    decisions, unlike the old ``id % denominator`` predicate.
    """
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
    """Seeded-hash keep predicate: keep when the title's stratum rank is below the kept fraction.

    Titles are partitioned by ``(kind_id, production_year)`` strata and
    selected uniformly within each stratum via ``title_hash_rank``. The
    ``seed`` decorrelates samples across runs; the same seed always keeps
    the same titles.
    """
    rank = title_hash_rank(title_id, stratum_key(kind_id, production_year), seed)
    return rank < float(fraction)


def sample_title_ids(
    records: Iterable[Mapping[str, int | None]],
    fraction: Fraction,
    *,
    seed: int = 0,
) -> set[int]:
    """Select an exact-quota title set with per-stratum proportionality.

    ``records`` maps each carry ``id`` plus optional ``kind_id`` /
    ``production_year`` stratum keys. The total kept count is
    ``round(fraction * N)``, apportioned across strata by largest
    remainder; within a stratum the lowest-ranked titles win, ordered by
    ``(title_hash_rank, id)`` for determinism.
    """
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
    """Merge ``episode_of_id`` maps from ``title`` and ``aka_title``.

    Both tables carry the secondary episode reference keyed by title id;
    a surviving episode's parent must be retained whichever table records
    it. The ``title`` value wins on conflict; a null on one side falls
    back to the other side.
    """
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
    """Expand a kept title set transitively over ``episode_of_id`` parents.

    A retained episode references its parent title in ``episode_of_id``,
    so the parent must be retained too, along with the parent's own
    parent for multi-level nesting. Walks parent chains until every kept
    title's ancestors are retained; cycles terminate via the visited set.
    Pass a map merged with :func:`merge_episode_parents` so parents
    recorded only in ``aka_title`` are closed over as well.
    """
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
    """Group titles into episode clusters keyed by ultimate ancestor.

    Each cluster holds a root title plus every episode that reaches it
    through transitive ``episode_of_id`` links. Parents referenced but
    absent from ``title_ids`` join their cluster so closure never dangles.
    """
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
    """Select whole episode clusters against the scale quota.

    Parent expansion is charged to the quota instead of added on top:
    titles are grouped into series clusters (root plus transitive
    episodes), the ``round(fraction * N)`` budget is apportioned across
    root strata by largest remainder, and clusters fill each stratum
    budget in hash-rank order. The retained/total ratio therefore tracks
    ``scale_factor`` up to cluster granularity instead of overshooting it.
    """
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
    """Keep a single-key dependent row when its title reference survives."""
    return all(row.get(column) is not None and row[column] in kept_title_ids for column in key_columns)


def keep_movie_link_row(
    row: Mapping[str, int | None],
    kept_title_ids: Container[int],
) -> bool:
    """Keep a movie_link row only when both title endpoints survive."""
    return all(row.get(column) is not None and row[column] in kept_title_ids for column in MOVIE_LINK_ENDPOINTS)


def surviving_person_ids(
    cast_rows: Iterable[Mapping[str, int | None]],
    kept_title_ids: Container[int],
) -> set[int]:
    """Collect persons referenced by surviving cast rows.

    ``cast_rows`` are the retained title-side ``cast_info`` rows (already
    filtered to surviving ``movie_id`` values); every non-null
    ``person_id`` they reference survives into the sampled person
    subgraph.
    """
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
    """Keep a person-side row (aka_name/person_info) when its person survives."""
    return all(row.get(column) is not None and row[column] in surviving for column in key_columns)


def manifest_hash(manifest: SampledManifest) -> str:
    """Content hash of the sampling manifest for oracle binding."""
    body = json.dumps(manifest.to_dict(), sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
