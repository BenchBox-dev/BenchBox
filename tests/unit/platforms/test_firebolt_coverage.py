"""Extended coverage tests for Firebolt platform adapter.

Targets branches not covered by test_firebolt_adapter.py and test_firebolt_cloud.py:
- check_server_database_exists (core + cloud paths)
- drop_database (core + cloud paths)
- create_connection with result-cache disable
- _disable_result_cache / validate_session_cache_control
- _create_admin_connection
- _get_platform_metadata
- _load_data_via_insert manifest fallback, batch flush, column-count mismatch
- _execute_batch_insert executemany fallback
- _get_parameter_placeholder / _coerce_bool helpers
- _parse_s3_url, S3 URL validation in __init__
- apply_unified_tuning / generate_tuning_clause (distribution)
- _get_existing_tables / analyze_table / apply_platform_optimizations
- supports_tuning_type ImportError path
- _build_firebolt_config function
- get_platform_info library-version + error branches

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from benchbox.platforms.base.data_loading import DataSource

pytestmark = [pytest.mark.unit, pytest.mark.fast]

# ---------------------------------------------------------------------------
# Shared module-level mock for the firebolt SDK so each test doesn't need to
# re-patch sys.modules individually.  We use an autouse fixture that installs
# the mocks for every test in this file.
# ---------------------------------------------------------------------------

_FIREBOLT_MOCKS = {
    "firebolt": MagicMock(),
    "firebolt.client": MagicMock(),
    "firebolt.client.auth": MagicMock(),
    "firebolt.client.auth.firebolt_core": MagicMock(),
    "firebolt.db": MagicMock(),
}


@pytest.fixture(autouse=True)
def _patch_firebolt_sdk():
    """Ensure firebolt SDK is mocked for every test in this file."""
    with patch.dict("sys.modules", _FIREBOLT_MOCKS):
        yield


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_core_adapter(**extra):
    """Return a FireboltAdapter in Core mode (no imports needed)."""
    from benchbox.platforms.firebolt import FireboltAdapter

    return FireboltAdapter(url="http://localhost:3473", **extra)


def _make_cloud_adapter(**extra):
    """Return a FireboltAdapter in Cloud mode."""
    from benchbox.platforms.firebolt import FireboltAdapter

    return FireboltAdapter(
        client_id="cid",
        client_secret="csec",
        account_name="acct",
        engine_name="engine",
        **extra,
    )


# ---------------------------------------------------------------------------
# check_server_database_exists - Cloud path
# ---------------------------------------------------------------------------


class TestCheckServerDatabaseExistsCloud:
    """Tests for check_server_database_exists in Cloud mode."""

    def test_cloud_database_exists_returns_true(self):
        """Cloud mode: database found in information_schema returns True."""
        adapter = _make_cloud_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("my_db",)

        with patch("benchbox.platforms.firebolt.firebolt_connect", return_value=mock_conn):
            result = adapter.check_server_database_exists(database="my_db")

        assert result is True

    def test_cloud_database_missing_returns_false(self):
        """Cloud mode: database not found returns False."""
        adapter = _make_cloud_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        with patch("benchbox.platforms.firebolt.firebolt_connect", return_value=mock_conn):
            result = adapter.check_server_database_exists(database="missing_db")

        assert result is False

    def test_cloud_connection_error_returns_false(self):
        """Cloud mode: connection error returns False gracefully."""
        adapter = _make_cloud_adapter()

        with patch("benchbox.platforms.firebolt.firebolt_connect", side_effect=Exception("auth failed")):
            result = adapter.check_server_database_exists(database="db")

        assert result is False

    def test_cloud_query_error_returns_false(self):
        """Cloud mode: query error returns False."""
        adapter = _make_cloud_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("query error")

        with patch("benchbox.platforms.firebolt.firebolt_connect", return_value=mock_conn):
            result = adapter.check_server_database_exists(database="db")

        assert result is False


class TestCheckServerDatabaseExistsCore:
    """Tests for check_server_database_exists in Core mode."""

    def test_core_with_tables_returns_true(self):
        """Core mode: existing tables means database 'exists' for benchmarks."""
        adapter = _make_core_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("table1",), ("table2",)]

        with patch("benchbox.platforms.firebolt.firebolt_connect", return_value=mock_conn):
            result = adapter.check_server_database_exists()

        assert result is True

    def test_core_empty_database_returns_false(self):
        """Core mode: empty database returns False (safe to recreate)."""
        adapter = _make_core_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        with patch("benchbox.platforms.firebolt.firebolt_connect", return_value=mock_conn):
            result = adapter.check_server_database_exists()

        assert result is False

    def test_core_connection_failure_returns_false(self):
        """Core mode: connection failure returns False."""
        adapter = _make_core_adapter()

        with patch("benchbox.platforms.firebolt.firebolt_connect", side_effect=Exception("docker not running")):
            result = adapter.check_server_database_exists()

        assert result is False


# ---------------------------------------------------------------------------
# drop_database
# ---------------------------------------------------------------------------


class TestDropDatabase:
    """Tests for drop_database in both modes."""

    def test_core_mode_drop_is_noop(self):
        """Core mode drop_database is a no-op (databases recreated implicitly)."""
        adapter = _make_core_adapter()

        with patch("benchbox.platforms.firebolt.firebolt_connect") as mock_connect:
            adapter.drop_database(database="some_db")

        mock_connect.assert_not_called()

    def test_cloud_drop_skips_when_db_missing(self):
        """Cloud mode drop_database is skipped if database doesn't exist."""
        adapter = _make_cloud_adapter()

        with patch.object(adapter, "check_server_database_exists", return_value=False):
            with patch("benchbox.platforms.firebolt.firebolt_connect") as mock_connect:
                adapter.drop_database(database="nonexistent")

        mock_connect.assert_not_called()

    def test_cloud_drop_executes_when_db_exists(self):
        """Cloud mode drop_database executes DROP DATABASE."""
        adapter = _make_cloud_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        with (
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch("benchbox.platforms.firebolt.firebolt_connect", return_value=mock_conn),
        ):
            adapter.drop_database(database="old_db")

        mock_cursor.execute.assert_called_once()
        sql_call = mock_cursor.execute.call_args[0][0]
        assert "DROP DATABASE" in sql_call

    def test_cloud_drop_raises_on_execute_error(self):
        """Cloud mode drop_database raises RuntimeError on failure."""
        adapter = _make_cloud_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("permission denied")

        with (
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch("benchbox.platforms.firebolt.firebolt_connect", return_value=mock_conn),
            pytest.raises(RuntimeError, match="Failed to drop"),
        ):
            adapter.drop_database(database="db")


