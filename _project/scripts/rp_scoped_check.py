"""Scoped read_primitives cross-surface check over a subset of query ids.

Builds ONE bounded DuckDB cell (SF default 0.05, override via --scale) and
compares only the query ids passed on the command line against the DuckDB-dialect
SQL reference, printing per-cell PASS/DIVERGE/ERROR/VACUOUS. Lets a burn-down
focus on a handful of queries without paying the full 148-query gate (~7 min).

Usage:
  uv run -- python _project/scripts/rp_scoped_check.py [--scale 0.05] <id> [<id> ...]
  uv run -- python _project/scripts/rp_scoped_check.py --all          # every gateable id
"""

import argparse
import tempfile
from pathlib import Path

from benchbox.core.equivalence.cross_surface import (
    build_production_contexts,
    build_read_primitives_duckdb,
    find_cross_surface_divergences,
)
from benchbox.core.equivalence.dataframe_surface import DATAFRAME_BACKENDS


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=float, default=0.05)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("ids", nargs="*")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        from benchbox.core.tpchavoc.validation import ResultValidator

        data = build_read_primitives_duckdb(args.scale, Path(tmp))
        gateable = list(data.query_ids)
        ids = gateable if args.all else [q for q in args.ids if q in gateable]
        missing = [q for q in args.ids if q not in gateable]
        if missing:
            print(f"NOT GATEABLE (skipped): {missing}")
        contexts = build_production_contexts(data.benchmark, data.data_dir, scale_factor=args.scale)
        ref_counts: dict = {}
        divs = find_cross_surface_divergences(
            data.connection,
            query_ids=ids,
            reference_sql=data.reference_sql,
            dataframe_query=data.dataframe_query,
            contexts=contexts,
            validator=ResultValidator(tolerance=1e-10),
            backends=DATAFRAME_BACKENDS,
            reference_row_counts=ref_counts,
        )
        data.connection.close()
        div_keys = {d.key for d in divs}
        by_key = {d.key: d.detail.replace("\n", " ")[:240] for d in divs}
        print(f"\n=== scoped check: {len(ids)} queries @ SF={args.scale} ===")
        passed = 0
        for qid in sorted(ids):
            vac = " [VACUOUS 0-ref]" if ref_counts.get(qid) == 0 else ""
            cells = [f"{qid}_{b}" for b in DATAFRAME_BACKENDS]
            bad = [c for c in cells if c in div_keys]
            if not bad and not vac:
                passed += 1
                print(f"  PASS  {qid}")
            else:
                if vac:
                    print(f"  VACUOUS {qid}{vac}")
                for c in bad:
                    print(f"  DIVERGE {c}: {by_key[c]}")
        print(f"\n{passed}/{len(ids)} clean; {len(divs)} divergent cells")
        return 1 if divs else 0


if __name__ == "__main__":
    raise SystemExit(main())
