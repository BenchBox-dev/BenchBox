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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomllib

from .errors import ManifestValidationError

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
    """Compute the pinned manifest hash with `manifest_hash` itself excluded."""
    return hashlib.sha256(_manifest_hash_input(Path(path).read_bytes())).hexdigest()


@dataclass(frozen=True)
class TableEntry:
    """One [[tables]] block from data_manifest.toml."""

    name: str
    file: str
    sha256: str
    row_count: int


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

    expected_manifest_hash = str(raw["manifest_hash"])
    actual_manifest_hash = hashlib.sha256(_manifest_hash_input(raw_bytes)).hexdigest()
    if expected_manifest_hash != actual_manifest_hash:
        raise ManifestValidationError(
            f"manifest_hash mismatch for {p}: expected {expected_manifest_hash}, got {actual_manifest_hash}"
        )

    tables_raw = raw.get("tables", [])
    if not isinstance(tables_raw, list):
        raise ManifestValidationError(f"manifest at {p}: `tables` must be an array of tables")
    tables: list[TableEntry] = []
    for i, t in enumerate(tables_raw):
        if not isinstance(t, dict):
            raise ManifestValidationError(f"manifest at {p}: tables[{i}] is not a table")
        try:
            entry = TableEntry(
                name=str(t["name"]),
                file=str(t["file"]),
                sha256=str(t["sha256"]),
                row_count=int(t["row_count"]),
            )
        except KeyError as exc:
            raise ManifestValidationError(f"manifest at {p}: tables[{i}] missing field {exc.args[0]!r}") from exc
        tables.append(entry)

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
