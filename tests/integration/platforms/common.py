"""Shared helpers for platform integration smoke tests.

This module provides reusable stubs for optional client libraries and
utility helpers used by the platform smoke tests. Each stub captures
executed statements so tests can assert on orchestration behaviour
without requiring real cloud services.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Generic benchmark helper


@dataclass
class SmokeBenchmark:
    """Minimal benchmark implementation for smoke testing."""

    name: str
    create_sql: str
    tables: dict[str, Path]

    def get_create_tables_sql(self, dialect: str = "ansi", **_: Any) -> str:
        return self.create_sql


def create_smoke_benchmark(tmp_path: Path, *, table_name: str = "lineitem", suffix: str = ".csv") -> SmokeBenchmark:
    """Create a simple benchmark with a single table data file."""

    data_path = tmp_path / f"{table_name}{suffix}"
    data_path.write_text("1,alpha\n2,beta\n", encoding="utf-8")

    create_sql = f"CREATE TABLE {table_name.upper()} (id INT, value STRING)"
    return SmokeBenchmark(name="SmokeBenchmark", create_sql=create_sql, tables={table_name: data_path})


def run_smoke_benchmark(
    adapter: Any, benchmark: SmokeBenchmark, data_dir: Path, benchmark_type: str = "analytics"
) -> tuple[dict[str, int], dict[str, Any], Any]:
    """Execute the key adapter phases for smoke testing.

    Returns the table statistics, platform metadata, and the underlying
    connection state captured by the stub connection.
    """

    connection = adapter.create_connection()
    try:
        adapter.create_schema(benchmark, connection)
        table_stats, _, _ = adapter.load_data(benchmark, connection, data_dir)
        adapter.configure_for_benchmark(connection, benchmark_type)
        metadata = adapter.get_platform_info(connection)
        state = getattr(connection, "_state", None)
    finally:
        adapter.close_connection(connection)

    return table_stats, metadata, state


# ---------------------------------------------------------------------------
# Databricks stub implementation


@dataclass
class DatabricksStubState:
    catalog: str = "main"
    schema: str = "benchbox"
    row_counts: dict[str, int] = field(default_factory=lambda: {"LINEITEM": 2})
    connect_calls: list[dict[str, Any]] = field(default_factory=list)
    statements: list[str] = field(default_factory=list)
    copy_statements: list[str] = field(default_factory=list)
    optimized_tables: list[str] = field(default_factory=list)


class _DatabricksCursor:
    def __init__(self, state: DatabricksStubState):
        self._state = state
        self._results: list[tuple[Any, ...]] = []

    def execute(self, query: str) -> None:
        self._state.statements.append(query)
        normalized = query.strip().lower()

        if normalized == "select 1":
            self._results = [(1,)]
        elif normalized.startswith("show catalogs"):
            self._results = [(self._state.catalog,)]
        elif normalized.startswith("show schemas"):
            self._results = [(self._state.schema,)]
        elif normalized.startswith("show tables"):
            self._results = [(self._state.schema, "lineitem", False)]
        elif normalized.startswith(("select version", "select spark_version")):
            self._results = [("13.3",)]
        elif normalized.startswith("select current_catalog"):
            self._results = [(self._state.catalog, self._state.schema)]
        elif normalized.startswith("set "):
            self._results = []
        elif normalized.startswith("copy into"):
            self._state.copy_statements.append(query)
            self._results = []
        elif normalized.startswith("optimize "):
            self._state.optimized_tables.append(query)
            self._results = []
        elif "select count(*)" in normalized:
            from_index = normalized.find("from")
            table_fragment = query[from_index + len("from") :].strip()
            table_fragment = table_fragment.strip('`"')
            table_name = table_fragment.split()[0].upper()
            count = self._state.row_counts.get(table_name, 0)
            self._results = [(count,)]
        elif normalized.startswith("describe extended"):
            self._results = [("format", "DELTA", "")]
        else:
            self._results = []

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._results)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._results[0] if self._results else None

    def close(self) -> None:  # pragma: no cover - simple stub
        return None


class _DatabricksConnection:
    def __init__(self, state_or_server: DatabricksStubState | str, *args: Any, **kwargs: Any) -> None:
        """Initialize connection, accepting either stub state or real Databricks connection args."""
        # If first arg is DatabricksStubState, use it; otherwise create default state
        if isinstance(state_or_server, DatabricksStubState):
            self._state = state_or_server
        else:
            # Being called with real connection args (server_hostname, http_path, access_token, ...)
            # Create a default state
            self._state = DatabricksStubState()
        self._closed = False

    def cursor(self) -> _DatabricksCursor:
        return _DatabricksCursor(self._state)

    def close(self) -> None:
        self._closed = True


def install_databricks_stub(monkeypatch, *, catalog: str = "main", schema: str = "benchbox") -> DatabricksStubState:
    """Install a databricks.sql stub returning the fake connection."""

    state = DatabricksStubState(catalog=catalog, schema=schema)

    def connect(**params: Any) -> _DatabricksConnection:
        state.connect_calls.append(params)
        return _DatabricksConnection(state)

    sql_module = types.ModuleType("databricks.sql")
    sql_module.__dict__.update({"connect": connect, "__version__": "0.9.0"})

    client_module = types.ModuleType("databricks.sql.client")
    client_module.Connection = _DatabricksConnection

    class _DatabricksFilesAPI:
        def upload(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    class _WorkspaceClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs
            self.files = _DatabricksFilesAPI()

    sdk_module = types.ModuleType("databricks.sdk")
    sdk_module.WorkspaceClient = _WorkspaceClient

    root_module = types.ModuleType("databricks")
    root_module.__path__ = []  # Mark as package
    root_module.sql = sql_module
    root_module.sdk = sdk_module

    sql_module.client = client_module

    monkeypatch.setitem(sys.modules, "databricks", root_module)
    monkeypatch.setitem(sys.modules, "databricks.sdk", sdk_module)
    monkeypatch.setitem(sys.modules, "databricks.sql", sql_module)
    monkeypatch.setitem(sys.modules, "databricks.sql.client", client_module)

    try:  # Ensure adapter module sees the stubbed client
        import benchbox.platforms.databricks.adapter as adapter_module

        adapter_module.databricks_sql = sql_module
        adapter_module.DatabricksConnection = _DatabricksConnection
    except ImportError:  # pragma: no cover - defensive
        pass

    return state


# ---------------------------------------------------------------------------
# Google BigQuery / Cloud Storage stub implementation


@dataclass
class BigQueryStubState:
    project_id: str
    location: str
    datasets: dict[str, dict[str, Any]] = field(default_factory=dict)
    queries: list[str] = field(default_factory=list)
    loads: list[tuple[str, str]] = field(default_factory=list)
    uploads: list[tuple[str, str]] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=lambda: {"LINEITEM": 2})


class _BigQueryQueryJob:
    def __init__(self, state: BigQueryStubState, sql: str) -> None:
        self._state = state
        self._sql = sql

    def result(self) -> Iterable[tuple[Any, ...]]:
        sql = self._sql.strip()
        self._state.queries.append(sql)

        lowered = sql.lower()
        if lowered.startswith("select 1"):
            return [(1,)]
        if lowered.startswith("select count(*)"):
            from_index = lowered.find("from")
            table_fragment = sql[from_index + len("from") :].strip().strip("`")
            table_name = table_fragment.split(".")[-1].split()[0].upper()
            return [(self._state.row_counts.get(table_name, 0),)]
        # Schema DDL queries return empty iterable
        return []


class _BigQueryLoadJob:
    def __init__(self, state: BigQueryStubState, table: str, uri: str) -> None:
        self._state = state
        self._table = table
        self._uri = uri

    def result(self) -> None:
        self._state.loads.append((self._table, self._uri))


class DatasetReference:
    def __init__(self, project: str, dataset_id: str) -> None:
        self.project = project
        self.dataset_id = dataset_id

    def table(self, table_name: str) -> str:
        return f"{self.project}.{self.dataset_id}.{table_name}"


class _BigQueryClient:
    def __init__(self, project: str, location: str) -> None:
        self._state = BigQueryStubState(project, location)
        self._storage_client: _StorageClient | None = None

    # Expose state for tests
    @property
    def state(self) -> BigQueryStubState:
        return self._state

    def dataset(self, dataset_id: str) -> DatasetReference:
        return DatasetReference(self._state.project_id, dataset_id)

    def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        if dataset_id not in self._state.datasets:
            raise NotFound(f"Dataset {dataset_id} not found")
        return self._state.datasets[dataset_id]

    def create_dataset(self, dataset: Any) -> dict[str, Any]:
        self._state.datasets[dataset.dataset_id] = {
            "location": getattr(dataset, "location", self._state.location),
            "description": getattr(dataset, "description", ""),
        }
        return dataset

    def query(self, sql: str) -> _BigQueryQueryJob:
        return _BigQueryQueryJob(self._state, sql)

    def load_table_from_uri(self, uri: str, table_ref: str, job_config: Any) -> _BigQueryLoadJob:
        _ = job_config  # job config not used in stub
        return _BigQueryLoadJob(self._state, table_ref, uri)


class _StorageClient:
    def __init__(self, state: BigQueryStubState) -> None:
        self._state = state

    def bucket(self, name: str) -> _Bucket:
        return _Bucket(self._state, name)


class _Bucket:
    def __init__(self, state: BigQueryStubState, name: str) -> None:
        self._state = state
        self._name = name

    def blob(self, blob_name: str) -> _Blob:
        return _Blob(self._state, self._name, blob_name)


class _Blob:
    def __init__(self, state: BigQueryStubState, bucket: str, blob_name: str) -> None:
        self._state = state
        self._bucket = bucket
        self._blob_name = blob_name

    def upload_from_filename(self, filename: str) -> None:
        self._state.uploads.append((self._bucket, self._blob_name))


class Dataset:
    def __init__(self, dataset_ref: Any) -> None:
        if isinstance(dataset_ref, DatasetReference):
            self.dataset_id = dataset_ref.dataset_id
            self.project = dataset_ref.project
        else:
            self.dataset_id = str(dataset_ref)
            self.project = None
        self.location: str | None = None
        self.description: str = ""


class LoadJobConfig:
    def __init__(self, **_: Any) -> None:
        return None


class QueryJobConfig:
    def __init__(self, dry_run: bool = False, **_: Any) -> None:
        self.dry_run = dry_run
        self.total_bytes_processed = 0
        self.job_id = "stub"


class SourceFormat:
    CSV = "CSV"


class WriteDisposition:
    WRITE_TRUNCATE = "WRITE_TRUNCATE"


class QueryPriority:
    INTERACTIVE = "INTERACTIVE"
    BATCH = "BATCH"


class NotFound(Exception):
    """Stubbed NotFound exception."""


class Conflict(Exception):
    """Stubbed Conflict exception."""


def install_google_cloud_stubs(
    monkeypatch, *, project_id: str = "smoke-project", location: str = "US"
) -> BigQueryStubState:
    """Install google.cloud.bigquery and storage stubs."""

    client = _BigQueryClient(project_id, location)
    client._storage_client = _StorageClient(client.state)

    bigquery_module = types.ModuleType("google.cloud.bigquery")
    bigquery_module.Client = lambda project, location=None, credentials=None: client  # type: ignore[assignment]
    bigquery_module.Dataset = Dataset
    bigquery_module.LoadJobConfig = LoadJobConfig
    bigquery_module.QueryJobConfig = QueryJobConfig
    bigquery_module.SourceFormat = SourceFormat
    bigquery_module.WriteDisposition = WriteDisposition
    bigquery_module.QueryPriority = QueryPriority
    bigquery_module.__version__ = "0.1.0"

    storage_module = types.ModuleType("google.cloud.storage")
    storage_module.Client = lambda project=None, credentials=None: client._storage_client  # type: ignore[assignment]

    exceptions_module = types.ModuleType("google.cloud.exceptions")
    exceptions_module.NotFound = NotFound
    exceptions_module.Conflict = Conflict

    cloud_module = types.ModuleType("google.cloud")
    cloud_module.__path__ = []
    cloud_module.bigquery = bigquery_module
    cloud_module.storage = storage_module

    auth_module = types.ModuleType("google.auth")

    def default_credentials():
        return (None, project_id)

    auth_module.default = default_credentials

    root_module = types.ModuleType("google")
    root_module.__path__ = []
    root_module.cloud = cloud_module
    root_module.auth = auth_module

    monkeypatch.setitem(sys.modules, "google", root_module)
    monkeypatch.setitem(sys.modules, "google.auth", auth_module)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_module)
    monkeypatch.setitem(sys.modules, "google.cloud.bigquery", bigquery_module)
    monkeypatch.setitem(sys.modules, "google.cloud.storage", storage_module)
    monkeypatch.setitem(sys.modules, "google.cloud.exceptions", exceptions_module)

    try:
        import benchbox.platforms.bigquery as adapter_module

        adapter_module.bigquery = bigquery_module
        adapter_module.storage = storage_module
        adapter_module.NotFound = NotFound
        adapter_module.Conflict = Conflict
        # Patch google_auth reference so _load_credentials works with stubs
        adapter_module.google_auth = auth_module
    except ImportError:  # pragma: no cover - defensive
        pass

    return client.state


# ---------------------------------------------------------------------------
# Redshift stub implementation


@dataclass
class RedshiftStubState:
    host: str
    port: int
    statements: list[str] = field(default_factory=list)
    copies: list[str] = field(default_factory=list)
    uploads: list[tuple[str, str]] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=lambda: {"LINEITEM": 2})
    commits: int = 0
    rollbacks: int = 0


class _RedshiftCursor:
    def __init__(self, state: RedshiftStubState):
        self._state = state
        self._results: list[tuple[Any, ...]] = []

    def execute(self, sql: str) -> None:
        self._state.statements.append(sql)
        lowered = sql.strip().lower()

        if lowered.startswith("select version"):
            self._results = [("Redshift 1.0",)]
        elif "select count(*)" in lowered:
            from_index = lowered.find("from")
            table_fragment = sql[from_index + len("from") :].strip().strip('"')
            # Extract table name, handling schema-qualified names (e.g., "public.lineitem" -> "lineitem")
            table_with_schema = table_fragment.split()[0]
            # If schema-qualified, take last part; otherwise use as-is
            table = table_with_schema.split(".")[-1].upper()
            self._results = [(self._state.row_counts.get(table, 0),)]
        elif lowered.startswith("copy "):
            self._state.copies.append(sql)
            self._results = []
        elif lowered.startswith("analyze "):
            self._results = []
        else:
            self._results = []

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._results[0] if self._results else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._results)

    def close(self) -> None:  # pragma: no cover - trivial stub
        return None


class _RedshiftConnection:
    def __init__(self, state: RedshiftStubState, **_: Any) -> None:
        self._state = state

    def cursor(self) -> _RedshiftCursor:
        return _RedshiftCursor(self._state)

    def commit(self) -> None:
        self._state.commits += 1

    def rollback(self) -> None:
        self._state.rollbacks += 1

    def close(self) -> None:
        return None

    def set_isolation_level(self, *_: Any) -> None:
        return None


class _Boto3Client:
    def __init__(self, state: RedshiftStubState) -> None:
        self._state = state

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self._state.uploads.append((bucket, key))


class _RedshiftBoto3Session:
    """Stub for boto3.Session used by Redshift's _create_s3_client."""

    def __init__(self, state: RedshiftStubState, **_: Any) -> None:
        self._state = state

    def client(self, service_name: str, **_: Any) -> Any:
        if service_name == "s3":
            return _Boto3Client(self._state)
        raise ValueError(f"Unknown service: {service_name}")

    def get_credentials(self) -> object:
        """Return a truthy sentinel so _create_s3_client does not raise."""
        return True


