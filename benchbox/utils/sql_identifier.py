from __future__ import annotations

import re

_VALID_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def is_valid_sql_identifier(identifier: str, *, max_length: int) -> bool:

    if not identifier or not isinstance(identifier, str):
        return False
    if len(identifier) > max_length:
        return False
    return bool(_VALID_IDENTIFIER_RE.match(identifier))
