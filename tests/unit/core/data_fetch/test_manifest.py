"""Tests for benchbox.core.data_fetch.manifest.

Exercises every required-field check, malformed-TOML handling, and the
TableEntry/provenance round-trip — all against TOML strings written to
tmp files; no fixture artifacts checked into the repo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchbox.core.data_fetch import (
    DataManifest,
    ManifestValidationError,
    compute_manifest_hash,
    load_manifest,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


_HEX_B = "b" * 64
_HEX_C = "c" * 64
_HEX_D = "d" * 64
_HASH_PLACEHOLDER = "0" * 64

_MINIMAL = f"""\
dataset_version    = "test-v1"
manifest_hash      = "{_HASH_PLACEHOLDER}"
data_archive_hash  = "{_HEX_B}"
url                = "https://example.com/test.tar.zst"
archive_sha256     = "{_HEX_C}"
license_file       = "DATA-LICENSE.md"

[[tables]]
name      = "t1"
file      = "t1.parquet"
sha256    = "33"
row_count = 100

[[tables]]
name      = "t2"
file      = "t2.parquet"
sha256    = "44"
row_count = 200

[provenance]
source_doi          = "10.7910/DVN/2QYZBT"
retrieval_timestamp = "2026-05-10T14:00:00Z"
"""


def _write(tmp: Path, body: str) -> Path:
    p = tmp / "data_manifest.toml"
    p.write_text(body)
    manifest_hash = compute_manifest_hash(p)
    p.write_text(body.replace(_HASH_PLACEHOLDER, manifest_hash))
    return p


def test_load_minimal_manifest(tmp_path: Path) -> None:
    p = _write(tmp_path, _MINIMAL)
    m = load_manifest(p)
    assert isinstance(m, DataManifest)
    assert m.dataset_version == "test-v1"
    assert m.manifest_hash == compute_manifest_hash(p)
    assert len(m.tables) == 2
    assert m.tables[0].name == "t1"
    assert m.tables[1].row_count == 200
    assert m.provenance["source_doi"] == "10.7910/DVN/2QYZBT"


def test_table_lookup_by_name(tmp_path: Path) -> None:
    p = _write(tmp_path, _MINIMAL)
    m = load_manifest(p)
    assert m.table("t2").file == "t2.parquet"
    with pytest.raises(KeyError):
        m.table("nope")


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ManifestValidationError, match="not found"):
        load_manifest(tmp_path / "does-not-exist.toml")


def test_malformed_toml_raises(tmp_path: Path) -> None:
    p = tmp_path / "data_manifest.toml"
    p.write_text("not valid toml = = =\n")
    with pytest.raises(ManifestValidationError, match="not valid TOML"):
        load_manifest(p)


def test_missing_required_top_key_raises(tmp_path: Path) -> None:
    body = _MINIMAL.replace('dataset_version    = "test-v1"\n', "")
    p = _write(tmp_path, body)
    with pytest.raises(ManifestValidationError, match="missing required keys"):
        load_manifest(p)


def test_manifest_hash_mismatch_raises(tmp_path: Path) -> None:
    p = _write(tmp_path, _MINIMAL)
    p.write_text(
        p.read_text().replace(
            'url                = "https://example.com/test.tar.zst"',
            'url = "https://evil.test/archive.tar.zst"',
        )
    )
    with pytest.raises(ManifestValidationError, match="manifest_hash mismatch"):
        load_manifest(p)


def test_manifest_hash_ignores_archive_sha256_transport_checksum(tmp_path: Path) -> None:
    p = _write(tmp_path, _MINIMAL)
    original_hash = compute_manifest_hash(p)
    p.write_text(p.read_text().replace(f'archive_sha256     = "{_HEX_C}"', f'archive_sha256     = "{_HEX_D}"'))

    assert compute_manifest_hash(p) == original_hash
    assert load_manifest(p).archive_sha256 == _HEX_D


def test_manifest_hash_normalizes_line_endings(tmp_path: Path) -> None:
    p = _write(tmp_path, _MINIMAL)
    original_body = p.read_text()
    original_hash = compute_manifest_hash(p)

    p.write_bytes(original_body.replace("\n", "\r\n").encode("utf-8"))

    assert compute_manifest_hash(p) == original_hash
    assert load_manifest(p).manifest_hash == original_hash


def test_missing_table_field_raises(tmp_path: Path) -> None:
    bad = _MINIMAL.replace('file      = "t1.parquet"\n', "")
    p = _write(tmp_path, bad)
    with pytest.raises(ManifestValidationError, match="missing field"):
        load_manifest(p)


def test_tables_must_be_array(tmp_path: Path) -> None:
    body = (
        f'dataset_version="x"\nmanifest_hash="{_HASH_PLACEHOLDER}"\n'
        'data_archive_hash="x"\nurl="x"\n'
        'archive_sha256="x"\nlicense_file="x"\ntables = "this should be a list"\n'
    )
    p = _write(tmp_path, body)
    with pytest.raises(ManifestValidationError, match="must be an array"):
        load_manifest(p)
