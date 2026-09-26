"""Replicated-IMDB scale-up prototype (deferred direction, measurement baseline).

Offset-replicates the canonical IMDb-2013 tables by an integer scale factor:
replica ``r`` (1-based) copies every replicated-table row with primary and
foreign keys shifted by ``r * key_space`` where ``key_space`` exceeds the
canonical max key per table. Predicate (non-key) values are preserved
verbatim, so per-predicate selectivity is scale-invariant by construction —
this is a measurement baseline for scale-stress infrastructure, not a model
of a larger IMDb.

Small lookup tables (``LOOKUP_TABLES``) stay single-copy: every replica
references their unchanged IDs, per the scale-stress framework's scale
semantics (``_project/decisions/joinorder-scale-stress-decision-2026-06-30.md``,
"Scale semantics"). Lookup foreign keys (``LOOKUP_FK_COLUMNS``) are never
shifted.

Deferral: the Track-2 scaling direction
(``_project/decisions/joinorder-track2-scaling-direction-2026-07-04.md``)
defers ``replicated_imdb`` until a future decision re-approves an upward
axis. This prototype is measurement-only scaffolding (offset math, identity,
oracle scaling invariants); it performs no replication, ships no derived
archive, and stays unwired from benchmark registration until that gate is
satisfied. ``REQUIRES_REAPPROVAL`` is the machine-checkable form of that
gate: it must remain ``True`` in any commit that does not cite the
re-approving decision note.

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

# Deferral gate: True until a future decision note re-approves an upward
# scaling axis (see module docstring). Generators and benchmark registration
# must refuse to consume this prototype while the gate is set.
REQUIRES_REAPPROVAL = True

# Lookup tables stay single-copy: their domain rows are referenced by FK
# from every replica and are never duplicated or key-shifted. Canonical row
# counts are 4-113 (see data_manifest.toml); the 15 fact/entity tables hold
# 30K-36M rows each and are the N x replication targets.
LOOKUP_TABLES: tuple[str, ...] = (
    "company_type",
    "comp_cast_type",
    "info_type",
    "kind_type",
    "link_type",
    "role_type",
)

# Foreign keys that reference lookup-table PKs. Values in these columns are
# canonical lookup IDs shared by every replica and must never be shifted.
# Each entry names the referencing table, the FK column, and the lookup
# table it points at (verified against benchbox/core/joinorder/schema_specs.yaml).
LOOKUP_FK_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("aka_title", "kind_id", "kind_type"),
    ("cast_info", "role_id", "role_type"),
    ("complete_cast", "subject_id", "comp_cast_type"),
    ("complete_cast", "status_id", "comp_cast_type"),
    ("movie_companies", "company_type_id", "company_type"),
    ("movie_info", "info_type_id", "info_type"),
    ("movie_info_idx", "info_type_id", "info_type"),
    ("movie_link", "link_type_id", "link_type"),
    ("person_info", "info_type_id", "info_type"),
    ("title", "kind_id", "kind_type"),
)

# Integer key columns shifted per replica. (table, column) pairs cover the
# primary keys and the foreign keys that reference replicated tables only.
# Lookup PKs/FKs are excluded by construction; see LOOKUP_TABLES and
# LOOKUP_FK_COLUMNS above. ``keyword`` is a replicated entity table (134K
# canonical rows), so ``movie_keyword.keyword_id`` shifts with its target.
KEY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("aka_name", "id"),
    ("aka_name", "person_id"),
    ("aka_title", "id"),
    ("aka_title", "movie_id"),
    ("aka_title", "episode_of_id"),
    ("cast_info", "id"),
    ("cast_info", "person_id"),
    ("cast_info", "movie_id"),
    ("cast_info", "person_role_id"),
    ("char_name", "id"),
    ("company_name", "id"),
    ("complete_cast", "id"),
    ("complete_cast", "movie_id"),
    ("movie_companies", "id"),
    ("movie_companies", "movie_id"),
    ("movie_companies", "company_id"),
    ("movie_info", "id"),
    ("movie_info", "movie_id"),
    ("movie_info_idx", "id"),
    ("movie_info_idx", "movie_id"),
    ("movie_keyword", "id"),
    ("movie_keyword", "movie_id"),
    ("movie_keyword", "keyword_id"),
    ("movie_link", "id"),
    ("movie_link", "movie_id"),
    ("movie_link", "linked_movie_id"),
    ("name", "id"),
    ("person_info", "id"),
    ("person_info", "person_id"),
    ("title", "id"),
    ("title", "episode_of_id"),
    ("keyword", "id"),
)

# Replicated entity/fact tables: every table not in LOOKUP_TABLES. Each is
# replicated N x with shifted keys; lookup tables stay single-copy.
REPLICATED_TABLES: tuple[str, ...] = (
    "aka_name",
    "aka_title",
    "cast_info",
    "char_name",
    "company_name",
    "complete_cast",
    "keyword",
    "movie_companies",
    "movie_info",
    "movie_info_idx",
    "movie_keyword",
    "movie_link",
    "name",
    "person_info",
    "title",
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
    """Replication scales a replicated table's row count by exactly the factor."""
    return canonical_rows * validate_scale_factor(scale_factor)


def expected_table_row_count(table: str, canonical_rows: int, scale_factor: int) -> int:
    """Row count for one table at a scale factor.

    Replicated tables scale N x; lookup tables stay single-copy at their
    canonical count so every replica references the same lookup IDs.
    """
    validate_scale_factor(scale_factor)
    if table in LOOKUP_TABLES:
        return canonical_rows
    return canonical_rows * scale_factor
