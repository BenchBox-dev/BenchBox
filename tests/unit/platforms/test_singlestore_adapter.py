"""Tests for SingleStore platform adapter.

Tests the SingleStoreAdapter for both Helios (cloud) and self-managed
SingleStore deployments using singlestoredb SDK and LOAD DATA LOCAL INFILE.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import importlib
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from benchbox.platforms.base.data_loading import CsvDialect, DataSource
from benchbox.platforms.singlestore import SingleStoreAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture(autouse=True)
def mock_singlestoredb():
    """Patch singlestoredb SDK so tests run without the package installed."""
    mock_s2 = MagicMock()
    mock_s2.__version__ = "1.0.0"
    with patch("benchbox.platforms.singlestore._s2", mock_s2):
        yield mock_s2


class TestSingleStoreIdentifierValidation:
    """Tests for SQL injection prevention via identifier validation."""

    def test_init_rejects_invalid_database(self):
        """SingleStoreAdapter should reject invalid database names at init time."""
        with pytest.raises(ValueError, match="Invalid database identifier"):
            SingleStoreAdapter(database="DROP TABLE; --")

    def test_init_accepts_valid_database(self):
        """SingleStoreAdapter should accept valid alphanumeric database names."""
        adapter = SingleStoreAdapter(database="benchbox_tpch")
        assert adapter.database == "benchbox_tpch"

    def test_init_rejects_database_with_spaces(self):
        """SingleStoreAdapter should reject database names with spaces."""
        with pytest.raises(ValueError, match="Invalid database identifier"):
            SingleStoreAdapter(database="my database")

    def test_validate_identifier_valid(self):
        """Valid identifiers pass validation."""
        adapter = SingleStoreAdapter()
        assert adapter._validate_identifier("valid_name") is True
        assert adapter._validate_identifier("benchbox") is True
        assert adapter._validate_identifier("tpch_sf1") is True
        assert adapter._validate_identifier("_underscore") is True

    def test_validate_identifier_invalid(self):
        """Invalid identifiers fail validation."""
        adapter = SingleStoreAdapter()
        assert adapter._validate_identifier("") is False
        assert adapter._validate_identifier("1starts_with_digit") is False
        assert adapter._validate_identifier("has-hyphen") is False
        assert adapter._validate_identifier("has space") is False
        assert adapter._validate_identifier(None) is False
        assert adapter._validate_identifier("a" * 129) is False


class TestSingleStoreAdapterInitialization:
    """Test SingleStore adapter initialization and configuration."""

    def test_initialization_default_config(self):
        """Test initialization with default configuration."""
        adapter = SingleStoreAdapter()

        assert adapter.host == "localhost"
        assert adapter.port == 3306
        assert adapter.username == "root"
        assert adapter.database == "benchbox"
        assert adapter.platform_name == "SingleStore"
        assert adapter.get_target_dialect() == "mysql"

    def test_initialization_custom_config(self):
        """Test initialization with custom configuration."""
        adapter = SingleStoreAdapter(
            host="singlestore.example.com",
            port=3307,
            username="admin",
            password="secret",
            database="my_benchmark",
        )

        assert adapter.host == "singlestore.example.com"
        assert adapter.port == 3307
        assert adapter.username == "admin"
        assert adapter.password == "secret"
        assert adapter.database == "my_benchmark"

    def test_init_uses_simple_defaults_not_env_vars(self):
        """Test that __init__ uses simple defaults; env var resolution is the builder's job."""
        with patch.dict(
            "os.environ",
            {
                "SINGLESTORE_HOST": "env-host",
                "SINGLESTORE_PORT": "3308",
                "SINGLESTORE_USER": "env-user",
                "SINGLESTORE_PASSWORD": "env-pass",
            },
        ):
            # Direct construction bypasses the builder; __init__ uses Python defaults.
            adapter = SingleStoreAdapter()

        assert adapter.host == "localhost"
        assert adapter.port == 3306
        assert adapter.username == "root"
        assert adapter.password is None

    def test_builder_resolves_env_vars(self):
        """Test that the config builder (_build_singlestore_config) resolves env vars."""
        from benchbox.platforms.singlestore import _build_singlestore_config

        with (
            patch("benchbox.security.credentials.CredentialManager.get_platform_credentials", return_value={}),
            patch.dict(
                "os.environ",
                {
                    "SINGLESTORE_HOST": "env-host",
                    "SINGLESTORE_PORT": "3308",
                    "SINGLESTORE_USER": "env-user",
                    "SINGLESTORE_PASSWORD": "env-pass",
                },
            ),
        ):
            config = _build_singlestore_config("singlestore", {}, {}, None)

        assert config.host == "env-host"
        assert config.port == 3308
        assert config.username == "env-user"
        assert config.password == "env-pass"

    def test_dialect_is_mysql(self):
        """Test that SingleStore uses the 'mysql' SQLGlot dialect."""
        adapter = SingleStoreAdapter()

        assert adapter.get_target_dialect() == "mysql"
        assert adapter._dialect == "mysql"

    def test_helios_endpoint_accepted(self):
        """Test that Helios cloud endpoints (*.singlestore.com) are accepted."""
        adapter = SingleStoreAdapter(
            host="xyz123.singlestore.com",
            port=3306,
            username="admin",
            password="secret",
        )

        assert adapter.host == "xyz123.singlestore.com"


class TestSingleStoreFromConfig:
    """Test from_config() factory method."""

    def test_from_config_basic(self):
        """Test from_config() with basic options."""
        config = {
            "host": "my-singlestore-host",
            "port": 3306,
            "database": "test_db",
            "username": "root",
            "password": "pass",
        }

        adapter = SingleStoreAdapter.from_config(config)

        assert adapter.host == "my-singlestore-host"
        assert adapter.port == 3306
        assert adapter.database == "test_db"

    def test_from_config_generates_database_name(self):
        """Test from_config() generates database name from benchmark config."""
        config = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
        }

        adapter = SingleStoreAdapter.from_config(config)

        assert adapter.database == "benchbox_tpch_sf001"

    def test_from_config_default_database(self):
        """Test from_config() uses 'benchbox' as default database."""
        config = {}

        adapter = SingleStoreAdapter.from_config(config)

        assert adapter.database == "benchbox"

    def test_from_config_env_database(self):
        """Test from_config() picks up SINGLESTORE_DATABASE env var."""
        config = {}

        with patch.dict("os.environ", {"SINGLESTORE_DATABASE": "env_db"}):
            adapter = SingleStoreAdapter.from_config(config)

        assert adapter.database == "env_db"