def install_redshift_stubs(
    monkeypatch, *, host: str = "example.redshift.amazonaws.com", port: int = 5439
) -> RedshiftStubState:
    """Install stubs for redshift_connector/psycopg and boto3."""

    state = RedshiftStubState(host=host, port=port)

    def connect(**params: Any) -> _RedshiftConnection:
        return _RedshiftConnection(state, **params)

    redshift_module = types.ModuleType("redshift_connector")
    redshift_module.connect = connect
    redshift_module.__version__ = "0.0.1"

    psycopg_module = types.ModuleType("psycopg")
    psycopg_module.connect = connect

    boto3_module = types.ModuleType("boto3")
    boto3_module.Session = lambda **kwargs: _RedshiftBoto3Session(state, **kwargs)
    boto3_module.client = lambda *_args, **_kwargs: _Boto3Client(state)

    monkeypatch.setitem(sys.modules, "redshift_connector", redshift_module)
    monkeypatch.setitem(sys.modules, "psycopg", psycopg_module)
    monkeypatch.setitem(sys.modules, "boto3", boto3_module)

    try:
        import benchbox.platforms.redshift as adapter_module

        adapter_module.redshift_connector = redshift_module
        adapter_module.psycopg = psycopg_module
        adapter_module.boto3 = boto3_module
    except ImportError:  # pragma: no cover - defensive
        pass

    return state


# ---------------------------------------------------------------------------
# Snowflake stub implementation


@dataclass
class SnowflakeStubState:
    statements: list[str] = field(default_factory=list)
    put_commands: list[str] = field(default_factory=list)
    copy_commands: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=lambda: {"LINEITEM": 2})


class _SnowflakeCursor:
    def __init__(self, state: SnowflakeStubState):
        self._state = state
        self._results: list[tuple[Any, ...]] = []

    def execute(self, sql: str) -> None:
        self._state.statements.append(sql)
        lowered = sql.strip().lower()
        if lowered.startswith("put "):
            self._state.put_commands.append(sql)
            self._results = [("local_file", 2, 2, "SKIPPED", "", "")]
        elif lowered.startswith("copy into"):
            self._state.copy_commands.append(sql)
            self._results = [("lineitem", 2, 2, "loaded", "", "")]
        elif "select count(*)" in lowered:
            from_index = lowered.find("from")
            table_fragment = sql[from_index + len("from") :].strip().strip('"')
            table = table_fragment.split()[0].upper()
            self._results = [(self._state.row_counts.get(table, 0),)]
        elif lowered.startswith("select version()"):
            self._results = [("Snowflake 1.0",)]
        elif lowered.startswith("select current_catalog"):
            self._results = [("BENCHBOX", "PUBLIC")]
        else:
            self._results = []

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._results)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._results[0] if self._results else None

    def close(self) -> None:  # pragma: no cover - trivial stub
        return None


class _SnowflakeConnection:
    def __init__(self, state: SnowflakeStubState, **_: Any) -> None:
        self._state = state

    def cursor(self) -> _SnowflakeCursor:
        return _SnowflakeCursor(self._state)

    def close(self) -> None:
        return None


def install_snowflake_stub(monkeypatch) -> SnowflakeStubState:
    """Install a snowflake.connector stub."""

    state = SnowflakeStubState()

    connector_module = types.ModuleType("snowflake.connector")
    connector_module.connect = lambda **_kwargs: _SnowflakeConnection(state)
    connector_module.__version__ = "0.1.0"

    errors_module = types.ModuleType("snowflake.connector.errors")

    class Error(Exception):
        pass

    errors_module.Error = Error

    root_module = types.ModuleType("snowflake")
    root_module.__path__ = []
    root_module.connector = connector_module

    monkeypatch.setitem(sys.modules, "snowflake", root_module)
    monkeypatch.setitem(sys.modules, "snowflake.connector", connector_module)
    monkeypatch.setitem(sys.modules, "snowflake.connector.errors", errors_module)

    try:
        import benchbox.platforms.snowflake as adapter_module

        adapter_module.snowflake = root_module
        adapter_module.DictCursor = None  # Not used in smoke tests
        adapter_module.SnowflakeError = errors_module.Error
    except ImportError:  # pragma: no cover - defensive
        pass

    return state


