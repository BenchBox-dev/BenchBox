"""Tests for benchbox.core.data_fetch.manager.

Exercises the air-gapped path (pre-populated files), the
download-then-extract path (mocked downloader + ExtractionRequiredError),
and the checksum mismatch surface.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from benchbox.core.data_fetch import (
    ChecksumMismatchError,
    ExtractionRequiredError,
    compute_manifest_hash,
    fetch_data,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ---- named payloads + pre-computed shas (N2: readable diagnostics) ----

ALPHA_PAYLOAD = b"alpha-table-row-bytes"
BETA_PAYLOAD = b"beta-table-row-bytes"

ALPHA_SHA = hashlib.sha256(ALPHA_PAYLOAD).hexdigest()
BETA_SHA = hashlib.sha256(BETA_PAYLOAD).hexdigest()
ARCHIVE_SHA = "00" * 32  # placeholder — fake_downloader doesn't recompute
MANIFEST_HASH_PLACEHOLDER = "a" * 64


def _write_manifest(tmp: Path, archive_sha: str = ARCHIVE_SHA) -> Path:
    """Build a minimal data_manifest.toml with two named tables."""
    body = (
        f'dataset_version    = "test-v1"\n'
        f'manifest_hash      = "{MANIFEST_HASH_PLACEHOLDER}"\n'
        f'data_archive_hash  = "{archive_sha}"\n'
        f'url                = "https://example.com/test.tar.zst"\n'
        f'archive_sha256     = "{archive_sha}"\n'
        f'license_file       = "DATA-LICENSE.md"\n\n'
        f"[[tables]]\n"
        f'name      = "alpha"\n'
        f'file      = "alpha.parquet"\n'
        f'sha256    = "{ALPHA_SHA}"\n'
        f"row_count = {len(ALPHA_PAYLOAD)}\n\n"
        f"[[tables]]\n"
        f'name      = "beta"\n'
        f'file      = "beta.parquet"\n'
        f'sha256    = "{BETA_SHA}"\n'
        f"row_count = {len(BETA_PAYLOAD)}\n"
    )
    p = tmp / "data_manifest.toml"
    p.write_text(body)
    manifest_hash = compute_manifest_hash(p)
    p.write_text(body.replace(MANIFEST_HASH_PLACEHOLDER, manifest_hash))
    return p


def test_air_gapped_pre_populated_returns_dir(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "alpha.parquet").write_bytes(ALPHA_PAYLOAD)
    (out_dir / "beta.parquet").write_bytes(BETA_PAYLOAD)
    manifest_path = _write_manifest(tmp_path)

    result = fetch_data("test", manifest_path, out_dir)
    assert result == out_dir


def test_pre_populated_with_bad_sha_short_circuits_before_download(tmp_path: Path) -> None:
    """Corrupt cache must surface ChecksumMismatchError WITHOUT touching
    the downloader. Otherwise the manager would re-download wastefully on
    every cache-rot event."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "alpha.parquet").write_bytes(b"corrupted contents")
    (out_dir / "beta.parquet").write_bytes(BETA_PAYLOAD)
    manifest_path = _write_manifest(tmp_path)

    download_calls: list[str] = []

    def fake_downloader(url, dest, expected_sha256=None):
        download_calls.append(url)
        return Path(dest)

    with pytest.raises(ChecksumMismatchError) as excinfo:
        fetch_data("test", manifest_path, out_dir, downloader=fake_downloader)
    assert "alpha.parquet" in excinfo.value.path
    assert excinfo.value.expected_sha256 == ALPHA_SHA
    assert download_calls == []


def test_empty_dir_downloads_then_raises_extraction_required(tmp_path: Path) -> None:
    """When no per-table files are present, manager downloads but defers
    extraction to the caller. ExtractionRequiredError carries the archive
    path so the caller's tar driver can pick it up."""
    manifest_path = _write_manifest(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    download_calls: list[tuple[str, Path]] = []

    def fake_downloader(url, dest, expected_sha256=None):
        download_calls.append((url, Path(dest)))
        Path(dest).write_bytes(b"pretend-archive-bytes")
        return Path(dest)

    with pytest.raises(ExtractionRequiredError) as excinfo:
        fetch_data("test", manifest_path, out_dir, downloader=fake_downloader)
    assert excinfo.value.output_dir == str(out_dir)
    assert "test.tar.zst" in excinfo.value.archive_path
    assert download_calls == [("https://example.com/test.tar.zst", out_dir / "test.tar.zst")]


def test_existing_verified_archive_raises_extraction_required_without_redownload(tmp_path: Path) -> None:
    """Interrupted first-runs can leave a complete archive before extraction."""
    archive_payload = b"complete-archive"
    archive_sha = hashlib.sha256(archive_payload).hexdigest()
    manifest_path = _write_manifest(tmp_path, archive_sha=archive_sha)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "test.tar.zst").write_bytes(archive_payload)

    def fail_downloader(url, dest, expected_sha256=None):
        raise AssertionError("verified archive cache should not be re-downloaded")

    with pytest.raises(ExtractionRequiredError) as excinfo:
        fetch_data("test", manifest_path, out_dir, downloader=fail_downloader)

    assert excinfo.value.archive_path == str(out_dir / "test.tar.zst")
    assert excinfo.value.output_dir == str(out_dir)


def test_post_extraction_returns_dir(tmp_path: Path) -> None:
    """If the caller extracts the tarball between the download and a
    second fetch_data call, the manager verifies all per-table sha256s
    and returns the directory."""
    manifest_path = _write_manifest(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    def extracting_downloader(url, dest, expected_sha256=None):
        # Simulate the caller running tar extraction inside the downloader
        # for the purposes of this test — production code does this in
        # the cutover wiring, NOT inside the downloader.
        Path(dest).write_bytes(b"pretend-archive-bytes")
        (out_dir / "alpha.parquet").write_bytes(ALPHA_PAYLOAD)
        (out_dir / "beta.parquet").write_bytes(BETA_PAYLOAD)
        return Path(dest)

    result = fetch_data("test", manifest_path, out_dir, downloader=extracting_downloader)
    assert result == out_dir


def test_post_extraction_with_bad_sha_raises_checksum_mismatch(tmp_path: Path) -> None:
    """If the caller's extractor produces a corrupted file, the
    post-download verifier catches it via the structured-diagnostic
    path and raises ChecksumMismatchError naming the offending file."""
    manifest_path = _write_manifest(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    def buggy_extracting_downloader(url, dest, expected_sha256=None):
        Path(dest).write_bytes(b"pretend-archive-bytes")
        # alpha is corrupt; beta is intact
        (out_dir / "alpha.parquet").write_bytes(b"truncated")
        (out_dir / "beta.parquet").write_bytes(BETA_PAYLOAD)
        return Path(dest)

    with pytest.raises(ChecksumMismatchError) as excinfo:
        fetch_data("test", manifest_path, out_dir, downloader=buggy_extracting_downloader)
    assert "alpha.parquet" in excinfo.value.path
    assert excinfo.value.expected_sha256 == ALPHA_SHA
