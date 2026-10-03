# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_IDENTIFIER_LENGTH = 128
MAX_QUERY_ID_LENGTH = 64
MAX_DATABASE_NAME_LENGTH = 64
MAX_SCHEMA_NAME_LENGTH = 64
MAX_TABLE_NAME_LENGTH = 128
MAX_COLUMN_NAME_LENGTH = 128
MAX_PATH_LENGTH = 4096
MAX_QUERY_LENGTH = 1_000_000
MAX_QUERIES_PER_RUN = 100

MAX_JOIN_COUNT = 50
MAX_SUBQUERY_DEPTH = 10
MAX_UNION_COUNT = 20
MAX_PREDICATE_COUNT = 100

VALID_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
VALID_QUERY_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_.\-]+$")
VALID_BENCHMARK_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")
VALID_PLATFORM_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")

SQL_RESERVED_KEYWORDS = frozenset(
    {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "CREATE",
        "ALTER",
        "TRUNCATE",
        "GRANT",
        "REVOKE",
        "UNION",
        "EXEC",
        "EXECUTE",
        "XP_",
        "SP_",
        "--",
        "/*",
        "*/",
        ";",
    }
)

TPCH_VALID_QUERY_IDS = frozenset({str(i) for i in range(1, 23)})

TPCDS_VALID_QUERY_IDS = frozenset(
    {str(i) for i in range(1, 100)} | {f"{i}a" for i in [14, 23, 24, 39]} | {f"{i}b" for i in [14, 23, 24, 39]}
)

SSB_VALID_QUERY_IDS = frozenset({f"{i}.{j}" for i in range(1, 5) for j in range(1, 4)})


class ValidationError(Exception):
    pass


class SQLInjectionError(ValidationError):
    pass


class QueryComplexityError(ValidationError):
    pass


class InputLengthError(ValidationError):
    pass


class InvalidIdentifierError(ValidationError):
    pass


@dataclass
class QueryComplexityMetrics:
    join_count: int = 0
    subquery_depth: int = 0
    union_count: int = 0
    predicate_count: int = 0
    query_length: int = 0

    def exceeds_limits(self) -> bool:
        return (
            self.join_count > MAX_JOIN_COUNT
            or self.subquery_depth > MAX_SUBQUERY_DEPTH
            or self.union_count > MAX_UNION_COUNT
            or self.predicate_count > MAX_PREDICATE_COUNT
            or self.query_length > MAX_QUERY_LENGTH
        )

    def get_violation_details(self) -> list[str]:
        violations = []
        if self.join_count > MAX_JOIN_COUNT:
            violations.append(f"JOIN count ({self.join_count}) exceeds limit ({MAX_JOIN_COUNT})")
        if self.subquery_depth > MAX_SUBQUERY_DEPTH:
            violations.append(f"Subquery depth ({self.subquery_depth}) exceeds limit ({MAX_SUBQUERY_DEPTH})")
        if self.union_count > MAX_UNION_COUNT:
            violations.append(f"UNION count ({self.union_count}) exceeds limit ({MAX_UNION_COUNT})")
        if self.predicate_count > MAX_PREDICATE_COUNT:
            violations.append(f"Predicate count ({self.predicate_count}) exceeds limit ({MAX_PREDICATE_COUNT})")
        if self.query_length > MAX_QUERY_LENGTH:
            violations.append(f"Query length ({self.query_length}) exceeds limit ({MAX_QUERY_LENGTH})")
        return violations


def validate_sql_identifier(
    name: str | None,
    context: str = "identifier",
    max_length: int = MAX_IDENTIFIER_LENGTH,
    allow_dots: bool = False,
) -> str:
    if name is None or not isinstance(name, str):
        raise InvalidIdentifierError(f"Empty or non-string {context} is not allowed")

    name = name.strip()

    if not name:
        raise InvalidIdentifierError(f"Empty {context} is not allowed")

    if len(name) > max_length:
        raise InputLengthError(f"{context} exceeds maximum length of {max_length} characters")

    check_sql_injection_patterns(name, context)

    if allow_dots:
        parts = name.split(".")
        if len(parts) > 3:
            raise InvalidIdentifierError(f"{context} has too many dot-separated parts")
        for part in parts:
            if not VALID_IDENTIFIER_PATTERN.match(part):
                raise InvalidIdentifierError(
                    f"Invalid {context}: '{part}' - must start with letter/underscore and contain only "
                    "alphanumeric characters and underscores"
                )
    else:
        if not VALID_IDENTIFIER_PATTERN.match(name):
            raise InvalidIdentifierError(
                f"Invalid {context}: '{name}' - must start with letter/underscore and contain only "
                "alphanumeric characters and underscores"
            )

    return name


