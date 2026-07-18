# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""Integration tests for the DuckLake platform adapter.

Everything here performs a real INSTALL/LOAD/ATTACH of the ducklake DuckDB
extension, so none of it belongs in tests/unit/platforms/test_ducklake_adapter.py
(which stays hermetic and mock-only). Keeping these out of the unit module also
keeps the fast lane free of live_integration tests, which the CI
fast-lane policy forbids.

Coverage:

1. Live connection - in-process ATTACH of a DuckDB-file catalog: cursor
   scoping, force-recreate, platform info.
2. SQLite catalog (--platform-option catalog=sqlite) - a real TPC-H SF 0.01
   run through the CLI. It needs no external service beyond the one-time
   ducklake/sqlite extension INSTALL, but it spawns a real CLI
   subprocess including data generation (~10-20s), so this module carries the
   slow speed marker in line with every other run_cli_command consumer
   in this directory (test_cli_e2e.py, test_export_cli.py,
   test_platforms_cli_integration.py).
3. PostgreSQL catalog (--platform-option catalog=postgres) - gated behind
   the same Docker-service-reachability convention as
   tests/integration/platforms/test_postgresql_live.py; skips cleanly when
   no PostgreSQL server is reachable at localhost:5432.
4. S3 data_path (cloud storage) - gated behind the same
   BENCHBOX_S3_TEST_BUCKET + AWS credential convention as
   tests/integration/platforms/test_pg_duckdb_live.py's S3 lake-query
   tests; skips cleanly when no test bucket/credentials are configured.

The suite MUST pass-or-skip cleanly in the CI default environment (only the
duckdb/ducklake/sqlite extensions available, no PostgreSQL server,
no AWS credentials) - it must never fail outright because PostgreSQL/S3 access
is unavailable.
"""

from __future__ import annotations

import json
import os
import uuid
from functools import cache
from pathlib import Path

import duckdb
import pytest

from benchbox.platforms.ducklake import DuckLakeAdapter
from tests.integration._cli_e2e_utils import run_cli_command
from tests.integration.platforms.conftest import get_env_or_skip, skip_unless_docker_service

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]


# =============================================================================
# Extension-availability probes
# =============================================================================
# Mirrors tests/integration/test_open_table_formats.py's TestDuckLakeFormatSmoke
# guard: INSTALL/LOAD an extension so the tests below can skip cleanly - never
# fail - when the environment cannot reach the DuckDB extension repository or
# lacks a given extension.
#
# The probe must stay LAZY (called from setup_method, never at module level):
# pytest imports every collected module to discover markers/tests regardless
# of which markers are later deselected (module-level pytestmark = [slow] only
# excludes these tests from EXECUTION, not from collection/import). A
# module-level probe call, or a `@pytest.mark.skipif(not <eager flag>, ...)`
# class decorator whose condition captures that eager flag, would therefore
# still spend a real, potentially-networked INSTALL/LOAD attempt on every test
# collection - including a fast/offline lane that will never run any test in
# this file (#1082 review: this is exactly what test_ducklake_adapter.py's own
# hermetic unit module avoids by never touching a live DuckDB connection).
# setup_method only runs for a test pytest has already decided to execute, so
# deferring the probe there means an excluded/deselected run never pays for it.


@cache
def _probe_extension(name: str) -> bool:
    """Return True if the named DuckDB extension can be INSTALL/LOAD'd here."""
    try:
        conn = duckdb.connect(":memory:")
        try:
            conn.execute(f"INSTALL {name}")
            conn.execute(f"LOAD {name}")
            return True
        finally:
            conn.close()
    except Exception:
        return False


def _skip_unless_extensions(*names: str) -> None:
    """Skip the calling test unless every named DuckDB extension is available."""
    missing = [name for name in names if not _probe_extension(name)]
    if missing:
        pytest.skip(f"DuckDB extension(s) not available: {', '.join(missing)}")


# =============================================================================
# 1. Live connection - in-process DuckDB-file catalog ATTACH
# =============================================================================


