"""Connection lifecycle helpers for PlatformAdapter.

Extracted from `benchbox.platforms.base.adapter` per the refactor map
(`docs/development/adapter-refactor-map.md` Slice 3a). Houses the
non-abstract connection lifecycle: dependency probes, connection-pool
fetch, file/server existence checks, drop/recreate decisions, and the
non-interactive existing-database handler.

The contract abstract methods (`from_config`, `create_connection`,
`close_connection`) stay on `PlatformAdapter` itself - 43, 38, and 21
subclass overrides respectively per refactor map §3.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.utils.printing import quiet_console

if TYPE_CHECKING:
    from benchbox.platforms.base.models import ConnectionConfig


class ConnectionLifecycleMixin:
    """Mixin providing connection lifecycle plumbing for `PlatformAdapter`.

    Expects the host class to expose `platform_name`, `logger`, `dry_run`,
    `force_recreate`, `connection_pool`, `platform_config`, plus the
    abstract `create_connection` / `close_connection` / `drop_database`
    methods.
    """

    platform_name: str
    logger: logging.Logger
    connection_pool: Any
    platform_config: dict[str, Any]

    def test_connection(self, connection_config: ConnectionConfig | None = None) -> bool:
        """Test database connectivity.

        Args:
            connection_config: Optional connection configuration

        Returns:
            True if connection successful, False otherwise
        """
        try:
            test_conn = self.create_connection(**(connection_config.__dict__ if connection_config else {}))
            self.close_connection(test_conn)
            return True
        except Exception as e:
            self.logger.error(f"Connection test failed: {e}")
            return False

    @staticmethod
    def validate_platform_dependencies() -> dict[str, bool]:
        """Validate platform-specific dependencies are available.

        Returns:
            Dictionary mapping dependency names to availability status
        """
        return {
            "duckdb": ConnectionLifecycleMixin._check_import("duckdb"),
            "databricks": ConnectionLifecycleMixin._check_databricks_dependencies(),
            "clickhouse": ConnectionLifecycleMixin._check_import("clickhouse_driver"),
            "cloudpathlib": ConnectionLifecycleMixin._check_import("cloudpathlib"),
            "snowflake": ConnectionLifecycleMixin._check_import("snowflake.connector"),
            "psutil": ConnectionLifecycleMixin._check_import("psutil"),
        }

    @staticmethod
    def _check_import(module_name: str) -> bool:
        """Check if a module can be imported."""
        try:
            __import__(module_name)
            return True
        except ImportError:
            return False

    @staticmethod
    def _check_databricks_dependencies() -> bool:
        """Check if Databricks-specific dependencies are available."""
        required_modules = ["databricks.sql", "databricks.sdk"]
        return all(ConnectionLifecycleMixin._check_import(module) for module in required_modules)

    @staticmethod
    def require_dependencies(required: list[str], exit_on_missing: bool = True) -> dict[str, bool]:
        """Require specific dependencies, optionally exit with helpful message if missing.

        Args:
            required: List of required dependency names
            exit_on_missing: Whether to exit if dependencies are missing

        Returns:
            Dictionary mapping dependency names to availability status
        """
        available_deps = ConnectionLifecycleMixin.validate_platform_dependencies()
        missing_deps = [dep for dep in required if not available_deps.get(dep, False)]

        if missing_deps:
            quiet_console.print("❌ Missing required dependencies:")
            for dep in missing_deps:
                quiet_console.print(f"   - {dep}")

            quiet_console.print("\n💡 Installation instructions:")
            for dep in missing_deps:
                install_cmd = ConnectionLifecycleMixin._get_install_command(dep)
                if install_cmd:
                    quiet_console.print(f"   {dep}: {install_cmd}")

            if exit_on_missing:
                sys.exit(1)
        else:
            quiet_console.print("✅ All required dependencies are available")

        return available_deps

    @staticmethod
    def _get_install_command(dependency: str) -> str | None:
        """Get installation command for a dependency."""
        install_commands = {
            "duckdb": "uv add duckdb",
            "databricks": "uv add databricks-sql-connector databricks-sdk",
            "clickhouse": "uv add clickhouse-driver",
            "cloudpathlib": "uv add cloudpathlib",
            "snowflake": "uv add snowflake-connector-python",
            "psutil": "uv add psutil",
        }
        return install_commands.get(dependency)

    def get_connection_from_pool(self) -> Any:
        """Get connection from pool (if supported by platform).

        Returns:
            Database connection from pool or new connection
        """
        if self.connection_pool:
            return self.connection_pool.get_connection()
        return self.create_connection(**self.platform_config)

    def get_database_path(self, **connection_config) -> str | None:
        """Get the database file path for file-based databases.

        Override this method in platform adapters that use file-based databases.
        """
        return None

    def check_database_exists(self, **connection_config) -> bool:
        """Check if database already exists.

        For file-based databases, checks if file exists.
        For server-based databases, checks if database/schema exists on server.
        """
        db_path = self.get_database_path(**connection_config)
        if db_path and db_path != ":memory:":
            return Path(db_path).exists()

        return self.check_server_database_exists(**connection_config)

    def check_server_database_exists(self, **connection_config) -> bool:
        """Check if database exists on server (for server-based databases).

        Override this method in platform adapters for server-based databases.
        """
        return False

    def _validate_database_compatibility(self, **connection_config):
        """Validate database compatibility for current benchmark and configuration."""
        from benchbox.platforms.base.validation import DatabaseValidator

        validator = DatabaseValidator(adapter=self, connection_config=connection_config)
        return validator.validate()

    def check_benchmark_tables_exist(self, **connection_config) -> bool | None:
        """Check whether a managed database has the current benchmark tables.

        Returns:
            True when the adapter can prove the required tables are present,
            False when the adapter can prove they are missing or unusable, and
            None when the adapter does not implement managed table validation.
        """
        return None

    def handle_existing_database(self, **connection_config) -> None:
        """Handle existing database non-interactively for core/programmatic usage.

        Performs validation of database compatibility and makes automatic decisions:
        - If force_recreate=True, always recreate
        - If database is valid, reuse it
        - If database has issues, recreate it
        - If skip_database_management=True, skip create/drop management while
          allowing adapters to opt into table-readiness checks
        """
        self.log_operation_start("Database validation", "Checking existing database compatibility")

        if self.dry_run:
            self.log_verbose("Database validation skipped (dry run mode)")
            return

        if getattr(self, "skip_database_management", False):
            self.log_verbose("Database management skipped (managed cloud database)")
            tables_exist = self.check_benchmark_tables_exist(**connection_config)
            if tables_exist is False:
                self.log_verbose("Managed database cannot be safely reused - treating as fresh database")
                self.database_was_reused = False
                return
            if tables_exist is True:
                self.log_verbose("Managed database has required benchmark tables")
            self.database_was_reused = True
            return

        # When _validating_database is True, we're inside a validation connection.
        # We still need to check database existence, but skip validation/recreation logic.
        if getattr(self, "_validating_database", False):
            self.log_very_verbose("Inside validation context - skipping reuse/recreate logic.")
            return

        self.log_very_verbose("Checking if database exists...")
        if not self.check_database_exists(**connection_config):
            self.log_very_verbose("Database does not exist. Returning.")
            return
        self.log_verbose("Existing database found")

        db_path = self.get_database_path(**connection_config)
        is_file_based = db_path and db_path != ":memory:"

        if is_file_based:
            file_size = Path(db_path).stat().st_size
            size_mb = file_size / (1024 * 1024)
            db_info = f"{Path(db_path).name} ({size_mb:.1f} MB)"
        else:
            db_name = connection_config.get("database", "default")
            db_info = f"'{db_name}'"

        if self.force_recreate:
            self.log_verbose(f"Force recreate enabled - removing existing database: {db_info}")
            self._remove_database(is_file_based, db_path, **connection_config)
            return

        self.log_verbose(f"Database {db_info} already exists, validating compatibility...")
        validation_result = self._validate_database_compatibility(**connection_config)

        if validation_result.warnings:
            for warning in validation_result.warnings:
                self.logger.warning(f"⚠️ {warning}")

        if validation_result.issues:
            for issue in validation_result.issues:
                self.logger.error(f"❌ {issue}")

        if validation_result.is_valid:
            self.log_verbose("Database is configured for this run")
            self.log_verbose(f"Using existing database: {db_info}")
            self.log_verbose("Database being reused - skipping schema creation and data loading")
            self.database_was_reused = True
            self.log_operation_complete(
                "Database validation", details="Database reused - compatible with current configuration"
            )
        else:
            if validation_result.can_reuse:
                self.log_verbose("Database has compatibility issues - recreating for reliable results")
            else:
                self.log_verbose("Database is not configured for this run - recreating")

            self.log_verbose("Recreating database...")
            self.database_was_reused = False
            self._remove_database(is_file_based, db_path, **connection_config)
            self.log_operation_complete("Database validation", details="Database recreated due to incompatibility")

    def _remove_database(self, is_file_based: bool, db_path: str, **connection_config) -> None:
        """Helper method to remove/delete an existing database."""
        try:
            if is_file_based:
                db_path_obj = Path(db_path)
                if db_path_obj.is_file():
                    db_path_obj.unlink()
                    self.logger.warning(f"Deleted database file: {db_path_obj}")
                elif db_path_obj.is_dir():
                    import shutil

                    shutil.rmtree(db_path_obj)
                    self.logger.warning(f"Deleted database directory: {db_path_obj}")
                else:
                    self.logger.warning("Database path exists but is neither file nor directory")
            else:
                self.drop_database(**connection_config)
                self.logger.warning("Dropped database")
        except Exception as e:
            self.logger.error(f"Failed to remove database: {e}")
            raise RuntimeError(f"Could not remove existing database: {e}") from e

    def drop_database(self, **connection_config) -> None:
        """Drop/remove database on server (for server-based databases).

        Override this method in platform adapters for server-based databases.
        """
        raise NotImplementedError("drop_database not implemented for this platform")