def validate_query_id(query_id: str | int, benchmark_type: str | None = None) -> str:
    if isinstance(query_id, int):
        query_id = str(query_id)

    if not isinstance(query_id, str):
        raise ValidationError(f"Query ID must be string or int, got {type(query_id).__name__}")

    query_id = query_id.strip()

    if not query_id:
        raise ValidationError("Empty query ID is not allowed")

    if len(query_id) > MAX_QUERY_ID_LENGTH:
        raise InputLengthError(f"Query ID exceeds maximum length of {MAX_QUERY_ID_LENGTH} characters")

    if not VALID_QUERY_ID_PATTERN.match(query_id):
        raise ValidationError(
            f"Invalid query ID: '{query_id}' - must contain only alphanumeric characters, underscores, hyphens, and dots"
        )

    if benchmark_type:
        benchmark_lower = benchmark_type.lower()
        if benchmark_lower in ("tpch", "tpc-h"):
            base_id = re.sub(r"[a-z]$", "", query_id.lower())
            if base_id not in TPCH_VALID_QUERY_IDS:
                raise ValidationError(f"Invalid TPC-H query ID: '{query_id}' (valid: 1-22)")
        elif benchmark_lower in ("tpcds", "tpc-ds"):
            if query_id.lower() not in TPCDS_VALID_QUERY_IDS:
                base_id = re.sub(r"[a-z]$", "", query_id.lower())
                if base_id not in TPCDS_VALID_QUERY_IDS:
                    raise ValidationError(f"Invalid TPC-DS query ID: '{query_id}' (valid: 1-99)")
        elif benchmark_lower == "ssb":
            if query_id not in SSB_VALID_QUERY_IDS:
                raise ValidationError(f"Invalid SSB query ID: '{query_id}' (valid: 1.1-4.3)")

    return query_id


def validate_query_ids_list(
    query_ids: list[str] | str,
    benchmark_type: str | None = None,
    max_queries: int = MAX_QUERIES_PER_RUN,
) -> list[str]:
    if isinstance(query_ids, str):
        query_ids = [q.strip() for q in query_ids.split(",") if q.strip()]

    if not query_ids:
        raise ValidationError("No query IDs provided")

    if len(query_ids) > max_queries:
        raise ValidationError(f"Too many queries: {len(query_ids)} (maximum: {max_queries})")

    validated = []
    seen = set()

    for qid in query_ids:
        validated_id = validate_query_id(qid, benchmark_type)
        if validated_id not in seen:
            validated.append(validated_id)
            seen.add(validated_id)

    return validated


def check_sql_injection_patterns(value: str, context: str = "input") -> None:
    if not value:
        return

    value_upper = value.upper()

    for keyword in SQL_RESERVED_KEYWORDS:
        if keyword in value_upper:
            raise SQLInjectionError(f"Potential SQL injection in {context}: contains '{keyword}'")

    injection_patterns = [
        r"'.*OR.*'",
        r"'.*AND.*'",
        r"\bOR\s+1\s*=\s*1",
        r"\bAND\s+1\s*=\s*1",
        r"'\s*;\s*",
        r"--\s*$",
        r"/\*.*\*/",
        r"\\x[0-9a-fA-F]{2}",
        r"0x[0-9a-fA-F]+",
        r"CHAR\s*\(",
        r"CONCAT\s*\(",
    ]

    for pattern in injection_patterns:
        if re.search(pattern, value, re.IGNORECASE):
            raise SQLInjectionError(f"Potential SQL injection pattern detected in {context}")


def escape_sql_string(value: str) -> str:
    if not isinstance(value, str):
        value = str(value)
    return value.replace("'", "''")


