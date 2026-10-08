from __future__ import annotations

from typing import Any


def iter_schema_columns(table_schema: Any) -> list[Any]:

    if isinstance(table_schema, dict):
        columns = table_schema.get("columns", [])
        if isinstance(columns, dict):
            normalized = []
            for name, spec in columns.items():
                column = dict(spec) if isinstance(spec, dict) else {"type": spec}
                column.setdefault("name", name)
                normalized.append(column)
            return normalized
        if isinstance(columns, (list, tuple)):
            return list(columns)
        return []

    columns = getattr(table_schema, "columns", None)
    if columns is None:
        return []
    return list(columns)


_CONSTRAINT_KEYWORDS = frozenset(
    {
        "NOT",
        "NULL",
        "DEFAULT",
        "PRIMARY",
        "KEY",
        "UNIQUE",
        "CHECK",
        "REFERENCES",
        "FOREIGN",
        "CONSTRAINT",
        "COLLATE",
        "GENERATED",
        "AUTO_INCREMENT",
        "AUTOINCREMENT",
        "IDENTITY",
        "COMMENT",
    }
)


_TYPE_CONTINUATIONS = {
    "DOUBLE": {"PRECISION"},
    "CHARACTER": {"VARYING"},
    "CHAR": {"VARYING"},
    "BIT": {"VARYING"},
    "TIMESTAMP": {"WITH", "WITHOUT"},
    "TIME": {"WITH", "WITHOUT", "ZONE"},
    "WITH": {"TIME"},
    "WITHOUT": {"TIME"},
}


_QUOTE_PAIRS = {'"': '"', "`": "`", "[": "]"}


def _read_quoted_identifier(text: str, opener: str, closer: str) -> tuple[str, int, bool]:

    i = 1
    n = len(text)
    chars: list[str] = []
    while i < n:
        ch = text[i]
        if ch == closer:
            if i + 1 < n and text[i + 1] == closer:
                chars.append(closer)
                i += 2
                continue
            return "".join(chars), i + 1, True
        chars.append(ch)
        i += 1
    return "".join(chars), n, False


def _split_ddl_column(column: str) -> tuple[str | None, str | None]:

    text = column.strip()
    if not text:
        return None, None

    pos = 0
    n = len(text)

    if text[0] in _QUOTE_PAIRS:
        closer = _QUOTE_PAIRS[text[0]]

        name, pos, terminated = _read_quoted_identifier(text, text[0], closer)
        if not terminated:
            return name, None
    else:
        start = pos
        while pos < n and not text[pos].isspace():
            pos += 1
        name = text[start:pos]

    while pos < n and text[pos].isspace():
        pos += 1
    if pos >= n:
        return name, None

    sql_type = _consume_type(text, pos, n)
    return name, sql_type or None


def _consume_type(text: str, pos: int, n: int) -> str:

    type_parts: list[str] = []
    while pos < n:
        while pos < n and text[pos].isspace():
            pos += 1
        if pos >= n:
            break

        start = pos
        while pos < n and not text[pos].isspace() and text[pos] != "(":
            pos += 1
        word = text[start:pos]

        if word:
            upper = word.upper()
            if not type_parts:
                type_parts.append(word)
            elif upper in _CONSTRAINT_KEYWORDS:
                break
            elif _is_type_continuation(type_parts, upper):
                type_parts.append(word)
            else:
                break

        if pos < n and text[pos] == "(":
            paren = _consume_parens(text, pos, n)
            if type_parts:
                type_parts[-1] = type_parts[-1] + paren
            pos += len(paren)
        elif not word:
            break

    return " ".join(type_parts)


def _is_type_continuation(type_parts: list[str], upper: str) -> bool:

    prev = type_parts[-1].upper()

    paren_idx = prev.find("(")
    if paren_idx != -1:
        prev = prev[:paren_idx]
    return upper in _TYPE_CONTINUATIONS.get(prev, set())


def _consume_parens(text: str, pos: int, n: int) -> str:

    depth = 0
    start = pos
    while pos < n:
        ch = text[pos]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start : pos + 1]
        pos += 1

    return text[start:n]


def column_name(column: Any) -> str | None:

    if isinstance(column, dict):
        name = column.get("name")
    elif isinstance(column, str):
        name, _ = _split_ddl_column(column)
    else:
        name = getattr(column, "name", None)
    return str(name) if name else None


def column_sql_type(column: Any, default: str = "VARCHAR") -> str:

    if isinstance(column, str):
        _, sql_type = _split_ddl_column(column)
        return sql_type if sql_type else default
    candidates: list[Any] = []
    if isinstance(column, dict):
        candidates.append(column.get("type") or column.get("data_type"))
    else:
        for attr_name in ("get_sql_type", "sql_type"):
            attr = getattr(column, attr_name, None)
            if callable(attr):
                candidates.append(attr())
            elif attr is not None:
                candidates.append(attr)
        candidates.append(getattr(column, "data_type", None))

    for value in candidates:
        enum_value = getattr(value, "value", None)
        if isinstance(enum_value, str):
            return enum_value
        if isinstance(value, str):
            return value
    return default


def extract_schema_columns(schema: Any) -> dict[str, list[dict[str, str]]]:

    if not isinstance(schema, dict):
        return {}

    result: dict[str, list[dict[str, str]]] = {}
    for table_name, table_schema in schema.items():
        columns = []
        for column in iter_schema_columns(table_schema):
            name = column_name(column)
            if name:
                columns.append({"name": name, "type": column_sql_type(column)})
        if columns:
            result[str(table_name).lower()] = columns
    return result


def get_benchmark_schema_columns(benchmark: Any) -> dict[str, list[dict[str, str]]]:

    if not hasattr(benchmark, "get_schema"):
        return {}
    try:
        return extract_schema_columns(benchmark.get_schema())
    except Exception:
        return {}
