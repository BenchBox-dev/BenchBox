"""Database connection fixtures for BenchBox tests.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import contextlib
import subprocess
import sys
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

import duckdb
import pytest


@dataclass
class DatabaseConfig:
    """Configuration for database fixtures."""

    # Connection settings
    connection_type: str = "memory"  # "memory", "file", "persistent"
    db_path: Optional[Union[str, Path]] = None
    read_only: bool = False

    # Performance settings
    memory_limit: str = "1GB"
    threads: int = 2
    max_memory: str = "1GB"
    enable_progress_bar: bool = False
    enable_profiling: bool = False
    enable_optimizer: bool = True
    preserve_insertion_order: bool = False
    default_order: str = "asc"

    # Extensions
    extensions: list[str] = field(default_factory=lambda: ["parquet", "json", "httpfs", "fts"])
    load_extensions: bool = False

    # Additional settings
    settings: dict[str, Any] = field(default_factory=dict)


# Predefined database configurations
DB_CONFIGS = {
    "memory": DatabaseConfig(connection_type="memory", load_extensions=False),
    "memory_with_extensions": DatabaseConfig(connection_type="memory", load_extensions=True),
    "configured": DatabaseConfig(
        connection_type="memory",
        load_extensions=False,
        settings={
            "memory_limit": "1GB",
            "threads": 2,
            "max_memory": "1GB",
            "enable_progress_bar": False,
            "enable_profiling": False,
            "enable_optimizer": True,
            "preserve_insertion_order": False,
            "default_order": "asc",
        },
    ),
    "file": DatabaseConfig(connection_type="file", load_extensions=False),
    "performance": DatabaseConfig(
        connection_type="memory",
        load_extensions=True,
        memory_limit="2GB",
        threads=4,
        max_memory="2GB",
        enable_optimizer=True,
        settings={
            "memory_limit": "2GB",
            "threads": 4,
            "max_memory": "2GB",
            "enable_optimizer": True,
            "enable_progress_bar": False,
            "enable_profiling": True,
        },
    ),
}


def _ensure_test_databases_exist():
    """Ensure test databases exist by running the creation script."""
    test_db_dir = Path(__file__).parent.parent / "databases"
    test_db_dir.mkdir(exist_ok=True)

    create_script = test_db_dir / "create_test_databases.py"
    if create_script.exists():
        try:
            result = subprocess.run(
                [sys.executable, str(create_script)],
                capture_output=True,
                text=True,
                cwd=str(test_db_dir.parent.parent),
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to create test databases: {result.stderr}")
        except Exception as e:
            raise RuntimeError(f"Error creating test databases: {e}") from e


def _setup_database_extensions(conn: duckdb.DuckDBPyConnection, extensions: list[str]) -> None:
    """Set up DuckDB extensions for testing.

    This function installs and loads specified DuckDB extensions.
    Fails silently if extensions cannot be loaded.

    Args:
        conn: DuckDB connection object
        extensions: List of extension names to install and load
    """
    try:
        for ext in extensions:
            try:
                conn.execute(f"INSTALL {ext};")
                conn.execute(f"LOAD {ext};")
            except Exception:
                # Continue if extension fails to load
                pass
    except Exception:
        # Ignore extension setup errors in tests
        pass


def _apply_database_settings(conn: duckdb.DuckDBPyConnection, settings: dict[str, Any]) -> None:
    """Apply configuration settings to a DuckDB connection.

    Args:
        conn: DuckDB connection object
        settings: Dictionary of setting name -> value pairs
    """
    try:
        for key, value in settings.items():
            if isinstance(value, str):
                conn.execute(f"SET {key} = '{value}';")
            else:
                conn.execute(f"SET {key} = {value};")
    except Exception:
        # Ignore configuration errors in tests
        pass


def _create_duckdb_connection(config: DatabaseConfig, tmp_path: Optional[Path] = None) -> duckdb.DuckDBPyConnection:
    """Create a DuckDB connection based on configuration.

    Args:
        config: Database configuration
        tmp_path: Optional temporary path for file databases

    Returns:
        duckdb.DuckDBPyConnection: Configured DuckDB connection
    """
    # Determine connection path
    if config.connection_type == "memory":
        conn_path = ":memory:"
    elif config.connection_type == "file":
        if config.db_path:
            conn_path = str(config.db_path)
        elif tmp_path:
            conn_path = str(tmp_path / "test.duckdb")
        else:
            raise ValueError("File database requires either db_path or tmp_path")
    elif config.connection_type == "persistent":
        if not config.db_path:
            raise ValueError("Persistent database requires db_path")
        # Ensure database exists
        if not Path(config.db_path).exists():
            _ensure_test_databases_exist()
        conn_path = str(config.db_path)
    else:
        raise ValueError(f"Unsupported connection type: {config.connection_type}")

    # Create connection
    conn = duckdb.connect(conn_path, read_only=config.read_only)

    # Apply extensions
    if config.load_extensions:
        _setup_database_extensions(conn, config.extensions)

    # Apply settings
    if config.settings:
        _apply_database_settings(conn, config.settings)

    return conn


# Main unified fixture
@pytest.fixture(params=["memory", "memory_with_extensions", "configured", "file"])
def duckdb_database(request, tmp_path: Path) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Unified parameterized DuckDB database fixture.

    This fixture can create different types of DuckDB databases based on
    predefined configurations. It's designed to replace multiple similar
    fixtures and reduce code duplication.

    Args:
        request: Pytest request object containing the parameter
        tmp_path: Pytest temporary directory fixture

    Returns:
        duckdb.DuckDBPyConnection: Configured DuckDB database connection
    """
    config_name = request.param
    config = DB_CONFIGS[config_name]

    conn = _create_duckdb_connection(config, tmp_path)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def duckdb_config_factory():
    """Factory fixture for creating custom database configurations.

    Returns:
        Callable: Function that creates DatabaseConfig instances
    """

    def create_config(**kwargs) -> DatabaseConfig:
        return DatabaseConfig(**kwargs)

    return create_config