# ---------------------------------------------------------------------------
# AWS Athena stub implementation


@dataclass
class AthenaStubState:
    region: str = "us-east-1"
    workgroup: str = "primary"
    database: str = "default"
    catalog: str = "AwsDataCatalog"
    s3_bucket: str = "benchbox-smoke"
    s3_prefix: str = "benchbox-data"
    statements: list[str] = field(default_factory=list)
    uploads: list[tuple[str, str]] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=lambda: {"LINEITEM": 2})
    databases_created: list[str] = field(default_factory=list)
    tables_created: list[str] = field(default_factory=list)


class _AthenaCursor:
    def __init__(self, state: AthenaStubState):
        self._state = state
        self._results: list[tuple[Any, ...]] = []
        self.query_id = "stub-query-id-12345"
        self.data_scanned_in_bytes = 1024 * 1024  # 1 MB

    def execute(self, sql: str) -> None:
        self._state.statements.append(sql)
        lowered = sql.strip().lower()

        if lowered == "select 1":
            self._results = [(1,)]
        elif lowered.startswith("select version"):
            self._results = [("Athena engine version 3",)]
        elif "select count(*)" in lowered:
            # Extract table name from query
            from_index = lowered.find("from")
            table_fragment = sql[from_index + len("from") :].strip()
            table_name = table_fragment.split()[0].upper()
            self._results = [(self._state.row_counts.get(table_name, 0),)]
        elif lowered.startswith("create external table"):
            # Track table creation
            import re

            match = re.search(r"create\s+external\s+table\s+(?:if\s+not\s+exists\s+)?(\S+)", lowered)
            if match:
                self._state.tables_created.append(match.group(1))
            self._results = []
        elif lowered.startswith("msck repair table"):
            self._results = []
        elif lowered.startswith("show tables"):
            self._results = [(t,) for t in self._state.tables_created]
        elif lowered.startswith("drop table"):
            self._results = []
        else:
            self._results = []

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._results)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._results[0] if self._results else None

    def close(self) -> None:  # pragma: no cover - trivial stub
        return None


class _AthenaConnection:
    def __init__(self, state: AthenaStubState, **_: Any) -> None:
        self._state = state

    def cursor(self) -> _AthenaCursor:
        return _AthenaCursor(self._state)

    def close(self) -> None:
        return None


class _EntityNotFoundError(Exception):
    """Stub for Glue EntityNotFoundException."""


class _GluePaginator:
    def __init__(self, state: AthenaStubState) -> None:
        self._state = state

    def paginate(self, DatabaseName: str) -> Iterable[dict[str, Any]]:  # noqa: N803 - boto3 API
        return [{"TableList": []}]


class _GlueExceptions:
    EntityNotFoundException = property(lambda self: _EntityNotFoundError)


class _GlueClient:
    """Stub for boto3 Glue client."""

    def __init__(self, state: AthenaStubState) -> None:
        self._state = state
        self._databases: set[str] = set()

    def get_database(self, Name: str) -> dict[str, Any]:  # noqa: N803 - boto3 API
        if Name not in self._databases:
            raise _EntityNotFoundError(f"Database {Name} not found")
        return {"Database": {"Name": Name}}

    def create_database(self, DatabaseInput: dict[str, Any]) -> dict[str, Any]:  # noqa: N803 - boto3 API
        name = DatabaseInput["Name"]
        self._databases.add(name)
        self._state.databases_created.append(name)
        return {"Database": DatabaseInput}

    def delete_database(self, Name: str) -> None:  # noqa: N803 - boto3 API
        self._databases.discard(Name)

    def delete_table(self, DatabaseName: str, Name: str) -> None:  # noqa: N803 - boto3 API
        pass

    def get_paginator(self, operation: str) -> _GluePaginator:
        return _GluePaginator(self._state)

    @property
    def exceptions(self) -> _GlueExceptions:
        return _GlueExceptions()


class _S3Client:
    """Stub for boto3 S3 client."""

    def __init__(self, state: AthenaStubState) -> None:
        self._state = state

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self._state.uploads.append((bucket, key))


class _Boto3Session:
    """Stub for boto3.Session."""

    def __init__(self, state: AthenaStubState, **_: Any) -> None:
        self._state = state

    def client(self, service_name: str, **_: Any) -> Any:
        if service_name == "glue":
            return _GlueClient(self._state)
        elif service_name == "s3":
            return _S3Client(self._state)
        raise ValueError(f"Unknown service: {service_name}")


def install_athena_stubs(
    monkeypatch,
    *,
    region: str = "us-east-1",
    workgroup: str = "primary",
    s3_bucket: str = "benchbox-smoke",
) -> AthenaStubState:
    """Install stubs for pyathena and boto3 (Glue/S3)."""

    state = AthenaStubState(region=region, workgroup=workgroup, s3_bucket=s3_bucket)

    def athena_connect(**params: Any) -> _AthenaConnection:
        return _AthenaConnection(state, **params)

    # Create pyathena module stub
    pyathena_module = types.ModuleType("pyathena")
    pyathena_module.connect = athena_connect
    pyathena_module.__version__ = "3.0.0"

    cursor_module = types.ModuleType("pyathena.cursor")
    cursor_module.Cursor = _AthenaCursor

    # Create boto3 module stub
    boto3_module = types.ModuleType("boto3")
    boto3_module.Session = lambda **kwargs: _Boto3Session(state, **kwargs)
    boto3_module.client = lambda service, **kwargs: _Boto3Session(state).client(service, **kwargs)

    monkeypatch.setitem(sys.modules, "pyathena", pyathena_module)
    monkeypatch.setitem(sys.modules, "pyathena.cursor", cursor_module)
    monkeypatch.setitem(sys.modules, "boto3", boto3_module)

    # Patch the adapter module to use our stubs
    try:
        import benchbox.platforms.athena as adapter_module

        adapter_module.boto3 = boto3_module
        adapter_module.athena_connect = athena_connect
        adapter_module.AthenaCursor = _AthenaCursor
    except ImportError:  # pragma: no cover - defensive
        pass

    return state


# ---------------------------------------------------------------------------
# ClickHouse stub implementation


@dataclass
class ClickHouseStubState:
    host: str = "localhost"
    port: int = 9000
    database: str = "default"
    statements: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=lambda: {"LINEITEM": 2})
    inserts: list[tuple[str, Any]] = field(default_factory=list)


class _ClickHouseCursor:
    def __init__(self, state: ClickHouseStubState):
        self._state = state
        self._results: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: Any = None) -> list[tuple[Any, ...]]:
        self._state.statements.append(sql)
        lowered = sql.strip().lower()

        if lowered == "select 1":
            self._results = [(1,)]
        elif lowered.startswith("select version"):
            self._results = [("24.1.0",)]
        elif "select count(*)" in lowered:
            from_index = lowered.find("from")
            table_fragment = sql[from_index + len("from") :].strip()
            table_name = table_fragment.split()[0].upper()
            self._results = [(self._state.row_counts.get(table_name, 0),)]
        elif lowered.startswith("insert into"):
            self._state.inserts.append((sql, params))
            self._results = []
        elif lowered.startswith("show databases"):
            self._results = [(self._state.database,)]
        elif lowered.startswith("show tables"):
            self._results = [("lineitem",)]
        else:
            self._results = []

        return self._results

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._results)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._results[0] if self._results else None


class _ClickHouseConnection:
    def __init__(self, state: ClickHouseStubState, **_: Any) -> None:
        self._state = state

    def cursor(self) -> _ClickHouseCursor:
        return _ClickHouseCursor(self._state)

    def execute(self, sql: str, params: Any = None) -> list[tuple[Any, ...]]:
        return self.cursor().execute(sql, params)

    def close(self) -> None:
        pass


def install_clickhouse_stub(
    monkeypatch,
    *,
    host: str = "localhost",
    port: int = 9000,
) -> ClickHouseStubState:
    """Install clickhouse-driver stub."""

    state = ClickHouseStubState(host=host, port=port)

    class StubClient:
        def __init__(self, **kwargs: Any) -> None:
            self._state = state
            self._kwargs = kwargs

        def execute(self, sql: str, params: Any = None) -> list[tuple[Any, ...]]:
            return _ClickHouseCursor(state).execute(sql, params)

        def disconnect(self) -> None:
            pass

    driver_module = types.ModuleType("clickhouse_driver")
    driver_module.Client = StubClient
    driver_module.__version__ = "0.2.0"

    errors_module = types.ModuleType("clickhouse_driver.errors")

    class ClickHouseError(Exception):
        pass

    errors_module.Error = ClickHouseError

    monkeypatch.setitem(sys.modules, "clickhouse_driver", driver_module)
    monkeypatch.setitem(sys.modules, "clickhouse_driver.errors", errors_module)

    try:
        import benchbox.platforms.clickhouse._dependencies as deps_module

        deps_module.ClickHouseClient = StubClient
        deps_module.ClickHouseError = ClickHouseError
    except ImportError:  # pragma: no cover - defensive
        pass

    try:
        import benchbox.platforms.clickhouse.setup as setup_module

        setup_module.ClickHouseClient = StubClient
    except ImportError:  # pragma: no cover - defensive
        pass

    return state


# ---------------------------------------------------------------------------
# Trino stub implementation


@dataclass
class TrinoStubState:
    host: str = "localhost"
    port: int = 8080
    catalog: str = "memory"
    schema: str = "default"
    statements: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=lambda: {"LINEITEM": 2})


