from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import os
import re
import shutil
import sys
import tempfile
import time
import types
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterator

import pytest

from benchbox.core.platform_registry import PlatformRegistry
from benchbox.core.tuning.applied_ledger import AppliedTuningLedger
from benchbox.core.tuning.interface import UnifiedTuningConfiguration

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

DESTRUCTIVE_SQL = re.compile(r"(?:^|;)\s*(?:--[^\n]*\n\s*)*(?:DROP|DELETE|TRUNCATE)\b", re.IGNORECASE)
TUNING_METADATA_REWRITE = re.compile(r"^\s*DELETE\s+FROM\s+\S*benchbox_tuning_metadata\b", re.IGNORECASE)
TABLE_RESET = re.compile(
    r"^\s*(?:DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?|TRUNCATE\s+(?:TABLE\s+)?|DELETE\s+FROM\s+)([\w.#\"`\[\]]+)",
    re.IGNORECASE,
)
BENCHMARK_TABLE = "region"
TABLE_CREATE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:\w+\s+)*?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.#\"`\[\]]+)", re.IGNORECASE
)
DESTRUCTIVE_CALL = re.compile(r"^(?:drop|delete|truncate|remove|rmtree|unlink|destroy|purge)(?:_|$)", re.IGNORECASE)
SQL_CALLS = frozenset(
    {
        "execute",
        "executemany",
        "executescript",
        "sql",
        "query",
        "command",
        "execute_query",
        "execute_statement",
        "execute_command",
        "run_query",
        "exec",
        "raw_query",
        "query_df",
        "query_arrow",
        "query_dataframe",
        "query_iter",
    }
)
FETCH_ALL = frozenset({"fetchall", "fetchmany", "fetch_all", "fetch"})
FETCH_ONE = frozenset({"fetchone", "fetch_one"})
TEXT_ATTRIBUTES = frozenset({"token", "access_token"})
FAR_FUTURE_ATTRIBUTES = frozenset({"expires_on"})
COUNT_QUERY = re.compile(r"\bCOUNT\s*\(", re.IGNORECASE)
CONNECTION_PROBE = re.compile(r"^\s*SELECT\s+1(?:\s+AS\s+\w+)?\s*;?\s*$", re.IGNORECASE)
FAKE_VERSION = "9.9.9"
FAKE_VERSIONS = {"duckdb": "1.4.0"}
CATALOG_NAME = "benchdb"


def table_key(identifier: str) -> str:
    return re.sub(r"[\"`\[\]]", "", identifier).rsplit(".", 1)[-1].lower()


class CatalogRow(tuple):
    def get(self, key: Any, default: Any = None) -> Any:
        return default

    def __getattr__(self, attribute: str) -> Any:
        if attribute.startswith("__") and attribute.endswith("__"):
            raise AttributeError(attribute)
        return CATALOG_NAME


class Payload(dict):
    def __missing__(self, key: Any) -> str:
        return f"fake-{key}"


class ValuesRow(tuple):
    def values(self) -> list[Any]:
        return list(self)


@dataclass
class Event:
    phase: str
    stage: str
    kind: str
    detail: str
    destructive: bool
    target: str = ""

    def __str__(self) -> str:
        return f"[{self.phase}/{self.stage}] {self.kind}: {self.detail}"


