"""Parse `data_manifest.toml` into structured records.

Schema (from _project/design/joinorder-step1-foundations.md
"Data-fetch infrastructure" section):

    dataset_version    = "joinorder-imdb-2013-v1"   # logical immutable id
    manifest_hash      = "<sha256 of this manifest file with the
                          manifest_hash and archive_sha256 fields
                          excluded — bumps on logical data or metadata
                          corrections, not transport-wrapper changes>"
    data_archive_hash  = "<aggregate sha256 over per-table Parquet file
                          hashes in deterministic table order; this
                          identifies the extracted canonical file set
                          copied into result bundles>"
    url                = "https://github.com/.../release/.../archive.tar.zst"
    archive_sha256     = "<sha256 the downloader uses to verify the
                          freshly-pulled tarball; distinct from
                          data_archive_hash because the tarball also
                          contains metadata files>"
    license_file       = "DATA-LICENSE.md"

    [[tables]]
    name      = "title"
    file      = "title.parquet"
    sha256    = "..."
    row_count = 12345

    [provenance]
    source_doi             = "10.7910/DVN/2QYZBT"
    retrieval_timestamp    = "2026-05-10T14:00:00Z"
    pg_dump_sha256         = "..."
    postgres_image         = "postgres:16.2"
    duckdb_version         = "1.0.0"
    gregrahn_commit        = "..."
    script_git_sha         = "..."

The manifest_hash is computed externally (build-pipeline) and pinned
in the file. At runtime, callers verify the manifest_hash field
matches a sha256 of the file contents with top-level `manifest_hash`
and `archive_sha256` removed from the hash input — that bootstraps
manifest tamper detection without making the hash circular with the
tarball's transport checksum.

This module only PARSES + VALIDATES the manifest; it does not fetch
or verify the data files. That's manager.py's job.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: stdlib tomllib is 3.11+
    import tomli as tomllib  # type: ignore[no-redef]

from .errors import ManifestValidationError
from .logical_hash import LOGICAL_CONTENT_VERSION, update_sized_hash_part

# Required top-level keys; missing any of these fails parse.
_REQUIRED_TOP_KEYS = (
    "dataset_version",
    "manifest_hash",
    "data_archive_hash",
    "url",
    "archive_sha256",
    "license_file",
)


def _manifest_hash_input(raw: bytes) -> bytes:
    """Return manifest bytes with top-level transport/bootstrap hashes removed."""
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
    """Compute the legacy pinned manifest hash with `manifest_hash` excluded.

    This is the byte-inclusive, text-projection hash used by manifests that do
    not carry per-table `logical_sha256` (legacy mode). Logical-mode manifests
    use `compute_manifest_identity_hash` instead.
    """
    return hashlib.sha256(_manifest_hash_input(Path(path).read_bytes())).hexdigest()


@dataclass(frozen=True)
class TableEntry:
    """One [[tables]] block from data_manifest.toml.

    `sha256` is the transport-integrity byte hash of the Parquet file (verified
    on the hot fetch path). `logical_sha256` is the reproducible row-content hash
    (present only in logical-mode manifests); `schema` maps column name ->
    PostgreSQL type in column order, and is what the logical hash is computed
    over.
    """

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
    """Compute the logical-mode manifest identity hash.

    Hashes a canonical *structured* projection — dataset version, the logical
    `data_archive_hash`, url, license, and each table's name/file/logical hash/
    row count/ordered schema — rather than the manifest's raw text. It therefore
    excludes everything that varies per rebuild (byte `sha256`, `archive_sha256`,
    `[provenance]`), so a logically-identical rebuild reproduces it exactly. The
    build script and this loader share this function so they cannot diverge.
    """
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
    """Parsed data_manifest.toml with field-level access."""

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
        """Return the named table entry; raise KeyError if missing."""
        for t in self.tables:
            if t.name == name:
                return t
        raise KeyError(f"table {name!r} not found in manifest {self.dataset_version}")

    @property
    def is_logical(self) -> bool:
        """True if this manifest pins per-table logical hashes (logical mode)."""
        return bool(self.tables) and all(t.logical_sha256 for t in self.tables)


def load_manifest(path: str | Path) -> DataManifest:
    """Parse `data_manifest.toml` at *path* and return a DataManifest.

    Raises:
        ManifestValidationError: if the file is missing required keys,
            has malformed table/provenance blocks, or cannot be parsed
            as TOML.
    """
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

    # Feature-detect the verification mode: a manifest that pins per-table
    # `logical_sha256` is a logical-mode manifest whose identity survives a
    # non-deterministic transport rebuild; older manifests fall back to the
    # byte-inclusive text hash. Mixing (some tables logical, some not) is an
    # inconsistent manifest, not a supported mode.
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
