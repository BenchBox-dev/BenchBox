"""Replicated-IMDB scale-up prototype (deferred direction, measurement baseline).

Offset-replicates the canonical IMDb-2013 tables by an integer scale factor:
replica ``r`` (1-based) copies every replicated-table row with primary and
foreign keys shifted by ``r * key_space`` where ``key_space`` exceeds the
canonical max key per table. Predicate (non-key) values are preserved
verbatim, so per-predicate selectivity is scale-invariant by construction —
this is a measurement baseline for scale-stress infrastructure, not a model
of a larger IMDb.

Foreign keys shift by the TARGET table's key space, not the referencing
table's. A ``movie_keyword.keyword_id`` value lives in ``keyword``'s key
space, so replica ``r`` adds ``r * key_space["keyword"]``; using the
referencing table's space would break the join against ``keyword.id``.
``REPLICATED_FK_TARGETS`` models every replicated FK as
``(referencing_table, column, target_table)`` and ``shifted_fk`` resolves
the offset from the target entry of ``key_space_per_table``.

Small lookup tables (``LOOKUP_TABLES``) stay single-copy: every replica
references their unchanged IDs, per the scale-stress framework's scale
semantics (``_project/decisions/joinorder-scale-stress-decision-2026-06-30.md``,
"Scale semantics"). Lookup foreign keys (``LOOKUP_FK_COLUMNS``) are never
shifted.

Key range and INT64 promotion: canonical key columns are INTEGER (INT32,
max 2,147,483,647). A shifted key is ``max_id + (scale_factor - 1) *
key_space[target]`` at most, so the largest scale factor that fits INT32 is
``min over key columns of ((INT32_MAX - max_id) // key_space[target] + 1)``
(see ``max_supported_scale_factor``). With canonical maxima near 36M and key
spaces near 40M the ceiling is on the order of 50x. Any scale factor above
the ceiling requires promoting every replicated key column to BIGINT (INT64)
BEFORE data generation: ``ALTER ... TYPE BIGINT`` or the Parquet/Arrow
equivalent, then generate replicas. ``requires_bigint_promotion`` and
``promoted_key_type`` encode that decision; the prototype itself generates
no data (see deferral below), so promotion is specified here, not executed.

Key spaces are derived from source Parquet metadata, never guessed:
``derive_key_spaces`` reads per-column maxima from the canonical Parquet
files and sets each table's space above every key value that lands in it;
``validate_key_spaces`` fails loudly (``ValueError``) on any collision risk.
``build_replicated_manifest`` wires derivation and validation into manifest
construction.

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
from pathlib import Path
from typing import Any

DERIVED_IDENTITY = "replicated_imdb"
SOURCE_IDENTITY = "canonical_imdb"

# Deferral gate: True until a future decision note re-approves an upward
# scaling axis (see module docstring). Generators and benchmark registration
# must refuse to consume this prototype while the gate is set.
REQUIRES_REAPPROVAL = True

# Signed 32-bit ceiling for the canonical INTEGER key columns. Shifted keys
# above this value require BIGINT promotion before data generation.
INT32_MAX = 2_147_483_647

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

# Replicated foreign-key targets. Each entry is
# (referencing_table, column, target_table): the shifted value of
# ``referencing_table.column`` lives in ``target_table``'s key space, so its
# replica offset comes from ``key_space_per_table[target_table]``. Verified
# against benchbox/core/joinorder/schema_specs.yaml; every non-PK entry of
# KEY_COLUMNS appears here exactly once.
REPLICATED_FK_TARGETS: tuple[tuple[str, str, str], ...] = (
    ("aka_name", "person_id", "name"),
    ("aka_title", "movie_id", "title"),
    ("aka_title", "episode_of_id", "title"),
    ("cast_info", "person_id", "name"),
    ("cast_info", "movie_id", "title"),
    ("cast_info", "person_role_id", "char_name"),
    ("complete_cast", "movie_id", "title"),
    ("movie_companies", "movie_id", "title"),
    ("movie_companies", "company_id", "company_name"),
    ("movie_info", "movie_id", "title"),
    ("movie_info_idx", "movie_id", "title"),
    ("movie_keyword", "movie_id", "title"),
    ("movie_keyword", "keyword_id", "keyword"),
    ("movie_link", "movie_id", "title"),
    ("movie_link", "linked_movie_id", "title"),
    ("person_info", "person_id", "name"),
    ("title", "episode_of_id", "title"),
)

_FK_TARGET_INDEX: dict[tuple[str, str], str] = {(t, c): target for t, c, target in REPLICATED_FK_TARGETS}

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
    """Provenance for one replicated archive.

    Provenance vocabulary (``dataset_version``, ``data_archive_hash``,
    ``source_manifest_hash``) matches the canonical manifest and oracle
    payload conventions (``benchbox/core/joinorder/benchmark.py``
    ``get_benchmark_info`` and ``_project/joinorder/reference_cardinalities.json``).
    """

    scale_factor: int
    key_space_per_table: dict[str, int] = field(default_factory=dict)
    dataset_version: str = ""
    data_archive_hash: str = ""
    source_manifest_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "derived_identity": DERIVED_IDENTITY,
            "source_identity": SOURCE_IDENTITY,
            "scale_factor": self.scale_factor,
            "key_space_per_table": self.key_space_per_table,
            "dataset_version": self.dataset_version,
            "data_archive_hash": self.data_archive_hash,
            "source_manifest_hash": self.source_manifest_hash,
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


def fk_target_table(referencing_table: str, column: str) -> str:
    """Return the target table of a replicated foreign-key column.

    Raises:
        ValueError: If ``(referencing_table, column)`` is not a replicated
            foreign key (primary keys and lookup FKs have no target here).
    """
    try:
        return _FK_TARGET_INDEX[(referencing_table, column)]
    except KeyError:
        raise ValueError(f"no replicated FK target for {referencing_table}.{column}") from None


def shifted_pk(
    value: int | None,
    *,
    replica: int,
    key_space_per_table: dict[str, int],
    table: str,
) -> int | None:
    """Shift a primary-key value using its own table's key space."""
    if value is None:
        return None
    try:
        key_space = key_space_per_table[table]
    except KeyError:
        raise ValueError(f"no key_space for table {table!r}") from None
    return int(value) + replica_offset(replica, key_space)


