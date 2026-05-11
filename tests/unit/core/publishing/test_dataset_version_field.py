"""Dataset identity fields in publication metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchbox.core.data_fetch import load_manifest
from benchbox.core.publishing.bundle_publisher import BundlePublisher
from benchbox.core.publishing.store import PublicationStore

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _write_bundle(path: Path, benchmark_id: str) -> None:
    path.write_text(
        json.dumps(
            {
                "benchmark": {"id": benchmark_id, "name": benchmark_id, "scale_factor": 1.0},
                "platform": {"name": "DuckDB"},
                "summary": {},
            }
        ),
        encoding="utf-8",
    )


def test_joinorder_publication_records_dataset_identity(tmp_path: Path) -> None:
    source = tmp_path / "joinorder_sf1_duckdb_sql_test.json"
    _write_bundle(source, "joinorder")
    store = PublicationStore(store_path=tmp_path / "published.json")

    result = BundlePublisher(destination=tmp_path / "published", store=store).publish(source)

    manifest = load_manifest(Path("benchbox/core/joinorder/data_manifest.toml"))
    assert result.record is not None
    assert result.record.dataset_version == manifest.dataset_version
    assert result.record.manifest_hash == manifest.manifest_hash
    assert result.record.data_archive_hash == manifest.data_archive_hash


def test_generated_benchmark_publication_records_null_dataset_identity(tmp_path: Path) -> None:
    source = tmp_path / "tpch_sf1_duckdb_sql_test.json"
    _write_bundle(source, "tpch")
    store = PublicationStore(store_path=tmp_path / "published.json")

    result = BundlePublisher(destination=tmp_path / "published", store=store).publish(source)

    assert result.record is not None
    assert result.record.dataset_version is None
    assert result.record.manifest_hash is None
    assert result.record.data_archive_hash is None


def test_republish_without_identity_preserves_existing_dataset_identity(tmp_path: Path) -> None:
    store = PublicationStore(store_path=tmp_path / "published.json")
    rec1 = store.add(
        source_path="/tmp/result.json",
        destination="/tmp/published",
        reference="file:///tmp/published/result.json",
        dataset_version="joinorder-imdb-2013-v1",
        manifest_hash="manifest-hash",
        data_archive_hash="archive-hash",
    )

    rec2 = store.add(
        source_path="/tmp/result.json",
        destination="/tmp/published",
        reference="file:///tmp/published/result.json",
    )

    assert rec2.pub_id == rec1.pub_id
    assert rec2.dataset_version == "joinorder-imdb-2013-v1"
    assert rec2.manifest_hash == "manifest-hash"
    assert rec2.data_archive_hash == "archive-hash"
