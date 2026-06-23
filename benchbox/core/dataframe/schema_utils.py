"""Schema normalization helpers for DataFrame loading paths."""

from __future__ import annotations

from typing import Any


def iter_schema_columns(table_schema: Any) -> list[Any]:
    """Return a table schema's columns across BenchBox schema shapes."""
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


# Column constraint keywords that terminate the SQL type in a DDL column
# definition. The type ends at the first of these tokens (case-insensitive).
# ``WITH``/``WITHOUT``/``PRECISION``/``VARYING``/``ZONE``/``TIME`` are
# intentionally absent: they are continuations of multi-word types
# (``TIMESTAMP WITH TIME ZONE``, ``DOUBLE PRECISION``, ``CHARACTER VARYING``),
# handled by the _TYPE_CONTINUATIONS table in _consume_type below.
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

# Tokens that may legitimately follow a base type word as part of a multi-word
# SQL type, keyed by the (uppercased) preceding token. Used to keep consuming
# type words past a space without crossing into a constraint.
_TYPE_CONTINUATIONS = {
    "DOUBLE": {"PRECISION"},
    "CHARACTER": {"VARYING"},
    "CHAR": {"VARYING"},
    "BIT": {"VARYING"},
    "TIMESTAMP": {"WITH", "WITHOUT"},
    "TIME": {"WITH", "WITHOUT", "ZONE"},
    # "<TIMESTAMP|TIME> WITH[OUT]" -> "TIME ZONE"
    "WITH": {"TIME"},
    "WITHOUT": {"TIME"},
}

# Pairs of (opening, closing) quote characters for quoted identifiers.
_QUOTE_PAIRS = {'"': '"', "`": "`", "[": "]"}


def _split_ddl_column(column: str) -> tuple[str | None, str | None]:
    """Split a DDL column definition into ``(name, type)``.

    Parses ``"name TYPE [constraints...]"`` with awareness of:

    - quoted/bracketed identifiers that may contain spaces
      (``"odd name" INTEGER``, ``[odd name] INT``, ```odd name` INT``),
    - parenthesized precision/scale with internal commas/spaces
      (``DECIMAL(10, 2)``, ``VARCHAR(255)``),
    - multi-word types (``DOUBLE PRECISION``, ``TIMESTAMP WITH TIME ZONE``,
      ``TIMESTAMP WITHOUT TIME ZONE``, ``CHARACTER VARYING``),
    - trailing column constraints (``NOT NULL``, ``DEFAULT ...``,
      ``PRIMARY KEY``, ``UNIQUE``, ``CHECK(...)``, ``REFERENCES ...``), which
      are stripped from the returned type.

    Returns ``(None, None)`` for an empty/whitespace-only string. Either field
    may be ``None`` if absent.
    """
    text = column.strip()
    if not text:
        return None, None

    pos = 0
    n = len(text)

    # --- extract the column name (respecting quoted identifiers) ---
    if text[0] in _QUOTE_PAIRS:
        closer = _QUOTE_PAIRS[text[0]]
        end = text.find(closer, 1)
        if end == -1:
            # Unterminated quote: treat the whole remainder as the name.
            return text, None
        name = text[: end + 1]
        pos = end + 1
    else:
        start = pos
        while pos < n and not text[pos].isspace():
            pos += 1
        name = text[start:pos]

    # Skip whitespace between name and type.
    while pos < n and text[pos].isspace():
        pos += 1
    if pos >= n:
        return name, None

    sql_type = _consume_type(text, pos, n)
    return name, sql_type or None


def _consume_type(text: str, pos: int, n: int) -> str:
    """Consume the SQL type starting at ``pos``, stopping before constraints."""
    type_parts: list[str] = []
    while pos < n:
        # Skip leading whitespace before the next token.
        while pos < n and text[pos].isspace():
            pos += 1
        if pos >= n:
            break

        # Read one type word (up to whitespace or an opening paren).
        start = pos
        while pos < n and not text[pos].isspace() and text[pos] != "(":
            pos += 1
        word = text[start:pos]

        if word:
            upper = word.upper()
            if not type_parts:
                # The first word is always the base type, even if it collides
                # with a constraint keyword (defensive; base types do not).
                type_parts.append(word)
            elif upper in _CONSTRAINT_KEYWORDS:
                break
            elif _is_type_continuation(type_parts, upper):
                type_parts.append(word)
            else:
                break

        # Capture a parenthesized precision/scale immediately following the word
        # (or following a base type with no space, e.g. ``DECIMAL(10, 2)``).
        if pos < n and text[pos] == "(":
            paren = _consume_parens(text, pos, n)
            if type_parts:
                type_parts[-1] = type_parts[-1] + paren
            pos += len(paren)
        elif not word:
            break

    return " ".join(type_parts)


def _is_type_continuation(type_parts: list[str], upper: str) -> bool:
    """Return True if ``upper`` continues the multi-word type so far."""
    prev = type_parts[-1].upper()
    # Strip any trailing parenthesized part from the previous token for lookup.
    paren_idx = prev.find("(")
    if paren_idx != -1:
        prev = prev[:paren_idx]
    return upper in _TYPE_CONTINUATIONS.get(prev, set())


def _consume_parens(text: str, pos: int, n: int) -> str:
    """Return the balanced parenthesized substring starting at ``text[pos]``."""
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
    # Unbalanced: return whatever was opened.
    return text[start:n]


def column_name(column: Any) -> str | None:
    """Return a schema column's name, if present.

    Handles dict columns, object columns, and DDL-string columns of the form
    ``"name TYPE [constraints...]"`` (e.g. ``"id INTEGER PRIMARY KEY"``), used by
    benchmarks like joinorder_synthetic whose schema lists raw column definitions.
    The DDL name respects quoted/bracketed identifiers that contain spaces.
    """
    if isinstance(column, dict):
        name = column.get("name")
    elif isinstance(column, str):
        name, _ = _split_ddl_column(column)
    else:
        name = getattr(column, "name", None)
    return str(name) if name else None


def column_sql_type(column: Any, default: str = "VARCHAR") -> str:
    """Return a schema column's SQL type across dict, object, and DDL-string schemas.

    For DDL-string columns the full type is preserved, including parenthesized
    precision/scale (``DECIMAL(10, 2)``, ``VARCHAR(255)``) and multi-word types
    (``DOUBLE PRECISION``, ``TIMESTAMP WITH TIME ZONE``); trailing column
    constraints (``NOT NULL``, ``DEFAULT``, ``PRIMARY KEY``, ...) are stripped.
    """
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
    """Normalize a benchmark schema to table -> column definitions."""
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
    """Extract normalized schema columns from a benchmark instance."""
    if not hasattr(benchmark, "get_schema"):
        return {}
    try:
        return extract_schema_columns(benchmark.get_schema())
    except Exception:
        return {}
