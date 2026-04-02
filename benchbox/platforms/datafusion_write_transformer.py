"""DataFusion write SQL transformer for bulk_load COPY→EXTERNAL TABLE rewriting.

Rewrites COPY-based bulk load SQL into DataFusion-compatible
CREATE EXTERNAL TABLE + INSERT INTO patterns. Called by the DataFusion
adapter's preprocess_operation_sql() to keep platform-specific logic
in the adapter layer rather than the core benchmark.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import re


def transform_write_sql(
    operation_id: str,
    category: str,
    sql: str,
    file_dependencies: list[str] | None = None,
) -> str:
    """Transform write SQL for DataFusion compatibility.

    Rewrites COPY-based bulk loads to CREATE EXTERNAL TABLE pattern.
    Returns original SQL unchanged for non-bulk_load operations.

    Args:
        operation_id: Operation identifier (e.g. 'bulk_load_csv_small_uncompressed')
        category: Operation category (e.g. 'bulk_load')
        sql: Original write SQL
        file_dependencies: List of file names the operation depends on

    Returns:
        Transformed SQL string compatible with DataFusion
    """
    if category.lower() != "bulk_load":
        return sql

    return _rewrite_bulk_load_sql(operation_id, sql, file_dependencies or [])


def _rewrite_multi_file(ext_base: str, files: list[str]) -> str:
    """Build UNION ALL across explicit file list."""
    stmts: list[str] = []
    selects: list[str] = []
    for idx, file_name in enumerate(files):
        ext_name = f"{ext_base}_{idx}"
        file_path = f"{{file_path}}/{file_name}"
        stmts.append(
            f"DROP TABLE IF EXISTS {ext_name};\n"
            f"CREATE EXTERNAL TABLE {ext_name} STORED AS CSV LOCATION '{file_path}' "
            "OPTIONS ('has_header' 'true')"
        )
        selects.append(f"SELECT * FROM {ext_name}")
    stmts.append("INSERT INTO bulk_load_ops_target\n" + "\nUNION ALL\n".join(selects))
    return ";\n".join(stmts)


def _rewrite_copy_based(ext_base: str, remaining_sql: str) -> str | None:
    """Rewrite COPY-based bulk loads to CREATE EXTERNAL TABLE pattern."""
    copy_match = re.search(
        r"COPY\s+bulk_load_ops_target\s+FROM\s+'(?P<path>[^']+)'\s*(?P<opts>\([^)]*\)|WITH\s*\([^)]*\))?",
        remaining_sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not copy_match:
        return None

    source_path = copy_match.group("path")
    opts = (copy_match.group("opts") or "").upper()
    fmt = "PARQUET" if "FORMAT PARQUET" in opts or source_path.endswith(".parquet") else "CSV"

    option_parts: list[str] = []
    if fmt == "CSV":
        _collect_csv_options(option_parts, source_path, opts)

    options_sql = f" OPTIONS ({', '.join(option_parts)})" if option_parts else ""
    return (
        f"DROP TABLE IF EXISTS {ext_base};\n"
        f"CREATE EXTERNAL TABLE {ext_base} STORED AS {fmt} LOCATION '{source_path}'{options_sql};\n"
        f"INSERT INTO bulk_load_ops_target SELECT * FROM {ext_base}"
    )


_COMPRESSION_MAP = {".gz": "gzip", ".zst": "zstd", ".bz2": "bzip2"}
_OPT_PATTERNS = [
    ("DELIMITER '|'", "'delimiter' '|'"),
    ("QUOTE '\"'", "'quote' '\"'"),
    ("ESCAPE '\"'", "'escape' '\"'"),
    ("DATEFORMAT", "'date_format' '%Y/%m/%d'"),
]


def _collect_csv_options(option_parts: list[str], source_path: str, opts: str) -> None:
    """Collect CSV-specific external table options."""
    option_parts.append("'has_header' 'true'")
    for ext, comp in _COMPRESSION_MAP.items():
        if source_path.endswith(ext):
            option_parts.append(f"'compression' '{comp}'")
            break
    for pattern, option in _OPT_PATTERNS:
        if pattern in opts:
            option_parts.append(option)
    if "NULL 'NULL'" in opts or "NULLSTR 'NULL'" in opts:
        option_parts.append("'null_value' 'NULL'")


def _rewrite_csv_auto(ext_base: str, remaining_sql: str) -> str | None:
    """Rewrite read_csv_auto-based operations to external table pattern."""
    csv_auto_match = re.search(r"FROM\s+read_csv_auto\('(?P<path>[^']+)'\)", remaining_sql, flags=re.IGNORECASE)
    if not csv_auto_match:
        return None

    source_path = csv_auto_match.group("path")
    rewritten_select = re.sub(
        r"FROM\s+read_csv_auto\('[^']+'\)",
        f"FROM {ext_base}",
        remaining_sql,
        flags=re.IGNORECASE,
    )
    stmts_list = [stmt.strip() for stmt in rewritten_select.split(";") if stmt.strip()]
    stmts_list = [stmt for stmt in stmts_list if not stmt.upper().startswith("TRUNCATE TABLE")]
    return (
        f"DROP TABLE IF EXISTS {ext_base};\n"
        f"CREATE EXTERNAL TABLE {ext_base} STORED AS CSV LOCATION '{source_path}' "
        f"OPTIONS ('has_header' 'true');\n" + ";\n".join(stmts_list)
    )


def _rewrite_bulk_load_sql(operation_id: str, sql: str, files: list[str]) -> str:
    """Rewrite bulk-load SQL to external-table based ingest."""
    ext_base = f"bb_df_ext_{operation_id}".replace("-", "_")

    # Strip TRUNCATE statements (DataFusion doesn't support TRUNCATE)
    statements = [stmt.strip() for stmt in sql.split(";") if stmt.strip()]
    non_truncate = [stmt for stmt in statements if not stmt.upper().startswith("TRUNCATE")]

    if operation_id == "bulk_load_parallel_multi_file" and files:
        return _rewrite_multi_file(ext_base, files)

    remaining_sql = ";\n".join(non_truncate) if non_truncate else sql

    return _rewrite_copy_based(ext_base, remaining_sql) or _rewrite_csv_auto(ext_base, remaining_sql) or remaining_sql
