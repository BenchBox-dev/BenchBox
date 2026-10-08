from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import duckdb

from benchbox.core.joinorder.schema import JoinOrderSchema
from benchbox.core.joinorder_synthetic.generator import JoinOrderGenerator
from benchbox.core.joinorder_synthetic.queries import JoinOrderQueryManager


def main() -> int:
    print("=" * 70)
    print("w0: re-validate issue #289 empty-query claim")
    print("=" * 70)

    with tempfile.TemporaryDirectory(prefix="w0_joinorder_sf001_") as td:
        out = Path(td)
        print(f"\nGenerating synthetic data at sf=0.01 into {out} ...")
        gen = JoinOrderGenerator(scale_factor=0.01, output_dir=out)
        files = gen.generate_data()
        print(f"  generated {len(files)} files")

        print("\nLoading tables into DuckDB (in-memory) ...")
        con = duckdb.connect()
        schema = JoinOrderSchema()
        loaded = []
        for table in schema.get_table_names():
            csv = out / f"{table}.csv"
            if not csv.exists():
                print(f"  WARN: missing {csv.name}; skipping")
                continue
            con.execute(schema.get_create_table_sql(table, dialect="duckdb"))
            con.execute(f"COPY {table} FROM '{csv}' (FORMAT CSV, HEADER FALSE, NULL '')")
            loaded.append(table)
        print(f"  loaded {len(loaded)}/{len(schema.get_table_names())} tables")

        print("\nRunning 13 embedded JOB queries; checking for empty result ...")
        print(
            "  (each query is SELECT MIN(..) ...; an all-NULL row means zero "
            "underlying rows matched the WHERE/JOIN predicates)"
        )
        manager = JoinOrderQueryManager()
        query_ids = sorted(
            manager.get_query_ids(),
            key=lambda q: (int("".join(c for c in q if c.isdigit()) or "0"), q),
        )

        empty = 0
        nonempty = 0
        per_query: list[tuple[str, str]] = []
        for qid in query_ids:
            sql = manager.get_query(qid).strip().rstrip(";")
            try:
                rows = con.execute(sql).fetchall()
            except Exception as exc:
                per_query.append((qid, f"ERROR: {type(exc).__name__}"))
                continue
            if not rows:
                per_query.append((qid, "0-rows"))
                empty += 1
                continue
            row = rows[0]
            if all(v is None for v in row):
                per_query.append((qid, "all-NULL"))
                empty += 1
            else:
                non_null = sum(1 for v in row if v is not None)
                per_query.append((qid, f"{non_null} non-NULL/{len(row)}"))
                nonempty += 1

        print()
        print(f"  {'qid':<6} {'verdict':<24}")
        print(f"  {'-' * 6} {'-' * 24}")
        for qid, verdict in per_query:
            print(f"  {qid:<6} {verdict:<24}")

        print()
        print(f"Empty queries:    {empty}/{len(query_ids)}")
        print(f"Non-empty:        {nonempty}/{len(query_ids)}")
        threshold = 8
        print(f"Threshold:        >= {threshold}/{len(query_ids)} empty")
        if empty >= threshold:
            print(f"VERDICT: PASS — defect signature reproduced ({empty} empties)")
            return 0
        print(
            f"VERDICT: FAIL — only {empty}/{len(query_ids)} empty, below {threshold}; "
            "STOP and re-survey before proceeding"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