class TestSingleStoreConnection:
    """Test connection creation and management."""

    def test_create_connection(self):
        """Test connection creation via singlestoredb SDK."""
        adapter = SingleStoreAdapter(
            host="localhost",
            port=3306,
            database="test_db",
            username="root",
            password="",
        )

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)

        with (
            patch.object(adapter, "handle_existing_database"),
            patch.object(adapter, "check_server_database_exists", return_value=True),
            patch("benchbox.platforms.singlestore._s2") as mock_s2,
        ):
            mock_s2.connect.return_value = mock_connection
            connection = adapter.create_connection()

        assert connection == mock_connection
        mock_s2.connect.assert_called_once()
        call_kwargs = mock_s2.connect.call_args.kwargs
        assert call_kwargs["host"] == "localhost"
        assert call_kwargs["port"] == 3306
        assert call_kwargs["database"] == "test_db"
        assert call_kwargs["user"] == "root"
        assert call_kwargs["local_infile"] is True

    def test_create_connection_creates_database_if_missing(self):
        """Test that create_connection creates database if it doesn't exist."""
        adapter = SingleStoreAdapter(database="new_db")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)

        with (
            patch.object(adapter, "handle_existing_database"),
            patch.object(adapter, "check_server_database_exists", return_value=False),
            patch.object(adapter, "_create_database") as mock_create_db,
            patch("benchbox.platforms.singlestore._s2") as mock_s2,
        ):
            mock_s2.connect.return_value = mock_connection
            adapter.create_connection()

        mock_create_db.assert_called_once()

    def test_create_connection_translates_2003_to_runtime_error(self):
        """Test that create_connection converts 2003 (server unreachable) into an actionable RuntimeError."""
        adapter = SingleStoreAdapter(host="localhost", port=3306)

        with patch.object(adapter, "handle_existing_database") as mock_handle:
            mock_handle.side_effect = Exception(2003, "Can't connect to MySQL server on 'localhost'")

            with pytest.raises(RuntimeError, match="Cannot connect to SingleStore at localhost:3306"):
                adapter.create_connection()

    def test_close_connection(self):
        """Test connection closing."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        adapter.close_connection(mock_connection)
        mock_connection.close.assert_called_once()

    def test_close_connection_none(self):
        """Test closing None connection doesn't raise."""
        adapter = SingleStoreAdapter()

        # Should not raise
        adapter.close_connection(None)

    def test_test_connection_success(self):
        """Test successful connection test."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)

        with patch("benchbox.platforms.singlestore._s2") as mock_s2:
            mock_s2.connect.return_value = mock_connection
            result = adapter.test_connection()

        assert result is True
        mock_cursor.execute.assert_called_with("SELECT 1")

    def test_test_connection_failure(self):
        """Test failed connection test."""
        adapter = SingleStoreAdapter()

        with patch("benchbox.platforms.singlestore._s2") as mock_s2:
            mock_s2.connect.side_effect = Exception("Connection refused")
            result = adapter.test_connection()

        assert result is False


class TestSingleStoreDatabaseOperations:
    """Test database existence checking and management."""

    def test_check_server_database_exists_true(self):
        """Test database existence check when database exists."""
        adapter = SingleStoreAdapter(database="test_db")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("information_schema",), ("test_db",), ("other_db",)]

        with patch("benchbox.platforms.singlestore._s2") as mock_s2:
            mock_s2.connect.return_value = mock_connection
            result = adapter.check_server_database_exists()

        assert result is True
        mock_cursor.execute.assert_called_with("SHOW DATABASES")

    def test_check_server_database_exists_false(self):
        """Test database existence check when database doesn't exist."""
        adapter = SingleStoreAdapter(database="nonexistent_db")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("information_schema",), ("other_db",)]

        with patch("benchbox.platforms.singlestore._s2") as mock_s2:
            mock_s2.connect.return_value = mock_connection
            result = adapter.check_server_database_exists()

        assert result is False

    def test_check_server_database_exists_connection_error(self):
        """Test database check returns False on generic (non-2003) errors."""
        adapter = SingleStoreAdapter()

        with patch("benchbox.platforms.singlestore._s2") as mock_s2:
            mock_s2.connect.side_effect = Exception("Connection refused")
            result = adapter.check_server_database_exists()

        assert result is False

    def test_check_server_database_exists_server_unreachable(self):
        """Test database check re-raises when error code is 2003 (server unreachable).

        CR_CONN_HOST_ERROR (2003) means the server itself cannot be reached.
        Swallowing it and returning False would mislead callers into thinking
        the database is simply absent rather than the server being down.
        """
        adapter = SingleStoreAdapter()

        with patch("benchbox.platforms.singlestore._s2") as mock_s2:
            mock_s2.connect.side_effect = Exception(2003, "Can't connect to MySQL server on 'localhost'")

            with pytest.raises(Exception, match="Can't connect"):
                adapter.check_server_database_exists()

    def test_drop_database(self):
        """Test database dropping."""
        adapter = SingleStoreAdapter(database="drop_me")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        with patch("benchbox.platforms.singlestore._s2") as mock_s2:
            mock_s2.connect.return_value = mock_connection
            adapter.drop_database()

        mock_cursor.execute.assert_called_with("DROP DATABASE IF EXISTS `drop_me`")

    def test_drop_database_invalid_identifier(self):
        """Test drop database rejects invalid identifiers."""
        adapter = SingleStoreAdapter()

        with pytest.raises(ValueError, match="Invalid database identifier"):
            adapter.drop_database(database="invalid; DROP TABLE")

    def test_create_database(self):
        """Test database creation."""
        adapter = SingleStoreAdapter(database="new_db")

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        with patch("benchbox.platforms.singlestore._s2") as mock_s2:
            mock_s2.connect.return_value = mock_connection
            adapter._create_database()

        mock_cursor.execute.assert_called_with("CREATE DATABASE IF NOT EXISTS `new_db`")

    def test_get_existing_tables(self):
        """Test getting list of existing tables."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("CUSTOMER",), ("orders",), ("LineItem",)]

        tables = adapter._get_existing_tables(mock_connection)

        assert tables == ["customer", "orders", "lineitem"]
        mock_cursor.execute.assert_called_with("SHOW TABLES")


class TestSingleStoreDDL:
    """Test DDL generation for shard keys and sort keys."""

    def test_shard_key_tpch_lineitem(self):
        """Test shard key for lineitem uses l_orderkey."""
        adapter = SingleStoreAdapter()
        clause = adapter.get_shard_key_clause("lineitem")
        assert clause == "SHARD KEY (l_orderkey)"

    def test_shard_key_tpch_orders(self):
        """Test shard key for orders table."""
        adapter = SingleStoreAdapter()
        clause = adapter.get_shard_key_clause("orders")
        assert clause == "SHARD KEY (o_orderkey)"

    def test_shard_key_tpch_customer(self):
        """Test shard key for customer table."""
        adapter = SingleStoreAdapter()
        clause = adapter.get_shard_key_clause("customer")
        assert clause == "SHARD KEY (c_custkey)"

    def test_shard_key_unknown_table(self):
        """Unknown tables get empty shard key (random distribution)."""
        adapter = SingleStoreAdapter()
        clause = adapter.get_shard_key_clause("unknown_table")
        assert clause == "SHARD KEY ()"

    def test_sort_key_tpch_lineitem(self):
        """Test sort key for lineitem is (l_orderkey, l_linenumber)."""
        adapter = SingleStoreAdapter()
        clause = adapter.get_sort_key_clause("lineitem")
        assert "l_orderkey" in clause
        assert "l_linenumber" in clause
        assert clause.startswith("SORT KEY")

    def test_sort_key_tpch_orders(self):
        """Test sort key for orders table."""
        adapter = SingleStoreAdapter()
        clause = adapter.get_sort_key_clause("orders")
        assert clause == "SORT KEY (o_orderkey)"

    def test_sort_key_unknown_table(self):
        """Unknown tables return empty sort key."""
        adapter = SingleStoreAdapter()
        clause = adapter.get_sort_key_clause("unknown_table")
        assert clause == ""

    def test_reference_table_nation(self):
        """Nation should be a reference table."""
        adapter = SingleStoreAdapter()
        assert adapter.is_reference_table("nation") is True

    def test_reference_table_region(self):
        """Region should be a reference table."""
        adapter = SingleStoreAdapter()
        assert adapter.is_reference_table("region") is True

    def test_not_reference_table_lineitem(self):
        """Lineitem is not a reference table."""
        adapter = SingleStoreAdapter()
        assert adapter.is_reference_table("lineitem") is False

    def test_not_reference_table_orders(self):
        """Orders is not a reference table."""
        adapter = SingleStoreAdapter()
        assert adapter.is_reference_table("orders") is False


class TestSingleStoreDataLoading:
    """Test LOAD DATA LOCAL INFILE bulk loading."""

    def test_load_data_infile_standard(self):
        """Test LOAD DATA LOCAL INFILE for standard (non-TPC) CSV files."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        # fetchone returns: pre-count (0), then post-count (1000)
        mock_cursor.fetchone.side_effect = [(0,), (1000,)]

        dialect = CsvDialect(delimiter=",", has_header=False, null_marker=None, normalize_booleans=False, quote=None)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("1,foo,bar\n2,baz,qux\n")
            tmp_path = f.name

        try:
            row_count = adapter._load_data_infile(
                mock_connection, "customer", Path(tmp_path), dialect, strip_trailing_delim=False
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        assert row_count == 1000
        # execute calls: pre-count SELECT, LOAD DATA, post-count SELECT
        load_call = mock_cursor.execute.call_args_list[1]
        assert "LOAD DATA LOCAL INFILE" in load_call.args[0]
        assert "`customer`" in load_call.args[0]

    def test_load_data_infile_tpc_format(self):
        """Test LOAD DATA LOCAL INFILE strips trailing delimiter for TPC format."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        # fetchone returns: pre-count (0), then post-count (5)
        mock_cursor.fetchone.side_effect = [(0,), (5,)]

        dialect = CsvDialect(delimiter="|", has_header=False, null_marker="", normalize_booleans=False, quote=None)
        # TPC format: each line ends with trailing pipe
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tbl", delete=False, encoding="utf-8") as f:
            f.write("1|foo|bar|\n2|baz|qux|\n")
            tmp_path = f.name

        try:
            row_count = adapter._load_data_infile(
                mock_connection, "lineitem", Path(tmp_path), dialect, strip_trailing_delim=True
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        assert row_count == 5
        # LOAD DATA is the second execute call (after pre-count SELECT)
        load_call = mock_cursor.execute.call_args_list[1]
        assert "LOAD DATA LOCAL INFILE" in load_call.args[0]

    def test_load_data_infile_delta_count_on_retry(self):
        """Test that _load_data_infile returns only newly loaded rows, not cumulative."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        # Simulate retry: 500 pre-existing rows, 700 after load → delta = 200
        mock_cursor.fetchone.side_effect = [(500,), (700,)]

        dialect = CsvDialect(delimiter=",", has_header=False, null_marker=None, normalize_booleans=False, quote=None)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("1,foo\n")
            tmp_path = f.name

        try:
            row_count = adapter._load_data_infile(
                mock_connection, "part", Path(tmp_path), dialect, strip_trailing_delim=False
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        assert row_count == 200

    @staticmethod
    def _make_benchmark(tables: dict[str, object]) -> Mock:
        """Build a Mock benchmark with csv_* attrs explicitly pinned to None.

        Without this, getattr(mock, "csv_delimiter", None) returns a child Mock
        (truthy, not None), flipping resolve_csv_dialect into the benchmark-attr
        branch with Mock objects as dialect fields. Tests then pass only because
        the patched _load_data_infile never consumes the dialect — a future test
        exercising the real helper would silently load garbage.
        """
        mock_benchmark = Mock()
        mock_benchmark.tables = tables
        mock_benchmark.csv_delimiter = None
        mock_benchmark.csv_has_header = None
        mock_benchmark.csv_normalize_booleans = None
        mock_benchmark.csv_null_marker = None
        return mock_benchmark

    def test_load_data_rejects_invalid_identifiers(self):
        """Test that load_data raises ValueError for invalid table identifiers."""
        adapter = SingleStoreAdapter()

        mock_benchmark = self._make_benchmark({"invalid; drop": "/path/to/file"})
        mock_connection = Mock()

        with pytest.raises(ValueError, match="Invalid table identifier"):
            adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))

    def test_load_data_skips_missing_files(self):
        """Test that load_data skips tables whose data files don't exist."""
        adapter = SingleStoreAdapter()

        mock_benchmark = self._make_benchmark({"orders": "/nonexistent/path/orders.tbl"})
        mock_connection = Mock()

        table_stats, _, _ = adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))

        assert table_stats["orders"] == 0

    def test_load_data_returns_per_table_timings(self):
        """Test that load_data returns per-table timing metadata."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("1,foo\n")
            tmp_path = f.name

        mock_benchmark = self._make_benchmark({"part": tmp_path})

        try:
            with (
                patch.object(adapter, "_load_data_infile", return_value=100),
            ):
                table_stats, loading_time, per_table = adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        assert table_stats["part"] == 100
        assert "part" in per_table
        assert per_table["part"]["rows"] == 100
        assert "duration_seconds" in per_table["part"]

    def test_load_data_strips_trailing_delim_for_tbl_files(self):
        """.tbl suffix → strip_trailing_delim=True regardless of dialect.

        TPC-H dbgen emits a spurious trailing pipe after every record.
        The extension is the authoritative discriminator; the dialect null_marker
        is irrelevant for this decision.
        """
        adapter = SingleStoreAdapter()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".tbl", delete=False, encoding="utf-8") as f:
            f.write("1|foo|bar|\n")
            tmp_path = Path(f.name)

        fake_ds = DataSource(
            source_type="manifest_v2",
            tables={"orders": tmp_path},
            table_metadata={"orders": {"csv_delimiter": "|", "csv_null_marker": ""}},
        )
        mock_benchmark = self._make_benchmark({"orders": tmp_path})
        mock_connection = Mock()

        try:
            with (
                patch("benchbox.platforms.singlestore.DataSourceResolver") as mock_resolver_cls,
                patch.object(adapter, "_load_data_infile", return_value=1) as mock_infile,
            ):
                mock_resolver_cls.return_value.resolve.return_value = fake_ds
                adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))
        finally:
            tmp_path.unlink(missing_ok=True)

        assert mock_infile.call_count == 1
        assert mock_infile.call_args.args[4] is True

    def test_load_data_does_not_strip_csv_files_with_null_marker(self):
        """.csv file with csv_null_marker="" → strip_trailing_delim=False.

        Regression guard: a trailing comma on a CSV line is an empty last field
        (NULL), not a spurious terminator. Stripping it would drop that field and
        cause SingleStore error 1261 "row N doesn't contain data for all columns".
        The JoinOrder benchmark is the canonical case — nullable trailing columns
        like episode_of_id produce lines ending with ",".
        """
        adapter = SingleStoreAdapter()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            # JoinOrder title row: id, title, kind_id, production_year, imdb_id (NULL),
            # phonetic_code (NULL), episode_of_id (NULL), season_nr (NULL), episode_nr (NULL),
            # series_years (NULL), md5sum (NULL), imdb_index (NULL).
            # Trailing commas = NULL fields; must NOT be stripped.
            f.write("1,Comedy Adventure,,4,1957,,,,,,,\n")
            tmp_path = Path(f.name)

        fake_ds = DataSource(
            source_type="manifest_v2",
            tables={"title": tmp_path},
            table_metadata={"title": {"csv_delimiter": ",", "csv_null_marker": ""}},
        )
        mock_benchmark = self._make_benchmark({"title": tmp_path})
        mock_connection = Mock()

        try:
            with (
                patch("benchbox.platforms.singlestore.DataSourceResolver") as mock_resolver_cls,
                patch.object(adapter, "_load_data_infile", return_value=1) as mock_infile,
            ):
                mock_resolver_cls.return_value.resolve.return_value = fake_ds
                adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))
        finally:
            tmp_path.unlink(missing_ok=True)

        assert mock_infile.call_count == 1
        passed_dialect = mock_infile.call_args.args[3]
        passed_strip = mock_infile.call_args.args[4]
        assert passed_dialect.null_marker == ""
        assert passed_strip is False

    def test_load_data_benchmark_attr_null_marker_on_csv_does_not_strip(self):
        """.csv with benchmark-attr csv_null_marker="" → null_marker="" in dialect, strip=False.

        Exercises path (b): no manifest table_metadata entry, so resolve_csv_dialect
        falls through to benchmark instance attributes.  csv_null_marker="" on the
        benchmark produces a dialect with null_marker="" but the .csv extension still
        keeps strip_trailing_delim=False.
        """
        adapter = SingleStoreAdapter()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("1,Comedy Adventure,,4,1957,,,,,,,\n")
            tmp_path = Path(f.name)

        # No table_metadata entry → path (a) is skipped; path (b) reads benchmark attrs.
        fake_ds = DataSource(
            source_type="manifest_v2",
            tables={"title": tmp_path},
            table_metadata={},
        )
        mock_benchmark = self._make_benchmark({"title": tmp_path})
        mock_benchmark.csv_delimiter = ","
        mock_benchmark.csv_null_marker = ""  # path (b) source of null_marker
        mock_connection = Mock()

        try:
            with (
                patch("benchbox.platforms.singlestore.DataSourceResolver") as mock_resolver_cls,
                patch.object(adapter, "_load_data_infile", return_value=1) as mock_infile,
            ):
                mock_resolver_cls.return_value.resolve.return_value = fake_ds
                adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))
        finally:
            tmp_path.unlink(missing_ok=True)

        assert mock_infile.call_count == 1
        passed_dialect = mock_infile.call_args.args[3]
        passed_strip = mock_infile.call_args.args[4]
        # Benchmark path (b): null_marker="" from benchmark attr
        assert passed_dialect.null_marker == ""
        # Extension is .csv → never strip, regardless of null_marker
        assert passed_strip is False


class TestSingleStoreQueryExecution:
    """Test query execution."""

    def test_execute_query(self):
        """Test query execution via execute_sql_query."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()

        with patch("benchbox.platforms.singlestore.execute_sql_query") as mock_exec:
            mock_exec.return_value = {"query_id": "Q1", "duration": 0.5}
            result = adapter.execute_query(mock_connection, "SELECT 1", "Q1")

        assert result["query_id"] == "Q1"
        mock_exec.assert_called_once()

    def test_get_query_plan(self):
        """Test EXPLAIN for query plan capture."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("id", "select_type", "table"), ("1", "SIMPLE", "lineitem")]

        plan = adapter.get_query_plan(mock_connection, "SELECT * FROM lineitem")

        assert plan is not None
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args.args[0]
        assert call_args.startswith("EXPLAIN")
        assert "SELECT * FROM lineitem" in call_args

    def test_get_query_plan_error(self):
        """Test get_query_plan returns error string on failure."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("EXPLAIN failed")

        plan = adapter.get_query_plan(mock_connection, "SELECT 1")

        assert "Failed to get query plan" in plan


