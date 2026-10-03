# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

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
    connection_type: str = "memory"
    db_path: Optional[Union[str, Path]] = None
    read_only: bool = False

    memory_limit: str = "1GB"
    threads: int = 2
    max_memory: str = "1GB"
    enable_progress_bar: bool = False
    enable_profiling: bool = False
    enable_optimizer: bool = True
    preserve_insertion_order: bool = False
    default_order: str = "asc"

    extensions: list[str] = field(default_factory=lambda: ["parquet", "json", "httpfs", "fts"])
    load_extensions: bool = False

    settings: dict[str, Any] = field(default_factory=dict)


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
    try:
        for ext in extensions:
            try:
                conn.execute(f"INSTALL {ext};")
                conn.execute(f"LOAD {ext};")
            except Exception:
                pass
    except Exception:
        pass


def _apply_database_settings(conn: duckdb.DuckDBPyConnection, settings: dict[str, Any]) -> None:
    try:
        for key, value in settings.items():
            if isinstance(value, str):
                conn.execute(f"SET {key} = '{value}';")
            else:
                conn.execute(f"SET {key} = {value};")
    except Exception:
        pass


def _create_duckdb_connection(config: DatabaseConfig, tmp_path: Optional[Path] = None) -> duckdb.DuckDBPyConnection:
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
        if not Path(config.db_path).exists():
            _ensure_test_databases_exist()
        conn_path = str(config.db_path)
    else:
        raise ValueError(f"Unsupported connection type: {config.connection_type}")

    conn = duckdb.connect(conn_path, read_only=config.read_only)

    if config.load_extensions:
        _setup_database_extensions(conn, config.extensions)

    if config.settings:
        _apply_database_settings(conn, config.settings)

    return conn


@pytest.fixture(params=["memory", "memory_with_extensions", "configured", "file"])
def duckdb_database(request, tmp_path: Path) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    config_name = request.param
    config = DB_CONFIGS[config_name]

    conn = _create_duckdb_connection(config, tmp_path)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def duckdb_config_factory():

    def create_config(**kwargs) -> DatabaseConfig:
        return DatabaseConfig(**kwargs)

    return create_config


@pytest.fixture
def duckdb_custom(duckdb_config_factory, tmp_path: Path):
    connections = []

    def create_database(**config_kwargs) -> duckdb.DuckDBPyConnection:
        config = duckdb_config_factory(**config_kwargs)
        conn = _create_duckdb_connection(config, tmp_path)
        connections.append(conn)
        return conn

    yield create_database

    for conn in connections:
        with contextlib.suppress(Exception):
            conn.close()


@pytest.fixture
def duckdb_memory_db(
    tmp_path: Path,
) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    config = DB_CONFIGS["memory"]
    conn = _create_duckdb_connection(config, tmp_path)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def duckdb_file_db(tmp_path: Path) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    config = DB_CONFIGS["file"]
    conn = _create_duckdb_connection(config, tmp_path)
    try:
        yield conn
    finally:
        conn.close()


def setup_duckdb_extensions(conn: duckdb.DuckDBPyConnection) -> None:
    extensions = ["parquet", "json", "httpfs", "fts"]
    _setup_database_extensions(conn, extensions)


@pytest.fixture
def duckdb_with_extensions(
    tmp_path: Path,
) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    config = DB_CONFIGS["memory_with_extensions"]
    conn = _create_duckdb_connection(config, tmp_path)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def database_config() -> dict[str, Any]:
    return DB_CONFIGS["configured"].settings.copy()


@pytest.fixture
def configured_duckdb(
    tmp_path: Path,
) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    config = DB_CONFIGS["configured"]
    conn = _create_duckdb_connection(config, tmp_path)
    try:
        yield conn
    finally:
        conn.close()


def _create_persistent_db_fixture(db_name: str):

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
    return _create_persistent_db_fixture("basic_test")()


@pytest.fixture
def tpch_test_db() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    return _create_persistent_db_fixture("tpch_test")()


@pytest.fixture
def tpcds_test_db() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    return _create_persistent_db_fixture("tpcds_test")()


@pytest.fixture
def ssb_test_db() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    return _create_persistent_db_fixture("ssb_test")()


@pytest.fixture
def primitives_test_db() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    return _create_persistent_db_fixture("primitives_test")()


@pytest.fixture
def duckdb_performance() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    config = DB_CONFIGS["performance"]
    conn = _create_duckdb_connection(config)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def duckdb_minimal() -> Generator[duckdb.DuckDBPyConnection, None, None]:
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


def get_database_config(config_name: str) -> DatabaseConfig:
    if config_name not in DB_CONFIGS:
        raise KeyError(
            f"Unknown database configuration: {config_name}. Available configurations: {list(DB_CONFIGS.keys())}"
        )
    return DB_CONFIGS[config_name]


def create_test_database(
    config_name: str = "memory", tmp_path: Optional[Path] = None, **config_overrides
) -> duckdb.DuckDBPyConnection:
    base_config = get_database_config(config_name)

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