@pytest.fixture
def duckdb_custom(duckdb_config_factory, tmp_path: Path):
    """Fixture for creating custom DuckDB databases.

    This fixture allows tests to create databases with custom configurations
    on-demand by calling the returned function.

    Args:
        duckdb_config_factory: Factory for creating database configurations
        tmp_path: Pytest temporary directory fixture

    Returns:
        Callable: Function that creates custom DuckDB connections
    """
    connections = []

    def create_database(**config_kwargs) -> duckdb.DuckDBPyConnection:
        config = duckdb_config_factory(**config_kwargs)
        conn = _create_duckdb_connection(config, tmp_path)
        connections.append(conn)
        return conn

    yield create_database

    # Cleanup all created connections
    for conn in connections:
        with contextlib.suppress(Exception):
            conn.close()


# Backward compatibility fixtures (implemented as aliases to the unified system)
@pytest.fixture
def duckdb_memory_db(
    tmp_path: Path,
) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Create an in-memory DuckDB database for testing.

    This fixture creates a fresh in-memory DuckDB database for each test.
    The database is automatically cleaned up after the test completes.

    Returns:
        duckdb.DuckDBPyConnection: DuckDB database connection for testing
    """
    config = DB_CONFIGS["memory"]
    conn = _create_duckdb_connection(config, tmp_path)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def duckdb_file_db(tmp_path: Path) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Create a file-based DuckDB database for testing.

    This fixture creates a temporary file-based DuckDB database that persists
    for the duration of the test. The database file is automatically cleaned
    up after the test completes.

    Args:
        tmp_path: Pytest temporary directory fixture

    Returns:
        duckdb.DuckDBPyConnection: DuckDB database connection for testing
    """
    config = DB_CONFIGS["file"]
    conn = _create_duckdb_connection(config, tmp_path)
    try:
        yield conn
    finally:
        conn.close()


def setup_duckdb_extensions(conn: duckdb.DuckDBPyConnection) -> None:
    """Set up commonly used DuckDB extensions for testing.

    This function installs and loads common DuckDB extensions that are
    frequently used in benchmark tests.

    Args:
        conn: DuckDB connection object

    Note:
        This function is deprecated. Use the unified fixture system with
        load_extensions=True instead.
    """
    extensions = ["parquet", "json", "httpfs", "fts"]
    _setup_database_extensions(conn, extensions)


@pytest.fixture
def duckdb_with_extensions(
    tmp_path: Path,
) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Create a DuckDB database with common extensions loaded.

    This fixture extends the basic DuckDB memory database with commonly
    used extensions pre-installed and loaded.

    Returns:
        duckdb.DuckDBPyConnection: DuckDB database connection with extensions loaded
    """
    config = DB_CONFIGS["memory_with_extensions"]
    conn = _create_duckdb_connection(config, tmp_path)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def database_config() -> dict[str, Any]:
    """Provide database configuration for testing.

    Returns:
        Dict[str, Any]: Database configuration parameters

    Note:
        This fixture is deprecated. Use DatabaseConfig dataclass instead.
    """
    return DB_CONFIGS["configured"].settings.copy()


@pytest.fixture
def configured_duckdb(
    tmp_path: Path,
) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Create a configured DuckDB database for testing.

    This fixture creates a DuckDB database with specific configuration
    settings applied that are suitable for testing.

    Returns:
        duckdb.DuckDBPyConnection: Configured DuckDB database connection
    """
    config = DB_CONFIGS["configured"]
    conn = _create_duckdb_connection(config, tmp_path)
    try:
        yield conn
    finally:
        conn.close()


# Persistent database fixtures (for pre-populated test databases)
def _create_persistent_db_fixture(db_name: str):
    """Create a persistent database fixture factory.

    Args:
        db_name: Name of the database file (without .duckdb extension)

    Returns:
        Generator function for the database fixture
    """

    def fixture_func() -> Generator[duckdb.DuckDBPyConnection, None, None]:
        db_path = Path(__file__).parent.parent / "databases" / f"{db_name}.duckdb"

        config = DatabaseConfig(connection_type="persistent", db_path=db_path, read_only=True)

        conn = _create_duckdb_connection(config)
        try:
            yield conn
        finally:
            conn.close()

    return fixture_func


