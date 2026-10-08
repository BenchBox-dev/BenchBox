#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TPCDS_SPLIT_QUERIES = (14, 23, 24, 39)

EXPECTED_QUERY_IDS: dict[str, frozenset[str]] = {
    "tpch": frozenset(str(number) for number in range(1, 23)),
    "tpcds": frozenset(
        [str(number) for number in range(1, 100) if number not in TPCDS_SPLIT_QUERIES]
        + [f"{number}{part}" for number in TPCDS_SPLIT_QUERIES for part in "ab"]
    ),
    "ssb": frozenset(
        f"{flight}.{query}" for flight, count in ((1, 3), (2, 3), (3, 4), (4, 3)) for query in range(1, count + 1)
    ),
    "clickbench": frozenset(str(number) for number in range(1, 44)),
}


def check_result(benchmark: str, payload: dict) -> list[str]:
    problems: list[str] = []
    measurements = [query for query in payload.get("queries", []) if query.get("run_type") == "measurement"]
    query_ids = {str(query.get("id")) for query in measurements}
    expected = EXPECTED_QUERY_IDS[benchmark]
    missing = sorted(expected - query_ids)
    unexpected = sorted(query_ids - expected)
    if missing:
        problems.append(f"{benchmark}: missing queries {', '.join(missing)}")
    if unexpected:
        problems.append(f"{benchmark}: unexpected queries {', '.join(unexpected)}")
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
    parser.add_argument("--benchmark", action="append", choices=sorted(EXPECTED_QUERY_IDS), dest="benchmarks")
    args = parser.parse_args(argv)

    problems: list[str] = []
    for benchmark in args.benchmarks or sorted(EXPECTED_QUERY_IDS):
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
