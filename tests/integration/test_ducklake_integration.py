# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""Integration tests for the DuckLake platform adapter.

These exercise a real INSTALL/LOAD/ATTACH of the ``ducklake`` DuckDB extension
against on-disk catalogs, so they live here rather than in
``tests/unit/platforms/test_ducklake_adapter.py`` (which stays hermetic and
mock-only). Keeping them out of the unit module also keeps the ``fast`` lane
free of ``live_integration`` tests, which the CI fast-lane policy forbids.
"""

from __future__ import annotations

import pytest

from benchbox.platforms.ducklake import DuckLakeAdapter

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]


# Probe whether the DuckLake DuckDB extension can actually be installed/loaded
# in this environment (mirrors tests/integration/test_open_table_formats.py's
# TestDuckLakeFormatSmoke guard), so these tests skip rather than fail when the
# extension repository is unreachable.
try:
    import duckdb as _duckdb

    _probe = _duckdb.connect(":memory:")
    _probe.execute("INSTALL ducklake")
    _probe.execute("LOAD ducklake")
    _probe.close()
    DUCKLAKE_AVAILABLE = True
except Exception:
    DUCKLAKE_AVAILABLE = False


@pytest.mark.live_integration
@pytest.mark.skipif(not DUCKLAKE_AVAILABLE, reason="DuckLake extension not available (needs DuckDB>=1.3 + network)")
class TestDuckLakeLiveConnection:
    """End-to-end tests exercising a real INSTALL/LOAD/ATTACH of the ducklake extension.

    Marked live_integration (deselected from the default/fast lane) because
    they perform a real, potentially-networked INSTALL ducklake; they also skip
    entirely when the extension cannot be installed/loaded.
    """

    def test_cursor_defaults_to_lake_catalog(self, tmp_path):
        # Regression for the w8 validation bug: framework seams (e.g.
        # phase_tracking._validate_data_integrity) probe tables via
        # connection.cursor().execute("SELECT 1 FROM <table> LIMIT 1"). A raw
        # DuckDB cursor starts in the base memory catalog, so unqualified names
        # in lake.main raise CatalogException. The _DuckLakeCursorConnection
        # wrapper re-applies USE lake to every cursor so the probe resolves.
        metadata_path = tmp_path / "catalog.ducklake"
        data_path = tmp_path / "data"
        adapter = DuckLakeAdapter(metadata_path=str(metadata_path), data_path=str(data_path))

        connection = adapter.create_connection()
        try:
            # Populate a table in the lake catalog via the parent execute path.
            connection.execute("CREATE TABLE nation (id INTEGER, name VARCHAR)")
            connection.execute("INSERT INTO nation VALUES (1, 'ALGERIA')")

            # Mimic _validate_data_integrity's accessibility probe exactly: a
            # fresh cursor + unqualified SELECT. Without the wrapper this raises
            # a CatalogException ("Table with name nation does not exist");
            # with it, the cursor is scoped to lake and the row resolves.
            cur = connection.cursor()
            cur.execute("SELECT 1 FROM nation LIMIT 1")
            assert cur.fetchone() is not None

            # The wrapper scopes each cursor to the lake catalog.
            assert connection.cursor().execute("SELECT current_catalog()").fetchone()[0] == "lake"

            # Parent execute path still works (queries + count/integrity checks).
            assert connection.execute("SELECT count(*) FROM nation").fetchone()[0] == 1
        finally:
            connection.close()

    def test_create_connection_attaches_lake_catalog(self, tmp_path):
        metadata_path = tmp_path / "catalog.ducklake"
        data_path = tmp_path / "data"
        adapter = DuckLakeAdapter(metadata_path=str(metadata_path), data_path=str(data_path))

        conn = adapter.create_connection()
        try:
            # create_connection lazily creates the dirs right before ATTACH.
            assert metadata_path.parent.is_dir()
            assert data_path.is_dir()

            # After USE lake, unqualified DDL/DML targets the lake catalog.
            conn.execute("CREATE TABLE ducklake_smoke (id INTEGER, name VARCHAR)")
            conn.execute("INSERT INTO ducklake_smoke VALUES (1, 'a'), (2, 'b')")
            rows = conn.execute("SELECT * FROM ducklake_smoke ORDER BY id").fetchall()
            assert rows == [(1, "a"), (2, "b")]

            current_catalog = conn.execute("SELECT current_catalog()").fetchone()[0]
            assert current_catalog == "lake"
        finally:
            conn.close()

        # Catalog metadata file and at least one Parquet data file exist on disk.
        assert metadata_path.exists()
        parquet_files = list(data_path.rglob("*.parquet"))
        assert len(parquet_files) >= 1

    def test_force_recreate_rebuilds_fresh_catalog(self, tmp_path):
        metadata_path = tmp_path / "catalog.ducklake"
        data_path = tmp_path / "data"

        # First run: populate a catalog with a table + row.
        adapter1 = DuckLakeAdapter(metadata_path=str(metadata_path), data_path=str(data_path))
        conn1 = adapter1.create_connection()
        try:
            conn1.execute("CREATE TABLE t (id INTEGER)")
            conn1.execute("INSERT INTO t VALUES (1)")
        finally:
            conn1.close()
        assert metadata_path.exists()
        assert list(data_path.rglob("*.parquet"))

        # Second run WITH force: the stale catalog + data must be removed, and
        # re-creating the same table must succeed (no "already exists").
        adapter2 = DuckLakeAdapter(
            metadata_path=str(metadata_path),
            data_path=str(data_path),
            force_recreate=True,
        )
        assert adapter2.force_recreate is True

        conn2 = adapter2.create_connection()
        try:
            # Fresh catalog: the previous table is gone, so CREATE succeeds.
            conn2.execute("CREATE TABLE t (id INTEGER)")
            count = conn2.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            assert count == 0
        finally:
            conn2.close()
        assert adapter2.database_was_reused is False

    def test_handle_existing_database_force_removes_artifacts(self, tmp_path):
        metadata_path = tmp_path / "catalog.ducklake"
        data_path = tmp_path / "data"

        adapter = DuckLakeAdapter(metadata_path=str(metadata_path), data_path=str(data_path))
        conn = adapter.create_connection()
        try:
            conn.execute("CREATE TABLE t (id INTEGER)")
        finally:
            conn.close()
        assert metadata_path.exists()
        assert data_path.exists()

        # Directly exercise the force-recreate removal path.
        adapter.force_recreate = True
        adapter.handle_existing_database()

        assert not metadata_path.exists()
        # data_path contents are cleared (rmtree removes the dir itself).
        assert not data_path.exists() or not any(data_path.iterdir())
        assert adapter.database_was_reused is False

    def test_get_platform_info_reports_ducklake_metadata(self, tmp_path):
        metadata_path = tmp_path / "catalog.ducklake"
        data_path = tmp_path / "data"
        adapter = DuckLakeAdapter(metadata_path=str(metadata_path), data_path=str(data_path))

        conn = adapter.create_connection()
        try:
            info = adapter.get_platform_info(conn)
        finally:
            conn.close()

        assert info["platform_type"] == "ducklake"
        assert info["platform_name"] == "DuckLake"
        assert info["catalog_backend"] == "duckdb"
        assert info["metadata_path"] == str(metadata_path)
        assert info["data_path"] == str(data_path)
        assert "ducklake_extension_version" in info
