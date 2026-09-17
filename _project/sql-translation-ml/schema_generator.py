"""Coverage-scheduled, seeded typed SQL over the TPC-H schema."""

from __future__ import annotations

import random

from corpus import digest, structure
from oracle import SETTINGS, safe_query
from sqlglot import exp
from tpch_fixtures import SCHEMA

from benchbox.core.tpch.schema import TABLES, DataType

SEED = 20260913
FORMS = ("projection", "distinct", "aggregate", "window", "cte", "exists", "union", "intersect", "left_join")
EXPRESSIONS = ("integer", "case", "coalesce", "length", "trim", "concat", "date_year", "date_add")


def expression(table, feature: str, dialect: str, rng: random.Random) -> str | None:
    integers = [c for c in table.columns if c.data_type == DataType.INTEGER]
    strings = [c for c in table.columns if c.data_type in (DataType.CHAR, DataType.VARCHAR)]
    dates = [c for c in table.columns if c.data_type == DataType.DATE]
    integer = f'a."{rng.choice(integers).name}"'
    string = f'a."{rng.choice(strings).name}"'
    if feature.startswith("date_"):
        if not dates:
            return None
        day = f'a."{rng.choice(dates).name}"'
        if feature == "date_year":
            return f"CAST(strftime('%Y',{day}) AS INTEGER)" if dialect == "sqlite" else f"date_part('year',{day})"
        return f"date({day},'+1 day')" if dialect == "sqlite" else f"CAST({day} + INTERVAL '1' DAY AS DATE)"
    return {
        "integer": f"ABS({integer})",
        "case": f"CASE WHEN {integer} < 2 THEN 'small' ELSE 'large' END",
        "coalesce": f"COALESCE({string},'missing')",
        "length": f"LENGTH({string})",
        "trim": f"TRIM({string})",
        "concat": f"{string} || ' suffix'",
    }[feature]


def construct(table, value: str, form: str, rng: random.Random) -> str:
    key = next(c.name for c in table.columns if c.primary_key)
    alias = rng.choice(["value", "metric_17", "Result Value"])
    relation = f'"{table.name}" AS a'
    predicate = f'a."{key}" >= {rng.choice([1, 2, 3])}'
    core = f'SELECT {value} AS "{alias}" FROM {relation} WHERE {predicate}'
    if form == "projection":
        return core
    if form == "distinct":
        return core.replace("SELECT ", "SELECT DISTINCT ", 1)
    if form == "aggregate":
        return f'SELECT {value} AS "{alias}", COUNT(*) AS n FROM {relation} GROUP BY {value}'
    if form == "window":
        return f'SELECT {value} AS "{alias}", ROW_NUMBER() OVER (PARTITION BY {value} ORDER BY a."{key}") AS rn FROM {relation}'
    if form == "cte":
        return f'WITH "chosen" AS ({core}) SELECT "{alias}" FROM "chosen" WHERE "{alias}" IS NOT NULL'
    if form == "exists":
        return core + f' AND EXISTS (SELECT 1 FROM "{table.name}" b WHERE b."{key}" = a."{key}" AND b."{key}" < 7)'
    if form in ("union", "intersect"):
        operator = "UNION ALL" if form == "union" else "INTERSECT"
        return f'{core} {operator} SELECT {value} AS "{alias}" FROM {relation} WHERE a."{key}" <= 5'
    foreign = next((c for c in table.columns if c.foreign_key), None)
    target, target_key = foreign.foreign_key if foreign else (table.name, key)
    join_key = foreign.name if foreign else key
    return (
        f'SELECT {value} AS "{alias}", b."{target_key}" AS matched FROM {relation} '
        f'LEFT JOIN "{target}" b ON a."{join_key}" = b."{target_key}" AND b."{target_key}" < 3'
    )


def record(sql: str, source: str, family: str, features: list[str], suite: str) -> dict:
    tree = safe_query(sql, source, SCHEMA)
    referenced = {t.name for t in tree.find_all(exp.Table) if t.name in SCHEMA}
    return {
        "case_id": digest([family, source, sql]),
        "family_id": family,
        "sql": sql,
        "source": source,
        "target": "sqlite" if source == "duckdb" else "duckdb",
        "schema": {name: SCHEMA[name] for name in sorted(referenced)},
        "settings": SETTINGS,
        "features": features,
        "structure": structure(sql, source),
        "suite": suite,
    }


def generate(variants: int = 2) -> tuple[list[dict], dict]:
    if variants not in (1, 2):
        raise ValueError("variants must be 1 or 2")
    cases, targets, unavailable = [], [], []
    for table_index, table in enumerate(TABLES):
        for feature_index, feature in enumerate(EXPRESSIONS):
            for form_index, form in enumerate(FORMS):
                family = f"{table.name}/{feature}/{form}"
                if feature.startswith("date_") and not any(c.data_type == DataType.DATE for c in table.columns):
                    unavailable.append({"target": family, "reason": "no DATE column in table"})
                    continue
                targets.append(family)
                for variant in range(variants):
                    seed = SEED + 10000 * table_index + 1000 * feature_index + 10 * form_index + variant
                    for dialect in ("duckdb", "sqlite"):
                        rng = random.Random(seed)
                        value = expression(table, feature, dialect, rng)
                        sql = construct(table, value, form, rng)
                        if variant % 2:
                            # Formatting is part of the input distribution, not repaired after inference.
                            sql = sql.replace(" FROM ", "\nFROM ")
                        cases.append(record(sql, dialect, family, [feature, form, table.name], "generated"))
    return cases, {
        "seed": SEED,
        "variants": variants,
        "targets": targets,
        "unavailable": unavailable,
        "forms": FORMS,
        "expressions": EXPRESSIONS,
        "scope": "TPC-H schema; finite read-only expression/form pairs, not all engine syntax",
    }
