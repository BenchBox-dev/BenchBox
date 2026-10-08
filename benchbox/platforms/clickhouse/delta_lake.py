# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

_S3_TABLE_FUNCTIONS = frozenset({"deltaLake", "deltaLakeS3"})

DeltaLocationKind = Literal["s3", "azure", "gcs", "local", "unknown"]

DELTA_BASE_FUNCTION = "deltaLake"

DELTA_LOCAL_FUNCTION = "deltaLakeLocal"

_S3_VIRTUAL_HOSTED_RE = re.compile(r"\.s3[.-][a-z0-9-]+\.amazonaws\.com$")

DELTA_TABLE_FUNCTION_NAMES = (DELTA_BASE_FUNCTION, "deltaLakeS3", "deltaLakeLocal", "deltaLakeAzure")

DELTA_ENGINE_NAME = "DeltaLake"

__all__ = [
    "DELTA_BASE_FUNCTION",
    "DELTA_ENGINE_NAME",
    "DELTA_LOCAL_FUNCTION",
    "DELTA_TABLE_FUNCTION_NAMES",
    "DeltaLocationKind",
    "DeltaReader",
    "classify_delta_location",
    "delta_engine_probe_sql",
    "delta_function_probe_sql",
    "delta_lake_azure_table_function",
    "delta_lake_count_sql",
    "delta_lake_engine_ddl",
    "delta_lake_local_table_function",
    "delta_lake_select_sql",
    "delta_lake_table_function",
    "has_local_delta_registration",
    "has_native_delta_registration",
    "quote_identifier",
    "quote_literal",
    "resolve_delta_reader",
]


def _require_credential(value: str | None, label: str) -> None:
    if value is not None and not value.strip():
        raise ValueError(f"Delta Lake {label} must be non-blank when provided.")


_EMPTY_LITERAL_ERROR = "Cannot quote an empty string literal."
_NUL_LITERAL_ERROR = "Cannot quote a string literal containing NUL."
_EMPTY_IDENTIFIER_ERROR = "Cannot quote an empty identifier."
_NUL_IDENTIFIER_ERROR = "Cannot quote an identifier containing NUL."


def _quote_wrapped(value: str, quote: str, empty_error: str, nul_error: str) -> str:
    if not value:
        raise ValueError(empty_error)
    if "\x00" in value:
        raise ValueError(nul_error)
    return quote + value.replace("\\", "\\\\").replace(quote, "\\" + quote) + quote


def quote_literal(value: str) -> str:
    return _quote_wrapped(value, "'", _EMPTY_LITERAL_ERROR, _NUL_LITERAL_ERROR)


def quote_identifier(name: str) -> str:
    return _quote_wrapped(name, "`", _EMPTY_IDENTIFIER_ERROR, _NUL_IDENTIFIER_ERROR)


def delta_lake_table_function(
    url: str,
    *,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    function: str = "deltaLake",
) -> str:
    if not url or not url.strip():
        raise ValueError("Delta Lake table function requires a non-empty URL.")
    if function not in _S3_TABLE_FUNCTIONS:
        raise ValueError(f"Unknown Delta Lake table function {function!r}: expected 'deltaLake' or 'deltaLakeS3'.")
    if (access_key_id is None) != (secret_access_key is None):
        raise ValueError("access_key_id and secret_access_key must be provided together or not at all.")
    _require_credential(access_key_id, "access_key_id")
    _require_credential(secret_access_key, "secret_access_key")
    expression = f"{function}({quote_literal(url)}"
    if access_key_id is not None and secret_access_key is not None:
        expression += f", {quote_literal(access_key_id)}, {quote_literal(secret_access_key)}"
    return expression + ")"


def delta_lake_local_table_function(path: str) -> str:
    if not path or not path.strip():
        raise ValueError("Delta Lake local table function requires a non-empty path.")
    return f"deltaLakeLocal({quote_literal(path)})"


def delta_lake_engine_ddl(
    table: str,
    url: str,
    *,
    database: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
) -> str:
    if not url or not url.strip():
        raise ValueError("DeltaLake engine DDL requires a non-empty URL.")
    if not table or not table.strip():
        raise ValueError("DeltaLake engine DDL requires a non-empty table name.")
    if (access_key_id is None) != (secret_access_key is None):
        raise ValueError("access_key_id and secret_access_key must be provided together or not at all.")
    name = quote_identifier(table)
    if database is not None:
        if not database.strip():
            raise ValueError("DeltaLake engine DDL requires a non-empty database name.")
        name = f"{quote_identifier(database)}.{name}"
    statement = f"CREATE TABLE {name} ENGINE = DeltaLake({quote_literal(url)}"
    if access_key_id is not None and secret_access_key is not None:
        statement += f", {quote_literal(access_key_id)}, {quote_literal(secret_access_key)}"
    return statement + ")"