class _TrinoCursor:
    def __init__(self, state: TrinoStubState):
        self._state = state
        self._results: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self._state.statements.append(sql)
        lowered = sql.strip().lower()

        if lowered == "select 1":
            self._results = [(1,)]
        elif lowered.startswith("select version"):
            self._results = [("Trino 435",)]
        elif "select count(*)" in lowered:
            from_index = lowered.find("from")
            table_fragment = sql[from_index + len("from") :].strip()
            table_name = table_fragment.split()[0].upper()
            self._results = [(self._state.row_counts.get(table_name, 0),)]
        elif lowered.startswith("show catalogs"):
            self._results = [(self._state.catalog,)]
        elif lowered.startswith("show schemas"):
            self._results = [(self._state.schema,)]
        elif lowered.startswith("show tables"):
            self._results = [("lineitem",)]
        else:
            self._results = []

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._results)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._results[0] if self._results else None

    def close(self) -> None:
        pass


class _TrinoConnection:
    def __init__(self, state: TrinoStubState, **_: Any) -> None:
        self._state = state

    def cursor(self) -> _TrinoCursor:
        return _TrinoCursor(self._state)

    def close(self) -> None:
        pass


def install_trino_stub(
    monkeypatch,
    *,
    host: str = "localhost",
    port: int = 8080,
    catalog: str = "memory",
) -> TrinoStubState:
    """Install trino stub."""

    state = TrinoStubState(host=host, port=port, catalog=catalog)

    def connect(**params: Any) -> _TrinoConnection:
        conn = _TrinoConnection(state, **params)
        conn._state = state  # Expose state for test verification
        return conn

    trino_module = types.ModuleType("trino")
    trino_module.dbapi = types.ModuleType("trino.dbapi")
    trino_module.dbapi.connect = connect
    trino_module.dbapi.Connection = _TrinoConnection
    trino_module.__version__ = "0.328.0"

    auth_module = types.ModuleType("trino.auth")

    @dataclass
    class BasicAuthentication:
        username: str
        password: str

    auth_module.BasicAuthentication = BasicAuthentication

    monkeypatch.setitem(sys.modules, "trino", trino_module)
    monkeypatch.setitem(sys.modules, "trino.dbapi", trino_module.dbapi)
    monkeypatch.setitem(sys.modules, "trino.auth", auth_module)

    try:
        import benchbox.platforms.trino as adapter_module

        adapter_module.trino = trino_module
        adapter_module.BasicAuthentication = BasicAuthentication
    except ImportError:  # pragma: no cover - defensive
        pass

    return state


# ---------------------------------------------------------------------------
# Presto stub implementation


@dataclass
class PrestoStubState:
    host: str = "localhost"
    port: int = 8080
    catalog: str = "memory"
    schema: str = "default"
    statements: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=lambda: {"LINEITEM": 2})


class _PrestoCursor:
    def __init__(self, state: PrestoStubState):
        self._state = state
        self._results: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self._state.statements.append(sql)
        lowered = sql.strip().lower()

        if lowered == "select 1":
            self._results = [(1,)]
        elif lowered.startswith("select version") or "presto_version" in lowered:
            self._results = [("0.284",)]
        elif "select count(*)" in lowered:
            from_index = lowered.find("from")
            table_fragment = sql[from_index + len("from") :].strip()
            table_name = table_fragment.split()[0].upper()
            self._results = [(self._state.row_counts.get(table_name, 0),)]
        elif lowered.startswith("show catalogs"):
            self._results = [(self._state.catalog,)]
        elif lowered.startswith("show schemas"):
            self._results = [(self._state.schema,)]
        elif lowered.startswith("show tables"):
            self._results = [("lineitem",)]
        else:
            self._results = []

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._results)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._results[0] if self._results else None

    def close(self) -> None:
        pass


class _PrestoConnection:
    def __init__(self, state: PrestoStubState, **_: Any) -> None:
        self._state = state

    def cursor(self) -> _PrestoCursor:
        return _PrestoCursor(self._state)

    def close(self) -> None:
        pass


def install_presto_stub(
    monkeypatch,
    *,
    host: str = "localhost",
    port: int = 8080,
    catalog: str = "memory",
) -> PrestoStubState:
    """Install prestodb stub."""

    state = PrestoStubState(host=host, port=port, catalog=catalog)

    def connect(**params: Any) -> _PrestoConnection:
        conn = _PrestoConnection(state, **params)
        conn._state = state  # Expose state for test verification
        return conn

    prestodb_module = types.ModuleType("prestodb")
    prestodb_module.dbapi = types.ModuleType("prestodb.dbapi")
    prestodb_module.dbapi.connect = connect
    prestodb_module.dbapi.Connection = _PrestoConnection
    prestodb_module.__version__ = "0.8.0"

    auth_module = types.ModuleType("prestodb.auth")

    @dataclass
    class PrestoBasicAuthentication:
        username: str
        password: str

    auth_module.BasicAuthentication = PrestoBasicAuthentication

    monkeypatch.setitem(sys.modules, "prestodb", prestodb_module)
    monkeypatch.setitem(sys.modules, "prestodb.dbapi", prestodb_module.dbapi)
    monkeypatch.setitem(sys.modules, "prestodb.auth", auth_module)

    try:
        import benchbox.platforms.presto as adapter_module

        adapter_module.prestodb = prestodb_module
        adapter_module.PrestoBasicAuthentication = PrestoBasicAuthentication
    except ImportError:  # pragma: no cover - defensive
        pass

    return state


# ---------------------------------------------------------------------------
# PostgreSQL stub implementation


@dataclass
class PostgreSQLStubState:
    host: str = "localhost"
    port: int = 5432
    database: str = "benchbox"
    statements: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=lambda: {"LINEITEM": 2})
    copies: list[str] = field(default_factory=list)
    commits: int = 0


class _PostgreSQLCursor:
    def __init__(self, state: PostgreSQLStubState):
        self._state = state
        self._results: list[tuple[Any, ...]] = []
        self.description = None

    def execute(self, sql: str, params: Any = None) -> None:
        self._state.statements.append(sql)
        lowered = sql.strip().lower()

        if lowered == "select 1":
            self._results = [(1,)]
        elif lowered.startswith("select version"):
            self._results = [("PostgreSQL 16.0",)]
        elif "select count(*)" in lowered:
            from_index = lowered.find("from")
            table_fragment = sql[from_index + len("from") :].strip()
            table_name = table_fragment.split()[0].upper()
            self._results = [(self._state.row_counts.get(table_name, 0),)]
        elif lowered.startswith("show server_version"):
            self._results = [("16.0",)]
        else:
            self._results = []

    def copy_expert(self, sql: str, file: Any) -> None:
        self._state.copies.append(sql)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._results)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._results[0] if self._results else None

    def close(self) -> None:
        pass


class _PostgreSQLConnection:
    def __init__(self, state: PostgreSQLStubState, **_: Any) -> None:
        self._state = state
        self.autocommit = False
        self.encoding = "UTF8"
        self.closed = 0

    def cursor(self, cursor_factory: Any = None) -> _PostgreSQLCursor:
        return _PostgreSQLCursor(self._state)

    def commit(self) -> None:
        self._state.commits += 1

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self.closed = 1

    def set_isolation_level(self, level: int) -> None:
        pass


def install_postgresql_stub(
    monkeypatch,
    *,
    host: str = "localhost",
    port: int = 5432,
    database: str = "benchbox",
) -> PostgreSQLStubState:
    """Install psycopg stub."""

    state = PostgreSQLStubState(host=host, port=port, database=database)

    def connect(**params: Any) -> _PostgreSQLConnection:
        conn = _PostgreSQLConnection(state, **params)
        conn._state = state  # Expose state for test verification
        return conn

    psycopg_module = types.ModuleType("psycopg")
    psycopg_module.connect = connect
    psycopg_module.__version__ = "3.1.0"

    monkeypatch.setitem(sys.modules, "psycopg", psycopg_module)

    try:
        import benchbox.platforms.postgresql as adapter_module

        adapter_module.psycopg = psycopg_module
    except ImportError:  # pragma: no cover - defensive
        pass

    return state


__all__ = [
    "SmokeBenchmark",
    "create_smoke_benchmark",
    "run_smoke_benchmark",
    "install_databricks_stub",
    "install_google_cloud_stubs",
    "install_redshift_stubs",
    "install_snowflake_stub",
    "install_athena_stubs",
    "install_clickhouse_stub",
    "install_trino_stub",
    "install_presto_stub",
    "install_postgresql_stub",
    "install_influxdb_stub",
    "install_starrocks_stub",
    "install_databend_stub",
    "install_doris_stub",
    "install_lakesail_stub",
    "DatabricksStubState",
    "BigQueryStubState",
    "RedshiftStubState",
    "SnowflakeStubState",
    "AthenaStubState",
    "ClickHouseStubState",
    "TrinoStubState",
    "PrestoStubState",
    "PostgreSQLStubState",
    "InfluxDBStubState",
    "StarRocksStubState",
    "DatabendStubState",
    "DorisStubState",
    "LakeSailStubState",
]


# ---------------------------------------------------------------------------
# InfluxDB stub implementation


@dataclass
class InfluxDBStubState:
    host: str = "localhost"
    port: int = 8086
    token: str = "test-token"
    database: str = "benchbox"
    org: str | None = None
    mode: str = "core"
    statements: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=lambda: {"cpu": 100, "mem": 100})


