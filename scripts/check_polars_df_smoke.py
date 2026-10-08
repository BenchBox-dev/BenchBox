#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EXPECTED_QUERY_COUNTS: dict[str, int] = {
    "tpch": 22,
    "tpcds": 103,
    "ssb": 13,
    "clickbench": 43,
}


def check_result(benchmark: str, payload: dict) -> list[str]:
    problems: list[str] = []
    measurements = [query for query in payload.get("queries", []) if query.get("run_type") == "measurement"]
    query_ids = {str(query.get("id")) for query in measurements}
    expected = EXPECTED_QUERY_COUNTS[benchmark]
    if len(query_ids) != expected:
        problems.append(f"{benchmark}: expected {expected} distinct queries, measured {len(query_ids)}")
    failed = sorted({str(query.get("id")) for query in measurements if query.get("status") != "SUCCESS"})
    if failed:
        problems.append(f"{benchmark}: non-successful queries {', '.join(failed)}")
    return problems


def latest_result(results_dir: Path, benchmark: str) -> Path | None:
    candidates = sorted(results_dir.glob(f"{benchmark}_*_polars_df_*.json"), key=lambda path: path.stat().st_mtime)
    return candidates[-1] if candidates else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check polars-df smoke results for complete, failure-free query coverage."
    )
    parser.add_argument("results_dir", type=Path)
    parser.add_argument("--benchmark", action="append", choices=sorted(EXPECTED_QUERY_COUNTS), dest="benchmarks")
    args = parser.parse_args(argv)

    problems: list[str] = []
    for benchmark in args.benchmarks or sorted(EXPECTED_QUERY_COUNTS):
        result_path = latest_result(args.results_dir, benchmark)
        if result_path is None:
            problems.append(f"{benchmark}: no polars-df result in {args.results_dir}")
            continue
        problems.extend(check_result(benchmark, json.loads(result_path.read_text(encoding="utf-8"))))

    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
