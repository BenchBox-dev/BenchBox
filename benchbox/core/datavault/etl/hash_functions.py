# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import hashlib
from typing import Any, Literal

HashAlgorithm = Literal["md5", "sha256"]

_SUPPORTED_SQL_ALGORITHMS: frozenset[str] = frozenset({"md5", "sha256"})


def _require_sql_algorithm(algorithm: str) -> None:
    if algorithm not in _SUPPORTED_SQL_ALGORITHMS:
        raise ValueError(
            f"SQL hash generation only supports {tuple(sorted(_SUPPORTED_SQL_ALGORITHMS))}, got: {algorithm}"
        )


def generate_hash_key(*business_keys: Any, algorithm: HashAlgorithm = "md5") -> str:
    key_string = "|".join(str(bk) if bk is not None else "" for bk in business_keys)

    if algorithm == "md5":
        return hashlib.md5(key_string.encode("utf-8")).hexdigest()
    if algorithm == "sha256":
        return hashlib.sha256(key_string.encode("utf-8")).hexdigest()
    raise ValueError(f"Unsupported hash algorithm: {algorithm}")


def generate_hashdiff(*attribute_values: Any, algorithm: HashAlgorithm = "md5") -> str:
    return generate_hash_key(*attribute_values, algorithm=algorithm)


def generate_hash_key_sql(
    *column_names: str,
    algorithm: HashAlgorithm = "md5",
    table_alias: str = "",
) -> str:
    _require_sql_algorithm(algorithm)

    prefix = f"{table_alias}." if table_alias else ""

    if len(column_names) == 1:
        return f"{algorithm}(CAST({prefix}{column_names[0]} AS VARCHAR))"

    cast_expressions = [f"CAST({prefix}{col} AS VARCHAR)" for col in column_names]
    concat_expr = " || '|' || ".join(cast_expressions)
    return f"{algorithm}({concat_expr})"


def generate_hashdiff_sql(
    *column_names: str,
    algorithm: HashAlgorithm = "md5",
    table_alias: str = "",
) -> str:
    _require_sql_algorithm(algorithm)

    prefix = f"{table_alias}." if table_alias else ""

    cast_expressions = [f"COALESCE(CAST({prefix}{col} AS VARCHAR), '')" for col in column_names]
    concat_expr = " || '|' || ".join(cast_expressions)
    return f"{algorithm}({concat_expr})"
