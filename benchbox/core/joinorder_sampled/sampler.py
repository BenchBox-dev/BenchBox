"""Sampled-from-real JOB scaling (Track-2, Option B).

Title-stratified downsampling of the canonical IMDb-2013 archive with
referential-integrity preservation. The sampler keeps a deterministic
fraction of ``title`` rows (by ``id % denominator``) and closes over the
join subgraph: every row in a title-referencing table whose ``movie_id``
(or ``linked_movie_id``) survives, plus the person rows referenced by the
surviving cast, plus dimension tables carried verbatim.

Derived identity is explicit: output archives are labeled
``joinorder_sampled``, never ``canonical_imdb``. Scale-factor semantics:
``scale_factor`` is the kept title fraction (1.0 = canonical). Only
fractional factors in (0, 1] are accepted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

# Tables keyed by title id. movie_link has two ends; a row survives when
# either end survives so no dangling link points at a dropped title.
TITLE_CHILD_TABLES: dict[str, tuple[str, ...]] = {
    "aka_title": ("movie_id",),
    "cast_info": ("movie_id",),
    "movie_companies": ("movie_id",),
    "movie_info": ("movie_id",),
    "movie_info_idx": ("movie_id",),
    "movie_keyword": ("movie_id",),
    "movie_link": ("movie_id", "linked_movie_id"),
    "complete_cast": ("movie_id",),
}

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "derived_identity": "joinorder_sampled",
            "source_identity": "canonical_imdb",
            "scale_factor": self.scale_factor,
            "kept_title_ids": self.kept_title_ids,
            "total_title_ids": self.total_title_ids,
            "seed_note": self.seed_note,
            "per_table_rows": self.per_table_rows,
        }


def scale_to_fraction(scale_factor: float) -> Fraction:
    """Express a (0, 1] scale factor as an exact kept fraction."""
    fraction = Fraction(scale_factor).limit_denominator(SAMPLING_MODULUS)
    if fraction <= 0 or fraction > 1:
        raise ValueError(f"sampled scale_factor must be in (0, 1], got {scale_factor}")
    return fraction


def keep_title_id(title_id: int, fraction: Fraction) -> bool:
    """Deterministic keep predicate: first N of every M title ids."""
    numerator = fraction.numerator
    denominator = fraction.denominator
    return (int(title_id) % denominator) < numerator


def manifest_hash(manifest: SampledManifest) -> str:
    """Content hash of the sampling manifest for oracle binding."""
    body = json.dumps(manifest.to_dict(), sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