# ---------------------------------------------------------------------------
# create_connection - result cache disable path
# ---------------------------------------------------------------------------


class TestCreateConnectionResultCache:
    """Tests for create_connection result-cache-disable branch."""

    def test_cloud_disables_result_cache_when_configured(self):
        """Cloud create_connection calls _disable_result_cache when enabled."""
        adapter = _make_cloud_adapter(disable_result_cache=True)

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)

        with (
            patch.object(adapter, "handle_existing_database"),
            patch("benchbox.platforms.firebolt.firebolt_connect", return_value=mock_conn),
            patch.object(adapter, "_disable_result_cache") as mock_disable,
        ):
            connection = adapter.create_connection()

        mock_disable.assert_called_once_with(mock_conn)
        assert connection is mock_conn

    def test_core_does_not_disable_result_cache(self):
        """Core create_connection does NOT call _disable_result_cache."""
        adapter = _make_core_adapter(disable_result_cache=True)

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)

        with (
            patch.object(adapter, "handle_existing_database"),
            patch("benchbox.platforms.firebolt.firebolt_connect", return_value=mock_conn),
            patch.object(adapter, "_disable_result_cache") as mock_disable,
        ):
            adapter.create_connection()

        mock_disable.assert_not_called()

    def test_create_connection_raises_on_connect_error(self):
        """create_connection propagates connection errors."""
        adapter = _make_core_adapter()

        with (
            patch.object(adapter, "handle_existing_database"),
            patch("benchbox.platforms.firebolt.firebolt_connect", side_effect=Exception("refused")),
            pytest.raises(Exception, match="refused"),
        ):
            adapter.create_connection()


# ---------------------------------------------------------------------------
# _disable_result_cache
# ---------------------------------------------------------------------------


class TestDisableResultCache:
    """Tests for _disable_result_cache."""

    def test_cloud_disables_cache_success(self):
        """Cloud mode: SET enable_result_cache = false is executed."""
        adapter = _make_cloud_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter._disable_result_cache(mock_conn)

        mock_cursor.execute.assert_called_once_with("SET enable_result_cache = false")
        mock_cursor.close.assert_called_once()

    def test_core_mode_skips_disable(self):
        """Core mode: _disable_result_cache is a no-op."""
        adapter = _make_core_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter._disable_result_cache(mock_conn)

        mock_cursor.execute.assert_not_called()

    def test_strict_validation_raises_on_failure(self):
        """With strict_validation, execute failure raises ConfigurationError."""
        from benchbox.core.exceptions import ConfigurationError

        adapter = _make_cloud_adapter(strict_validation=True)

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("not supported")

        with pytest.raises(ConfigurationError, match="Failed to disable"):
            adapter._disable_result_cache(mock_conn)

    def test_non_strict_logs_warning_on_failure(self):
        """Without strict_validation, execute failure only logs warning."""
        adapter = _make_cloud_adapter(strict_validation=False)

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("not supported")

        # Should not raise
        adapter._disable_result_cache(mock_conn)

    def test_strict_validation_validates_cache_after_disable(self):
        """With strict_validation, validate_session_cache_control is called."""
        adapter = _make_cloud_adapter(strict_validation=True)

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(adapter, "validate_session_cache_control") as mock_validate:
            adapter._disable_result_cache(mock_conn)

        mock_validate.assert_called_once_with(mock_conn)