@pytest.mark.live_integration
class TestDuckLakeLiveConnection:
    """End-to-end tests exercising a real INSTALL/LOAD/ATTACH of the ducklake extension.

    Marked live_integration (deselected from the default/fast lane) because
    they perform a real, potentially-networked INSTALL ducklake; they also skip
    entirely when the extension cannot be installed/loaded (checked in
    setup_method, not a collection-time skipif - see the probe docstring
    above for why).
    """

    def setup_method(self) -> None:
        _skip_unless_extensions("ducklake")

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

    def test_sqlite_catalog_end_to_end(self, tmp_path):
        # Regression coverage for w1: a real INSTALL sqlite / ATTACH
        # 'ducklake:sqlite:<path>' round trip, plus the w8-style cursor-wrapper
        # regression (see test_cursor_defaults_to_lake_catalog above) replayed
        # against the sqlite catalog specifically.
        metadata_path = tmp_path / "catalog.ducklake"
        data_path = tmp_path / "data"
        adapter = DuckLakeAdapter(
            metadata_path=str(metadata_path),
            data_path=str(data_path),
            catalog="sqlite",
        )
        # __init__ swaps the default-derived .ducklake filename to .sqlite.
        sqlite_metadata_path = tmp_path / "catalog.sqlite"
        assert adapter.metadata_path == sqlite_metadata_path

        conn = adapter.create_connection()
        try:
            conn.execute("CREATE TABLE sqlite_smoke (id INTEGER, name VARCHAR)")
            conn.execute("INSERT INTO sqlite_smoke VALUES (1, 'a'), (2, 'b')")
            rows = conn.execute("SELECT * FROM sqlite_smoke ORDER BY id").fetchall()
            assert rows == [(1, "a"), (2, "b")]

            # Regression: a fresh cursor must still resolve the unqualified
            # table via the _DuckLakeCursorConnection wrapper's USE lake.
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM sqlite_smoke")
            assert cur.fetchone()[0] == 2
        finally:
            conn.close()

        # The .sqlite metadata file (not .ducklake) and at least one Parquet
        # data file exist on disk.
        assert sqlite_metadata_path.exists()
        assert not metadata_path.exists()
        parquet_files = list(data_path.rglob("*.parquet"))
        assert len(parquet_files) >= 1


# =============================================================================
# 2. SQLite catalog - live CLI end-to-end run
# =============================================================================


class TestDuckLakeSqliteCatalogLive:
    """Real end-to-end TPC-H run through the DuckLake adapter with catalog=sqlite."""

    def setup_method(self) -> None:
        _skip_unless_extensions("ducklake", "sqlite")

    def test_tpch_sf001_sqlite_catalog_end_to_end(self, tmp_path: Path) -> None:
        """Run TPC-H SF 0.01 via `benchbox run` with --platform-option catalog=sqlite.

        Exercises the full pipeline (generate -> load -> power-run query
        execution) via a real CLI subprocess, not just a hand-rolled table -
        that in-process round trip is already covered at the unit level by
        ``TestDuckLakeLiveConnection.test_sqlite_catalog_end_to_end`` in
        ``tests/unit/platforms/test_ducklake_adapter.py``. This test instead
        proves the catalog=sqlite option resolves correctly end-to-end through
        the real CLI/config-parsing path and that queries actually succeed.
        """
        result = run_cli_command(
            [
                "run",
                "--platform",
                "ducklake",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--platform-option",
                "catalog=sqlite",
                "--queries",
                "Q1,Q6,Q17",
                "--non-interactive",
            ],
            cwd=tmp_path,
        )
        assert result.returncode == 0, (
            f"benchbox run failed (exit {result.returncode}).\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

        result_files = sorted((tmp_path / "benchmark_runs" / "results").glob("*.json"))
        assert result_files, f"No result JSON exported.\nSTDOUT:\n{result.stdout}"
        payload = json.loads(result_files[-1].read_text(encoding="utf-8"))

        summary = payload["summary"]
        assert summary["validation"] == "passed", summary
        assert summary["queries"]["failed"] == 0, summary["queries"]
        assert summary["queries"]["passed"] >= 1, summary["queries"]
        assert payload["platform"]["config"]["catalog_backend"] == "sqlite"

        # A real .sqlite catalog metadata file (not .ducklake - __init__ swaps
        # the suffix for the sqlite backend) and Parquet DATA_PATH files landed
        # on disk under the CLI's default benchmark_runs/databases layout.
        databases_dir = tmp_path / "benchmark_runs" / "databases"
        sqlite_metadata_files = list(databases_dir.rglob("*.sqlite"))
        assert sqlite_metadata_files, f"Expected a .sqlite DuckLake catalog file under {databases_dir}"

        parquet_files = list(databases_dir.rglob("*.parquet"))
        assert parquet_files, f"Expected DuckLake Parquet data files under {databases_dir}"


# =============================================================================
# 3. PostgreSQL catalog - live, gated behind Docker-service reachability
# =============================================================================


@pytest.mark.docker_integration
@pytest.mark.live_integration
@pytest.mark.live_postgresql
class TestDuckLakePostgresCatalogLive:
    """PostgreSQL catalog backend tests.

    Deselected from the default lane by ``live_integration`` (matches
    ``tests/integration/platforms/test_postgresql_live.py``); run explicitly via
    ``make test-live`` (or ``-m live_integration``) against a PostgreSQL
    instance started with ``make test-docker-up-postgresql``. The target
    catalog DATABASE must already exist - DuckLake's postgres ATTACH does not
    ``CREATE DATABASE`` - so this reuses the ``benchbox_test`` database that
    Docker Compose already provisions for the plain PostgreSQL live tests.
    """

    def test_postgres_catalog_attach_and_query(self, tmp_path: Path) -> None:
        _skip_unless_extensions("ducklake", "postgres")
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "unused-for-postgres-catalog.ducklake"),
            data_path=str(tmp_path / "data"),
            catalog="postgres",
            pg_host=os.getenv("PG_DUCKLAKE_HOST", "localhost"),
            pg_port=int(os.getenv("PG_DUCKLAKE_PORT", "5432")),
            pg_user=os.getenv("PG_DUCKLAKE_USER", "benchbox"),
            pg_password=os.getenv("PG_DUCKLAKE_PASSWORD", "benchbox"),
            pg_database=os.getenv("PG_DUCKLAKE_DATABASE", "benchbox_test"),
        )
        assert adapter.catalog == "postgres"

        # Connection-string construction is pure (no I/O) - exercise it before
        # the reachability skip so it is verified regardless of whether a live
        # server is available.
        attach_target = adapter._build_catalog_attach_target()
        assert attach_target.startswith("postgres:")
        assert "dbname=benchbox_test" in attach_target
        assert f"host={adapter.pg_host}" in attach_target

        skip_unless_docker_service(adapter.pg_host, adapter.pg_port, platform="DuckLake PostgreSQL catalog")

        connection = adapter.create_connection()
        table = f"ducklake_pg_smoke_{uuid.uuid4().hex[:8]}"
        try:
            connection.execute(f"DROP TABLE IF EXISTS {table}")
            connection.execute(f"CREATE TABLE {table} (id INTEGER, name VARCHAR)")
            connection.execute(f"INSERT INTO {table} VALUES (1, 'alpha'), (2, 'beta')")
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 2
        finally:
            try:
                connection.execute(f"DROP TABLE IF EXISTS {table}")
            except Exception:
                pass
            connection.close()


