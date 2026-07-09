"""Setup and connection routines for StarRocks."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from benchbox.platforms.base.mysql_wire import MySqlWireConnectionWrapper, build_database_config, split_sql_statements

from ._dependencies import PYMYSQL_AVAILABLE, pymysql

# Valid database/identifier name pattern
_VALID_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

logger = logging.getLogger(__name__)


_split_sql_statements = split_sql_statements


class _StarRocksConnectionWrapper(MySqlWireConnectionWrapper):
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

    reject_create_or_replace = True


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
    return build_database_config(
        platform=platform,
        options=options,
        overrides=overrides,
        info=info,
        default_name="StarRocks",
        default_driver_package="pymysql",
        fields={
            "host": lambda m: m.get("host") or os.environ.get("STARROCKS_HOST", "localhost"),
            "port": lambda m: int(m.get("port") or os.environ.get("STARROCKS_PORT", 9030)),
            "username": lambda m: m.get("username") or os.environ.get("STARROCKS_USER", "root"),
            "password": lambda m: m.get("password") or os.environ.get("STARROCKS_PASSWORD", ""),
            "database": lambda m: m.get("database") or os.environ.get("STARROCKS_DATABASE"),
            "http_port": lambda m: int(m.get("http_port") or os.environ.get("STARROCKS_HTTP_PORT", 8040)),
        },
    )


__all__ = ["StarRocksSetupMixin", "_build_starrocks_config"]