# ---------------------------------------------------------------------------
# validate_session_cache_control
# ---------------------------------------------------------------------------


class TestValidateSessionCacheControl:
    """Tests for validate_session_cache_control."""

    def test_core_mode_returns_true(self):
        """Core mode always returns True (no cache to validate)."""
        adapter = _make_core_adapter()
        assert adapter.validate_session_cache_control(Mock()) is True

    def test_cloud_cache_disabled_returns_true(self):
        """Cloud mode: cache disabled => returns True."""
        adapter = _make_cloud_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("false",)

        result = adapter.validate_session_cache_control(mock_conn)
        assert result is True

    def test_cloud_cache_enabled_returns_false_non_strict(self):
        """Cloud mode: cache still enabled => returns False (non-strict)."""
        adapter = _make_cloud_adapter(strict_validation=False)

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("true",)

        result = adapter.validate_session_cache_control(mock_conn)
        assert result is False

    def test_cloud_cache_enabled_raises_strict(self):
        """Cloud mode: cache still enabled raises ConfigurationError (strict)."""
        from benchbox.core.exceptions import ConfigurationError

        adapter = _make_cloud_adapter(strict_validation=True)

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("1",)

        with pytest.raises(ConfigurationError, match="Result cache is still enabled"):
            adapter.validate_session_cache_control(mock_conn)

    def test_show_not_supported_returns_true(self):
        """SHOW command not supported logs debug and returns True."""
        adapter = _make_cloud_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("SHOW command not supported")

        result = adapter.validate_session_cache_control(mock_conn)
        assert result is True

    def test_non_show_error_non_strict_returns_false(self):
        """Non-SHOW error in non-strict mode returns False."""
        adapter = _make_cloud_adapter(strict_validation=False)

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("network error")

        result = adapter.validate_session_cache_control(mock_conn)
        assert result is False

    def test_non_show_error_strict_raises(self):
        """Non-SHOW error in strict mode raises ConfigurationError."""
        from benchbox.core.exceptions import ConfigurationError

        adapter = _make_cloud_adapter(strict_validation=True)

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("network error")

        with pytest.raises(ConfigurationError, match="Cache validation failed"):
            adapter.validate_session_cache_control(mock_conn)

    def test_no_result_from_show(self):
        """SHOW returns None result; cache disabled assumed."""
        adapter = _make_cloud_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        result = adapter.validate_session_cache_control(mock_conn)
        assert result is True


# ---------------------------------------------------------------------------
# _create_admin_connection
# ---------------------------------------------------------------------------


class TestCreateAdminConnection:
    """Tests for _create_admin_connection."""

    def test_cloud_connects_to_information_schema(self):
        """Cloud mode admin connection targets information_schema."""
        adapter = _make_cloud_adapter()

        mock_conn = Mock()
        with patch("benchbox.platforms.firebolt.firebolt_connect", return_value=mock_conn) as mock_connect:
            result = adapter._create_admin_connection()

        assert result is mock_conn
        call_kwargs = mock_connect.call_args.kwargs
        assert call_kwargs["database"] == "information_schema"

    def test_core_connects_without_information_schema(self):
        """Core mode admin connection does NOT override database."""
        adapter = _make_core_adapter()

        mock_conn = Mock()
        with patch("benchbox.platforms.firebolt.firebolt_connect", return_value=mock_conn) as mock_connect:
            result = adapter._create_admin_connection()

        assert result is mock_conn
        call_kwargs = mock_connect.call_args.kwargs
        assert call_kwargs.get("database") != "information_schema"

    def test_connection_error_propagates(self):
        """Admin connection failure propagates."""
        adapter = _make_cloud_adapter()

        with (
            patch("benchbox.platforms.firebolt.firebolt_connect", side_effect=RuntimeError("auth failed")),
            pytest.raises(RuntimeError, match="auth failed"),
        ):
            adapter._create_admin_connection()


# ---------------------------------------------------------------------------
# _get_platform_metadata
# ---------------------------------------------------------------------------


