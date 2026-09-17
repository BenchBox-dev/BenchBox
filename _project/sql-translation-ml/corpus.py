"""Source-native typed analytical query grammar with pre-label family splits."""

from __future__ import annotations

import hashlib
import itertools
import json
from typing import Any

import sqlglot
from oracle import SCHEMA, SETTINGS
from sqlglot import exp

SEED = 20260912
FIXTURES = [101, 202, 303, 404, 505]
FEATURES = [
    "joins",
    "ctes",
    "subqueries",
    "aggregates",
    "windows",
    "set_operations",
    "case",
    "casts",
    "strings",
    "dates",
]


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def structure(sql: str, dialect: str) -> str:
    tree = sqlglot.parse_one(sql, read=dialect)
    names: dict[str, str] = {}
    for node in tree.walk():
        if isinstance(node, exp.Identifier):
            names.setdefault(node.name, f"v{len(names)}")
            node.set("this", names[node.name])
        elif isinstance(node, exp.Literal):
            node.set("this", "s" if node.is_string else "0")
    return digest(tree.sql())


def expressions(dialect: str) -> list[tuple[str, str]]:
    integer = "BIGINT" if dialect == "duckdb" else "INTEGER"
    year = "date_part('year', day)" if dialect == "duckdb" else "CAST(strftime('%Y',day) AS INTEGER)"
    day = "CAST(day + INTERVAL '1' DAY AS DATE)" if dialect == "duckdb" else "date(day,'+1 day')"
    return [
        ("integer", "amount"),
        ("integer", "grp"),
        ("integer", "id"),
        ("arithmetic", "amount + grp"),
        ("arithmetic", "amount - grp"),
        ("arithmetic", "amount * grp"),
        ("arithmetic", "amount % 3"),
        ("arithmetic", "ABS(amount)"),
        ("nulls", "COALESCE(amount,0)"),
        ("nulls", "NULLIF(amount,0)"),
        ("case", "CASE WHEN amount < 0 THEN -amount ELSE amount END"),
        ("case", "CASE WHEN grp IS NULL THEN amount ELSE grp END"),
        ("case", "CASE WHEN amount > 0 THEN txt ELSE 'missing' END"),
        ("casts", f"CAST(amount AS {integer})"),
        ("casts", "CAST(amount AS TEXT)"),
        ("strings", "txt"),
        ("strings", "LENGTH(txt)"),
        ("strings", "SUBSTR(txt,1,2)"),
        ("strings", "REPLACE(txt,'a','z')"),
        ("strings", "txt || ' suffix'"),
        ("strings", "TRIM(txt)"),
        ("strings", "COALESCE(txt,'NULL')"),
        ("dates", "day"),
        ("dates", year),
        ("dates", day),
    ]


PREDICATES = [
    "amount IS NULL",
    "amount IS NOT NULL",
    "amount > 0",
    "amount < 0",
    "amount = 2",
    "amount <> 2",
    "grp IS NULL",
    "grp = 0",
    "grp IN (0,2)",
    "grp NOT IN (0,2)",
    "amount BETWEEN -3 AND 7",
    "amount > grp",
    "amount = grp",
    "amount + grp > 0",
    "txt IS NULL",
    "txt IS NOT NULL",
    "txt = 'a'",
    "LENGTH(txt) > 1",
    "txt <> ''",
    "(amount > 0 OR grp IS NULL)",
    "(amount < 0 AND grp IS NOT NULL)",
    "id IN (SELECT id FROM other)",
    "id NOT IN (SELECT id FROM other)",
    "EXISTS (SELECT 1 FROM other b WHERE b.id=items.id)",
    "NOT EXISTS (SELECT 1 FROM other b WHERE b.id=items.id)",
]