class _InfluxDBStubClient:
    """Stub for influxdb3-python InfluxDBClient3."""

    def __init__(self, state: InfluxDBStubState, **kwargs: Any) -> None:
        self._state = state
        self._kwargs = kwargs

    def query(self, sql: str) -> Any:
        """Return stub Arrow table-like object."""
        self._state.statements.append(sql)
        lowered = sql.strip().lower()

        # Create mock PyArrow Table-like response
        class MockTable:
            def __init__(self, data: dict[str, list[Any]], num_rows: int):
                self._data = data
                self.num_rows = num_rows

            def to_pydict(self) -> dict[str, list[Any]]:
                return self._data

        if lowered == "select 1":
            return MockTable({"result": [1]}, 1)
        elif "count(*)" in lowered:
            # Extract table name for count queries (handles quoted names like FROM "cpu")
            # Remove quotes for matching
            normalized = lowered.replace('"', "")
            if "from cpu" in normalized:
                return MockTable({"count": [self._state.row_counts.get("cpu", 0)]}, 1)
            elif "from mem" in normalized:
                return MockTable({"count": [self._state.row_counts.get("mem", 0)]}, 1)
            return MockTable({"count": [0]}, 1)
        elif "information_schema.tables" in lowered:
            return MockTable({"table_name": ["cpu", "mem", "disk", "net"]}, 4)
        else:
            return MockTable({}, 0)

    def write(self, data: str, write_precision: str = "ns") -> None:
        """Record write operation."""
        self._state.writes.append(data)

    def close(self) -> None:
        pass


def install_influxdb_stub(
    monkeypatch,
    *,
    host: str = "localhost",
    port: int = 8086,
    token: str = "test-token",
    database: str = "benchbox",
    mode: str = "core",
) -> InfluxDBStubState:
    """Install influxdb3-python stub."""

    state = InfluxDBStubState(host=host, port=port, token=token, database=database, mode=mode)

    # Create stub module
    influxdb3_module = types.ModuleType("influxdb3")
    influxdb3_module.InfluxDBClient3 = lambda **kwargs: _InfluxDBStubClient(state, **kwargs)

    # Install in sys.modules before any imports
    monkeypatch.setitem(sys.modules, "influxdb3", influxdb3_module)

    # Patch the _dependencies module - critical for adapter availability check
    import benchbox.platforms.influxdb._dependencies as deps_module

    monkeypatch.setattr(deps_module, "INFLUXDB3_AVAILABLE", True)
    monkeypatch.setattr(deps_module, "FLIGHTSQL_AVAILABLE", False)
    monkeypatch.setattr(deps_module, "INFLUXDB_AVAILABLE", True)
    monkeypatch.setattr(deps_module, "InfluxDBClient3", lambda **kwargs: _InfluxDBStubClient(state, **kwargs))

    # Also patch the main __init__ module which re-exports these
    import benchbox.platforms.influxdb as influxdb_module

    monkeypatch.setattr(influxdb_module, "INFLUXDB_AVAILABLE", True)
    monkeypatch.setattr(influxdb_module, "INFLUXDB3_AVAILABLE", True)
    monkeypatch.setattr(influxdb_module, "FLIGHTSQL_AVAILABLE", False)

    # Patch check_platform_dependencies to return True for influxdb
    import benchbox.utils.dependencies as dep_utils

    original_check = dep_utils.check_platform_dependencies

    def patched_check(platform: str) -> tuple[bool, list[str]]:
        if platform == "influxdb":
            return True, []
        return original_check(platform)

    monkeypatch.setattr(dep_utils, "check_platform_dependencies", patched_check)

    # Also need to patch the adapter module directly since it imports the flag
    import benchbox.platforms.influxdb.adapter as adapter_module

    monkeypatch.setattr(adapter_module, "INFLUXDB_AVAILABLE", True)

    # Patch the client module which also checks availability during connect()
    import benchbox.platforms.influxdb.client as client_module

    monkeypatch.setattr(client_module, "INFLUXDB3_AVAILABLE", True)
    monkeypatch.setattr(client_module, "FLIGHTSQL_AVAILABLE", False)
    monkeypatch.setattr(client_module, "InfluxDBClient3", lambda **kwargs: _InfluxDBStubClient(state, **kwargs))

    return state


# ---------------------------------------------------------------------------
# Cloud Spark adapter stubs (Athena Spark, EMR Serverless, Dataproc, Dataproc Serverless)
# These adapters use session-based/batch-based execution, not traditional SQL connections.


@dataclass
class CloudSparkStubState:
    """Shared state for cloud Spark adapter stubs."""

    project_id: str = "smoke-project"
    region: str = "us-east-1"
    bucket: str = "benchbox-smoke"
    database: str = "benchbox"
    session_id: str = "session-12345"
    batch_id: str = "batch-12345"
    application_id: str = "app-12345"
    cluster_name: str = "benchbox-cluster"
    row_counts: dict[str, int] = field(default_factory=lambda: {"lineitem": 2, "LINEITEM": 2})
    statements: list[str] = field(default_factory=list)
    uploads: list[tuple[str, str]] = field(default_factory=list)
    calculations: list[str] = field(default_factory=list)
    batches_submitted: list[dict[str, Any]] = field(default_factory=list)
    jobs_submitted: list[dict[str, Any]] = field(default_factory=list)


class _CloudSparkAthenaClient:
    """Stub for boto3 Athena client (Spark sessions)."""

    def __init__(self, state: CloudSparkStubState):
        self._state = state

    def start_session(self, **kwargs: Any) -> dict[str, Any]:
        self._state.session_id = f"session-{len(self._state.statements)}"
        return {
            "SessionId": self._state.session_id,
            "State": "IDLE",
        }

    def get_session_status(self, SessionId: str) -> dict[str, Any]:
        return {
            "SessionId": SessionId,
            "Status": {"State": "IDLE"},
        }

    def terminate_session(self, SessionId: str) -> dict[str, Any]:
        return {"State": "TERMINATED"}

    def start_calculation_execution(self, **kwargs: Any) -> dict[str, Any]:
        code = kwargs.get("CodeBlock", "")
        self._state.calculations.append(code)
        return {"CalculationExecutionId": f"calc-{len(self._state.calculations)}"}

    def get_calculation_execution_status(self, CalculationExecutionId: str) -> dict[str, Any]:
        return {
            "Status": {"State": "COMPLETED"},
            "Statistics": {"DpuExecutionInMillis": 1000},
        }

    def get_calculation_execution(self, CalculationExecutionId: str) -> dict[str, Any]:
        return {
            "Status": {"State": "COMPLETED"},
            "Result": {"StdOutS3Uri": f"s3://{self._state.bucket}/results/stdout.txt"},
        }


class _CloudSparkEMRServerlessClient:
    """Stub for boto3 EMR Serverless client."""

    def __init__(self, state: CloudSparkStubState):
        self._state = state

    def get_application(self, applicationId: str) -> dict[str, Any]:
        return {
            "application": {
                "applicationId": applicationId,
                "state": "STARTED",
                "releaseLabel": "emr-7.0.0",
            }
        }

    def create_application(self, **kwargs: Any) -> dict[str, Any]:
        self._state.application_id = f"app-{len(self._state.batches_submitted)}"
        return {"applicationId": self._state.application_id}

    def start_job_run(self, **kwargs: Any) -> dict[str, Any]:
        self._state.batches_submitted.append(kwargs)
        return {"applicationId": kwargs.get("applicationId"), "jobRunId": f"job-{len(self._state.batches_submitted)}"}

    def get_job_run(self, applicationId: str, jobRunId: str) -> dict[str, Any]:
        return {
            "jobRun": {
                "applicationId": applicationId,
                "jobRunId": jobRunId,
                "state": "SUCCESS",
                "totalExecutionDurationSeconds": 10,
            }
        }


class _CloudSparkDataprocBatchClient:
    """Stub for google.cloud.dataproc_v1.BatchControllerClient."""

    def __init__(self, state: CloudSparkStubState):
        self._state = state

    def create_batch(self, **kwargs: Any) -> Any:
        self._state.batches_submitted.append(kwargs)

        # Return a mock operation that resolves immediately
        class MockOperation:
            def __init__(self, state: CloudSparkStubState):
                self._state = state

            def result(self, timeout: int | None = None) -> Any:
                class MockBatch:
                    state = 4  # SUCCEEDED
                    runtime_info = type("RuntimeInfo", (), {"endpoints": {}})()

                return MockBatch()

        return MockOperation(self._state)

    def get_batch(self, name: str) -> Any:
        class MockBatch:
            state = 4  # SUCCEEDED
            runtime_info = type("RuntimeInfo", (), {"endpoints": {}})()

        return MockBatch()


class _CloudSparkDataprocJobClient:
    """Stub for google.cloud.dataproc_v1.JobControllerClient."""

    def __init__(self, state: CloudSparkStubState):
        self._state = state

    def submit_job_as_operation(self, **kwargs: Any) -> Any:
        self._state.jobs_submitted.append(kwargs)

        class MockOperation:
            def __init__(self, state: CloudSparkStubState):
                self._state = state

            def result(self, timeout: int | None = None) -> Any:
                class MockJob:
                    status = type("Status", (), {"state": 4})()  # DONE
                    reference = type("Reference", (), {"job_id": f"job-{len(self._state.jobs_submitted)}"})()
                    driver_output_resource_uri = f"gs://{self._state.bucket}/output"

                return MockJob()

        return MockOperation(self._state)

    def get_job(self, **kwargs: Any) -> Any:
        class MockJob:
            status = type("Status", (), {"state": 4})()  # DONE

        return MockJob()


class _CloudSparkGCSClient:
    """Stub for google.cloud.storage.Client."""

    def __init__(self, state: CloudSparkStubState):
        self._state = state

    def bucket(self, bucket_name: str) -> Any:
        class MockBucket:
            def __init__(self, state: CloudSparkStubState, name: str):
                self._state = state
                self.name = name

            def blob(self, blob_name: str) -> Any:
                class MockBlob:
                    def __init__(self, state: CloudSparkStubState, bucket: str, name: str):
                        self._state = state
                        self._bucket = bucket
                        self.name = name

                    def upload_from_filename(self, filename: str) -> None:
                        self._state.uploads.append((self._bucket, self.name))

                    def upload_from_string(self, data: str) -> None:
                        self._state.uploads.append((self._bucket, self.name))

                    def download_as_text(self) -> str:
                        return '{"result": "success"}'

                    def exists(self) -> bool:
                        return True

                return MockBlob(self._state, self.name, blob_name)

            def list_blobs(self, prefix: str | None = None) -> list[Any]:
                return []

        return MockBucket(self._state, bucket_name)


