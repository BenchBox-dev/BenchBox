from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DERIVED_IDENTITY = "replicated_imdb"
SOURCE_IDENTITY = "canonical_imdb"

REQUIRES_REAPPROVAL = True

INT32_MAX = 2_147_483_647

LOOKUP_TABLES: tuple[str, ...] = (
    "company_type",
    "comp_cast_type",
    "info_type",
    "kind_type",
    "link_type",
    "role_type",
)

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
    if not isinstance(scale_factor, int) or isinstance(scale_factor, bool) or scale_factor < 1:
        raise ValueError(f"replicated scale_factor must be an integer >= 1, got {scale_factor!r}")
    return scale_factor


def replica_offset(replica: int, key_space: int) -> int:
    if replica < 0:
        raise ValueError(f"replica must be >= 0, got {replica}")
    if key_space <= 0:
        raise ValueError(f"key_space must be > 0, got {key_space}")
    return replica * key_space


def shifted_key(value: int | None, *, replica: int, key_space: int) -> int | None:
    if value is None:
        return None
    return int(value) + replica_offset(replica, key_space)


def fk_target_table(referencing_table: str, column: str) -> str:
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
    if value is None:
        return None
    target = fk_target_table(referencing_table, column)
    try:
        key_space = key_space_per_table[target]
    except KeyError:
        raise ValueError(f"no key_space for FK target table {target!r}") from None
    return int(value) + replica_offset(replica, key_space)


def _key_space_owner(table: str, column: str) -> str:
    if column == "id":
        return table
    return fk_target_table(table, column)


def parquet_column_max(parquet_path: Path, column: str) -> int:
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
    data_dir = Path(data_dir)
    return {pair: parquet_column_max(data_dir / f"{pair[0]}.parquet", pair[1]) for pair in KEY_COLUMNS}


def validate_key_spaces(
    key_space_per_table: dict[str, int],
    key_maxima: dict[tuple[str, str], int],
) -> dict[str, int]:
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
    return validate_scale_factor(scale_factor) > max_supported_scale_factor(key_space_per_table, key_maxima)


def promoted_key_type(
    scale_factor: int,
    key_space_per_table: dict[str, int],
    key_maxima: dict[tuple[str, str], int],
) -> str:
    return "BIGINT" if requires_bigint_promotion(scale_factor, key_space_per_table, key_maxima) else "INTEGER"


def manifest_hash(manifest: ReplicatedManifest) -> str:
    body = json.dumps(manifest.to_dict(), sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def expected_row_count(canonical_rows: int, scale_factor: int) -> int:
    return canonical_rows * validate_scale_factor(scale_factor)


def expected_table_row_count(table: str, canonical_rows: int, scale_factor: int) -> int:
    validate_scale_factor(scale_factor)
    if table in LOOKUP_TABLES:
        return canonical_rows
    if table in REPLICATED_TABLES:
        return canonical_rows * scale_factor
    raise ValueError(f"unknown joinorder table {table!r}: not in REPLICATED_TABLES or LOOKUP_TABLES")
