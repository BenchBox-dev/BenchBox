"""Replicated-IMDB scale-up prototype (deferred direction, measurement baseline).

Offset-replicates the canonical IMDb-2013 tables by an integer scale factor:
replica ``r`` (1-based) copies every row with primary and foreign keys
shifted by ``r * key_space`` where ``key_space`` exceeds the canonical max
key per table. Predicate (non-key) values are preserved verbatim, so
per-predicate selectivity is scale-invariant by construction — this is a
measurement baseline for scale-stress infrastructure, not a model of a
larger IMDb.

Derived identity is explicit: ``replicated_imdb``, never ``canonical_imdb``.
Module separation from ``benchbox.core.joinorder`` enforces the
canonical/derived boundary at the file-system level.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

DERIVED_IDENTITY = "replicated_imdb"
SOURCE_IDENTITY = "canonical_imdb"

# Integer key columns shifted per replica. (table, column) pairs cover the
# primary keys and the foreign keys that reference them.
KEY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("aka_name", "id"),
    ("aka_name", "person_id"),
    ("aka_title", "id"),
    ("aka_title", "movie_id"),
    ("aka_title", "kind_id"),
    ("aka_title", "episode_of_id"),
    ("cast_info", "id"),
    ("cast_info", "person_id"),
    ("cast_info", "movie_id"),
    ("cast_info", "person_role_id"),
    ("cast_info", "role_id"),
    ("char_name", "id"),
    ("company_name", "id"),
    ("company_type", "id"),
    ("comp_cast_type", "id"),
    ("complete_cast", "id"),
    ("complete_cast", "movie_id"),
    ("complete_cast", "subject_id"),
    ("complete_cast", "status_id"),
    ("info_type", "id"),
    ("keyword", "id"),
    ("kind_type", "id"),
    ("link_type", "id"),
    ("movie_companies", "id"),
    ("movie_companies", "movie_id"),
    ("movie_companies", "company_id"),
    ("movie_companies", "company_type_id"),
    ("movie_info", "id"),
    ("movie_info", "movie_id"),
    ("movie_info", "info_type_id"),
    ("movie_info_idx", "id"),
    ("movie_info_idx", "movie_id"),
    ("movie_info_idx", "info_type_id"),
    ("movie_keyword", "id"),
    ("movie_keyword", "movie_id"),
    ("movie_keyword", "keyword_id"),
    ("movie_link", "id"),
    ("movie_link", "movie_id"),
    ("movie_link", "linked_movie_id"),
    ("movie_link", "link_type_id"),
    ("name", "id"),
    ("person_info", "id"),
    ("person_info", "person_id"),
    ("person_info", "info_type_id"),
    ("role_type", "id"),
    ("title", "id"),
    ("title", "kind_id"),
    ("title", "episode_of_id"),
)


@dataclass
class ReplicatedManifest:
    """Provenance for one replicated archive."""

    scale_factor: int
    key_space_per_table: dict[str, int] = field(default_factory=dict)
    source_archive_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "derived_identity": DERIVED_IDENTITY,
            "source_identity": SOURCE_IDENTITY,
            "scale_factor": self.scale_factor,
            "key_space_per_table": self.key_space_per_table,
            "source_archive_hash": self.source_archive_hash,
        }


def validate_scale_factor(scale_factor: int) -> int:
    """Only integer factors >= 1; 1 is the canonical identity replica."""
    if not isinstance(scale_factor, int) or isinstance(scale_factor, bool) or scale_factor < 1:
        raise ValueError(f"replicated scale_factor must be an integer >= 1, got {scale_factor!r}")
    return scale_factor


def replica_offset(replica: int, key_space: int) -> int:
    """Key offset for replica ``r`` (0-based canonical replica has offset 0)."""
    if replica < 0:
        raise ValueError(f"replica must be >= 0, got {replica}")
    if key_space <= 0:
        raise ValueError(f"key_space must be > 0, got {key_space}")
    return replica * key_space


def shifted_key(value: int | None, *, replica: int, key_space: int) -> int | None:
    """Shift one key value into a replica's key space; NULLs pass through."""
    if value is None:
        return None
    return int(value) + replica_offset(replica, key_space)


def manifest_hash(manifest: ReplicatedManifest) -> str:
    """Content hash of the replication manifest for oracle binding."""
    body = json.dumps(manifest.to_dict(), sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def expected_row_count(canonical_rows: int, scale_factor: int) -> int:
    """Replication scales every table's row count by exactly the factor."""
    return canonical_rows * validate_scale_factor(scale_factor)