class _CloudSparkS3Client:
    """Stub for boto3 S3 client (for cloud Spark adapters)."""

    def __init__(self, state: CloudSparkStubState):
        self._state = state

    def upload_file(self, filename: str, bucket: str, key: str, **kwargs: Any) -> None:
        self._state.uploads.append((bucket, key))

    def upload_fileobj(self, fileobj: Any, bucket: str, key: str, **kwargs: Any) -> None:
        self._state.uploads.append((bucket, key))

    def put_object(self, Bucket: str, Key: str, Body: Any) -> None:
        self._state.uploads.append((Bucket, Key))

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        class MockBody:
            def read(self) -> bytes:
                return b'{"result": "success"}'

        return {"Body": MockBody()}

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        return {"ContentLength": 100}

    def list_objects_v2(self, Bucket: str, Prefix: str = "") -> dict[str, Any]:
        return {"Contents": [], "KeyCount": 0}


def install_athena_spark_stub(
    monkeypatch,
    *,
    region: str = "us-east-1",
    workgroup: str = "spark-workgroup",
    s3_bucket: str = "benchbox-smoke",
) -> CloudSparkStubState:
    """Install stubs for Athena Spark adapter (boto3 Athena + S3)."""

    state = CloudSparkStubState(region=region, bucket=s3_bucket)

    # Create boto3 client factory
    def make_client(service: str, **kwargs: Any) -> Any:
        if service == "athena":
            return _CloudSparkAthenaClient(state)
        elif service == "s3":
            return _CloudSparkS3Client(state)
        raise ValueError(f"Unknown service: {service}")

    boto3_module = types.ModuleType("boto3")
    boto3_module.client = make_client

    monkeypatch.setitem(sys.modules, "boto3", boto3_module)

    # Patch the adapter module
    import benchbox.platforms.aws.athena_spark_adapter as adapter_module

    monkeypatch.setattr(adapter_module, "BOTO3_AVAILABLE", True)
    monkeypatch.setattr(adapter_module, "boto3", boto3_module)

    # Patch dependency check
    import benchbox.utils.dependencies as dep_utils

    original_check = dep_utils.check_platform_dependencies

    def patched_check(platform: str) -> tuple[bool, list[str]]:
        if platform == "athena-spark":
            return True, []
        return original_check(platform)

    monkeypatch.setattr(dep_utils, "check_platform_dependencies", patched_check)

    return state


def install_emr_serverless_stub(
    monkeypatch,
    *,
    region: str = "us-east-1",
    s3_bucket: str = "benchbox-smoke",
    application_id: str = "app-12345",
) -> CloudSparkStubState:
    """Install stubs for EMR Serverless adapter (boto3 EMR Serverless + S3)."""

    state = CloudSparkStubState(region=region, bucket=s3_bucket, application_id=application_id)

    def make_client(service: str, **kwargs: Any) -> Any:
        if service == "emr-serverless":
            return _CloudSparkEMRServerlessClient(state)
        elif service == "s3":
            return _CloudSparkS3Client(state)
        raise ValueError(f"Unknown service: {service}")

    boto3_module = types.ModuleType("boto3")
    boto3_module.client = make_client

    monkeypatch.setitem(sys.modules, "boto3", boto3_module)

    import benchbox.platforms.aws.emr_serverless_adapter as adapter_module

    monkeypatch.setattr(adapter_module, "BOTO3_AVAILABLE", True)
    monkeypatch.setattr(adapter_module, "boto3", boto3_module)

    import benchbox.utils.dependencies as dep_utils

    original_check = dep_utils.check_platform_dependencies

    def patched_check(platform: str) -> tuple[bool, list[str]]:
        if platform == "emr-serverless":
            return True, []
        return original_check(platform)

    monkeypatch.setattr(dep_utils, "check_platform_dependencies", patched_check)

    return state


def install_dataproc_stub(
    monkeypatch,
    *,
    project_id: str = "smoke-project",
    region: str = "us-central1",
    gcs_bucket: str = "benchbox-smoke",
    cluster_name: str = "benchbox-cluster",
) -> CloudSparkStubState:
    """Install stubs for Dataproc adapter (google.cloud.dataproc_v1 + storage)."""

    state = CloudSparkStubState(project_id=project_id, region=region, bucket=gcs_bucket, cluster_name=cluster_name)

    # Create dataproc_v1 module stubs
    dataproc_v1_module = types.ModuleType("google.cloud.dataproc_v1")
    dataproc_v1_module.JobControllerClient = lambda: _CloudSparkDataprocJobClient(state)
    dataproc_v1_module.ClusterControllerClient = lambda: None  # Not used in smoke tests

    # Job state enum
    class JobState:
        PENDING = 1
        RUNNING = 2
        DONE = 4
        ERROR = 5
        CANCELLED = 6

    dataproc_v1_module.Job = type("Job", (), {"State": JobState})

    storage_module = types.ModuleType("google.cloud.storage")
    storage_module.Client = lambda project=None, credentials=None: _CloudSparkGCSClient(state)

    # Create module hierarchy
    cloud_module = types.ModuleType("google.cloud")
    cloud_module.__path__ = []
    cloud_module.dataproc_v1 = dataproc_v1_module
    cloud_module.storage = storage_module

    root_module = types.ModuleType("google")
    root_module.__path__ = []
    root_module.cloud = cloud_module

    monkeypatch.setitem(sys.modules, "google", root_module)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_module)
    monkeypatch.setitem(sys.modules, "google.cloud.dataproc_v1", dataproc_v1_module)
    monkeypatch.setitem(sys.modules, "google.cloud.storage", storage_module)

    import benchbox.platforms.gcp.dataproc_adapter as adapter_module

    monkeypatch.setattr(adapter_module, "GOOGLE_CLOUD_AVAILABLE", True)
    monkeypatch.setattr(adapter_module, "dataproc_v1", dataproc_v1_module)
    monkeypatch.setattr(adapter_module, "storage", storage_module)

    import benchbox.utils.dependencies as dep_utils

    original_check = dep_utils.check_platform_dependencies

    def patched_check(platform: str) -> tuple[bool, list[str]]:
        if platform == "dataproc":
            return True, []
        return original_check(platform)

    monkeypatch.setattr(dep_utils, "check_platform_dependencies", patched_check)

    return state


def install_dataproc_serverless_stub(
    monkeypatch,
    *,
    project_id: str = "smoke-project",
    region: str = "us-central1",
    gcs_bucket: str = "benchbox-smoke",
) -> CloudSparkStubState:
    """Install stubs for Dataproc Serverless adapter (google.cloud.dataproc_v1 + storage)."""

    state = CloudSparkStubState(project_id=project_id, region=region, bucket=gcs_bucket)

    # Create dataproc_v1 module stubs
    dataproc_v1_module = types.ModuleType("google.cloud.dataproc_v1")
    dataproc_v1_module.BatchControllerClient = lambda: _CloudSparkDataprocBatchClient(state)

    # Batch state enum
    class BatchState:
        PENDING = 1
        RUNNING = 2
        SUCCEEDED = 4
        FAILED = 5
        CANCELLED = 6

    class Batch:
        State = BatchState

    dataproc_v1_module.Batch = Batch

    storage_module = types.ModuleType("google.cloud.storage")
    storage_module.Client = lambda project=None, credentials=None: _CloudSparkGCSClient(state)

    cloud_module = types.ModuleType("google.cloud")
    cloud_module.__path__ = []
    cloud_module.dataproc_v1 = dataproc_v1_module
    cloud_module.storage = storage_module

    root_module = types.ModuleType("google")
    root_module.__path__ = []
    root_module.cloud = cloud_module

    monkeypatch.setitem(sys.modules, "google", root_module)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_module)
    monkeypatch.setitem(sys.modules, "google.cloud.dataproc_v1", dataproc_v1_module)
    monkeypatch.setitem(sys.modules, "google.cloud.storage", storage_module)

    import benchbox.platforms.gcp.dataproc_serverless_adapter as adapter_module

    monkeypatch.setattr(adapter_module, "GOOGLE_CLOUD_AVAILABLE", True)
    monkeypatch.setattr(adapter_module, "dataproc_v1", dataproc_v1_module)
    monkeypatch.setattr(adapter_module, "storage", storage_module)

    import benchbox.utils.dependencies as dep_utils

    original_check = dep_utils.check_platform_dependencies

    def patched_check(platform: str) -> tuple[bool, list[str]]:
        if platform == "dataproc-serverless":
            return True, []
        return original_check(platform)

    monkeypatch.setattr(dep_utils, "check_platform_dependencies", patched_check)

    return state


# ---------------------------------------------------------------------------
# StarRocks stub implementation


@dataclass
class StarRocksStubState:
    host: str = "localhost"
    port: int = 9030
    database: str = "benchbox"
    statements: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=lambda: {"lineitem": 2})
    inserts: list[tuple[str, Any]] = field(default_factory=list)