def shifted_fk(
    value: int | None,
    *,
    replica: int,
    key_space_per_table: dict[str, int],
    referencing_table: str,
    column: str,
) -> int | None:
    """Shift a foreign-key value using the TARGET table's key space.

    The shifted FK must land in the same space as the shifted target PK it
    references; using the referencing table's space would break the join
    whenever per-table spaces differ.
    """
    if value is None:
        return None
    target = fk_target_table(referencing_table, column)
    try:
        key_space = key_space_per_table[target]
    except KeyError:
        raise ValueError(f"no key_space for FK target table {target!r}") from None
    return int(value) + replica_offset(replica, key_space)


def _key_space_owner(table: str, column: str) -> str:
    """Return the table whose key space governs ``table.column``."""
    if column == "id":
        return table
    return fk_target_table(table, column)


def parquet_column_max(parquet_path: Path, column: str) -> int:
    """Return ``max(column)`` over a source Parquet file.

    Prefers row-group statistics from the Parquet metadata (no full scan);
    falls back to a column read when statistics are absent. NULL-only
    columns report 0. Raises loudly on missing files or columns so a
    collision risk can never pass silently.
    """
    import pyarrow.parquet as pq

    parquet_path = Path(parquet_path)
    if not parquet_path.exists():
        raise FileNotFoundError(f"source Parquet file not found: {parquet_path}")
    parquet_file = pq.ParquetFile(parquet_path)
    if column not in parquet_file.schema.names:
        raise ValueError(f"column {column!r} not in {parquet_path.name}")
    column_index = parquet_file.schema.names.index(column)
    maxima: list[int] = []
    for group in range(parquet_file.metadata.num_row_groups):
        statistics = parquet_file.metadata.row_group(group).column(column_index).statistics
        if statistics is not None and statistics.has_min_max:
            maxima.append(int(statistics.max))
    if maxima:
        return max(maxima)
    values = parquet_file.read(columns=[column]).column(column).to_pylist()
    present = [int(v) for v in values if v is not None]
    return max(present) if present else 0


def collect_key_maxima(data_dir: Path) -> dict[tuple[str, str], int]:
    """Collect ``max(column)`` for every ``KEY_COLUMNS`` entry from Parquet metadata.

    Args:
        data_dir: Directory holding one ``<table>.parquet`` file per table.

    Raises:
        FileNotFoundError: If any table's Parquet file is missing.
        ValueError: If any key column is missing from its file.
    """
    data_dir = Path(data_dir)
    return {pair: parquet_column_max(data_dir / f"{pair[0]}.parquet", pair[1]) for pair in KEY_COLUMNS}


