"""Same-invocation datagen must stay visible to the load phase.

Regression test for tracker item ``loader-fresh-manifest-invisible``: a fresh
parallel (sharded, compressed) generate produced ``benchmark.tables`` values
that were stringified Python lists (``str()`` applied to a ``list[Path]``),
so no entry resolved to an existing file. Multi-file tables were then
skipped by the loader (``Skipping <table> - no valid data files``) while
single-file tables loaded, exactly matching the BigQuery cloud failure. A
warm rerun worked because ``_populate_tables_from_manifest`` rebuilds proper
lists.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchbox.core.read_primitives.generator import ReadPrimitivesDataGenerator
from benchbox.core.ssb.generator import SSBDataGenerator
from benchbox.platforms.base.data_loading import normalize_table_paths

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _make_shard_files(output_dir: Path) -> dict[str, Path | list[Path]]:
    """Create a fake sharded layout: one multi-file table, one single file."""
    shards = []
    for chunk in (1, 2, 3):
        shard = output_dir / f"customer.tbl.{chunk}.gz"
        shard.write_bytes(b"fake-gzip-payload")
        shards.append(shard)
    nation = output_dir / "nation.tbl.gz"
    nation.write_bytes(b"fake-gzip-payload")
    return {"customer": shards, "nation": nation}


def _assert_tables_resolve(tables: dict) -> None:
    """Every tables value must normalize to paths that exist on disk."""
    assert tables, "generate_data() must return a non-empty mapping"
    for table_name, value in tables.items():
        assert not (isinstance(value, str) and value.startswith("[")), (
            f"table {table_name!r} holds a stringified list, invisible to the loader: {value!r}"
        )
        paths = normalize_table_paths(value)
        assert paths, f"table {table_name!r} normalized to zero paths"
        for path in paths:
            assert isinstance(path, Path), f"table {table_name!r} entry is not a path: {path!r}"
            assert path.exists(), f"table {table_name!r} references missing file: {path}"


def test_read_primitives_generate_preserves_sharded_lists(tmp_path, monkeypatch):
    """Fresh sharded generate must keep list values, not repr strings."""
    gen = ReadPrimitivesDataGenerator(scale_factor=0.01, output_dir=tmp_path)
    layout = _make_shard_files(tmp_path)
    monkeypatch.setattr(gen.tpch_generator, "generate", lambda: layout)

    tables = gen.generate_data()

    assert isinstance(tables["customer"], list), f"expected a list, got {tables['customer']!r}"
    assert all(isinstance(entry, str) for entry in tables["customer"])
    _assert_tables_resolve(tables)
    # Impl-facing mapping must agree with what generate_data() returned.
    assert gen.tpch_generator.generate() == layout


def test_ssb_generate_preserves_sharded_lists(tmp_path, monkeypatch):
    """SSB generator shares the str-conversion helper contract."""
    gen = SSBDataGenerator(scale_factor=0.0001, output_dir=tmp_path)
    layout = _make_shard_files(tmp_path)
    monkeypatch.setattr(
        SSBDataGenerator,
        "_generate_data_local",
        lambda self, output_dir, tables=None: layout,
    )

    tables = gen.generate_data()

    assert isinstance(tables["customer"], list), f"expected a list, got {tables['customer']!r}"
    assert all(isinstance(entry, str) for entry in tables["customer"])
    _assert_tables_resolve(tables)