class _StarRocksCursor:
    def __init__(self, state: StarRocksStubState):
        self._state = state
        self._results: list[tuple[Any, ...]] = []
        self.closed = False
        self.description = None
        self.rowcount = 0

    def execute(self, sql: str, args: Any = None) -> None:
        self._state.statements.append(sql)
        lowered = sql.strip().lower()

        if lowered == "select 1":
            self._results = [(1,)]
        elif lowered.startswith("select version"):
            self._results = [("3.3.0-a1b2c3d",)]
        elif "select count" in lowered:
            from_index = lowered.find("from")
            if from_index >= 0:
                table_fragment = sql[from_index + len("from") :].strip()
                table_name = table_fragment.split()[0].strip("`").lower()
                self._results = [(self._state.row_counts.get(table_name, 0),)]
            else:
                self._results = [(0,)]
        elif lowered.startswith("show databases"):
            self._results = [(self._state.database,)]
        elif lowered.startswith("show tables"):
            self._results = [("lineitem",)]
        elif lowered.startswith("insert into"):
            self._state.inserts.append((sql, args))
            self._results = []
        elif lowered.startswith("select 1 from"):
            self._results = [(1,)]
        else:
            self._results = []

        self.rowcount = len(self._results)

    def executemany(self, sql: str, args: Any = None) -> None:
        self._state.statements.append(sql)
        self._state.inserts.append((sql, args))
        self.rowcount = len(args) if args else 0

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._results)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._results[0] if self._results else None

    def close(self) -> None:
        self.closed = True


class _StarRocksConnection:
    def __init__(self, state: StarRocksStubState, **_: Any) -> None:
        self._state = state
        self._autocommit = False

    def cursor(self) -> _StarRocksCursor:
        return _StarRocksCursor(self._state)

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass

    @property
    def autocommit(self) -> bool:
        return self._autocommit

    @autocommit.setter
    def autocommit(self, value: bool) -> None:
        self._autocommit = value


def install_starrocks_stub(
    monkeypatch,
    *,
    host: str = "localhost",
    port: int = 9030,
) -> StarRocksStubState:
    """Install pymysql stub for StarRocks adapter testing."""

    state = StarRocksStubState(host=host, port=port)

    pymysql_module = types.ModuleType("pymysql")
    pymysql_module.connect = lambda **kwargs: _StarRocksConnection(state, **kwargs)
    pymysql_module.__version__ = "1.1.0"

    cursors_module = types.ModuleType("pymysql.cursors")
    cursors_module.DictCursor = type("DictCursor", (), {})

    err_module = types.ModuleType("pymysql.err")

    class OperationalError(Exception):
        pass

    class ProgrammingError(Exception):
        pass

    err_module.OperationalError = OperationalError
    err_module.ProgrammingError = ProgrammingError
    pymysql_module.OperationalError = OperationalError
    pymysql_module.ProgrammingError = ProgrammingError
    pymysql_module.err = err_module

    monkeypatch.setitem(sys.modules, "pymysql", pymysql_module)
    monkeypatch.setitem(sys.modules, "pymysql.cursors", cursors_module)
    monkeypatch.setitem(sys.modules, "pymysql.err", err_module)

    import benchbox.platforms.starrocks._dependencies as deps_module

    monkeypatch.setattr(deps_module, "pymysql", pymysql_module)
    monkeypatch.setattr(deps_module, "PyMySQLDictCursor", cursors_module.DictCursor)
    monkeypatch.setattr(deps_module, "PYMYSQL_AVAILABLE", True)
    monkeypatch.setattr(deps_module, "STARROCKS_AVAILABLE", True)

    import benchbox.platforms.starrocks.setup as setup_module

    monkeypatch.setattr(setup_module, "pymysql", pymysql_module)
    monkeypatch.setattr(setup_module, "PYMYSQL_AVAILABLE", True)

    return state


# ---------------------------------------------------------------------------
# Databend stub implementation


@dataclass
class DatabendStubState:
    host: str = "localhost"
    port: int = 8000
    database: str = "benchbox"
    statements: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=lambda: {"lineitem": 2})
    inserts: list[str] = field(default_factory=list)


class _DatabendRow:
    """Stub row object returned by Databend driver queries."""

    def __init__(self, data: tuple[Any, ...]):
        self._data = data

    def values(self) -> tuple[Any, ...]:
        return self._data


class _DatabendBlockingClient:
    """Stub for databend_driver.BlockingDatabendClient."""

    def __init__(self, dsn: str, state: DatabendStubState):
        self._dsn = dsn
        self._state = state

    def exec(self, sql: str) -> None:
        self._state.statements.append(sql)
        lowered = sql.strip().lower()
        if lowered.startswith("insert into"):
            self._state.inserts.append(sql)

    def query_row(self, sql: str) -> _DatabendRow | None:
        self._state.statements.append(sql)
        lowered = sql.strip().lower()

        if lowered == "select 1":
            return _DatabendRow((1,))
        elif lowered.startswith("select version"):
            return _DatabendRow(("v1.2.100-nightly",))
        elif "select count" in lowered:
            from_index = lowered.find("from")
            if from_index >= 0:
                table_fragment = sql[from_index + len("from") :].strip()
                table_name = table_fragment.split()[0].strip("`").lower()
                return _DatabendRow((self._state.row_counts.get(table_name, 0),))
            return _DatabendRow((0,))
        else:
            return _DatabendRow((None,))

    def query_iter(self, sql: str) -> Iterable[_DatabendRow]:
        self._state.statements.append(sql)
        lowered = sql.strip().lower()

        if lowered == "select 1":
            return [_DatabendRow((1,))]
        elif lowered.startswith("select version"):
            return [_DatabendRow(("v1.2.100-nightly",))]
        elif "select count" in lowered:
            from_index = lowered.find("from")
            if from_index >= 0:
                table_fragment = sql[from_index + len("from") :].strip()
                table_name = table_fragment.split()[0].strip("`").lower()
                return [_DatabendRow((self._state.row_counts.get(table_name, 0),))]
            return [_DatabendRow((0,))]
        elif lowered.startswith("show databases"):
            return [_DatabendRow((self._state.database,))]
        elif lowered.startswith("explain"):
            return [_DatabendRow(("TableScan: lineitem",))]
        else:
            return [_DatabendRow((1, "result"))]

    def close(self) -> None:
        pass


def install_databend_stub(
    monkeypatch,
    *,
    host: str = "localhost",
    port: int = 8000,
) -> DatabendStubState:
    """Install databend_driver stub for Databend adapter testing."""

    state = DatabendStubState(host=host, port=port)

    def make_client(dsn: str) -> _DatabendBlockingClient:
        return _DatabendBlockingClient(dsn, state)

    driver_module = types.ModuleType("databend_driver")
    driver_module.BlockingDatabendClient = make_client
    driver_module.__version__ = "0.20.0"

    monkeypatch.setitem(sys.modules, "databend_driver", driver_module)

    # Patch the adapter module's import state
    import benchbox.platforms.databend.adapter as adapter_module

    monkeypatch.setattr(adapter_module, "DATABEND_AVAILABLE", True)
    monkeypatch.setattr(adapter_module, "databend_driver", driver_module)

    return state


# ---------------------------------------------------------------------------
# Apache Doris stub implementation


@dataclass
class DorisStubState:
    host: str = "localhost"
    port: int = 9030
    http_port: int = 8030
    database: str = "benchbox"
    statements: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=lambda: {"lineitem": 2})
    inserts: list[tuple[str, Any]] = field(default_factory=list)


class _DorisCursor:
    def __init__(self, state: DorisStubState):
        self._state = state
        self._results: list[tuple[Any, ...]] = []
        self.description = None
        self.rowcount = 0

    def execute(self, sql: str, args: Any = None) -> None:
        self._state.statements.append(sql)
        lowered = sql.strip().lower()

        if lowered == "select 1" or lowered == "select 1 as test_value":
            self._results = [(1,)]
        elif lowered.startswith("select version"):
            self._results = [("5.7.99-Doris-2.1.7",)]
        elif lowered.startswith("select database"):
            self._results = [(self._state.database,)]
        elif "select count" in lowered:
            from_index = lowered.find("from")
            if from_index >= 0:
                table_fragment = sql[from_index + len("from") :].strip()
                table_name = table_fragment.split()[0].strip("`").lower()
                self._results = [(self._state.row_counts.get(table_name, 0),)]
            else:
                self._results = [(0,)]
        elif lowered.startswith("show databases"):
            self._results = [(self._state.database,)]
        elif lowered.startswith("show tables"):
            self._results = [("lineitem",)]
        elif lowered.startswith("show frontends"):
            self._results = [("fe1", "127.0.0.1", "9010", "true")]
        elif lowered.startswith("insert into"):
            self._state.inserts.append((sql, args))
            self._results = []
        elif lowered.startswith(("set ", "analyze")):
            self._results = []
        elif lowered.startswith("explain"):
            self._results = [("0:OlapScanNode TABLE: lineitem",)]
        else:
            self._results = []

        self.rowcount = len(self._results)

    def executemany(self, sql: str, args: Any = None) -> None:
        self._state.statements.append(sql)
        self._state.inserts.append((sql, args))
        self.rowcount = len(args) if args else 0

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._results)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._results[0] if self._results else None

    def close(self) -> None:
        pass


class _DorisConnection:
    def __init__(self, state: DorisStubState, **_: Any) -> None:
        self._state = state

    def cursor(self) -> _DorisCursor:
        return _DorisCursor(self._state)

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


def install_doris_stub(
    monkeypatch,
    *,
    host: str = "localhost",
    port: int = 9030,
) -> DorisStubState:
    """Install pymysql stub for Apache Doris adapter testing."""

    state = DorisStubState(host=host, port=port)

    pymysql_module = types.ModuleType("pymysql")
    pymysql_module.connect = lambda **kwargs: _DorisConnection(state, **kwargs)
    pymysql_module.__version__ = "1.1.1"

    cursors_module = types.ModuleType("pymysql.cursors")
    cursors_module.DictCursor = type("DictCursor", (), {})

    err_module = types.ModuleType("pymysql.err")

    class OperationalError(Exception):
        pass

    class ProgrammingError(Exception):
        pass

    err_module.OperationalError = OperationalError
    err_module.ProgrammingError = ProgrammingError
    pymysql_module.OperationalError = OperationalError
    pymysql_module.ProgrammingError = ProgrammingError
    pymysql_module.err = err_module

    monkeypatch.setitem(sys.modules, "pymysql", pymysql_module)
    monkeypatch.setitem(sys.modules, "pymysql.cursors", cursors_module)
    monkeypatch.setitem(sys.modules, "pymysql.err", err_module)

    # Patch the adapter module to use our stubs
    try:
        import benchbox.platforms.doris as adapter_module

        adapter_module.pymysql = pymysql_module
        # Disable requests so load_data uses INSERT fallback (testable without HTTP)
        adapter_module._requests = None
    except ImportError:  # pragma: no cover - defensive
        pass

    return state


