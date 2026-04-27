"""Project-wide SQL-identifier validation.

A single regex-and-length gate used everywhere we string-interpolate identifiers
into SQL DDL.  The regex is the conservative ``^[a-zA-Z_][a-zA-Z0-9_]*$`` shape
that every supported engine accepts; the length cap is engine-specific (see
caller sites).  Callers must pass the engine-appropriate ``max_length``:

  - PostgreSQL / TimescaleDB / pg_duckdb / pg_mooncake / CedarDB:  63
  - QuestDB:                                                       127
  - Spark / LakeSail / Velox / Hive metastore:                     128

Use this helper rather than re-implementing the check; it is the single safety
gate against SQL injection at points where parameter binding is not available
(catalog operations, DDL, etc.).
"""

from __future__ import annotations

import re

_VALID_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def is_valid_sql_identifier(identifier: str, *, max_length: int) -> bool:
    """Return True iff ``identifier`` is a safe SQL identifier under ``max_length``.

    Safe means: non-empty string, matches the conservative
    ``^[a-zA-Z_][a-zA-Z0-9_]*$`` regex, and is no longer than ``max_length``
    characters.  Non-string inputs are rejected as a defensive guard.
    """
    if not identifier or not isinstance(identifier, str):
        return False
    if len(identifier) > max_length:
        return False
    return bool(_VALID_IDENTIFIER_RE.match(identifier))
