"""Unit tests for shared Iceberg table-layout helpers.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from benchbox.utils.iceberg_layout import is_iceberg_directory, resolve_iceberg_metadata_file


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