def delta_lake_select_sql(
    source: str,
    *,
    columns: str | list[str] | tuple[str, ...] = "*",
    limit: int | None = None,
) -> str:
    if not source or not source.strip():
        raise ValueError("Delta Lake SELECT requires a non-empty source expression.")
    if isinstance(columns, tuple):
        columns = list(columns)
    if isinstance(columns, list):
        if not columns or any(not column or not column.strip() for column in columns):
            raise ValueError("Delta Lake SELECT requires at least one non-blank column.")
        column_sql = ", ".join(quote_identifier(column) for column in columns)
    else:
        if not columns or not columns.strip():
            raise ValueError("Delta Lake SELECT requires at least one column.")
        column_sql = columns
    if isinstance(limit, bool) or (limit is not None and (not isinstance(limit, int) or limit < 0)):
        raise ValueError(f"Delta Lake SELECT limit must be a non-negative int, got {limit!r}.")
    statement = f"SELECT {column_sql} FROM {source}"
    if limit is not None:
        statement += f" LIMIT {limit}"
    return statement


def delta_lake_count_sql(source: str) -> str:
    if not source or not source.strip():
        raise ValueError("Delta Lake COUNT requires a non-empty source expression.")
    return f"SELECT count() FROM {source}"


def delta_lake_azure_table_function(
    account_url: str,
    container: str,
    blobpath: str,
    *,
    account_name: str | None = None,
    account_key: str | None = None,
) -> str:
    for label, part in (("account URL", account_url), ("container", container), ("blob path", blobpath)):
        if not part or not part.strip():
            raise ValueError(f"Delta Lake Azure table function requires a non-empty {label}.")
    if (account_name is None) != (account_key is None):
        raise ValueError("account_name and account_key must be provided together or not at all.")
    _require_credential(account_name, "account_name")
    _require_credential(account_key, "account_key")
    expression = f"deltaLakeAzure({quote_literal(account_url)}, {quote_literal(container)}, {quote_literal(blobpath)}"
    if account_name is not None and account_key is not None:
        expression += f", {quote_literal(account_name)}, {quote_literal(account_key)}"
    return expression + ")"


def delta_function_probe_sql() -> str:
    names = ", ".join(quote_literal(name) for name in DELTA_TABLE_FUNCTION_NAMES)
    return f"SELECT name FROM system.table_functions WHERE name IN ({names})"


def delta_engine_probe_sql() -> str:
    return f"SELECT name FROM system.table_engines WHERE name = {quote_literal(DELTA_ENGINE_NAME)}"


def has_native_delta_registration(function_names: list[str], engine_names: list[str]) -> bool:
    return DELTA_BASE_FUNCTION in function_names and DELTA_ENGINE_NAME in engine_names


def has_local_delta_registration(function_names: list[str]) -> bool:
    return DELTA_LOCAL_FUNCTION in function_names


def _is_https_s3_location(lowered: str) -> bool:
    if not lowered.startswith(("https://", "http://")):
        return False
    try:
        host = urlsplit(lowered).hostname or ""
    except ValueError:
        return False
    if host == "s3.amazonaws.com" or (host.startswith("s3.") and host.endswith(".amazonaws.com")):
        return True
    if ".s3.amazonaws.com" in host or _S3_VIRTUAL_HOSTED_RE.search(host):
        return True
    return False


def classify_delta_location(location: str) -> DeltaLocationKind:
    if not location or not location.strip():
        raise ValueError("Cannot classify an empty Delta location.")
    lowered = location.lower()
    if lowered.startswith("s3://") or _is_https_s3_location(lowered):
        return "s3"
    if lowered.startswith("gs://") or lowered.startswith("https://storage.googleapis.com/"):
        return "gcs"
    if (
        lowered.startswith(("abfs://", "abfss://", "wasb://", "wasbs://"))
        or ".blob.core.windows.net" in lowered
        or ".dfs.core.windows.net" in lowered
        or "accountname=" in lowered
        or "defaultendpointsprotocol=" in lowered
    ):
        return "azure"
    if lowered.startswith(("/", "./", "../", "file://")) or (
        len(location) > 3 and location[0].isalpha() and location[1] == ":" and location[2] in "\\/"
    ):
        return "local"
    return "unknown"


@dataclass(frozen=True)
class DeltaReader:
    kind: str
    location_kind: str
    source_sql: str
    reason: str


def resolve_delta_reader(location: str, *, native_available: bool, local_native_available: bool = False) -> DeltaReader:
    kind = classify_delta_location(location)
    if kind == "unknown":
        raise ValueError(f"Unrecognized Delta location {location!r}: expected an S3/Azure/GCS URL or a local path.")
    if native_available and kind == "s3":
        return DeltaReader("native", kind, delta_lake_table_function(location), "server registers deltaLake")
    if native_available and local_native_available and kind == "local":
        return DeltaReader("native", kind, delta_lake_local_table_function(location), "server registers deltaLakeLocal")
    if kind == "local":
        return DeltaReader(
            "parquet-snapshot", kind, "", "server does not register deltaLakeLocal; export to Parquet first"
        )
    raise ValueError(
        f"No executable Delta read path for {kind} location {location!r}: the server does not register native "
        "Delta reads and remote Parquet snapshot export is not provided."
    )