class TestGetPlatformMetadata:
    """Tests for _get_platform_metadata."""

    def test_cloud_includes_engine_details(self):
        """Cloud mode metadata includes account, engine, api endpoint."""
        adapter = _make_cloud_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            ("Firebolt 1.2.3",),  # version()
            ("my-engine", "M", "RUNNING"),  # engine details
        ]

        metadata = adapter._get_platform_metadata(mock_conn)

        assert metadata["mode"] == "cloud"
        assert metadata["account_name"] == "acct"
        assert metadata["engine_name"] == "engine"
        assert metadata["version"] == "Firebolt 1.2.3"

    def test_core_includes_url(self):
        """Core mode metadata includes url."""
        adapter = _make_core_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("Firebolt 1.0.0",)

        metadata = adapter._get_platform_metadata(mock_conn)

        assert metadata["mode"] == "core"
        assert metadata["url"] == "http://localhost:3473"

    def test_version_query_error_skipped(self):
        """Version query failure is swallowed; metadata still returns."""
        adapter = _make_core_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("version() not available")

        metadata = adapter._get_platform_metadata(mock_conn)

        assert metadata["mode"] == "core"
        assert "database" in metadata

    def test_engine_details_query_error_ignored(self):
        """Cloud engine details query failure is ignored."""
        adapter = _make_cloud_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        # First call (version()) succeeds, second (engine details) fails
        mock_cursor.fetchone.side_effect = [("v1",), Exception("engine query failed")]
        mock_cursor.execute.side_effect = [None, Exception("engine query failed")]

        # Should not raise
        metadata = adapter._get_platform_metadata(mock_conn)
        assert metadata["mode"] == "cloud"


# ---------------------------------------------------------------------------
# get_platform_info - SDK version + error branches
# ---------------------------------------------------------------------------


class TestGetPlatformInfoBranches:
    """Tests for get_platform_info SDK and version branches."""

    def test_firebolt_version_from_sdk(self):
        """get_platform_info retrieves firebolt SDK version when available."""
        adapter = _make_core_adapter()

        mock_firebolt = MagicMock()
        mock_firebolt.__version__ = "2.0.0"
        with patch.dict("sys.modules", {"firebolt": mock_firebolt}):
            info = adapter.get_platform_info(None)

        assert info["client_library_version"] == "2.0.0"

    def test_firebolt_version_none_on_attribute_error(self):
        """get_platform_info handles missing __version__ gracefully."""
        adapter = _make_core_adapter()

        mock_firebolt = MagicMock(spec=[])  # No __version__
        with patch.dict("sys.modules", {"firebolt": mock_firebolt}):
            info = adapter.get_platform_info(None)

        assert info["client_library_version"] is None

    def test_version_query_error_is_swallowed(self):
        """get_platform_info swallows cursor errors from version query."""
        adapter = _make_core_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("SELECT version() failed")

        info = adapter.get_platform_info(mock_conn)
        assert info["platform_version"] is None


# ---------------------------------------------------------------------------
# _load_data_via_insert - manifest fallback + batch flushing
# ---------------------------------------------------------------------------


class TestLoadDataInsertBranches:
    """Tests for _load_data_via_insert edge-case branches."""

    def test_manifest_fallback_loads_data(self):
        """_load_data_via_insert reads tables from _datagen_manifest.json."""
        adapter = _make_core_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a CSV data file
            data_file = Path(tmp_dir) / "orders.csv"
            data_file.write_text("1,foo\n2,bar\n")

            # Create manifest
            manifest = {
                "tables": {
                    "orders": [{"path": "orders.csv"}],
                }
            }
            (Path(tmp_dir) / "_datagen_manifest.json").write_text(json.dumps(manifest))

            mock_benchmark = Mock(spec=[])  # No .tables attribute

            table_stats, load_time, _ = adapter._load_data_via_insert(mock_benchmark, mock_conn, Path(tmp_dir))

        assert "orders" in table_stats
        assert table_stats["orders"] == 2

    def test_missing_data_files_raises_value_error(self):
        """_load_data_via_insert raises ValueError when no data found."""
        adapter = _make_core_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        with tempfile.TemporaryDirectory() as tmp_dir:
            mock_benchmark = Mock(spec=[])

            with pytest.raises(ValueError, match="No data files found"):
                adapter._load_data_via_insert(mock_benchmark, mock_conn, Path(tmp_dir))

    def test_large_batch_is_flushed_mid_file(self):
        """_load_data_via_insert flushes batches when batch_size exceeded."""
        adapter = _make_core_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        # Create a file with 600 rows (> default batch_size=500)
        rows = "\n".join(f"{i},value{i}" for i in range(600))

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write(rows)
            tmp_path = Path(f.name)

        try:
            mock_benchmark = Mock()
            mock_benchmark.tables = {"big_table": str(tmp_path)}

            table_stats, _, _ = adapter._load_data_via_insert(mock_benchmark, mock_conn, Path("/tmp"))
        finally:
            tmp_path.unlink()

        assert table_stats["big_table"] == 600
        # executemany should have been called multiple times (mid-batch + remainder)
        assert mock_cursor.executemany.call_count >= 2

    def test_empty_file_is_skipped(self):
        """_load_data_via_insert skips empty files gracefully."""
        adapter = _make_core_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("")  # Empty file
            tmp_path = Path(f.name)

        try:
            mock_benchmark = Mock()
            mock_benchmark.tables = {"empty_table": str(tmp_path)}

            table_stats, _, _ = adapter._load_data_via_insert(mock_benchmark, mock_conn, Path("/tmp"))
        finally:
            tmp_path.unlink()

        assert table_stats["empty_table"] == 0
        mock_cursor.executemany.assert_not_called()

    def test_column_count_mismatch_raises(self):
        """_load_data_via_insert raises on inconsistent column counts."""
        adapter = _make_core_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("1,a\n2,b,extra\n")  # Row 2 has 3 columns, row 1 has 2
            tmp_path = Path(f.name)

        try:
            mock_benchmark = Mock()
            mock_benchmark.tables = {"bad_table": str(tmp_path)}

            # The error is caught internally and logged; table_stats gets 0
            table_stats, _, _ = adapter._load_data_via_insert(mock_benchmark, mock_conn, Path("/tmp"))
        finally:
            tmp_path.unlink()

        assert table_stats["bad_table"] == 0

    def test_null_values_converted(self):
        """_load_data_via_insert converts empty/null strings to Python None."""
        adapter = _make_core_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        # Use pipe-delimited .tbl so trailing-delimiter logic doesn't strip columns
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            # Two columns: id (non-null) and name (null/empty)
            # No trailing delimiter, so columns are preserved
            f.write("1,empty_col\n2,NULL\n")
            tmp_path = Path(f.name)

        try:
            mock_benchmark = Mock()
            mock_benchmark.tables = {"nullable_table": str(tmp_path)}

            source = DataSource(
                source_type="manifest_v2",
                tables={"nullable_table": [tmp_path]},
                table_metadata={"nullable_table": {"csv_delimiter": ",", "csv_null_marker": "NULL"}},
            )

            with patch.object(adapter, "_resolve_data_files", return_value=source):
                adapter._load_data_via_insert(mock_benchmark, mock_conn, Path("/tmp"))

            _, rows = mock_cursor.executemany.call_args[0]
            # Second column "empty_col" stays as-is (not empty string)
            assert rows[0] == ("1", "empty_col")
            # NULL → None
            assert rows[1] == ("2", None)
        finally:
            tmp_path.unlink()


