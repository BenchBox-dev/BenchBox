"""ClickHouse-specific TPC-DS query rewrites."""

from __future__ import annotations

import re


def rewrite_q35_for_clickhouse(query: str) -> str:
    """Rewrite Q35's correlated ``EXISTS`` predicates as semi-joins.

    chDB expands Q35's comma-join form into a large hash join before it
    evaluates the correlated ``EXISTS`` predicates. At TPC-DS SF1 that plan
    exceeds 14 GiB in ClickHouse Local, even though the predicates are
    existence checks and do not need duplicate rows. Replacing each existence
    check with an equivalent ``IN`` semi-join lets ClickHouse build only the
    customer-key sets and keeps the baseline memory policy unchanged.

    The rewrite is deliberately shape-checked. If the generated query
    changes, failing closed is safer than silently running the known
    high-memory form.
    """
    patterns = (
        ("store_sales", "ss_customer_sk", "ss_sold_date_sk"),
        ("web_sales", "ws_bill_customer_sk", "ws_sold_date_sk"),
        ("catalog_sales", "cs_ship_customer_sk", "cs_sold_date_sk"),
    )
    rewritten = query
    replacements = 0
    for table, customer_key, date_key in patterns:
        pattern = re.compile(
            rf"EXISTS\s*\(SELECT\s+\*\s+FROM\s+{table}\s*,\s*date_dim\s+"
            rf"WHERE\s+c\.c_customer_sk\s*=\s*{customer_key}\s+"
            rf"AND\s+{date_key}\s*=\s*d_date_sk\s+"
            rf"AND\s+d_year\s*=\s*(?P<year>\d+)\s+"
            rf"AND\s+d_qoy\s*<\s*(?P<qoy>\d+)\s*\)",
            flags=re.IGNORECASE,
        )

        def replace(
            match: re.Match[str],
            *,
            table: str = table,
            customer_key: str = customer_key,
            date_key: str = date_key,
        ) -> str:
            return (
                f"c.c_customer_sk IN (SELECT {customer_key} FROM {table}, date_dim "
                f"WHERE {date_key} = d_date_sk AND d_year = {match.group('year')} "
                f"AND d_qoy < {match.group('qoy')})"
            )

        rewritten, count = pattern.subn(replace, rewritten, count=1)
        replacements += count

    if replacements != len(patterns):
        raise ValueError(f"Unsupported ClickHouse Q35 shape: expected {len(patterns)} semi-join predicates")
    return rewritten