# =============================================================================
# 4. S3 data_path (cloud storage) - live, gated behind AWS credentials
# =============================================================================


@pytest.mark.live_integration
class TestDuckLakeS3DataPathLive:
    """S3-backed DATA_PATH tests.

    Deselected from the default lane by ``live_integration``; run explicitly
    (e.g. ``-m live_integration``) with ``BENCHBOX_S3_TEST_BUCKET`` and AWS
    credentials set, following the same convention as
    ``tests/integration/platforms/test_pg_duckdb_live.py``'s S3 lake-query
    tests. Absent creds/bucket -> skip, never fail.
    """

    def test_s3_data_path_credential_chain_attach_and_query(self, tmp_path: Path) -> None:
        _skip_unless_extensions("ducklake", "httpfs")
        bucket = os.getenv("BENCHBOX_S3_TEST_BUCKET")
        if not bucket:
            pytest.skip("Requires BENCHBOX_S3_TEST_BUCKET for DuckLake S3 DATA_PATH tests")
        get_env_or_skip("AWS_ACCESS_KEY_ID", "DuckLake S3")
        get_env_or_skip("AWS_SECRET_ACCESS_KEY", "DuckLake S3")

        run_id = uuid.uuid4().hex[:8]
        data_path = f"s3://{bucket}/benchbox_ducklake_test/{run_id}"

        # Default (duckdb-file) catalog metadata stays local; only DATA_PATH is
        # cloud. Credentials are picked up via DuckDB's credential_chain S3
        # secret provider (ambient AWS env vars/profile/IMDS) - no explicit
        # s3_key_id/s3_secret platform options are passed here.
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=data_path,
        )
        assert adapter._data_path_is_cloud is True

        connection = adapter.create_connection()
        table = f"ducklake_s3_smoke_{run_id}"
        try:
            connection.execute(f"CREATE TABLE {table} (id INTEGER, name VARCHAR)")
            connection.execute(f"INSERT INTO {table} VALUES (1, 'alpha'), (2, 'beta')")
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 2
        finally:
            try:
                connection.execute(f"DROP TABLE IF EXISTS {table}")
            except Exception:
                pass
            connection.close()