# ---------------------------------------------------------------------------
# _execute_batch_insert - executemany fallback
# ---------------------------------------------------------------------------


class TestExecuteBatchInsert:
    """Tests for _execute_batch_insert fallback logic."""

    def test_uses_executemany_when_available(self):
        """_execute_batch_insert prefers executemany."""
        adapter = _make_core_adapter()

        cursor = Mock()
        cursor.executemany = Mock()
        rows = [("a",), ("b",)]
        adapter._execute_batch_insert(cursor, "INSERT INTO t VALUES (?)", rows)

        cursor.executemany.assert_called_once_with("INSERT INTO t VALUES (?)", rows)

    def test_fallback_to_execute_when_no_executemany(self):
        """_execute_batch_insert falls back to individual execute calls."""
        adapter = _make_core_adapter()

        cursor = Mock(spec=["execute"])  # No executemany
        rows = [("a",), ("b",)]
        adapter._execute_batch_insert(cursor, "INSERT INTO t VALUES (?)", rows)

        assert cursor.execute.call_count == 2

    def test_empty_rows_does_nothing(self):
        """_execute_batch_insert returns immediately for empty rows."""
        adapter = _make_core_adapter()

        cursor = Mock()
        adapter._execute_batch_insert(cursor, "INSERT INTO t VALUES (?)", [])

        cursor.executemany.assert_not_called()
        cursor.execute.assert_not_called()


# ---------------------------------------------------------------------------
# _get_parameter_placeholder
# ---------------------------------------------------------------------------


class TestGetParameterPlaceholder:
    """Tests for _get_parameter_placeholder."""

    def test_format_style_returns_percent_s(self):
        """format paramstyle returns %s."""
        adapter = _make_core_adapter()

        cursor = Mock()
        cursor.paramstyle = "format"
        assert adapter._get_parameter_placeholder(cursor) == "%s"

    def test_pyformat_style_returns_percent_s(self):
        """pyformat paramstyle returns %s."""
        adapter = _make_core_adapter()

        cursor = Mock()
        cursor.paramstyle = "pyformat"
        assert adapter._get_parameter_placeholder(cursor) == "%s"

    def test_unknown_style_returns_question_mark(self):
        """Unknown paramstyle returns ?."""
        adapter = _make_core_adapter()

        cursor = Mock()
        cursor.paramstyle = "qmark"
        assert adapter._get_parameter_placeholder(cursor) == "?"

    def test_no_paramstyle_returns_question_mark(self):
        """Missing paramstyle returns ?."""
        adapter = _make_core_adapter()

        cursor = Mock(spec=["execute"])  # No paramstyle
        assert adapter._get_parameter_placeholder(cursor) == "?"


# ---------------------------------------------------------------------------
# _coerce_bool
# ---------------------------------------------------------------------------


