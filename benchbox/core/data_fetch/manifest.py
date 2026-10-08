from __future__ import annotations

import hashlib
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ManifestValidationError
from .logical_hash import LOGICAL_CONTENT_VERSION, update_sized_hash_part

_REQUIRED_TOP_KEYS = (
    "dataset_version",
    "manifest_hash",
    "data_archive_hash",
    "url",
    "archive_sha256",
    "license_file",
)


def _manifest_hash_input(raw: bytes) -> bytes:
    excluded_top_level_keys = {b"archive_sha256", b"manifest_hash"}
    lines: list[bytes] = []
    in_top_level = True
    for line in raw.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith(b"["):
            in_top_level = False
        if in_top_level:
            before_equals = stripped.split(b"=", 1)[0].strip()
            if before_equals in excluded_top_level_keys:
                continue
        lines.append(line)
    return b"".join(lines)


def compute_manifest_hash(path: str | Path) -> str:
    return hashlib.sha256(_manifest_hash_input(Path(path).read_bytes())).hexdigest()


@dataclass(frozen=True)
class TableEntry:
    name: str
    file: str
    sha256: str
    row_count: int
    logical_sha256: str | None = None
    schema: dict[str, str] = field(default_factory=dict)


def compute_manifest_identity_hash(
    *,
    dataset_version: str,
    data_archive_hash: str,
    url: str,
    license_file: str,
    tables: Sequence[TableEntry],
) -> str:
    hasher = hashlib.sha256()
    update_sized_hash_part(hasher, "V", LOGICAL_CONTENT_VERSION.encode("ascii"))
    update_sized_hash_part(hasher, "dsv", dataset_version.encode("utf-8"))
    update_sized_hash_part(hasher, "dah", data_archive_hash.encode("utf-8"))
    update_sized_hash_part(hasher, "url", url.encode("utf-8"))
    update_sized_hash_part(hasher, "lic", license_file.encode("utf-8"))
    for entry in sorted(tables, key=lambda e: e.name):
        update_sized_hash_part(hasher, "tbl", entry.name.encode("utf-8"))
        update_sized_hash_part(hasher, "file", entry.file.encode("utf-8"))
        update_sized_hash_part(hasher, "lsh", (entry.logical_sha256 or "").encode("utf-8"))
        update_sized_hash_part(hasher, "rc", str(entry.row_count).encode("ascii"))
        for column_name, column_type in entry.schema.items():
            update_sized_hash_part(hasher, "scn", column_name.encode("utf-8"))
            update_sized_hash_part(hasher, "sct", column_type.encode("utf-8"))
    return hasher.hexdigest()


@dataclass(frozen=True)
class DataManifest:
    dataset_version: str
    manifest_hash: str
    data_archive_hash: str
    url: str
    archive_sha256: str
    license_file: str
    tables: list[TableEntry]
    provenance: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None

    def table(self, name: str) -> TableEntry:
        for t in self.tables:
            if t.name == name:
                return t
        raise KeyError(f"table {name!r} not found in manifest {self.dataset_version}")

    @property
    def is_logical(self) -> bool:
        return bool(self.tables) and all(t.logical_sha256 for t in self.tables)


def load_manifest(path: str | Path) -> DataManifest:
    p = Path(path)
    if not p.is_file():
        raise ManifestValidationError(f"manifest not found at {p}")

    try:
        raw_bytes = p.read_bytes()
        raw = tomllib.loads(raw_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ManifestValidationError(f"manifest at {p} is not valid UTF-8: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ManifestValidationError(f"manifest at {p} is not valid TOML: {exc}") from exc

    missing = [k for k in _REQUIRED_TOP_KEYS if k not in raw]
    if missing:
        raise ManifestValidationError(f"manifest at {p} is missing required keys: {sorted(missing)}")

    tables_raw = raw.get("tables", [])
    if not isinstance(tables_raw, list):
        raise ManifestValidationError(f"manifest at {p}: `tables` must be an array of tables")
    tables: list[TableEntry] = []
    for i, t in enumerate(tables_raw):
        if not isinstance(t, dict):
            raise ManifestValidationError(f"manifest at {p}: tables[{i}] is not a table")
        schema_raw = t["schema"] if "schema" in t else {}
        if not isinstance(schema_raw, dict):
            raise ManifestValidationError(f"manifest at {p}: tables[{i}].schema must be a TOML table")
        logical_sha256 = t["logical_sha256"] if "logical_sha256" in t else None
        try:
            entry = TableEntry(
                name=str(t["name"]),
                file=str(t["file"]),
                sha256=str(t["sha256"]),
                row_count=int(t["row_count"]),
                logical_sha256=None if logical_sha256 is None else str(logical_sha256),
                schema={str(k): str(v) for k, v in schema_raw.items()},
            )
        except KeyError as exc:
            raise ManifestValidationError(f"manifest at {p}: tables[{i}] missing field {exc.args[0]!r}") from exc
        tables.append(entry)

    logical_flags = [t.logical_sha256 is not None for t in tables]
    if any(logical_flags) and not all(logical_flags):
        without = [t.name for t in tables if t.logical_sha256 is None]
        raise ManifestValidationError(
            f"manifest at {p}: logical_sha256 is present on some tables but missing on {sorted(without)}"
        )

    expected_manifest_hash = str(raw["manifest_hash"])
    if logical_flags and all(logical_flags):
        actual_manifest_hash = compute_manifest_identity_hash(
            dataset_version=str(raw["dataset_version"]),
            data_archive_hash=str(raw["data_archive_hash"]),
            url=str(raw["url"]),
            license_file=str(raw["license_file"]),
            tables=tables,
        )
    else:
        actual_manifest_hash = hashlib.sha256(_manifest_hash_input(raw_bytes)).hexdigest()
    if expected_manifest_hash != actual_manifest_hash:
        raise ManifestValidationError(
            f"manifest_hash mismatch for {p}: expected {expected_manifest_hash}, got {actual_manifest_hash}"
        )

    provenance = raw.get("provenance", {})
    if not isinstance(provenance, dict):
        raise ManifestValidationError(f"manifest at {p}: `provenance` must be a TOML table")

    return DataManifest(
        dataset_version=str(raw["dataset_version"]),
        manifest_hash=str(raw["manifest_hash"]),
        data_archive_hash=str(raw["data_archive_hash"]),
        url=str(raw["url"]),
        archive_sha256=str(raw["archive_sha256"]),
        license_file=str(raw["license_file"]),
        tables=tables,
        provenance=dict(provenance),
        source_path=p,
    )