def validate_key_spaces(
    key_space_per_table: dict[str, int],
    key_maxima: dict[tuple[str, str], int],
) -> dict[str, int]:
    """Validate that every key space strictly exceeds the max key landing in it.

    Each PK is governed by its own table's space; each replicated FK is
    governed by its TARGET table's space. Raises ``ValueError`` on any
    missing space, non-positive space, or collision risk
    (``key_space <= max_key``), which would let two replicas share a key.
    """
    for (table, column), maximum in key_maxima.items():
        owner = _key_space_owner(table, column)
        if owner not in key_space_per_table:
            raise ValueError(f"no key_space for table {owner!r} (governs {table}.{column})")
        space = key_space_per_table[owner]
        if space <= 0:
            raise ValueError(f"key_space for {owner!r} must be > 0, got {space}")
        if space <= maximum:
            raise ValueError(
                f"key_space {space} for {owner!r} does not exceed max key {maximum} "
                f"(governs {table}.{column}): replicas would collide"
            )
    return key_space_per_table


def derive_key_spaces(data_dir: Path) -> dict[str, int]:
    """Derive a collision-free ``key_space_per_table`` from source Parquet metadata.

    Each table's space is ``max + 1`` over every key value that lands in it:
    its own PK maxima plus the maxima of all replicated FKs targeting it.
    """
    key_maxima = collect_key_maxima(data_dir)
    spaces: dict[str, int] = {}
    for table in REPLICATED_TABLES:
        landing = [
            maximum
            for (owner_table, column), maximum in key_maxima.items()
            if _key_space_owner(owner_table, column) == table
        ]
        spaces[table] = max(landing) + 1 if landing else 1
    return validate_key_spaces(spaces, key_maxima)


def build_replicated_manifest(
    scale_factor: int,
    data_dir: Path,
    *,
    dataset_version: str = "",
    data_archive_hash: str = "",
    source_manifest_hash: str = "",
) -> ReplicatedManifest:
    """Build a manifest with key spaces derived and validated from source Parquet files."""
    validate_scale_factor(scale_factor)
    return ReplicatedManifest(
        scale_factor=scale_factor,
        key_space_per_table=derive_key_spaces(data_dir),
        dataset_version=dataset_version,
        data_archive_hash=data_archive_hash,
        source_manifest_hash=source_manifest_hash,
    )


def max_supported_scale_factor(
    key_space_per_table: dict[str, int],
    key_maxima: dict[tuple[str, str], int],
) -> int:
    """Largest scale factor whose shifted keys still fit signed INT32.

    The largest value landing in a space is ``max_id + (scale - 1) * space``;
    the ceiling is the minimum over key columns of
    ``(INT32_MAX - max_id) // space + 1``.
    """
    validate_key_spaces(key_space_per_table, key_maxima)
    return min(
        (INT32_MAX - maximum) // key_space_per_table[_key_space_owner(table, column)] + 1
        for (table, column), maximum in key_maxima.items()
    )


def requires_bigint_promotion(
    scale_factor: int,
    key_space_per_table: dict[str, int],
    key_maxima: dict[tuple[str, str], int],
) -> bool:
    """Whether ``scale_factor`` overflows INT32 and needs BIGINT key columns."""
    return validate_scale_factor(scale_factor) > max_supported_scale_factor(key_space_per_table, key_maxima)


def promoted_key_type(
    scale_factor: int,
    key_space_per_table: dict[str, int],
    key_maxima: dict[tuple[str, str], int],
) -> str:
    """SQL key-column type required BEFORE generating replicas: ``INTEGER`` or ``BIGINT``."""
    return "BIGINT" if requires_bigint_promotion(scale_factor, key_space_per_table, key_maxima) else "INTEGER"


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

    Raises:
        ValueError: If ``table`` is neither a replicated nor a lookup table.
    """
    validate_scale_factor(scale_factor)
    if table in LOOKUP_TABLES:
        return canonical_rows
    if table in REPLICATED_TABLES:
        return canonical_rows * scale_factor
    raise ValueError(f"unknown joinorder table {table!r}: not in REPLICATED_TABLES or LOOKUP_TABLES")