class TestCoerceBool:
    """Tests for _coerce_bool helper."""

    def test_none_returns_default(self):
        adapter = _make_core_adapter()
        assert adapter._coerce_bool(None, True) is True
        assert adapter._coerce_bool(None, False) is False

    def test_true_bool(self):
        adapter = _make_core_adapter()
        assert adapter._coerce_bool(True, False) is True

    def test_false_bool(self):
        adapter = _make_core_adapter()
        assert adapter._coerce_bool(False, True) is False

    def test_string_false_values(self):
        adapter = _make_core_adapter()
        for falsy in ("false", "0", "no", "off", "False", "FALSE", "  0  "):
            assert adapter._coerce_bool(falsy, True) is False, f"Expected False for {falsy!r}"

    def test_string_truthy_values(self):
        adapter = _make_core_adapter()
        for truthy in ("true", "yes", "1", "on", "True"):
            assert adapter._coerce_bool(truthy, False) is True, f"Expected True for {truthy!r}"


# ---------------------------------------------------------------------------
# S3 URL validation in __init__
# ---------------------------------------------------------------------------


class TestS3UrlValidation:
    """Tests for S3 staging URL validation."""

    def test_valid_s3_url_accepted(self):
        """Valid s3:// URL is accepted."""
        adapter = _make_cloud_adapter(s3_staging_url="s3://my-bucket/prefix/")
        assert adapter.s3_staging_url == "s3://my-bucket/prefix/"

    def test_s3_url_without_trailing_slash_gets_one(self):
        """S3 URL without trailing slash gets one appended."""
        adapter = _make_cloud_adapter(s3_staging_url="s3://my-bucket/prefix")
        assert adapter.s3_staging_url == "s3://my-bucket/prefix/"

    def test_invalid_s3_url_raises(self):
        """Non-s3:// URL raises ConfigurationError."""
        from benchbox.core.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError, match="Invalid S3 staging URL"):
            _make_cloud_adapter(s3_staging_url="https://my-bucket/prefix")

    def test_env_var_s3_url(self):
        """S3 URL from env var is read and validated."""
        with patch.dict(os.environ, {"FIREBOLT_S3_STAGING_URL": "s3://env-bucket/path/"}):
            adapter = _make_cloud_adapter()
        assert adapter.s3_staging_url == "s3://env-bucket/path/"


# ---------------------------------------------------------------------------
# _parse_s3_url
# ---------------------------------------------------------------------------


class TestParseS3Url:
    """Tests for _parse_s3_url static helper."""

    def test_parses_bucket_and_prefix(self):
        """_parse_s3_url splits bucket and prefix correctly."""
        from benchbox.platforms.firebolt import FireboltAdapter

        bucket, prefix = FireboltAdapter._parse_s3_url("s3://my-bucket/some/prefix/")
        assert bucket == "my-bucket"
        assert prefix == "some/prefix/"

    def test_parses_bucket_only(self):
        """_parse_s3_url handles bucket-only URL."""
        from benchbox.platforms.firebolt import FireboltAdapter

        bucket, prefix = FireboltAdapter._parse_s3_url("s3://my-bucket/")
        assert bucket == "my-bucket"
        assert prefix == ""


# ---------------------------------------------------------------------------
# generate_tuning_clause - distribution path
# ---------------------------------------------------------------------------


class TestGenerateTuningClauseDistribution:
    """Tests for generate_tuning_clause distribution columns path."""

    def test_distribution_generates_primary_index(self):
        """Distribution tuning generates PRIMARY INDEX clause."""
        adapter = _make_core_adapter()

        mock_tuning = Mock()
        mock_tuning.has_any_tuning.return_value = True

        mock_col1 = Mock()
        mock_col1.name = "customer_id"
        mock_col1.order = 1
        mock_col2 = Mock()
        mock_col2.name = "order_date"
        mock_col2.order = 2

        with patch("benchbox.core.tuning.interface.TuningType") as mock_tt:
            mock_tt.DISTRIBUTION = "distribution"
            mock_tt.PARTITIONING = "partitioning"

            def _get_cols(tuning_type):
                if tuning_type == mock_tt.DISTRIBUTION:
                    return [mock_col1, mock_col2]
                return []

            mock_tuning.get_columns_by_type.side_effect = _get_cols
            clause = adapter.generate_tuning_clause(mock_tuning)

        assert "PRIMARY INDEX" in clause
        assert "customer_id" in clause
        assert "order_date" in clause

    def test_both_distribution_and_partition(self):
        """Distribution + partition generates both clauses."""
        adapter = _make_core_adapter()

        mock_tuning = Mock()
        mock_tuning.has_any_tuning.return_value = True

        mock_dist_col = Mock()
        mock_dist_col.name = "user_id"
        mock_dist_col.order = 1

        mock_part_col = Mock()
        mock_part_col.name = "event_date"
        mock_part_col.order = 1

        with patch("benchbox.core.tuning.interface.TuningType") as mock_tt:
            mock_tt.DISTRIBUTION = "distribution"
            mock_tt.PARTITIONING = "partitioning"

            def _get_cols(tuning_type):
                if tuning_type == mock_tt.DISTRIBUTION:
                    return [mock_dist_col]
                if tuning_type == mock_tt.PARTITIONING:
                    return [mock_part_col]
                return []

            mock_tuning.get_columns_by_type.side_effect = _get_cols
            clause = adapter.generate_tuning_clause(mock_tuning)

        assert "PRIMARY INDEX" in clause
        assert "PARTITION BY" in clause