def render(form: int, expression: str, predicate: str) -> tuple[str, str]:
    inner = f"SELECT id,grp,{expression} AS value FROM items WHERE {predicate}"
    forms = [
        ("projection", f"SELECT {expression} AS value FROM items WHERE {predicate}"),
        ("distinct", f"SELECT DISTINCT {expression} AS value FROM items WHERE {predicate}"),
        ("ctes", f"WITH q AS ({inner}) SELECT value FROM q"),
        ("subqueries", f"SELECT value FROM ({inner}) q WHERE value IS NOT NULL"),
        ("aggregates", f"SELECT grp,COUNT(value) FROM ({inner}) q GROUP BY grp"),
        ("aggregates", f"SELECT grp,COUNT(DISTINCT value) FROM ({inner}) q GROUP BY grp"),
        ("aggregates", f"SELECT grp,MIN(value),MAX(value) FROM ({inner}) q GROUP BY grp"),
        ("aggregates", f"SELECT grp,COUNT(*) FROM ({inner}) q GROUP BY grp HAVING COUNT(*)>1"),
        ("windows", f"SELECT value,ROW_NUMBER() OVER (PARTITION BY grp ORDER BY id NULLS LAST) FROM ({inner}) q"),
        ("windows", f"SELECT value,LAG(value) OVER (ORDER BY id NULLS LAST) FROM ({inner}) q"),
        ("windows", f"SELECT value,LEAD(value) OVER (ORDER BY id NULLS LAST) FROM ({inner}) q"),
        ("windows", f"SELECT value,SUM(id) OVER (PARTITION BY grp ORDER BY id NULLS LAST) FROM ({inner}) q"),
        ("joins", f"SELECT q.value,b.amount FROM ({inner}) q JOIN other b ON q.id=b.id"),
        ("joins", f"SELECT q.value,b.amount FROM ({inner}) q LEFT JOIN other b ON q.id=b.id"),
        ("joins", f"SELECT q.value,b.amount FROM ({inner}) q JOIN other b ON q.grp=b.grp"),
        ("set_operations", f"SELECT value FROM ({inner}) q UNION SELECT value FROM ({inner}) r"),
        ("set_operations", f"SELECT value FROM ({inner}) q UNION ALL SELECT value FROM ({inner}) r"),
        ("set_operations", f"SELECT value FROM ({inner}) q EXCEPT SELECT value FROM ({inner}) r WHERE id<3"),
        ("set_operations", f"SELECT value FROM ({inner}) q INTERSECT SELECT value FROM ({inner}) r WHERE id<3"),
        ("ordered", f"SELECT value FROM ({inner}) q ORDER BY value NULLS LAST,id NULLS LAST LIMIT 5"),
    ]
    return forms[form]


def cases() -> list[dict[str, Any]]:
    result = []
    # A family contains all expression variants of one feature class, predicate,
    # and relational skeleton. Both translation directions are always together.
    for form, expr_index, pred_index in itertools.product(range(20), range(25), range(25)):
        feature = expressions("duckdb")[expr_index][0]
        family = digest([form, feature, pred_index])
        bucket = int(family[:8], 16) % 10
        split = "test" if form == 18 or bucket < 2 else "development" if bucket == 2 else "train"
        group = digest([form, expr_index, pred_index])
        for dialect in ("duckdb", "sqlite"):
            expression = expressions(dialect)[expr_index][1]
            relational, sql = render(form, expression, PREDICATES[pred_index])
            result.append(
                {
                    "case_id": f"{group}/{dialect}",
                    "family_id": family,
                    "group_id": group,
                    "split": split,
                    "source": dialect,
                    "target": "sqlite" if dialect == "duckdb" else "duckdb",
                    "sql": sql,
                    "features": [feature, relational],
                    "schema": SCHEMA,
                    "settings": SETTINGS,
                    "seeds": FIXTURES,
                    "held_out_workload": form == 18,
                }
            )
    # Merge families joined by a normalized structure before assigning any split.
    parents = {case["family_id"]: case["family_id"] for case in result}

    def root(key: str) -> str:
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    seen: dict[str, str] = {}
    for case in result:
        key = structure(case["sql"], case["source"])
        case["structure"] = key
        if key in seen:
            parents[root(case["family_id"])] = root(seen[key])
        seen[key] = case["family_id"]
    held_out = {root(case["family_id"]) for case in result if case["held_out_workload"]}
    for case in result:
        case["family_id"] = root(case["family_id"])
        bucket = int(case["family_id"][:8], 16) % 10
        case["split"] = (
            "test" if case["family_id"] in held_out or bucket < 2 else ("development" if bucket in (2, 3) else "train")
        )
    return sorted(result, key=lambda case: digest([SEED, case["case_id"]]))
