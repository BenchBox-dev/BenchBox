from __future__ import annotations

import re


def normalize_table_name_in_sql(sql: str) -> str:
    sql = re.sub(
        r'CREATE(\s+EXTERNAL)?\s+TABLE(\s+IF\s+NOT\s+EXISTS)?\s+"?([A-Za-z_][A-Za-z0-9_]*)"?',
        lambda m: f"CREATE{m.group(1) or ''} TABLE{m.group(2) or ''} {m.group(3).lower()}",
        sql,
        flags=re.IGNORECASE,
    )

    sql = re.sub(
        r'REFERENCES\s+"?([A-Za-z_][A-Za-z0-9_]*)"?',
        lambda m: f"REFERENCES {m.group(1).lower()}",
        sql,
        flags=re.IGNORECASE,
    )

    return sql


def extract_table_name(statement: str) -> str | None:
    try:
        match = re.search(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)",
            statement,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
    except Exception:
        pass
    return None