# ---------------------------------------------------------------------------
# supports_tuning_type - ImportError path
# ---------------------------------------------------------------------------


class TestSupportsTuningTypeImportError:
    """Tests for supports_tuning_type when TuningType is unavailable."""

    def test_import_error_returns_false(self):
        """supports_tuning_type returns False when TuningType can't be imported."""
        adapter = _make_core_adapter()

        with patch("benchbox.core.tuning.interface.TuningType", side_effect=ImportError("no tuning")):
            # patch the actual import location
            with patch.dict("sys.modules", {"benchbox.core.tuning.interface": None}):
                result = adapter.supports_tuning_type("anything")

        assert result is False


# ---------------------------------------------------------------------------
# _get_existing_tables
# ---------------------------------------------------------------------------


class TestGetExistingTables:
    """Tests for _get_existing_tables."""

    def test_returns_lowercase_table_names(self):
        """_get_existing_tables returns lowercase table names."""
        adapter = _make_core_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("LINEITEM",), ("ORDERS",), ("Customer",)]

        result = adapter._get_existing_tables(mock_conn)

        assert result == ["lineitem", "orders", "customer"]

    def test_returns_empty_on_error(self):
        """_get_existing_tables returns empty list on error."""
        adapter = _make_core_adapter()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("SHOW TABLES failed")

        result = adapter._get_existing_tables(mock_conn)

        assert result == []


# ---------------------------------------------------------------------------
# analyze_table
# ---------------------------------------------------------------------------


class TestAnalyzeTable:
    """Tests for analyze_table (Firebolt auto-collects stats)."""

    def test_analyze_is_noop(self):
        """analyze_table does not execute any SQL (Firebolt auto-collects)."""
        adapter = _make_core_adapter()

        mock_conn = Mock()

        # Should not raise and should not interact with the connection
        adapter.analyze_table(mock_conn, "lineitem")

        mock_conn.cursor.assert_not_called()


# ---------------------------------------------------------------------------
# apply_platform_optimizations
# ---------------------------------------------------------------------------


class TestApplyPlatformOptimizations:
    """Tests for apply_platform_optimizations."""

    def test_none_config_is_noop(self):
        """apply_platform_optimizations returns early for None config."""
        adapter = _make_core_adapter()
        adapter.apply_platform_optimizations(None, Mock())  # Should not raise

    def test_valid_config_logs_info(self):
        """apply_platform_optimizations logs informational message."""
        adapter = _make_core_adapter()

        mock_config = Mock()
        with patch.object(adapter.logger, "info") as mock_log:
            adapter.apply_platform_optimizations(mock_config, Mock())

        mock_log.assert_called_once()
        assert "optimized" in mock_log.call_args[0][0].lower()


# ---------------------------------------------------------------------------
# apply_unified_tuning
# ---------------------------------------------------------------------------


class TestApplyUnifiedTuning:
    """Tests for apply_unified_tuning."""

    def test_none_config_returns_early(self):
        """apply_unified_tuning returns early for None input."""
        adapter = _make_core_adapter()
        adapter.apply_unified_tuning(None, Mock())  # Should not raise

    def test_delegates_to_sub_methods(self):
        """apply_unified_tuning calls each sub-method."""
        adapter = _make_core_adapter()

        mock_config = Mock()
        mock_config.primary_keys = Mock()
        mock_config.foreign_keys = Mock()
        mock_config.platform_optimizations = Mock()
        mock_config.table_tunings = {"tbl1": Mock()}

        with (
            patch.object(adapter, "apply_constraint_configuration") as mock_constraint,
            patch.object(adapter, "apply_platform_optimizations") as mock_opt,
            patch.object(adapter, "apply_table_tunings") as mock_table,
        ):
            adapter.apply_unified_tuning(mock_config, Mock())

        mock_constraint.assert_called_once()
        mock_opt.assert_called_once()
        mock_table.assert_called_once()


# ---------------------------------------------------------------------------
# from_config - mode override path
# ---------------------------------------------------------------------------


