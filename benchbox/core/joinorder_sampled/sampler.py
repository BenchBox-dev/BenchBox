"""Sampled-from-real JOB scaling (Track-2, Option B).

Title-stratified downsampling of the canonical IMDb-2013 archive with
referential-integrity preservation. The sampler keeps a deterministic
fraction of ``title`` rows (by ``id % denominator``), closes the retained
set over episode parents (``title.episode_of_id`` and
``aka_title.episode_of_id``), and then keeps dependent rows: every row in a
title-referencing table whose ``movie_id`` survives, every ``movie_link``
row whose ``movie_id`` and ``linked_movie_id`` both survive, plus the
person rows referenced by the surviving cast, plus dimension tables
carried verbatim.

Derived identity is explicit: output archives are labeled
``joinorder_sampled``, never ``canonical_imdb``. Scale-factor semantics:
``scale_factor`` is the kept title fraction (1.0 = canonical). Only
fractional factors in (0, 1] are accepted.
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
# so neither foreign key can dangle.
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

# Tables keyed by person id; kept rows close over persons referenced by
# the surviving cast_info / aka_name / person_info rows.
PERSON_CHILD_TABLES: dict[str, tuple[str, ...]] = {
    "aka_name": ("person_id",),
    "cast_info": ("person_id",),
    "person_info": ("person_id",),
}

# Small dimension tables carried verbatim (no title/person key).
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


@dataclass
class SampledManifest:
    """Provenance for one sampled archive."""

    scale_factor: float
    kept_title_ids: int
    total_title_ids: int
    seed_note: str = "deterministic: keep title.id where id % denominator < numerator"
    per_table_rows: dict[str, int] = field(default_factory=dict)
    _: KW_ONLY
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
            "seed_note": self.seed_note,
            "per_table_rows": self.per_table_rows,
        }


def scale_to_fraction(scale_factor: float | Fraction) -> Fraction:
    """Express a (0, 1] scale factor as an exact kept fraction.

    The raw requested value is validated before rounding: non-finite
    values and values outside (0, 1] are rejected even when
    ``limit_denominator`` would round them back into range. A requested
    value below the supported 1/1000 resolution (whose best rational
    approximation rounds to zero) is likewise rejected.
    """
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


def keep_title_id(title_id: int, fraction: Fraction) -> bool:
    """Deterministic keep predicate: first N of every M title ids."""
    numerator = fraction.numerator
    denominator = fraction.denominator
    return (int(title_id) % denominator) < numerator


def close_title_set_over_episode_parents(
    kept_title_ids: Collection[int],
    episode_parents: Mapping[int, int | None],
) -> set[int]:
    """Expand a kept title set over ``episode_of_id`` parents.

    A retained episode references the title in its ``episode_of_id``
    column (``title`` and ``aka_title`` share this secondary reference),
    so the parent must be retained too. Only non-null parents of kept
    titles are added; no transitive walk is needed because the parent is
    always a series-level title row.
    """
    closed = set(kept_title_ids)
    for title_id in kept_title_ids:
        parent_id = episode_parents.get(title_id)
        if parent_id is not None:
            closed.add(parent_id)
    return closed


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


def manifest_hash(manifest: SampledManifest) -> str:
    """Content hash of the sampling manifest for oracle binding."""
    body = json.dumps(manifest.to_dict(), sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