class TestSingleStorePlatformInfo:
    """Test platform information retrieval."""

    def test_get_platform_info_without_connection(self):
        """Test platform info without an active connection."""
        adapter = SingleStoreAdapter(host="test-host", port=3306)

        info = adapter.get_platform_info()

        assert info["platform_type"] == "singlestore"
        assert info["platform_name"] == "SingleStore"
        assert info["host"] == "test-host"
        assert info["port"] == 3306
        assert info["dialect"] == "mysql"

    def test_get_platform_info_with_connection(self):
        """Test platform info with an active connection."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [("8.0.12",), ("benchbox",)]

        info = adapter.get_platform_info(mock_connection)

        assert "platform_version" in info
        assert info["platform_version"] == "8.0.12"

    def test_analyze_table(self):
        """Test ANALYZE TABLE execution."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter.analyze_table(mock_connection, "lineitem")

        mock_cursor.execute.assert_called_with("ANALYZE TABLE `lineitem`")

    def test_analyze_table_invalid_identifier(self):
        """Test that analyze_table skips invalid table names."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Should not raise and should not execute the dangerous SQL
        adapter.analyze_table(mock_connection, "invalid; DROP")

        mock_cursor.execute.assert_not_called()


class TestSingleStoreConfigureBenchmark:
    """Test benchmark-specific configuration."""

    def test_configure_for_benchmark(self):
        """Test that configure_for_benchmark sets session variables."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Should not raise
        adapter.configure_for_benchmark(mock_connection, "olap")

        mock_cursor.execute.assert_called()
        mock_cursor.close.assert_called()

    def test_configure_for_benchmark_handles_errors_gracefully(self):
        """Test that configure_for_benchmark tolerates SET failures."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("SET not supported")

        # Should not raise even if SET commands fail
        adapter.configure_for_benchmark(mock_connection, "olap")

    def test_configure_for_benchmark_closes_cursor_on_exception(self):
        """Test that configure_for_benchmark closes cursor even when an unexpected error occurs."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        # Simulate an unexpected non-Exception error
        mock_cursor.execute.side_effect = Exception("SET not supported")

        adapter.configure_for_benchmark(mock_connection, "olap")
        mock_cursor.close.assert_called_once()

    def test_load_data_infile_closes_cursor_on_exception(self):
        """Test that _load_data_infile closes cursor even when LOAD DATA fails."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        # First execute (pre-count SELECT) succeeds, second (LOAD DATA) fails
        mock_cursor.fetchone.return_value = (0,)
        mock_cursor.execute.side_effect = [None, Exception("LOAD DATA failed"), None]

        dialect = CsvDialect(delimiter=",", has_header=False, null_marker=None, normalize_booleans=False, quote=None)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("1,foo,bar\n")
            tmp_path = f.name

        try:
            with pytest.raises(Exception, match="LOAD DATA failed"):
                adapter._load_data_infile(
                    mock_connection, "customer", Path(tmp_path), dialect, strip_trailing_delim=False
                )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        mock_cursor.close.assert_called_once()

    def test_load_data_infile_normalizes_booleans_for_tpcdi(self):
        """Test that normalize_booleans replaces 'True'/'False' with '1'/'0' in TPC-DI data.

        SingleStore STRICT_ALL_TABLES mode rejects 'True'/'False' strings for
        TINYINT(1) / BOOLEAN columns (error 1264).  TPC-DI generates these values.
        """
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [(0,), (2,)]

        # TPC-DI style data: has 'True'/'False' for BOOLEAN columns
        tpcdi_data = "1|SK001|Active|LastName|True|1|2010-01-01|9999-12-31\n2|SK002|Inactive|OtherName|False|2|2010-01-01|9999-12-31\n"

        # Capture the temp file content when LOAD DATA is called (before it's deleted).
        captured_temp_content: list[str] = []

        def capture_on_load(sql: str) -> None:
            if "LOAD DATA LOCAL INFILE" in sql:
                path_part = sql.split("'")[1]
                try:
                    captured_temp_content.append(Path(path_part).read_text(encoding="utf-8"))
                except FileNotFoundError:
                    pass

        mock_cursor.execute.side_effect = capture_on_load

        dialect = CsvDialect(delimiter="|", has_header=False, null_marker="", normalize_booleans=True, quote=None)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tbl", delete=False, encoding="utf-8") as f:
            f.write(tpcdi_data)
            tmp_path = f.name

        try:
            adapter._load_data_infile(
                mock_connection, "dimcustomer", Path(tmp_path), dialect, strip_trailing_delim=True
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        # Verify the LOAD DATA was called and temp file had normalized content
        assert len(captured_temp_content) == 1, "LOAD DATA was not called"
        content = captured_temp_content[0]
        assert "True" not in content, "True was not normalized to 1"
        assert "False" not in content, "False was not normalized to 0"
        assert "|1|" in content, "Expected |1| (True→1) in normalized content"
        assert "|0|" in content, "Expected |0| (False→0) in normalized content"

    def test_load_data_infile_skip_header_emits_ignore_lines(self):
        """has_header=True manifest metadata → IGNORE 1 LINES in LOAD DATA SQL.

        Proves the table_metadata → resolve_csv_dialect → SQL pipeline end-to-end.
        """
        adapter = SingleStoreAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [(0,), (1,)]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("time,host,value\n2026-01-01,h1,42\n")
            tmp_path = f.name

        fake_ds = DataSource(
            source_type="manifest_v2",
            tables={"metrics": Path(tmp_path)},
            table_metadata={"metrics": {"csv_has_header": True, "csv_delimiter": ","}},
        )

        try:
            with patch("benchbox.platforms.singlestore.DataSourceResolver") as mock_resolver_cls:
                mock_resolver_cls.return_value.resolve.return_value = fake_ds
                adapter.load_data(Mock(), mock_connection, Path(tmp_path).parent)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        assert len(mock_cursor.execute.call_args_list) >= 2, "LOAD DATA was not called"
        load_sql = mock_cursor.execute.call_args_list[1].args[0]
        assert "IGNORE 1 LINES" in load_sql

    def test_load_data_infile_omits_ignore_lines_by_default(self):
        """has_header=False manifest metadata → IGNORE 1 LINES absent from LOAD DATA SQL.

        Proves the table_metadata → resolve_csv_dialect → SQL pipeline end-to-end.
        """
        adapter = SingleStoreAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [(0,), (1,)]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("1,foo,bar\n")
            tmp_path = f.name

        fake_ds = DataSource(
            source_type="manifest_v2",
            tables={"customer": Path(tmp_path)},
            table_metadata={"customer": {"csv_has_header": False, "csv_delimiter": ","}},
        )

        try:
            with patch("benchbox.platforms.singlestore.DataSourceResolver") as mock_resolver_cls:
                mock_resolver_cls.return_value.resolve.return_value = fake_ds
                adapter.load_data(Mock(), mock_connection, Path(tmp_path).parent)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        assert len(mock_cursor.execute.call_args_list) >= 2, "LOAD DATA was not called"
        load_sql = mock_cursor.execute.call_args_list[1].args[0]
        assert "IGNORE 1 LINES" not in load_sql

    def test_load_data_infile_tbl_emits_null_defined_by_empty(self):
        """csv_null_marker='' in manifest metadata → NULL DEFINED BY '' in LOAD DATA SQL.

        Proves the table_metadata → resolve_csv_dialect → SQL pipeline end-to-end.
        TPC-style .tbl files use empty string to encode SQL NULL.
        """
        adapter = SingleStoreAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [(0,), (1,)]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".tbl", delete=False, encoding="utf-8") as f:
            f.write("1|foo|\n")
            tmp_path = f.name

        fake_ds = DataSource(
            source_type="manifest_v2",
            tables={"lineitem": Path(tmp_path)},
            table_metadata={"lineitem": {"csv_delimiter": "|", "csv_null_marker": ""}},
        )

        try:
            with patch("benchbox.platforms.singlestore.DataSourceResolver") as mock_resolver_cls:
                mock_resolver_cls.return_value.resolve.return_value = fake_ds
                adapter.load_data(Mock(), mock_connection, Path(tmp_path).parent)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        assert len(mock_cursor.execute.call_args_list) >= 2, "LOAD DATA was not called"
        load_sql = mock_cursor.execute.call_args_list[1].args[0]
        assert "NULL DEFINED BY ''" in load_sql

    def test_load_data_infile_csv_omits_null_defined_by_empty(self):
        """csv_null_marker=None in manifest metadata → NULL DEFINED BY absent from LOAD DATA SQL.

        Proves the table_metadata → resolve_csv_dialect → SQL pipeline end-to-end.
        ClickBench-style CSV files use empty columns without a NULL conversion marker.
        """
        adapter = SingleStoreAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [(0,), (1,)]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("1,,bar\n")
            tmp_path = f.name

        fake_ds = DataSource(
            source_type="manifest_v2",
            tables={"hits": Path(tmp_path)},
            table_metadata={"hits": {"csv_delimiter": ",", "csv_null_marker": None}},
        )

        try:
            with patch("benchbox.platforms.singlestore.DataSourceResolver") as mock_resolver_cls:
                mock_resolver_cls.return_value.resolve.return_value = fake_ds
                adapter.load_data(Mock(), mock_connection, Path(tmp_path).parent)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        assert len(mock_cursor.execute.call_args_list) >= 2, "LOAD DATA was not called"
        load_sql = mock_cursor.execute.call_args_list[1].args[0]
        assert "NULL DEFINED BY" not in load_sql

    def test_load_data_infile_always_uses_optionally_enclosed(self):
        """OPTIONALLY ENCLOSED BY '\"' is always present — datavault quoted fields require it.

        Proves the table_metadata → resolve_csv_dialect → SQL pipeline end-to-end.
        """
        adapter = SingleStoreAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [(0,), (1,)]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("1,foo\n")
            tmp_path = f.name

        fake_ds = DataSource(
            source_type="manifest_v2",
            tables={"customer": Path(tmp_path)},
            table_metadata={"customer": {"csv_delimiter": ","}},
        )

        try:
            with patch("benchbox.platforms.singlestore.DataSourceResolver") as mock_resolver_cls:
                mock_resolver_cls.return_value.resolve.return_value = fake_ds
                adapter.load_data(Mock(), mock_connection, Path(tmp_path).parent)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        assert len(mock_cursor.execute.call_args_list) >= 2, "LOAD DATA was not called"
        load_sql = mock_cursor.execute.call_args_list[1].args[0]
        assert "OPTIONALLY ENCLOSED BY '\"'" in load_sql

    def test_load_data_infile_strips_trailing_delim_for_tbl(self):
        """.tbl extension → strip_trailing_delim=True; manifest metadata routes dialect correctly.

        Proves the table_metadata → resolve_csv_dialect → prepare_local_load_file pipeline
        end-to-end: trailing field separator is stripped before LOAD DATA sees the file.
        """
        adapter = SingleStoreAdapter()
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [(0,), (2,)]

        captured_temp_content: list[str] = []

        def capture_on_load(sql: str) -> None:
            if "LOAD DATA LOCAL INFILE" in sql:
                path_part = sql.split("'")[1]
                try:
                    captured_temp_content.append(Path(path_part).read_text(encoding="utf-8"))
                except FileNotFoundError:
                    pass

        mock_cursor.execute.side_effect = capture_on_load

        with tempfile.NamedTemporaryFile(mode="w", suffix=".tbl", delete=False, encoding="utf-8") as f:
            f.write("1|foo|bar|\n2|baz|qux|\n")
            tmp_path = f.name

        fake_ds = DataSource(
            source_type="manifest_v2",
            tables={"lineitem": Path(tmp_path)},
            table_metadata={"lineitem": {"csv_delimiter": "|", "csv_null_marker": ""}},
        )

        try:
            with patch("benchbox.platforms.singlestore.DataSourceResolver") as mock_resolver_cls:
                mock_resolver_cls.return_value.resolve.return_value = fake_ds
                adapter.load_data(Mock(), mock_connection, Path(tmp_path).parent)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        assert len(captured_temp_content) == 1, "LOAD DATA was not called"
        for line in captured_temp_content[0].splitlines():
            assert not line.endswith("|"), f"Trailing delim not stripped from {line!r}"

    def test_load_data_infile_decompresses_gzip(self):
        """LOAD DATA LOCAL INFILE has no native compression — gzip must be decoded inline.

        prepare_local_load_file uses FileFormatRegistry to dispatch to GzipHandler,
        so any algorithm the registry supports is decoded transparently.
        """
        import gzip

        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [(0,), (2,)]

        captured_temp_content: list[str] = []

        def capture_on_load(sql: str) -> None:
            if "LOAD DATA LOCAL INFILE" in sql:
                path_part = sql.split("'")[1]
                try:
                    captured_temp_content.append(Path(path_part).read_text(encoding="utf-8"))
                except FileNotFoundError:
                    pass

        mock_cursor.execute.side_effect = capture_on_load

        # Real gzip-compressed .csv file
        with tempfile.NamedTemporaryFile(suffix=".csv.gz", delete=False) as f:
            tmp_path = f.name
        with gzip.open(tmp_path, "wt", encoding="utf-8") as gz:
            gz.write("1,foo,bar\n2,baz,qux\n")

        dialect = CsvDialect(delimiter=",", has_header=False, null_marker=None, normalize_booleans=False, quote=None)
        try:
            adapter._load_data_infile(mock_connection, "customer", Path(tmp_path), dialect, strip_trailing_delim=False)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        assert len(captured_temp_content) == 1, "LOAD DATA was not called"
        content = captured_temp_content[0]
        # Decompressed content reaches the temp file in plain form
        assert "1,foo,bar" in content
        assert "2,baz,qux" in content


class TestSingleStoreValidation:
    """Test validation methods."""

    def test_validate_platform_capabilities_no_sdk(self):
        """Test validation reports error when singlestoredb is not available."""
        adapter = SingleStoreAdapter()

        with patch("benchbox.platforms.singlestore._s2", None):
            result = adapter.validate_platform_capabilities("olap")

        if result is not None:
            assert not result.is_valid
            assert any("singlestoredb" in e for e in result.errors)

    def test_validate_platform_capabilities_with_sdk(self):
        """Test validation passes when singlestoredb is available."""
        adapter = SingleStoreAdapter()

        mock_s2 = MagicMock()
        mock_s2.__version__ = "1.0.0"

        with patch("benchbox.platforms.singlestore._s2", mock_s2):
            result = adapter.validate_platform_capabilities("olap")

        if result is not None:
            assert result.is_valid

    def test_validate_connection_health_success(self):
        """Test connection health check with a healthy connection."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [(1,), ("8.0.12",), ("benchbox",)]

        result = adapter.validate_connection_health(mock_connection)

        if result is not None:
            assert result.is_valid

    def test_validate_connection_health_failure(self):
        """Test connection health check with a broken connection."""
        adapter = SingleStoreAdapter()

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("Lost connection")

        result = adapter.validate_connection_health(mock_connection)

        if result is not None:
            assert not result.is_valid


