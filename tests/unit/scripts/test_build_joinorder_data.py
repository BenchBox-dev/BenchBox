"""Unit tests for the JoinOrder canonical data build script."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script():
    name = "build_joinorder_data"
    path = REPO_ROOT / "_project" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_joinorder_data = _load_script()


def _metadata(files: list[dict]) -> dict:
    return {"data": {"latestVersion": {"files": files}}}


def test_select_pgdump_file_extracts_dataverse_download_metadata() -> None:
    metadata = _metadata(
        [
            {
                "label": "imdb_pg11",
                "dataFile": {
                    "id": 3590041,
                    "filesize": 1_277_543_282,
                    "checksum": {
                        "type": "MD5",
                        "value": "df3e976b235288005cb410cea09a115f",
                    },
                },
            }
        ]
    )

    dataverse_file = build_joinorder_data.select_pgdump_file(metadata)

    assert dataverse_file.file_id == 3590041
    assert dataverse_file.label == "imdb_pg11"
    assert dataverse_file.filesize == 1_277_543_282
    assert dataverse_file.checksum_type == "MD5"
    assert dataverse_file.download_url.endswith("/api/access/datafile/3590041")


def test_select_pgdump_file_rejects_ambiguous_metadata() -> None:
    metadata = _metadata(
        [
            {
                "label": "imdb_pg11",
                "dataFile": {"id": 1, "filesize": 10, "checksum": {"type": "MD5", "value": "a"}},
            },
            {
                "label": "imdb_pg11",
                "dataFile": {"id": 2, "filesize": 10, "checksum": {"type": "MD5", "value": "b"}},
            },
        ]
    )

    with pytest.raises(build_joinorder_data.DataverseMetadataError, match="exactly one"):
        build_joinorder_data.select_pgdump_file(metadata)


def test_validate_row_counts_accepts_one_percent_edge() -> None:
    row_counts = dict(build_joinorder_data.EXPECTED_ROW_COUNTS)
    expected = build_joinorder_data.EXPECTED_ROW_COUNTS["movie_info"]
    row_counts["movie_info"] = expected + int(expected * 0.01)

    validation = build_joinorder_data.validate_row_counts(row_counts)

    assert validation.ok
    assert validation.row_count_failures == []


def test_validate_row_counts_reports_missing_and_out_of_tolerance_tables() -> None:
    row_counts = dict(build_joinorder_data.EXPECTED_ROW_COUNTS)
    row_counts.pop("aka_title")
    row_counts["cast_info"] = build_joinorder_data.EXPECTED_ROW_COUNTS["cast_info"] + 400_000

    validation = build_joinorder_data.validate_row_counts(row_counts, unexpected_tables=["extra_table"])

    assert not validation.ok
    assert validation.missing_tables == ["aka_title"]
    assert validation.unexpected_tables == ["extra_table"]
    assert [(failure.table, failure.expected, failure.actual) for failure in validation.row_count_failures] == [
        ("cast_info", 36_244_344, 36_644_344)
    ]


def test_validate_pgdump_file_requires_custom_format_magic(tmp_path: Path) -> None:
    dump_path = tmp_path / "imdb_pg11"
    dump_path.write_bytes(b"not-a-pgdump")
    sha256, md5, size = build_joinorder_data.hash_file(dump_path)
    dataverse_file = build_joinorder_data.DataverseFile(
        file_id=3590041,
        label="imdb_pg11",
        filesize=size,
        checksum_type="MD5",
        checksum_value=md5,
        download_url="https://example.invalid/file",
    )
    assert sha256

    with pytest.raises(build_joinorder_data.DownloadIntegrityError, match="custom-format"):
        build_joinorder_data.validate_pgdump_file(dump_path, dataverse_file)


def test_write_build_manifest_records_source_sha256(tmp_path: Path) -> None:
    dataverse_file = build_joinorder_data.DataverseFile(
        file_id=3590041,
        label="imdb_pg11",
        filesize=5,
        checksum_type="MD5",
        checksum_value="275876e34cf609db118f3d84b799a790",
        download_url="https://dataverse.harvard.edu/api/access/datafile/3590041",
    )
    artifact = build_joinorder_data.PgDumpArtifact(
        path=tmp_path / "source" / "imdb_pg11",
        size=5,
        sha256="2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        md5="275876e34cf609db118f3d84b799a790",
        dataverse_file=dataverse_file,
    )

    manifest_path = build_joinorder_data.write_source_manifest(tmp_path, artifact, reused=False)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["dataset_version"] == "joinorder-imdb-2013-v1"
    assert manifest["source"]["sha256"] == artifact.sha256
    assert manifest["source"]["dataverse_file_id"] == 3590041
    assert manifest["source"]["reused_existing_file"] is False


def test_download_pgdump_recovers_invalid_cached_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    destination = source_dir / "imdb_pg11"
    destination.write_bytes(b"truncated")
    valid_payload = b"PGDMPvalid"
    dataverse_file = build_joinorder_data.DataverseFile(
        file_id=3590041,
        label="imdb_pg11",
        filesize=len(valid_payload),
        checksum_type="MD5",
        checksum_value=hashlib.md5(valid_payload, usedforsecurity=False).hexdigest(),
        download_url="https://dataverse.harvard.edu/api/access/datafile/3590041",
    )

    def fake_download(_url: str, path: Path) -> None:
        assert path.name == "imdb_pg11.part"
        path.write_bytes(valid_payload)

    monkeypatch.setattr(build_joinorder_data, "resolve_dataverse_file", lambda: dataverse_file)
    monkeypatch.setattr(build_joinorder_data, "download_to_file", fake_download)

    artifact = build_joinorder_data.download_pgdump(tmp_path)

    assert destination.read_bytes() == valid_payload
    assert not destination.with_name("imdb_pg11.part").exists()
    assert artifact.path == destination
    assert artifact.sha256 == hashlib.sha256(valid_payload).hexdigest()