@dataclass
class Ledger:
    world: Path
    phase: str = "decision"
    stage: str = "first_connection"
    events: list[Event] = field(default_factory=list)
    protected: set[str] = field(default_factory=set)
    rows: list[Any] = field(default_factory=lambda: [CatalogRow((CATALOG_NAME,) * 4)])
    scripted: list[tuple[re.Pattern[str], list[Any]]] = field(default_factory=list)
    last_sql: str = ""
    deletable_roots: tuple[Path, ...] = ()

    def rows_now(self) -> list[Any]:
        for pattern, rows in self.scripted:
            if pattern.search(self.last_sql):
                return rows
        return self.rows

    def record(self, kind: str, detail: str, destructive: bool, target: str = "") -> None:
        self.events.append(Event(self.phase, self.stage, kind, detail.strip()[:240], destructive, target))

    def record_sql(self, origin: str, statement: str) -> None:
        self.last_sql = statement
        self.record("sql", f"{origin}: {statement}", bool(DESTRUCTIVE_SQL.search(statement)), statement)

    def record_call(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        leaf = name.rsplit(".", 1)[-1]
        statements = [value for value in (*args, *kwargs.values()) if isinstance(value, str)]
        if leaf in SQL_CALLS and statements:
            self.record_sql(name, statements[0])
        elif any(DESTRUCTIVE_SQL.search(statement) for statement in statements):
            self.record_sql(name, next(statement for statement in statements if DESTRUCTIVE_SQL.search(statement)))
        elif DESTRUCTIVE_CALL.match(leaf):
            self.record("call", name, True)

    def may_delete_for_real(self, target: Path) -> bool:
        resolved = target.resolve()
        return not self.removes_protected_path(resolved) and any(
            resolved.is_relative_to(root) for root in self.deletable_roots
        )

    def protect_current_files(self) -> None:
        self.protected |= {str(path.resolve()) for path in self.world.rglob("*")}

    def removes_protected_path(self, target: Path) -> bool:
        resolved = str(target.resolve())
        return any(path == resolved or path.startswith(resolved + os.sep) for path in self.protected)

    def violations(self) -> list[Event]:
        post = [event for event in self.events if event.phase == "post"]
        recreated = {
            (event.stage, table_key(match.group(1)))
            for event in post
            if event.kind == "sql"
            for match in TABLE_CREATE.finditer(event.target)
        }
        return [event for event in post if event.destructive and not self._is_sanctioned(event, recreated)]

    @staticmethod
    def _is_sanctioned(event: Event, recreated: set[tuple[str, str]]) -> bool:
        if event.kind != "sql":
            return False
        if event.stage == "save_tuning_metadata" and TUNING_METADATA_REWRITE.match(event.target):
            return True
        reset = TABLE_RESET.match(event.target)
        if not reset:
            return False
        table = table_key(reset.group(1))
        if (event.stage, table) in recreated:
            return True
        return event.stage == "load_data" and table.startswith(BENCHMARK_TABLE)

    def in_phase(self, phase: str, *, destructive: bool | None = None, kind: str | None = None) -> list[Event]:
        return [
            event
            for event in self.events
            if event.phase == phase
            and (destructive is None or event.destructive == destructive)
            and (kind is None or event.kind == kind)
        ]


_EXCEPTION_TYPES: dict[str, type[Exception]] = {}


def exception_type(name: str) -> type[Exception]:
    if name not in _EXCEPTION_TYPES:
        _EXCEPTION_TYPES[name] = type(name, (Exception,), {})
    return _EXCEPTION_TYPES[name]


class Fake:
    def __init__(self, ledger: Ledger, name: str) -> None:
        object.__setattr__(self, "_ledger", ledger)
        object.__setattr__(self, "_name", name)

    def __getattr__(self, attribute: str) -> Any:
        if attribute.startswith("__") and attribute.endswith("__"):
            raise AttributeError(attribute)
        if attribute.endswith(("Error", "Exception", "Warning")):
            return exception_type(attribute)
        if attribute in TEXT_ATTRIBUTES:
            return "fake-" + attribute
        if attribute in FAR_FUTURE_ATTRIBUTES:
            return time.time() + 10**9
        if attribute == "status_code":
            return 200
        return Fake(self._ledger, f"{self._name}.{attribute}")

    def __setattr__(self, attribute: str, value: Any) -> None:
        return None

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self._ledger.record_call(self._name, args, kwargs)
        leaf = self._name.rsplit(".", 1)[-1]
        rows = self._ledger.rows_now()
        if leaf in FETCH_ALL:
            return list(rows)
        if leaf in FETCH_ONE:
            return rows[0] if rows else None
        if leaf == "bytes":
            return b""
        if leaf == "json":
            return Payload()
        if leaf == "default":
            return Fake(self._ledger, "credentials"), CATALOG_NAME
        return Fake(self._ledger, f"{self._name}()")

    def __enter__(self) -> Fake:
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        return False

    def __iter__(self):
        return iter(self._ledger.rows_now())

    def __len__(self) -> int:
        return len(self._ledger.rows_now())

    def __bool__(self) -> bool:
        return True

    def __getitem__(self, key: Any) -> Any:
        try:
            return self._ledger.rows_now()[key]
        except (IndexError, TypeError):
            return Fake(self._ledger, f"{self._name}[]")

    def __setitem__(self, key: Any, value: Any) -> None:
        return None

    def __str__(self) -> str:
        return "fake"

    def __format__(self, spec: str) -> str:
        return format(1, spec) if spec else "fake"

    def __int__(self) -> int:
        return 1

    def __float__(self) -> float:
        return 1.0

    def __lt__(self, other: Any) -> bool:
        return False

    __le__ = __gt__ = __ge__ = __lt__

    def __hash__(self) -> int:
        return id(self)


class FakeModule(types.ModuleType):
    def __init__(self, ledger: Ledger, name: str) -> None:
        super().__init__(name)
        self.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
        self.__path__ = []
        self.__version__ = FAKE_VERSIONS.get(name, FAKE_VERSION)
        self._ledger = ledger

    def __getattr__(self, attribute: str) -> Any:
        if attribute.startswith("__") and attribute.endswith("__"):
            raise AttributeError(attribute)
        if attribute.endswith(("Error", "Exception", "Warning")):
            return exception_type(attribute)
        return Fake(self._ledger, f"{self.__name__}.{attribute}")


DRIVER_ROOTS = frozenset(
    {
        "sqlite3",
        "duckdb",
        "psycopg",
        "psycopg2",
        "pymysql",
        "pyodbc",
        "clickhouse_driver",
        "clickhouse_connect",
        "chdb",
        "snowflake",
        "databricks",
        "google",
        "boto3",
        "redshift_connector",
        "trino",
        "prestodb",
        "databend_driver",
        "singlestoredb",
        "pyathena",
        "pyspark",
        "pysail",
        "requests",
        "azure",
        "firebolt",
        "influxdb_client_3",
        "influxdb3",
        "datafusion",
        "polars",
    }
)
OPTIONAL_IMPORT_NAMES = frozenset(
    {
        "google_auth",
        "bigquery",
        "storage",
        "service_account",
        "DictCursor",
        "snowflake",
        "firebolt_connect",
        "ClientCredentials",
        "FireboltCore",
        "DefaultAzureCredential",
        "DataLakeServiceClient",
        "requests",
        "HTTPAdapter",
        "Retry",
        "dataproc_v1",
        "Session",
        "InfluxDBClient3",
        "FlightSQLClient",
        "databend_driver",
        "redshift_connector",
        "DatabricksSession",
        "F",
        "boto3",
        "pyodbc",
        "databricks_sql",
        "_s2",
        "SparkSession",
        "StructType",
        "StructField",
        "StringType",
        "IntegerType",
        "LongType",
        "DoubleType",
        "pl",
        "psycopg",
        "psycopg_sql",
        "psql",
        "duckdb",
        "trino",
        "prestodb",
        "athena_connect",
        "ClickHouseClient",
        "clickhouse_connect",
        "pymysql",
        "PyMySQLDictCursor",
    }
)


class FakeServiceNeverCompletes(Exception):
    pass


class PollingClock:
    def __getattr__(self, attribute: str) -> Any:
        return getattr(time, attribute)

    @staticmethod
    def sleep(seconds: float) -> None:
        raise FakeServiceNeverCompletes(f"fake service cannot complete a {seconds}s poll")


class FakeFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def find_spec(self, name: str, path: Any, target: Any = None) -> importlib.machinery.ModuleSpec | None:
        if name.split(".")[0] in DRIVER_ROOTS:
            return importlib.machinery.ModuleSpec(name, self, is_package=True)
        return None

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> types.ModuleType:
        return FakeModule(self.ledger, spec.name)

    def exec_module(self, module: types.ModuleType) -> None:
        return None


def driver_replacement(ledger: Ledger, owner: str, name: str, value: Any) -> Any:
    if value is None:
        return Fake(ledger, f"{owner}.{name}") if name in OPTIONAL_IMPORT_NAMES else None
    if isinstance(value, types.ModuleType):
        if value.__name__.split(".")[0] in DRIVER_ROOTS:
            return importlib.import_module(value.__name__)
        return None
    if isinstance(value, type) and issubclass(value, BaseException):
        return None
    if (getattr(value, "__module__", None) or "").split(".")[0] in DRIVER_ROOTS:
        return Fake(ledger, f"{owner}.{name}")
    return None


@dataclass
class Spec:
    config: dict[str, Any] = field(default_factory=dict)
    patches: dict[str, Any] = field(default_factory=dict)
    scripted: dict[str, list[Any]] = field(default_factory=dict)
    connection_sites: tuple[str, ...] = ()
    no_positive_control: str = ""


AWS = {
    "s3_staging_dir": "s3://bench-bucket/benchbox/",
    "aws_access_key_id": "AKIAFAKEFAKEFAKE",
    "aws_secret_access_key": "secret",
    "region": "us-east-1",
}
GCP = {
    "project_id": "bench-project",
    "region": "us-central1",
    "gcs_staging_dir": "gs://bench-bucket/benchbox",
}
ROLE_ARN = "arn:aws:iam::123456789012:role/bench"
FABRIC = {"workspace": "00000000-0000-0000-0000-000000000000"}
DUCKLAKE = {
    "catalog": "duckdb",
    "metadata_path": "{world}/db/bench.db",
    "data_path": "{world}/db/dir_db",
    "benchmark": "tpch",
    "scale_factor": 0.01,
}
DATABRICKS = Spec(
    config={
        "server_hostname": "ws.cloud.databricks.com",
        "http_path": "/sql/1.0/warehouses/x",
        "access_token": "tok",
        "catalog": CATALOG_NAME,
        "schema": CATALOG_NAME,
        "staging_root": "dbfs:/Volumes/workspace/tmp",
    },
    scripted={
        r"SET use_cached_result\s*$": [("use_cached_result", "false")],
        r"SHOW TABLES IN": [(CATALOG_NAME, "region", False)],
    },
)

SPECS: dict[str, Spec] = {
    "athena": Spec(config=AWS),
    "athena-spark": Spec(
        config={**AWS, "workgroup": "spark-wg"}, patches={"_wait_for_session_ready": lambda *a, **k: None}
    ),
    "bigquery": Spec(config={"project_id": "bench-project", "dataset_id": CATALOG_NAME}),
    "clickhouse-cloud": Spec(
        no_positive_control="check_server_database_exists builds a native-protocol admin client from "
        "attributes the cloud adapter never sets, fails with AttributeError, and reports no database",
    ),
    "databend": Spec(scripted={r"SHOW DATABASES": [ValuesRow((CATALOG_NAME,))]}),
    "databricks": DATABRICKS,
    "databricks-df": DATABRICKS,
    "datafusion": Spec(config={"working_dir": "{world}/db/dir_db"}),
    "dataproc": Spec(config=GCP),
    "dataproc-serverless": Spec(config=GCP),
    "ducklake": Spec(config=DUCKLAKE, scripted={r"version\(\)": [("v1.4.0",)]}),
    "emr-serverless": Spec(config={**AWS, "execution_role_arn": ROLE_ARN, "application_id": "app-1"}),
    "fabric-lakehouse": Spec(config=FABRIC, connection_sites=("get_platform_info",)),
    "fabric-spark": Spec(config={"workspace_id": FABRIC["workspace"], "lakehouse_id": FABRIC["workspace"]}),
    "fabric_dw": Spec(
        config=FABRIC, connection_sites=("test_connection", "check_server_database_exists", "get_platform_info")
    ),
    "firebolt": Spec(
        no_positive_control="Firebolt Core recreates databases implicitly, so drop_database only logs",
    ),
    "glue": Spec(config={**AWS, "job_role": ROLE_ARN}),
    "influxdb": Spec(
        no_positive_control="InfluxDB reports no file path and no server database, so force_recreate only warns",
    ),
    "motherduck": Spec(config={"token": "tok"}, connection_sites=("execute_query", "test_connection")),
    "polars": Spec(config={"working_dir": "{world}/db/dir_db"}),
    "pyspark": Spec(
        no_positive_control="create_connection runs the existing-database check before the Spark session exists, "
        "so check_server_database_exists reports no database",
    ),
    "quanton": Spec(config={**AWS, "api_key": "key"}),
    "snowflake": Spec(config={"account": "acct"}),
    "snowpark-connect": Spec(config={"account": "acct", "user": "user"}),
    "starrocks": Spec(connection_sites=("get_connection",)),
    "synapse": Spec(config={"server": "ws.sql.azuresynapse.net"}),
    "synapse-spark": Spec(
        config={
            "workspace_name": "ws",
            "spark_pool_name": "pool",
            "storage_account": "acct",
            "storage_container": "bench",
        }
    ),
    "velox": Spec(
        config={"gluten_jar_path": "{world}/db/bench.db"},
        no_positive_control="the adapter defines no database existence check",
    ),
}

VARIANTS: dict[str, dict[str, Spec]] = {
    "ducklake": {
        "postgres_catalog": Spec(
            config={**DUCKLAKE, "catalog": "postgres"},
            scripted={r"version\(\)": [("v1.4.0",)], r"duckdb_tables\(\)": [("main", "region")]},
        )
    },
    "firebolt": {
        "cloud": Spec(
            config={
                "deployment_mode": "cloud",
                "client_id": "id",
                "client_secret": "secret",
                "account_name": "acct",
                "engine_name": "engine",
            }
        )
    },
}

REQUIRED_ADAPTERS = frozenset(
    {
        "clickhouse-local",
        "clickhouse-server",
        "clickhouse-cloud",
        "ducklake",
        "starrocks",
        "citus",
        "paradedb",
        "pg-duckdb",
        "pg-mooncake",
        "timescaledb",
        "fabric_dw",
        "fabric-lakehouse",
        "motherduck",
    }
)


@dataclass(frozen=True)
class Case:
    key: str
    variant: str
    spec: Spec

    @property
    def id(self) -> str:
        return f"{self.key}-{self.variant}" if self.variant else self.key


def adapter_names() -> list[str]:
    return sorted(PlatformRegistry.get_available_platforms())


def build_cases() -> list[Case]:
    cases = []
    for name in adapter_names():
        cases.append(Case(name, "", SPECS.get(name, Spec())))
        cases.extend(Case(name, variant, spec) for variant, spec in VARIANTS.get(name, {}).items())
    return cases


CASES = build_cases()
CASE_PARAMS = [pytest.param(case, id=case.id) for case in CASES]


def path_operation(ledger: Ledger, label: str, original: Callable[..., Any]) -> Callable[..., Any]:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        target_arg = args[0] if args else kwargs.get("path", "")
        try:
            target = Path(os.fspath(target_arg))
        except TypeError:
            return original(*args, **kwargs)
        if ledger.may_delete_for_real(target):
            ledger.record("fs", f"{label} {target} (created during this run)", False, str(target))
            return original(*args, **kwargs)
        ledger.record("fs", f"{label} {target}", True, str(target))
        return None

    return wrapper


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "world"
    (root / "db" / "dir_db").mkdir(parents=True)
    (root / "db" / "bench.db").write_bytes(b"stub")
    for stub in ("stub.bin", "stub.parquet", "stub.csv"):
        (root / "db" / "dir_db" / stub).write_bytes(b"stub")
    (root / "data").mkdir()
    (root / "data" / "region.tbl").write_text("0|AFRICA|comment|\n")
    monkeypatch.chdir(root)
    monkeypatch.setenv("JAVA_HOME", os.environ.get("JAVA_HOME", str(root)))
    return root


@pytest.fixture
def ledger(world: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Ledger]:
    ledger = Ledger(world=world, deletable_roots=(world.resolve(), Path(tempfile.gettempdir()).resolve()))
    ledger.scripted.append((CONNECTION_PROBE, [(1,)]))
    ledger.scripted.append((COUNT_QUERY, [(1,)]))
    ledger.protect_current_files()

    for module, attribute in (
        (os, "remove"),
        (os, "unlink"),
        (os, "rmdir"),
        (os, "removedirs"),
        (shutil, "rmtree"),
    ):
        original = getattr(module, attribute)
        monkeypatch.setattr(module, attribute, path_operation(ledger, f"{module.__name__}.{attribute}", original))

    path_unlink = Path.unlink
    path_rmdir = Path.rmdir

    def unlink(self: Path, *args: Any, **kwargs: Any) -> None:
        return path_operation(ledger, "Path.unlink", lambda *a, **k: path_unlink(self, *args, **kwargs))(self)

    def rmdir(self: Path, *args: Any, **kwargs: Any) -> None:
        return path_operation(ledger, "Path.rmdir", lambda *a, **k: path_rmdir(self, *args, **kwargs))(self)

    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(Path, "rmdir", rmdir)

    for module_name in [name for name in sys.modules if name.split(".")[0] in DRIVER_ROOTS]:
        monkeypatch.delitem(sys.modules, module_name)
    monkeypatch.setattr(sys, "meta_path", [FakeFinder(ledger), *sys.meta_path])
    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith("benchbox.") or module is None:
            continue
        for name, value in list(vars(module).items()):
            replacement = driver_replacement(ledger, module_name, name, value)
            if replacement is not None:
                monkeypatch.setattr(module, name, replacement)
        if vars(module).get("time") is time:
            monkeypatch.setattr(module, "time", PollingClock())
        for name, stand_in in NETWORK_STAND_INS.items():
            if name in vars(module):
                monkeypatch.setattr(module, name, stand_in)
    yield ledger
    for module_name in [name for name, module in sys.modules.items() if isinstance(module, FakeModule)]:
        del sys.modules[module_name]


NETWORK_STAND_INS: dict[str, Callable[..., Any]] = {
    "is_spark_connect_reachable": lambda *a, **k: True,
    "check_platform_dependencies": lambda *a, **k: (True, []),
    "_ensure_compatible_java": lambda *a, **k: None,
}


def make_adapter(case: Case, world: Path, ledger: Ledger, *, force_recreate: bool) -> Any:
    config: dict[str, Any] = {
        "database_path": str(world / "db" / "bench.db"),
        "host": "db.test",
        "username": "user",
        "password": "secret",
        "database": CATALOG_NAME,
        "schema": CATALOG_NAME,
        "catalog": CATALOG_NAME,
        "force_recreate": force_recreate,
        "tuning_enabled": True,
        "unified_tuning_configuration": UnifiedTuningConfiguration(),
    }
    config.update(
        {key: value.format(world=world) if isinstance(value, str) else value for key, value in case.spec.config.items()}
    )
    ledger.scripted[:0] = [(re.compile(pattern, re.IGNORECASE), rows) for pattern, rows in case.spec.scripted.items()]
    adapter = PlatformRegistry.get_adapter_class(case.key)(**config)
    for attribute, replacement in case.spec.patches.items():
        setattr(adapter, attribute, replacement)
    return adapter


def make_benchmark(world: Path) -> Any:
    data_dir = world / "data"
    return SimpleNamespace(
        output_dir=data_dir,
        scale_factor=0.01,
        tables={"region": data_dir / "region.tbl"},
        _name="tpch",
        get_table_names=lambda: ["region"],
        get_schema=lambda: {"region": {"r_regionkey": "INTEGER", "r_name": "VARCHAR(25)"}},
        get_create_tables_sql=lambda *a, **k: "CREATE TABLE region (r_regionkey INTEGER, r_name VARCHAR(25));",
        get_data_source_benchmark=lambda: None,
    )


@dataclass
class Outcome:
    stage_errors: dict[str, str] = field(default_factory=dict)
    connections: dict[str, int] = field(default_factory=dict)
    decision_calls: int = 0
    metadata_saved: bool | None = None


MIDRUN_HELPERS = (
    "get_platform_info",
    "test_connection",
    "check_server_database_exists",
    "get_connection",
    "get_connection_from_pool",
)


def instrument(adapter: Any, ledger: Ledger, outcome: Outcome) -> Callable[..., Any]:
    original_create = adapter.create_connection
    original_handle = adapter.handle_existing_database
    depth = 0

    def create_connection(*args: Any, **kwargs: Any) -> Any:
        nonlocal depth
        depth += 1
        if ledger.phase == "post":
            outcome.connections[ledger.stage] = outcome.connections.get(ledger.stage, 0) + 1
        try:
            return original_create(*args, **kwargs)
        finally:
            depth -= 1
            if depth == 0 and ledger.phase == "decision":
                ledger.phase = "post"
                ledger.protect_current_files()

    def handle_existing_database(*args: Any, **kwargs: Any) -> None:
        if ledger.phase == "decision":
            outcome.decision_calls += 1
        return original_handle(*args, **kwargs)

    adapter.create_connection = create_connection
    adapter.handle_existing_database = handle_existing_database
    return create_connection


def run_stage(ledger: Ledger, outcome: Outcome, name: str, call: Callable[[], Any]) -> Any:
    ledger.stage = name
    try:
        return call()
    except Exception as exc:
        outcome.stage_errors[name] = f"{type(exc).__name__}: {exc}"
        return None


def drive_lifecycle(adapter: Any, benchmark: Any, ledger: Ledger) -> Outcome:
    outcome = Outcome()
    create_connection = instrument(adapter, ledger, outcome)

    adapter._reset_run_scoped_state()
    adapter.benchmark = benchmark
    adapter._drift_validation_result = None
    connection = create_connection()
    adapter.connection = connection
    adapter._applied_tuning_ledger = AppliedTuningLedger()
    adapter._applied_layout_operations = []
    tuning = adapter.get_effective_tuning_configuration()
    data_dir = benchmark.output_dir

    def stage(name: str, call: Callable[[], Any]) -> Any:
        return run_stage(ledger, outcome, name, call)

    stage("create_schema", lambda: adapter.create_schema(benchmark, connection))
    stage("apply_unified_tuning", lambda: adapter.apply_unified_tuning(tuning, connection))
    outcome.metadata_saved = stage("save_tuning_metadata", lambda: adapter.save_tuning_metadata(connection))
    stage("load_data", lambda: adapter.load_data(benchmark, connection, data_dir))
    stage("second_connection", create_connection)
    stage("new_stream_connection", lambda: adapter.new_stream_connection(connection))
    for helper in MIDRUN_HELPERS:
        if callable(getattr(adapter, helper, None)):
            adapter.connection = None
            stage(helper, getattr(adapter, helper))
    adapter.connection = None
    stage("execute_query", lambda: adapter.execute_query(None, "SELECT 1", "probe"))
    adapter.connection = connection
    stage("close_connection", lambda: adapter.close_connection(connection))
    return outcome


def describe(events: list[Event]) -> str:
    return "\n".join(str(event) for event in events)


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_no_destructive_ops_after_first_connection_decision(case, world, ledger):
    adapter = make_adapter(case, world, ledger, force_recreate=True)

    outcome = drive_lifecycle(adapter, make_benchmark(world), ledger)

    assert not ledger.violations(), describe(ledger.violations())
    assert "save_tuning_metadata" not in outcome.stage_errors, outcome.stage_errors
    assert not outcome.connections.get("save_tuning_metadata"), "tuning metadata opened its own connection"
    for site in case.spec.connection_sites:
        assert outcome.connections.get(site, 0) >= 1, f"{site} did not open a mid-run connection"


@pytest.mark.parametrize("case", CASE_PARAMS)
def test_force_recreate_still_acts_at_the_first_connection(case, world, ledger):
    adapter = make_adapter(case, world, ledger, force_recreate=True)

    outcome = drive_lifecycle(adapter, make_benchmark(world), ledger)

    if not outcome.decision_calls or getattr(adapter, "skip_database_management", False):
        assert not case.spec.no_positive_control, "stale exemption: adapter makes no first-connection decision"
        return
    acted = ledger.in_phase("decision", destructive=True)
    if case.spec.no_positive_control:
        assert not acted, f"exemption is stale, the adapter now acts: {describe(acted)}"
    else:
        assert acted, "force_recreate did not remove anything at the first connection"


def test_every_registered_adapter_has_a_case():
    covered = {case.key for case in CASES}

    assert covered == set(PlatformRegistry.get_available_platforms())
    assert covered >= REQUIRED_ADAPTERS


@pytest.mark.parametrize("name", ["sqlite", "postgresql", "clickhouse-server", "duckdb"])
def test_harness_flags_a_repeated_decision(name, world, ledger):
    case = next(case for case in CASES if case.key == name and not case.variant)
    adapter = make_adapter(case, world, ledger, force_recreate=True)
    outcome = Outcome()
    create_connection = instrument(adapter, ledger, outcome)
    create_connection()
    assert not ledger.violations()

    adapter._existing_db_decided = False
    ledger.stage = "repeated_decision"
    create_connection()

    assert ledger.violations()