def quote_identifier(name: str, platform: str = "default") -> str:
    validate_sql_identifier(name, "identifier", allow_dots=False)

    platform_lower = platform.lower()

    if platform_lower in ("mysql", "bigquery"):
        return "`" + name.replace("`", "``") + "`"
    elif platform_lower in ("postgresql", "redshift", "snowflake", "trino", "presto", "duckdb"):
        return '"' + name.replace('"', '""') + '"'
    elif platform_lower in ("sqlserver", "synapse", "azure_synapse", "tsql"):
        return "[" + name.replace("]", "]]") + "]"
    else:
        return '"' + name.replace('"', '""') + '"'


def quote_qualified_identifier(name: str, platform: str = "default") -> str:
    parts = name.split(".")
    quoted_parts = [quote_identifier(part, platform) for part in parts]
    return ".".join(quoted_parts)


def analyze_query_complexity(query: str) -> QueryComplexityMetrics:
    query_upper = query.upper()

    metrics = QueryComplexityMetrics(query_length=len(query))

    join_pattern = r"\b(INNER|LEFT|RIGHT|FULL|CROSS|NATURAL)?\s*JOIN\b"
    metrics.join_count = len(re.findall(join_pattern, query_upper))

    union_pattern = r"\bUNION\s+(ALL\s+)?SELECT\b"
    metrics.union_count = len(re.findall(union_pattern, query_upper))

    select_count = query_upper.count("SELECT")
    metrics.subquery_depth = max(0, select_count - 1)

    predicate_patterns = [r"\bWHERE\b", r"\bAND\b", r"\bOR\b", r"\bHAVING\b"]
    for pattern in predicate_patterns:
        metrics.predicate_count += len(re.findall(pattern, query_upper))

    return metrics


def validate_query_complexity(query: str, enforce: bool = True) -> QueryComplexityMetrics:
    metrics = analyze_query_complexity(query)

    if enforce and metrics.exceeds_limits():
        violations = metrics.get_violation_details()
        raise QueryComplexityError(f"Query complexity exceeds limits: {'; '.join(violations)}")

    return metrics


def validate_benchmark_name(name: str) -> str:
    if not name or not isinstance(name, str):
        raise ValidationError("Benchmark name is required")

    name = name.strip().lower()

    if not VALID_BENCHMARK_NAME_PATTERN.match(name):
        raise ValidationError(
            f"Invalid benchmark name: '{name}' - must start with letter and contain only "
            "alphanumeric characters, underscores, and hyphens"
        )

    return name


def validate_platform_name(name: str) -> str:
    if not name or not isinstance(name, str):
        raise ValidationError("Platform name is required")

    name = name.strip().lower()

    if not VALID_PLATFORM_NAME_PATTERN.match(name):
        raise ValidationError(
            f"Invalid platform name: '{name}' - must start with letter and contain only "
            "alphanumeric characters, underscores, and hyphens"
        )

    return name


def validate_scale_factor(scale_factor: float | int | str) -> float:
    try:
        sf = float(scale_factor)
    except (ValueError, TypeError) as e:
        raise ValidationError(f"Invalid scale factor: {scale_factor}") from e

    if sf <= 0:
        raise ValidationError(f"Scale factor must be positive, got: {sf}")

    if sf > 100000:
        raise ValidationError(f"Scale factor too large: {sf} (maximum: 100000)")

    return sf


def validate_database_name(name: str) -> str:
    return validate_sql_identifier(name, "database name", MAX_DATABASE_NAME_LENGTH)


def validate_schema_name(name: str) -> str:
    return validate_sql_identifier(name, "schema name", MAX_SCHEMA_NAME_LENGTH)


def validate_table_name(name: str, allow_schema_prefix: bool = False) -> str:
    return validate_sql_identifier(name, "table name", MAX_TABLE_NAME_LENGTH, allow_dots=allow_schema_prefix)


def safe_format_table_reference(
    table_name: str,
    schema_name: str | None = None,
    platform: str = "default",
) -> str:
    validated_table = validate_table_name(table_name)
    quoted_table = quote_identifier(validated_table, platform)

    if schema_name:
        validated_schema = validate_schema_name(schema_name)
        quoted_schema = quote_identifier(validated_schema, platform)
        return f"{quoted_schema}.{quoted_table}"

    return quoted_table