class TestFromConfigCoreOverride:
    """Tests for from_config core mode override."""

    def test_core_mode_override_sets_default_url(self):
        """from_config with deployment_mode=core sets default URL."""
        from benchbox.platforms.firebolt import FireboltAdapter

        config = {
            "deployment_mode": "core",
            "benchmark": "tpch",
            "scale_factor": 1.0,
        }
        adapter = FireboltAdapter.from_config(config)

        assert adapter.deployment_mode == "core"
        assert adapter.url == "http://localhost:3473"

    def test_cloud_from_config_with_s3(self):
        """from_config passes s3_staging_url through."""
        from benchbox.platforms.firebolt import FireboltAdapter

        config = {
            "client_id": "cid",
            "client_secret": "csec",
            "account_name": "acct",
            "engine_name": "eng",
            "s3_staging_url": "s3://bucket/prefix/",
            "s3_region": "us-east-1",
            "benchmark": "tpch",
            "scale_factor": 1.0,
        }
        adapter = FireboltAdapter.from_config(config)

        assert adapter.s3_staging_url == "s3://bucket/prefix/"
        assert adapter.s3_region == "us-east-1"


# ---------------------------------------------------------------------------
# _build_firebolt_config
# ---------------------------------------------------------------------------


class TestBuildFireboltConfig:
    """Tests for the _build_firebolt_config module-level function."""

    def test_builds_config_with_merged_options(self):
        """_build_firebolt_config merges saved_creds < options < overrides."""
        from benchbox.platforms.firebolt import _build_firebolt_config

        mock_info = Mock()
        mock_info.display_name = "Firebolt"
        mock_info.driver_package = "firebolt-sdk"

        mock_cred_mgr = Mock()
        mock_cred_mgr.get_platform_credentials.return_value = {
            "client_id": "saved-id",
            "client_secret": "saved-secret",
        }

        options = {"account_name": "options-acct"}
        overrides = {
            "engine_name": "override-engine",
            "benchmark": "tpch",
            "scale_factor": 1.0,
        }

        with patch("benchbox.security.credentials.CredentialManager", return_value=mock_cred_mgr):
            config = _build_firebolt_config("firebolt", options, overrides, mock_info)

        assert config.client_id == "saved-id"
        assert config.account_name == "options-acct"
        assert config.engine_name == "override-engine"

    def test_builds_config_without_platform_info(self):
        """_build_firebolt_config handles None info gracefully."""
        from benchbox.platforms.firebolt import _build_firebolt_config

        mock_cred_mgr = Mock()
        mock_cred_mgr.get_platform_credentials.return_value = {}

        overrides = {"benchmark": "tpch", "scale_factor": 1.0}

        with patch("benchbox.security.credentials.CredentialManager", return_value=mock_cred_mgr):
            config = _build_firebolt_config("firebolt", {}, overrides, None)

        assert config is not None

    def test_explicit_database_override_is_used(self):
        """_build_firebolt_config uses explicit database override when provided."""
        from benchbox.platforms.firebolt import _build_firebolt_config

        mock_info = Mock()
        mock_info.display_name = "Firebolt"
        mock_info.driver_package = "firebolt-sdk"

        mock_cred_mgr = Mock()
        mock_cred_mgr.get_platform_credentials.return_value = {}

        overrides = {
            "database": "explicit_db",
            "benchmark": "tpch",
            "scale_factor": 1.0,
        }

        with patch("benchbox.security.credentials.CredentialManager", return_value=mock_cred_mgr):
            config = _build_firebolt_config("firebolt", {}, overrides, mock_info)

        assert config.database == "explicit_db"


# ---------------------------------------------------------------------------
# _quote_identifier edge cases
# ---------------------------------------------------------------------------


class TestQuoteIdentifier:
    """Tests for _quote_identifier."""

    def test_quotes_simple_name(self):
        adapter = _make_core_adapter()
        assert adapter._quote_identifier("lineitem") == '"lineitem"'

    def test_escapes_embedded_quotes(self):
        adapter = _make_core_adapter()
        assert adapter._quote_identifier('weird"name') == '"weird""name"'

    def test_empty_name_raises(self):
        adapter = _make_core_adapter()
        with pytest.raises(ValueError, match="non-empty"):
            adapter._quote_identifier("")

    def test_non_string_raises(self):
        adapter = _make_core_adapter()
        with pytest.raises(ValueError, match="non-empty"):
            adapter._quote_identifier(None)


# ---------------------------------------------------------------------------
# configure_for_benchmark
# ---------------------------------------------------------------------------


class TestConfigureForBenchmark:
    """Tests for configure_for_benchmark."""

    def test_tpch_is_accepted(self):
        """configure_for_benchmark works for tpch."""
        adapter = _make_core_adapter()
        adapter.configure_for_benchmark(Mock(), "tpch")  # Should not raise

    def test_tpcds_is_accepted(self):
        """configure_for_benchmark works for tpcds."""
        adapter = _make_core_adapter()
        adapter.configure_for_benchmark(Mock(), "tpcds")

    def test_generic_type_accepted(self):
        """configure_for_benchmark works for generic benchmark types."""
        adapter = _make_core_adapter()
        adapter.configure_for_benchmark(Mock(), "custom_benchmark")