@pytest.fixture(scope="module")
def singlestore_ddl_decisions():
    """All Phase.DDL_OPTIMIZE decisions for SingleStore, in registration order."""
    importlib.import_module("benchbox.sql_compat.rules.ddl_optimize.singlestore_ddl_rewrites")

    from benchbox.sql_compat.context import CompatibilityContext, Phase
    from benchbox.sql_compat.registry import REGISTRY

    ctx = CompatibilityContext(
        platform="singlestore",
        platform_version=None,
        benchmark="",
        query_id=None,
        phase=Phase.DDL_OPTIMIZE,
        mode="sql",
        dialect=None,
    )
    return REGISTRY.resolve_all(ctx)


class TestSingleStoreDDLTransformation:
    """Test _transform_create_statement for columnstore DDL injection."""

    # -- combined registry + behavior tests (governance link explicit) --

    def test_strip_fk_rule_registered_and_applied(self, singlestore_ddl_decisions):
        """strip_foreign_keys rule is registered AND the transformer removes FK clauses."""
        rule_ids = [d.rule_id for d in singlestore_ddl_decisions]
        assert "ddl_optimize.singlestore.all.strip_foreign_keys" in rule_ids

        adapter = SingleStoreAdapter()
        stmt = (
            "CREATE TABLE `orders` (\n"
            "  o_orderkey BIGINT,\n"
            "  o_custkey BIGINT,\n"
            "  FOREIGN KEY (o_custkey) REFERENCES customer (c_custkey) ON DELETE CASCADE\n"
            ")"
        )
        result = adapter._transform_create_statement(stmt)
        assert "FOREIGN KEY" not in result
        assert "o_orderkey" in result

    def test_reference_table_rule_registered_and_applied(self, singlestore_ddl_decisions):
        """reference_table_for_dimensions rule is registered AND nation becomes REFERENCE TABLE."""
        rule_ids = [d.rule_id for d in singlestore_ddl_decisions]
        assert "ddl_optimize.singlestore.all.reference_table_for_dimensions" in rule_ids

        adapter = SingleStoreAdapter()
        stmt = "CREATE TABLE `nation` (\n  n_nationkey INT\n)"
        result = adapter._transform_create_statement(stmt)
        assert "CREATE REFERENCE TABLE" in result

    def test_inject_shard_key_rule_registered_and_applied(self, singlestore_ddl_decisions):
        """inject_shard_key rule is registered AND SHARD KEY is injected for lineitem."""
        rule_ids = [d.rule_id for d in singlestore_ddl_decisions]
        assert "ddl_optimize.singlestore.all.inject_shard_key" in rule_ids

        adapter = SingleStoreAdapter()
        stmt = "CREATE TABLE `lineitem` (\n  l_orderkey BIGINT\n)"
        result = adapter._transform_create_statement(stmt)
        assert "SHARD KEY (l_orderkey)" in result

    def test_inject_sort_key_rule_registered_and_applied(self, singlestore_ddl_decisions):
        """inject_sort_key rule is registered AND SORT KEY is injected for lineitem."""
        rule_ids = [d.rule_id for d in singlestore_ddl_decisions]
        assert "ddl_optimize.singlestore.all.inject_sort_key" in rule_ids

        adapter = SingleStoreAdapter()
        stmt = "CREATE TABLE `lineitem` (\n  l_orderkey BIGINT,\n  l_linenumber INT\n)"
        result = adapter._transform_create_statement(stmt)
        assert "SORT KEY (l_orderkey, l_linenumber)" in result

    # -- behavioral tests --

    def test_transform_injects_shard_key(self):
        """Test that SHARD KEY is injected for known TPC-H tables."""
        adapter = SingleStoreAdapter()
        stmt = "CREATE TABLE `lineitem` (\n  l_orderkey BIGINT\n)"
        result = adapter._transform_create_statement(stmt)
        assert "SHARD KEY (l_orderkey)" in result

    def test_transform_injects_sort_key(self):
        """Test that SORT KEY is injected for known TPC-H tables (only columns present in DDL)."""
        adapter = SingleStoreAdapter()
        stmt = "CREATE TABLE `lineitem` (\n  l_orderkey BIGINT,\n  l_linenumber INT\n)"
        result = adapter._transform_create_statement(stmt)
        assert "SORT KEY (l_orderkey, l_linenumber)" in result

    def test_transform_reference_table_nation(self):
        """Test that nation becomes a REFERENCE TABLE."""
        adapter = SingleStoreAdapter()
        stmt = "CREATE TABLE `nation` (\n  n_nationkey INT\n)"
        result = adapter._transform_create_statement(stmt)
        assert "CREATE REFERENCE TABLE" in result
        # Reference tables should NOT have shard/sort keys
        assert "SHARD KEY" not in result
        assert "SORT KEY" not in result

    def test_transform_reference_table_region(self):
        """Test that region becomes a REFERENCE TABLE."""
        adapter = SingleStoreAdapter()
        stmt = "CREATE TABLE region (\n  r_regionkey INT\n)"
        result = adapter._transform_create_statement(stmt)
        assert "CREATE REFERENCE TABLE" in result

    def test_transform_if_not_exists(self):
        """Test that IF NOT EXISTS is preserved and table name is still extracted."""
        adapter = SingleStoreAdapter()
        stmt = "CREATE TABLE IF NOT EXISTS `orders` (\n  o_orderkey BIGINT\n)"
        result = adapter._transform_create_statement(stmt)
        assert "SHARD KEY (o_orderkey)" in result
        assert "SORT KEY (o_orderkey)" in result

    def test_transform_unknown_table_gets_empty_shard(self):
        """Unknown tables get SHARD KEY () for random distribution."""
        adapter = SingleStoreAdapter()
        stmt = "CREATE TABLE `custom_table` (\n  id INT\n)"
        result = adapter._transform_create_statement(stmt)
        assert "SHARD KEY ()" in result

    def test_transform_non_create_passthrough(self):
        """Non-CREATE-TABLE statements pass through unchanged."""
        adapter = SingleStoreAdapter()
        stmt = "INSERT INTO lineitem VALUES (1, 2, 3)"
        result = adapter._transform_create_statement(stmt)
        assert result == stmt

    def test_transform_drop_passthrough(self):
        """DROP TABLE statements pass through unchanged."""
        adapter = SingleStoreAdapter()
        stmt = "DROP TABLE IF EXISTS lineitem"
        result = adapter._transform_create_statement(stmt)
        assert result == stmt

    def test_transform_customer_shard_key(self):
        """Test customer table gets c_custkey shard key."""
        adapter = SingleStoreAdapter()
        stmt = "CREATE TABLE `customer` (\n  c_custkey BIGINT\n)"
        result = adapter._transform_create_statement(stmt)
        assert "SHARD KEY (c_custkey)" in result
        assert "SORT KEY (c_custkey)" in result

    def test_transform_partsupp_compound_sort_key(self):
        """Test partsupp gets compound sort key (only columns present in DDL)."""
        adapter = SingleStoreAdapter()
        stmt = "CREATE TABLE `partsupp` (\n  ps_partkey BIGINT,\n  ps_suppkey BIGINT\n)"
        result = adapter._transform_create_statement(stmt)
        assert "SHARD KEY (ps_partkey)" in result
        assert "SORT KEY (ps_partkey, ps_suppkey)" in result
