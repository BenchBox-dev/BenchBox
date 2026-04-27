"""Setup and connection routines for StarRocks."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from ._dependencies import PYMYSQL_AVAILABLE, pymysql

# Valid database/identifier name pattern
_VALID_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

logger = logging.getLogger(__name__)


def _split_sql_statements(sql: str) -> list[str]:
    """Split SQL on semicolons outside of single-quoted string literals.

    Returns a list of non-empty statement strings (semicolons stripped).
    Handles both backslash escapes and SQL-standard '' doubling inside literals.
    """
    statements: list[str] = []
    current: list[str] = []
    n = len(sql)
    i = 0
    while i < n:
        c = sql[i]
        if c == "'":
            lit_start = i
            i += 1
            while i < n:
                lc = sql[i]
                if lc == "\\" and i + 1 < n:
                    i += 2
                    continue
                if lc == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            current.append(sql[lit_start:i])
        elif c == ";":
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
        else:
            current.append(c)
            i += 1
    stmt = "".join(current).strip()
    if stmt:
        statements.append(stmt)
    return statements


class _StarRocksConnectionWrapper:
    """Thin adapter that adds a DuckDB-compatible execute() to a PyMySQL connection.

    PyMySQL exposes execute() only on cursors; many BenchBox benchmarks (write_primitives,
    transaction_primitives, metadata_primitives) call connection.execute(sql) directly.
    This wrapper intercepts that call and delegates to a fresh cursor, returning it so
    that .fetchone() / .fetchall() work naturally on the result.

    When ddl_optimizer is provided (the adapter's _optimize_table_definition method),
    CREATE TABLE statements issued directly by benchmarks (write_primitives setup lock,
    transaction_primitives staging tables, etc.) are automatically transformed into
    StarRocks-compatible DDL before execution.

    Multi-statement SQL (statements separated by semicolons) is split and each statement
    executed individually so the DDL optimizer is applied only to CREATE TABLE statements
    and does not corrupt subsequent ALTER TABLE / CREATE INDEX statements.
    """

    def __init__(self, conn: Any, ddl_optimizer: Any = None) -> None:
        self._conn = conn
        self._ddl_optimizer = ddl_optimizer

    def _check_or_replace(self, stmt: str) -> None:
        if stmt.upper().startswith("CREATE OR REPLACE TABLE"):
            raise NotImplementedError(
                "CREATE OR REPLACE TABLE is not supported on StarRocks. "
                "Use DROP TABLE IF EXISTS followed by CREATE TABLE."
            )

    def _optimize_if_create(self, stmt: str) -> str:
        if self._ddl_optimizer is not None and stmt.upper().startswith("CREATE TABLE"):
            return self._ddl_optimizer(stmt)
        return stmt

    def execute(self, sql: str, params: Any = None) -> Any:
        if not sql or not sql.strip():
            return self._conn.cursor()

        statements = _split_sql_statements(sql)

        if len(statements) <= 1:
            stmt = sql.strip()
            self._check_or_replace(stmt)
            stmt = self._optimize_if_create(stmt)
            cursor = self._conn.cursor()
            cursor.execute(stmt, params)
            return cursor

        # Multi-statement: execute each individually; return cursor from last statement.
        # params are not forwarded to multi-statement SQL (they apply to single queries).
        last_cursor: Any = None
        for stmt in statements:
            self._check_or_replace(stmt)
            stmt = self._optimize_if_create(stmt)
            c = self._conn.cursor()
            c.execute(stmt)
            last_cursor = c
        return last_cursor if last_cursor is not None else self._conn.cursor()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


class StarRocksSetupMixin:
    """Provide setup and connection helpers for StarRocks."""

    def _setup_connection_config(self, config: dict[str, Any]) -> None:
        """Setup connection parameters from config with env var fallbacks."""
        self.host = config.get("host") or os.environ.get("STARROCKS_HOST", "localhost")
        self.port = int(config.get("port") or os.environ.get("STARROCKS_PORT", 9030))
        self.username = config.get("username") or os.environ.get("STARROCKS_USER", "root")
        self.password = config.get("password") or os.environ.get("STARROCKS_PASSWORD", "")
        self.database = config.get("database") or os.environ.get("STARROCKS_DATABASE")
        self.http_port = int(config.get("http_port") or os.environ.get("STARROCKS_HTTP_PORT", 8040))
        # Forward-compat: stored for future Stream Load HTTP support (StarRocks uses MySQL protocol today)
        self.verify_ssl = config.get("verify_ssl") if config.get("verify_ssl") is not None else True
        self.ca_cert_path = config.get("ca_cert_path")

        # Performance settings
        self.max_execution_time = config.get("max_execution_time", 300)

        # Result cache control - disable by default for accurate benchmarking
        self.disable_result_cache = config.get("disable_result_cache", True)

        # Validation strictness
        self.strict_validation = config.get("strict_validation", True)

        # Deployment mode
        self.deployment_mode = config.get("deployment_mode", "self-hosted")

    def _create_database(self) -> None:
        """Create the target database if it doesn't exist."""
        if not _VALID_IDENTIFIER_PATTERN.match(self.database or ""):
            raise ValueError(f"Invalid database identifier: {self.database!r}")

        conn = self._create_admin_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{self.database}`")
            cursor.close()
            self.logger.info(f"Created database: {self.database}")
        except Exception as e:
            self.logger.error(f"Failed to create database: {e}")
            raise
        finally:
            conn.close()

    def create_connection(self, **connection_config) -> Any:
        """Create StarRocks connection via MySQL protocol."""
        self.log_operation_start("StarRocks connection", f"host: {self.host}:{self.port}")

        if not PYMYSQL_AVAILABLE:
            raise ImportError(
                "StarRocks adapter requires PyMySQL but it is not installed.\n"
                "Install with: uv add pymysql\n"
                "Or install the StarRocks extra: uv add benchbox --extra starrocks"
            )

        # Handle existing database (reuse/recreate logic)
        self.handle_existing_database(**connection_config)

        # Create database if it doesn't exist yet (only when a name is configured)
        if self.database and not self.check_server_database_exists():
            self._create_database()

        host = connection_config.get("host", self.host)
        port = connection_config.get("port", self.port)
        username = connection_config.get("username", self.username)
        password = connection_config.get("password", self.password)
        database = connection_config.get("database", self.database)

        try:
            conn = pymysql.connect(
                host=host,
                port=port,
                user=username,
                password=password,
                database=database,
                connect_timeout=30,
                # Large timeouts to survive multi-hour bulk-INSERT sessions
                # (loading 10M+ rows via batch INSERT takes 45-90 min).
                read_timeout=86400,
                write_timeout=86400,
                charset="utf8mb4",
                autocommit=True,
            )

            # Test connection
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()

            self.logger.info(f"Connected to StarRocks at {host}:{port}")
            # Pass DDL optimizer so benchmarks that create their own tables
            # (write_primitives, transaction_primitives) get StarRocks-compatible DDL.
            ddl_optimizer = getattr(self, "_optimize_table_definition", None)
            return _StarRocksConnectionWrapper(conn, ddl_optimizer=ddl_optimizer)

        except Exception as e:
            self.logger.error(f"Failed to connect to StarRocks: {e}")
            raise

    def close_connection(self, connection: Any) -> None:
        """Close StarRocks connection."""
        try:
            if connection and hasattr(connection, "close"):
                connection.close()
        except Exception as e:
            self.logger.warning(f"Error closing StarRocks connection: {e}")

    def _create_admin_connection(self, **connection_config) -> Any:
        """Create StarRocks connection without specifying database (for admin ops)."""
        if not PYMYSQL_AVAILABLE:
            raise ImportError("StarRocks adapter requires PyMySQL.")

        host = connection_config.get("host", self.host)
        port = connection_config.get("port", self.port)
        username = connection_config.get("username", self.username)
        password = connection_config.get("password", self.password)

        return pymysql.connect(
            host=host,
            port=port,
            user=username,
            password=password,
            connect_timeout=30,
            charset="utf8mb4",
            autocommit=True,
        )

    def check_server_database_exists(self, **connection_config) -> bool:
        """Check if database exists on StarRocks server."""
        try:
            admin_conn = self._create_admin_connection(**connection_config)
            try:
                cursor = admin_conn.cursor()
                try:
                    db_name = connection_config.get("database", self.database)
                    cursor.execute("SHOW DATABASES")
                    databases = [row[0] for row in cursor.fetchall()]
                    return db_name in databases
                finally:
                    cursor.close()
            finally:
                admin_conn.close()
        except Exception as e:
            self.logger.debug(f"Failed to check database existence: {e}")
            return False

    def drop_database(self, **connection_config) -> None:
        """Drop database on StarRocks server."""
        db_name = connection_config.get("database", self.database)
        if not db_name or not _VALID_IDENTIFIER_PATTERN.match(db_name):
            raise ValueError(f"Invalid database name: {db_name!r}")

        try:
            admin_conn = self._create_admin_connection(**connection_config)
            try:
                cursor = admin_conn.cursor()
                try:
                    cursor.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
                finally:
                    cursor.close()
            finally:
                admin_conn.close()
        except Exception as e:
            raise RuntimeError(f"Failed to drop StarRocks database: {e}") from e


def _build_starrocks_config(
    platform: str,
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: Any,
) -> Any:
    """Build StarRocks database configuration with credential loading.

    Args:
        platform: Platform name (should be 'starrocks')
        options: CLI platform options from --platform-option flags
        overrides: Runtime overrides from orchestrator
        info: Platform info from registry

    Returns:
        DatabaseConfig with credentials loaded and connection params as top-level fields
    """
    # Intentionally inline - not using build_platform_config because env-var fallback and int coercion
    # must happen at builder runtime for CLI/test parity. See the Group D TODO investigation notes.
    from benchbox.core.schemas import DatabaseConfig
    from benchbox.security.credentials import CredentialManager

    cred_manager = CredentialManager()
    saved_creds = cred_manager.get_platform_credentials("starrocks") or {}

    # Priority: defaults < saved_creds < explicit_options < overrides
    explicit_options = overrides.get("_explicit_platform_options", {})
    merged_options: dict[str, Any] = {}
    merged_options.update(options)
    merged_options.update(saved_creds)
    merged_options.update(explicit_options)
    merged_options.update(overrides)

    name = info.display_name if info else "StarRocks"
    driver_package = info.driver_package if info else "pymysql"

    config_dict = {
        "type": "starrocks",
        "name": name,
        "options": merged_options,
        "driver_package": driver_package,
        "driver_version": overrides.get("driver_version") or options.get("driver_version"),
        "driver_auto_install": bool(overrides.get("driver_auto_install", options.get("driver_auto_install", False))),
        "host": merged_options.get("host") or os.environ.get("STARROCKS_HOST", "localhost"),
        "port": int(merged_options.get("port") or os.environ.get("STARROCKS_PORT", 9030)),
        "username": (merged_options.get("username") or os.environ.get("STARROCKS_USER", "root")),
        "password": merged_options.get("password") or os.environ.get("STARROCKS_PASSWORD", ""),
        "database": merged_options.get("database") or os.environ.get("STARROCKS_DATABASE"),
        "http_port": int(merged_options.get("http_port") or os.environ.get("STARROCKS_HTTP_PORT", 8040)),
        "benchmark": overrides.get("benchmark"),
        "scale_factor": overrides.get("scale_factor"),
        "tuning_config": overrides.get("tuning_config"),
    }

    return DatabaseConfig(**config_dict)


__all__ = ["StarRocksSetupMixin", "_build_starrocks_config"]
