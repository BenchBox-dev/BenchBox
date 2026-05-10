"""Tests for benchbox.core.data_fetch.manager.

Exercises the air-gapped path (pre-populated files), the
download-on-empty-dir path (mocked downloader), and the checksum
mismatch surface.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from benchbox.core.data_fetch import (
    ChecksumMismatchError,
    fetch_data,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write_manifest(tmp: Path, *, table_payloads: dict[str, bytes], archive_sha: str = "00" * 32) -> Path:
    """Build a minimal data_manifest.toml describing the given files.

    The manifest sha256 fields are set to the actual sha of each
    payload so the air-gapped verifier matches.
    """
    table_blocks = "\n".join(
        f'[[tables]]\nname = "{name}"\nfile = "{name}.parquet"\n'
        f'sha256 = "{_hex(payload)}"\nrow_count = {len(payload)}\n'
        for name, payload in table_payloads.items()
    )
    body = (
        f'dataset_version    = "test-v1"\n'
        f'manifest_hash      = "{"a" * 64}"\n'
        f'data_archive_hash  = "{archive_sha}"\n'
        f'url                = "https://example.com/test.tar.zst"\n'
        f'archive_sha256     = "{archive_sha}"\n'
        f'license_file       = "DATA-LICENSE.md"\n'
        f"\n{table_blocks}\n"
    )
    p = tmp / "data_manifest.toml"
    p.write_text(body)
    return p


def test_air_gapped_pre_populated_returns_dir(tmp_path: Path) -> None:
    payloads = {"alpha": b"alpha rows", "beta": b"beta-rows"}
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    for name, payload in payloads.items():
        (out_dir / f"{name}.parquet").write_bytes(payload)
    manifest_path = _write_manifest(tmp_path, table_payloads=payloads)

    result = fetch_data("test", manifest_path, out_dir)
    assert result == out_dir


def test_pre_populated_with_bad_sha_raises(tmp_path: Path) -> None:
    payloads = {"alpha": b"alpha rows"}
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    # Write the wrong bytes — manifest's sha refers to the "alpha rows" payload.
    (out_dir / "alpha.parquet").write_bytes(b"corrupted contents")
    manifest_path = _write_manifest(tmp_path, table_payloads=payloads)

    # downloader stub is invoked because the air-gapped check fails;
    # it doesn't actually download (just records that it was called)
    # so the manager re-verifies and surfaces a ChecksumMismatchError
    # for the offending table file.
    calls: list[tuple[str, Path]] = []

    def fake_downloader(url, dest, expected_sha256=None):
        calls.append((url, dest))
        # Simulate the user not having extracted yet — leave the file as is.
        Path(dest).write_bytes(b"pretend-archive")
        return Path(dest)

    with pytest.raises(ChecksumMismatchError) as excinfo:
        fetch_data("test", manifest_path, out_dir, downloader=fake_downloader)
    assert "alpha.parquet" in excinfo.value.path
    assert excinfo.value.expected_sha256 == _hex(b"alpha rows")


def test_empty_output_triggers_download(tmp_path: Path) -> None:
    payloads = {"alpha": b"alpha rows"}
    manifest_path = _write_manifest(tmp_path, table_payloads=payloads)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    calls: list[tuple[str, Path]] = []

    def fake_downloader(url, dest, expected_sha256=None):
        calls.append((url, dest))
        Path(dest).write_bytes(b"pretend-archive")
        return Path(dest)

    # No table files are present; manager downloads but extraction is
    # the call site's responsibility — fetch_data returns the output
    # directory once the download succeeds even if the per-table files
    # aren't yet on disk.
    result = fetch_data("test", manifest_path, out_dir, downloader=fake_downloader)
    assert result == out_dir
    assert len(calls) == 1
    assert calls[0][0] == "https://example.com/test.tar.zst"