# ---------------------------------------------------------------------------
# LakeSail stub implementation


@dataclass
class LakeSailStubState:
    endpoint: str = "sc://localhost:50051"
    database: str = "benchbox_test"
    statements: list[str] = field(default_factory=list)
    databases: list[str] = field(default_factory=lambda: ["default", "benchbox_test"])
    tables: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=lambda: {"LINEITEM": 2, "ORDERS": 2})


class _LakeSailStubRow:
    """Stub for a PySpark Row-like object."""

    def __init__(self, **kwargs: Any) -> None:
        self._values = list(kwargs.values())
        for key, value in kwargs.items():
            object.__setattr__(self, key, value)

    def __iter__(self):
        return iter(self._values)

    def __getitem__(self, index):
        return self._values[index]


class _LakeSailStubDataFrame:
    """Stub for a PySpark DataFrame."""

    def __init__(self, data: list[dict[str, Any]] | None = None, schema: Any = None) -> None:
        self._data = data or []
        self._schema = schema

    def collect(self) -> list[Any]:
        return [_LakeSailStubRow(**row) for row in self._data]

    def count(self) -> int:
        return len(self._data)

    @property
    def columns(self) -> list[str]:
        if self._data:
            return list(self._data[0].keys())
        return []

    def first(self) -> Any:
        if self._data:
            return _LakeSailStubRow(**self._data[0])
        return None

    def cache(self) -> _LakeSailStubDataFrame:
        return self

    def unpersist(self) -> _LakeSailStubDataFrame:
        return self

    def withColumnRenamed(self, existing: str, new: str) -> _LakeSailStubDataFrame:
        return _LakeSailStubDataFrame(self._data, self._schema)

    def withColumn(self, name: str, col: Any) -> _LakeSailStubDataFrame:
        return _LakeSailStubDataFrame(self._data, self._schema)

    def select(self, *cols: Any) -> _LakeSailStubDataFrame:
        return _LakeSailStubDataFrame(self._data, self._schema)

    def __getitem__(self, key: str) -> Any:
        class _StubColumn:
            def __init__(self, name: str) -> None:
                self.name = name

            def cast(self, data_type: Any) -> _StubColumn:
                return self

        return _StubColumn(key)

    @property
    def schema(self) -> Any:
        return self._schema

    @property
    def write(self) -> Any:
        class Writer:
            def saveAsTable(self, name: str) -> None:
                pass

            def insertInto(self, name: str) -> None:
                pass

            def mode(self, m: str) -> Writer:
                return self

            def format(self, fmt: str) -> Writer:
                return self

        return Writer()


class _LakeSailStubCatalog:
    """Stub for SparkSession.catalog."""

    def __init__(self, state: LakeSailStubState) -> None:
        self._state = state

    def listDatabases(self) -> list[Any]:
        return [_LakeSailStubRow(name=db) for db in self._state.databases]

    def listTables(self, dbName: str | None = None) -> list[Any]:
        return [_LakeSailStubRow(name=t) for t in self._state.tables]

    def clearCache(self) -> None:
        pass


class _LakeSailStubReader:
    """Stub for SparkSession.read."""

    def __init__(self, state: LakeSailStubState) -> None:
        self._state = state
        self._format = "csv"
        self._schema = None
        self._options: dict[str, str] = {}

    def format(self, fmt: str) -> _LakeSailStubReader:
        self._format = fmt
        return self

    def schema(self, schema: Any) -> _LakeSailStubReader:
        self._schema = schema
        return self

    def option(self, key: str, value: str) -> _LakeSailStubReader:
        self._options[key] = value
        return self

    def csv(self, path: Any) -> _LakeSailStubDataFrame:
        return _LakeSailStubDataFrame([{"col1": "value1"}])

    def parquet(self, path: Any) -> _LakeSailStubDataFrame:
        return _LakeSailStubDataFrame([{"col1": "value1"}])

    def load(self, path: str | None = None) -> _LakeSailStubDataFrame:
        return _LakeSailStubDataFrame([{"col1": "value1"}])


class _LakeSailStubConf:
    """Stub for SparkSession.conf."""

    def __init__(self) -> None:
        self._conf: dict[str, str] = {}

    def set(self, key: str, value: str) -> None:
        self._conf[key] = value

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._conf.get(key, default)


class _LakeSailStubSession:
    """Stub for PySpark SparkSession connected via Spark Connect."""

    def __init__(self, state: LakeSailStubState) -> None:
        self._state = state
        self.catalog = _LakeSailStubCatalog(state)
        self.read = _LakeSailStubReader(state)
        self.conf = _LakeSailStubConf()

    @property
    def version(self) -> str:
        return "3.5.0-sail"

    def table(self, table_name: str) -> _LakeSailStubDataFrame:
        """Return a stub DataFrame for a table (used by SparkDataLoadMixin for schema inference)."""
        return _LakeSailStubDataFrame([{"col1": "value1"}])

    def sql(self, query: str) -> _LakeSailStubDataFrame:
        self._state.statements.append(query)
        lowered = query.strip().lower()

        if lowered == "select 1" or lowered == "select 1 as value":
            return _LakeSailStubDataFrame([{"value": 1}])
        elif "count(*)" in lowered or "count(1)" in lowered:
            for table, count in self._state.row_counts.items():
                if table.lower() in lowered:
                    return _LakeSailStubDataFrame([{"count(1)": count}])
            return _LakeSailStubDataFrame([{"count(1)": 0}])
        elif "show tables" in lowered or "show databases" in lowered:
            return _LakeSailStubDataFrame([{"name": t} for t in self._state.tables])
        elif (
            "create database" in lowered
            or "create schema" in lowered
            or "drop database" in lowered
            or "drop schema" in lowered
            or "create table" in lowered
            or "create external table" in lowered
            or "drop table" in lowered
            or "use " in lowered
        ):
            return _LakeSailStubDataFrame()
        else:
            # Default: return 2 rows for query execution
            return _LakeSailStubDataFrame([{"col1": "val1"}, {"col1": "val2"}])

    def stop(self) -> None:
        pass


class _LakeSailStubBuilder:
    """Stub for SparkSession.builder with Spark Connect .remote() support."""

    def __init__(self, state: LakeSailStubState) -> None:
        self._state = state

    def remote(self, endpoint: str) -> _LakeSailStubBuilder:
        self._state.endpoint = endpoint
        return self

    def config(self, key: str, value: str | None = None) -> _LakeSailStubBuilder:
        return self

    def appName(self, name: str) -> _LakeSailStubBuilder:
        return self

    def getOrCreate(self) -> _LakeSailStubSession:
        return _LakeSailStubSession(self._state)


def install_lakesail_stub(
    monkeypatch,
    *,
    endpoint: str = "sc://localhost:50051",
    database: str = "benchbox_test",
) -> LakeSailStubState:
    """Install stubs for LakeSail adapter (PySpark Spark Connect)."""

    state = LakeSailStubState(endpoint=endpoint, database=database)

    # Create stub PySpark modules
    pyspark_module = types.ModuleType("pyspark")
    pyspark_module.__version__ = "3.5.0"

    pyspark_sql_module = types.ModuleType("pyspark.sql")

    # Create SparkSession class with stub builder
    class StubSparkSession:
        builder = _LakeSailStubBuilder(state)

    pyspark_sql_module.SparkSession = StubSparkSession

    # Create stub types module
    pyspark_types_module = types.ModuleType("pyspark.sql.types")
    for type_name in [
        "StructType",
        "StructField",
        "StringType",
        "IntegerType",
        "LongType",
        "DoubleType",
        "DecimalType",
        "DateType",
    ]:
        setattr(pyspark_types_module, type_name, type(type_name, (), {"__init__": lambda self, *a, **kw: None}))

    monkeypatch.setitem(sys.modules, "pyspark", pyspark_module)
    monkeypatch.setitem(sys.modules, "pyspark.sql", pyspark_sql_module)
    monkeypatch.setitem(sys.modules, "pyspark.sql.types", pyspark_types_module)

    # Patch the adapter module
    try:
        import benchbox.platforms.lakesail as adapter_module

        adapter_module.SparkSession = StubSparkSession
        for type_name in [
            "StructType",
            "StructField",
            "StringType",
            "IntegerType",
            "LongType",
            "DoubleType",
            "DecimalType",
            "DateType",
        ]:
            setattr(adapter_module, type_name, getattr(pyspark_types_module, type_name))

        # Make the adapter think the server is reachable so tests skip the
        # real TCP connection and pysail import checks.
        # The adapter calls is_spark_connect_reachable from _spark_helpers, which
        # the lakesail module imports by name - patch that imported name.
        monkeypatch.setattr(
            adapter_module,
            "is_spark_connect_reachable",
            lambda endpoint, *, timeout=2.0: True,
        )
    except ImportError:  # pragma: no cover
        pass

    # Patch dependency check
    try:
        import benchbox.utils.dependencies as dep_utils

        original_check = dep_utils.check_platform_dependencies

        def patched_check(platform: str) -> tuple[bool, list[str]]:
            if platform in ("spark", "lakesail"):
                return True, []
            return original_check(platform)

        monkeypatch.setattr(dep_utils, "check_platform_dependencies", patched_check)
    except ImportError:  # pragma: no cover
        pass

    return state