@pytest.fixture
def basic_test_db() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Create a connection to the basic test database.

    This fixture provides a connection to the pre-populated basic test database
    which includes simple tables for connection and query testing.

    Returns:
        duckdb.DuckDBPyConnection: DuckDB database connection to basic test database
    """
    return _create_persistent_db_fixture("basic_test")()


@pytest.fixture
def tpch_test_db() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Create a connection to the TPC-H test database.

    This fixture provides a connection to the pre-populated TPC-H test database
    which includes minimal TPC-H schema and data for testing.

    Returns:
        duckdb.DuckDBPyConnection: DuckDB database connection to TPC-H test database
    """
    return _create_persistent_db_fixture("tpch_test")()


@pytest.fixture
def tpcds_test_db() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Create a connection to the TPC-DS test database.

    This fixture provides a connection to the pre-populated TPC-DS test database
    which includes minimal TPC-DS schema and data for testing.

    Returns:
        duckdb.DuckDBPyConnection: DuckDB database connection to TPC-DS test database
    """
    return _create_persistent_db_fixture("tpcds_test")()


@pytest.fixture
def ssb_test_db() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Create a connection to the SSB test database.

    This fixture provides a connection to the pre-populated Star Schema Benchmark
    test database which includes minimal SSB schema and data for testing.

    Returns:
        duckdb.DuckDBPyConnection: DuckDB database connection to SSB test database
    """
    return _create_persistent_db_fixture("ssb_test")()


@pytest.fixture
def primitives_test_db() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Create a connection to the primitives test database.

    This fixture provides a connection to the pre-populated primitives test database
    which includes tables for testing basic OLAP operations and window functions.

    Returns:
        duckdb.DuckDBPyConnection: DuckDB database connection to primitives test database
    """
    return _create_persistent_db_fixture("primitives_test")()


# Performance and specialized fixtures
@pytest.fixture
def duckdb_performance() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Create a high-performance DuckDB database for performance testing.

    This fixture creates a DuckDB database optimized for performance testing
    with higher memory limits and parallel processing enabled.

    Returns:
        duckdb.DuckDBPyConnection: High-performance DuckDB database connection
    """
    config = DB_CONFIGS["performance"]
    conn = _create_duckdb_connection(config)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def duckdb_minimal() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Create a minimal DuckDB database for basic testing.

    This fixture creates a DuckDB database with minimal configuration,
    suitable for unit tests that need fast startup.

    Returns:
        duckdb.DuckDBPyConnection: Minimal DuckDB database connection
    """
    config = DatabaseConfig(
        connection_type="memory",
        memory_limit="256MB",
        threads=1,
        load_extensions=False,
        settings={
            "memory_limit": "256MB",
            "threads": 1,
            "enable_progress_bar": False,
            "enable_profiling": False,
        },
    )
    conn = _create_duckdb_connection(config)
    try:
        yield conn
    finally:
        conn.close()


# Utility functions for tests
def get_database_config(config_name: str) -> DatabaseConfig:
    """Get a predefined database configuration by name.

    Args:
        config_name: Name of the configuration (memory, configured, etc.)

    Returns:
        DatabaseConfig: The requested configuration

    Raises:
        KeyError: If the configuration name is not found
    """
    if config_name not in DB_CONFIGS:
        raise KeyError(
            f"Unknown database configuration: {config_name}. Available configurations: {list(DB_CONFIGS.keys())}"
        )
    return DB_CONFIGS[config_name]


def create_test_database(
    config_name: str = "memory", tmp_path: Optional[Path] = None, **config_overrides
) -> duckdb.DuckDBPyConnection:
    """Create a test database with the specified configuration.

    This utility function allows creating databases outside of fixtures
    for advanced testing scenarios.

    Args:
        config_name: Name of the base configuration to use
        tmp_path: Optional temporary path for file databases
        **config_overrides: Configuration parameters to override

    Returns:
        duckdb.DuckDBPyConnection: Configured DuckDB database connection

    Note:
        The caller is responsible for closing the connection.
    """
    base_config = get_database_config(config_name)

    # Apply overrides
    if config_overrides:
        config_dict = {
            "connection_type": base_config.connection_type,
            "db_path": base_config.db_path,
            "read_only": base_config.read_only,
            "memory_limit": base_config.memory_limit,
            "threads": base_config.threads,
            "max_memory": base_config.max_memory,
            "enable_progress_bar": base_config.enable_progress_bar,
            "enable_profiling": base_config.enable_profiling,
            "enable_optimizer": base_config.enable_optimizer,
            "preserve_insertion_order": base_config.preserve_insertion_order,
            "default_order": base_config.default_order,
            "extensions": base_config.extensions.copy(),
            "load_extensions": base_config.load_extensions,
            "settings": base_config.settings.copy(),
        }
        config_dict.update(config_overrides)
        config = DatabaseConfig(**config_dict)
    else:
        config = base_config

    return _create_duckdb_connection(config, tmp_path)
