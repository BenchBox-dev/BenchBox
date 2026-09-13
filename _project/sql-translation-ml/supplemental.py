"""A held-out existing workload, adapted only to the small fixture schema."""

from pathlib import Path

import yaml
from artifacts import sha256
from corpus import FIXTURES, digest, structure
from oracle import SCHEMA, SETTINGS


def cases() -> list[dict]:
    catalog = Path(__file__).resolve().parents[2] / "benchbox/core/read_primitives/catalog/queries.yaml"
    rows = yaml.safe_load(catalog.read_text(encoding="utf-8"))["queries"]
    selected = {
        "aggregation_materialize",
        "aggregation_distinct_groupby",
        "aggregation_groupby_small",
        "shuffle_left_join_one_to_many_string_with_groupby",
    }
    mappings = {
        "lineitem": "items",
        "nation": "items",
        "orders": "other",
        "customer": "items",
        "o_custkey": "grp",
        "o_totalprice": "amount",
        "o_orderkey": "id",
        "l_returnflag": "grp",
        "l_linestatus": "txt",
        "l_orderkey": "id",
        "l_partkey": "amount",
        "n_regionkey": "grp",
        "n_name": "txt",
        "c_custkey": "id",
        "c_mktsegment": "txt",
    }
    result = []
    for row in rows:
        if row["id"] not in selected:
            continue
        # Identifier-only adaptation: every selected query uses identical native
        # syntax on the two engines; no target transpilation enters the input.
        import re

        sql = re.sub(r"\b\w+\b", lambda match: mappings.get(match[0], match[0]), row["sql"])
        for dialect in ("duckdb", "sqlite"):
            result.append(
                {
                    "case_id": f"read-primitives/{row['id']}/{dialect}",
                    "family_id": "read-primitives-aggregation-join",
                    "group_id": row["id"],
                    "structure": structure(sql, dialect),
                    "source": dialect,
                    "target": "sqlite" if dialect == "duckdb" else "duckdb",
                    "sql": sql,
                    "schema": SCHEMA,
                    "settings": SETTINGS,
                    "seeds": FIXTURES,
                    "features": ["existing_workload", row["category"]],
                    "split": "supplemental",
                    "held_out_workload": True,
                    "provenance": {
                        "catalog_sha256": sha256(catalog),
                        "original_sql_sha256": digest(row["sql"]),
                        "query_id": row["id"],
                        "mappings": mappings,
                    },
                }
            )
    if len(result) != len(selected) * 2:
        raise ValueError("existing workload selection changed")
    return result
