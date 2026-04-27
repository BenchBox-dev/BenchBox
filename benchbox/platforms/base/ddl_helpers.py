"""Shared DDL helper utilities used across multiple platform adapters.

These helpers consolidate DDL-text transformations that were previously
duplicated with slightly different regexes across six adapters.

Import discipline: adapter modules MUST import these names directly
(``from .base.ddl_helpers import strip_foreign_keys``) rather than via
attribute access. Tests patch the imported name in the adapter module
(``benchbox.platforms.questdb.strip_foreign_keys``), and attribute-access
calls would bypass that patch.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# FOREIGN KEY stripping
# ---------------------------------------------------------------------------

# Union of all FK clause patterns observed across six adapters:
#   - optional leading comma  ( ",?" — present when FK follows a column line; absent
#     when FK is the first item inside the column-defs paren)
#   - optional CONSTRAINT name (SingleStore, MySQL-family)
#   - FOREIGN KEY (...) REFERENCES table(...) or schema.table(...)
#   - optional backtick / double-quote identifier quoting
#   - zero or more ON DELETE/UPDATE referential actions, restricted to the SQL-standard
#     keyword set so trailing identifiers (e.g. another column definition right after a
#     CASCADE) are not eaten by a greedy \w+ run.
_REF_ACTION = r"(?:NO\s+ACTION|RESTRICT|CASCADE|SET\s+(?:NULL|DEFAULT))"
_FK_CLAUSE_RE = re.compile(
    r",?\s*"
    r"(?:CONSTRAINT\s+[`\"\w]+\s+)?"
    r"FOREIGN\s+KEY\s*\([^)]*\)"
    r"\s*REFERENCES\s+"
    r"[`\"\w]+(?:\.[`\"\w]+)?"  # table or schema.table, backtick/double-quote safe
    r"\s*\([^)]*\)"
    rf"(?:\s+ON\s+(?:DELETE|UPDATE)\s+{_REF_ACTION})*",  # zero or more standard ON actions
    re.IGNORECASE,
)
_INLINE_REFERENCES_RE = re.compile(
    r"\s+REFERENCES\s+"
    r"[`\"\w]+(?:\.[`\"\w]+)?"
    r"\s*(?:\([^)]*\))?"
    rf"(?:\s+ON\s+(?:DELETE|UPDATE)\s+{_REF_ACTION})*",
    re.IGNORECASE,
)

# After FK removal, a clause that was penultimate may leave a trailing comma
# immediately before the closing paren: ", ... last_col TYPE\n)".
_TRAILING_COMMA_RE = re.compile(r",(\s*\))")


def strip_foreign_keys(stmt: str) -> str:
    """Remove all FOREIGN KEY constraint clauses from a CREATE TABLE statement.

    Handles the union of FK clause variants observed across six platform adapters:
      - bare ``FOREIGN KEY (col) REFERENCES table(col)``
      - with ``CONSTRAINT name`` prefix
      - with backtick or double-quote identifier quoting
      - with schema-qualified references (``schema.table``)
      - with one or more ``ON DELETE / ON UPDATE`` referential actions
      - with or without a leading comma
      - inline column-level references (``col INT REFERENCES other(id)``)

    After removal, cleans up trailing commas left before the closing parenthesis.

    Non-CREATE-TABLE statements pass through unchanged. This helper strips FK
    constraints only; PRIMARY KEY handling is platform-specific and stays in
    each adapter.

    Limitation — string-literal false positive:
        The regexes are not SQL-string-aware. If a non-FK statement contains the
        token ``REFERENCES`` followed by an identifier-shaped word inside a
        string literal (e.g. ``DEFAULT 'see references for details'``), that
        substring will be matched and stripped. All current callers invoke this
        helper from CREATE TABLE pipelines and no benchmark schema in the suite
        uses such literals, so production exposure is zero, but a future caller
        passing arbitrary DDL/DML through this helper should pre-gate on
        ``\\bCREATE\\s+TABLE\\b``.

    Args:
        stmt: A single SQL statement string (no trailing semicolon required).

    Returns:
        Statement with FK clauses removed, or original statement if no FK found.
    """
    stmt_upper = stmt.upper()
    if "FOREIGN KEY" not in stmt_upper and "REFERENCES" not in stmt_upper:
        return stmt

    cleaned = _FK_CLAUSE_RE.sub("", stmt)
    cleaned = _INLINE_REFERENCES_RE.sub("", cleaned)
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", cleaned)
    return cleaned


# ---------------------------------------------------------------------------
# PRIMARY KEY stripping
# ---------------------------------------------------------------------------

# Matches table-level PRIMARY KEY (...) and inline column-level PRIMARY KEY.
# The [^)]*  inside \(...\) is intentionally left simple here — we use it only
# for the *keyword detection* pass; the actual paren extent is found by the
# balanced walker below.
_TABLE_PK_RE = re.compile(r",?\s*PRIMARY\s+KEY\s*\(", re.IGNORECASE)
_INLINE_PK_RE = re.compile(r"\s+PRIMARY\s+KEY\b", re.IGNORECASE)


def strip_primary_keys(stmt: str) -> str:
    """Remove PRIMARY KEY constraint clauses from a CREATE TABLE statement.

    Handles both table-level ``PRIMARY KEY (col_a, coalesce(col_b, 0))`` (with
    arbitrary nesting inside the argument list) and inline column-level
    ``col_name TYPE PRIMARY KEY``.  The table-level form is stripped with a
    character-level depth counter so that expressions such as
    ``PRIMARY KEY ("a", coalesce(b, 0))`` are handled correctly — a plain
    ``[^)]*`` regex would stop at the first ``)`` inside ``coalesce``.

    After removal, trailing commas before the closing parenthesis are cleaned
    up by the same ``_TRAILING_COMMA_RE`` used in ``strip_foreign_keys``.

    Non-CREATE-TABLE statements and statements with no PRIMARY KEY keyword
    pass through unchanged.

    Args:
        stmt: A single SQL statement string.

    Returns:
        Statement with PK clauses removed, or original if none found.
    """
    if "PRIMARY KEY" not in stmt.upper():
        return stmt

    result = stmt

    # Strip table-level PRIMARY KEY (...) using balanced-paren walk
    while True:
        m = _TABLE_PK_RE.search(result)
        if m is None:
            break
        open_pos = m.end() - 1  # position of the opening '('
        depth = 0
        close_pos = -1
        for i in range(open_pos, len(result)):
            if result[i] == "(":
                depth += 1
            elif result[i] == ")":
                depth -= 1
                if depth == 0:
                    close_pos = i
                    break
        if close_pos == -1:
            break  # unbalanced — leave untouched
        result = result[: m.start()] + result[close_pos + 1 :]

    # Strip inline column-level PRIMARY KEY keywords
    result = _INLINE_PK_RE.sub("", result)

    # Clean up trailing commas before closing paren
    result = _TRAILING_COMMA_RE.sub(r"\1", result)

    return result


# ---------------------------------------------------------------------------
# Balanced-parenthesis WITH-properties stripping
# ---------------------------------------------------------------------------

_WITH_KEYWORD_RE = re.compile(r"\s+WITH\s*\(", re.IGNORECASE)


def strip_with_properties(stmt: str) -> str:
    """Remove trailing ``WITH (...)`` table-property clauses from a DDL statement.

    Regex-based ``\\([^)]*\\)`` approaches fail when the WITH value contains
    nested parentheses (e.g. ``WITH (partitioning = ARRAY['bucket(x, 16)'])``
    or ``WITH (format = 'PARQUET', sorted_by = ARRAY[date_trunc('day', ts)])``).
    This function uses a character-level depth counter instead.

    Only strips WITH clauses that appear *after* the column-definition block
    (i.e. after the closing ``)`` of the CREATE TABLE body).  WITH inside the
    column list — e.g. ``DEFAULT (now())`` — is not affected because the scanner
    only looks for ``WITH\\s*(`` from the end of the column-definition ``)``.

    Args:
        stmt: A single DDL statement string.

    Returns:
        Statement with all trailing WITH-properties blocks removed, or the
        original statement unchanged if no ``WITH (`` is found.
    """
    if "WITH" not in stmt.upper():
        return stmt

    result = stmt
    while True:
        m = _WITH_KEYWORD_RE.search(result)
        if m is None:
            break
        open_pos = m.end() - 1  # position of the opening '('
        depth = 0
        close_pos = -1
        for i in range(open_pos, len(result)):
            if result[i] == "(":
                depth += 1
            elif result[i] == ")":
                depth -= 1
                if depth == 0:
                    close_pos = i
                    break
        if close_pos == -1:
            break  # unbalanced — leave untouched
        result = result[: m.start()] + result[close_pos + 1 :]

    return result
