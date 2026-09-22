"""Unit tests for shared Iceberg table-layout helpers.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.utils.iceberg_layout import (
    is_iceberg_directory,
    relocate_iceberg_table,
    resolve_iceberg_metadata_file,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _make_table(root, files):
    (root / "metadata").mkdir(parents=True)
    for name in files:
        (root / "metadata" / name).write_text("{}")
    return root


def test_rejects_non_directories_and_plain_dirs(tmp_path):
    assert is_iceberg_directory(tmp_path / "missing") is False
    plain = tmp_path / "plain"
    plain.mkdir()
    assert is_iceberg_directory(plain) is False
    assert resolve_iceberg_metadata_file(plain) is None


def test_detects_version_hint_and_metadata_json(tmp_path):
    hinted = _make_table(tmp_path / "hinted", [])
    (hinted / "metadata" / "version-hint.text").write_text("1")
    assert is_iceberg_directory(hinted) is True

    jsoned = _make_table(tmp_path / "jsoned", ["00000-aaa.metadata.json"])
    assert is_iceberg_directory(jsoned) is True


def test_resolves_newest_metadata_file(tmp_path):
    table = _make_table(tmp_path / "t", ["00001-bbb.metadata.json", "00000-aaa.metadata.json"])
    resolved = resolve_iceberg_metadata_file(table)
    assert resolved is not None
    assert resolved.name == "00001-bbb.metadata.json"


def test_resolve_returns_none_without_metadata_files(tmp_path):
    table = tmp_path / "empty-meta"
    (table / "metadata").mkdir(parents=True)
    assert is_iceberg_directory(table) is False
    assert resolve_iceberg_metadata_file(table) is None


def test_relocate_rewrites_graph_for_new_location(tmp_path):
    """Relocating a table yields a loadable graph rooted at the new URI."""
    pytest.importorskip("pyiceberg", reason="relocation needs pyiceberg")
    pa = pytest.importorskip("pyarrow", reason="relocation needs pyarrow")
    from pyiceberg.catalog.sql import SqlCatalog
    from pyiceberg.schema import Schema
    from pyiceberg.table import StaticTable
    from pyiceberg.types import LongType, NestedField, StringType

    src = tmp_path / "src"
    catalog = SqlCatalog("reloc", uri=f"sqlite:///{tmp_path}/cat.db", warehouse=str(tmp_path))
    catalog.create_namespace_if_not_exists("ns")
    table = catalog.create_table(
        "ns.t",
        schema=Schema(NestedField(1, "id", LongType()), NestedField(2, "name", StringType())),
        location=(src / "t").as_uri(),
        properties={"format-version": "2"},
    )
    table.overwrite(pa.table({"id": [1, 2], "name": ["a", "b"]}))

    staging = tmp_path / "staging"
    dest = tmp_path / "dest" / "t"
    relocated = relocate_iceberg_table(src / "t", dest.as_uri(), staging)

    # Simulate the cloud upload: data files unchanged, graph files rewritten.
    dest.mkdir(parents=True)
    for rel in relocated.data_files:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((src / "t" / rel).read_bytes())
    for rel, staged in relocated.graph_files.items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(staged.read_bytes())

    reloaded = StaticTable.from_metadata(relocated.metadata_location)
    assert reloaded.location() == dest.as_uri()
    result = reloaded.scan().to_arrow()
    assert result.num_rows == 2
    assert sorted(result.column("id").to_pylist()) == [1, 2]

    # No rewritten graph file still references the source location.
    for staged in relocated.graph_files.values():
        if staged.suffix == ".json":
            assert (src / "t").as_uri() not in staged.read_text(encoding="utf-8")


def test_relocate_rejects_non_table(tmp_path):
    with pytest.raises(ValueError, match="Not an Iceberg table directory"):
        relocate_iceberg_table(tmp_path / "missing", "s3://bucket/prefix", tmp_path / "staging")
