#!/usr/bin/env python3
"""Compute median DuckDB version-matrix metrics from a run manifest."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

EXPECTED_VERSIONS = ("1.0.0", "1.1.3", "1.2.2", "1.3.2", "1.4.4", "1.5.5", "1.6.0.dev365")
EXPECTED_BENCHMARKS = ("tpch", "tpcds", "clickbench", "ssb")
EXPECTED_SCALES = {"tpch": 10.0, "tpcds": 10.0, "clickbench": 10.0, "ssb": 10.0}
EXPECTED_REPETITIONS = 3


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _result_path(root: Path, record: dict[str, Any]) -> Path:
    path = root / str(record["path"])
    if not path.is_file():
        raise ValueError(f"missing result bundle: {path}")
    return path


def _query_medians(payload: dict[str, Any]) -> dict[str, float]:
    values: defaultdict[str, list[float]] = defaultdict(list)
    queries = payload.get("queries")
    if not isinstance(queries, list):
        return {}
    for query in queries:
        if not isinstance(query, dict) or not isinstance(query.get("ms"), (int, float)):
            continue
        if query.get("run_type") not in (None, "measurement"):
            continue
        if str(query.get("status", "SUCCESS")).upper() not in {"SUCCESS", "PASS", "PASSED"}:
            continue
        values[str(query.get("id"))].append(float(query["ms"]))
    return {query_id: float(statistics.median(samples)) for query_id, samples in sorted(values.items())}


def _total_ms(payload: dict[str, Any]) -> float:
    timing = payload.get("summary", {}).get("timing", {})
    value = timing.get("total_ms") if isinstance(timing, dict) else None
    if not isinstance(value, (int, float)):
        raise ValueError("power result has no numeric summary.timing.total_ms")
    return float(value)


def analyze(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if tuple(manifest.get("versions", ())) != EXPECTED_VERSIONS:
        raise ValueError(f"unexpected version matrix: {manifest.get('versions')}")
    benchmark_entries = tuple((item.get("id"), float(item.get("scale"))) for item in manifest.get("benchmarks", ()))
    expected_entries = tuple((benchmark, EXPECTED_SCALES[benchmark]) for benchmark in EXPECTED_BENCHMARKS)
    if benchmark_entries != expected_entries:
        raise ValueError(f"unexpected benchmark matrix: {manifest.get('benchmarks')}")
    records = [record for record in manifest.get("records", ()) if record.get("phase") == "power"]
    expected_count = len(EXPECTED_VERSIONS) * len(EXPECTED_BENCHMARKS) * EXPECTED_REPETITIONS
    if len(records) != expected_count:
        raise ValueError(f"expected {expected_count} power records, found {len(records)}")

    root = manifest_path.parent
    cells: list[dict[str, Any]] = []
    grouped: defaultdict[tuple[str, str], list[tuple[float, dict[str, float], dict[str, Any]]]] = defaultdict(list)
    for record in records:
        version = str(record["requested_version"])
        benchmark = str(record["benchmark"])
        payload = json.loads(_result_path(root, record).read_text(encoding="utf-8"))
        if payload.get("summary", {}).get("validation") != "passed":
            raise ValueError(f"non-passing validation in {record['path']}")
        grouped[(version, benchmark)].append((_total_ms(payload), _query_medians(payload), payload))

    baseline: dict[str, float] = {}
    for version in EXPECTED_VERSIONS:
        for benchmark in EXPECTED_BENCHMARKS:
            samples = grouped[(version, benchmark)]
            if len(samples) != EXPECTED_REPETITIONS:
                raise ValueError(f"expected {EXPECTED_REPETITIONS} repetitions for {version}/{benchmark}")
            query_ids = sorted({query_id for _, queries, _ in samples for query_id in queries})
            query_medians = {
                query_id: float(
                    statistics.median([queries[query_id] for _, queries, _ in samples if query_id in queries])
                )
                for query_id in query_ids
            }
            total_median = float(statistics.median([total for total, _, _ in samples]))
            power_scores = [
                float(payload.get("summary", {}).get("tpc_metrics", {}).get("power_at_size"))
                for _, _, payload in samples
                if isinstance(payload.get("summary", {}).get("tpc_metrics", {}).get("power_at_size"), (int, float))
            ]
            if version == EXPECTED_VERSIONS[0]:
                baseline[benchmark] = total_median
            cells.append(
                {
                    "version": version,
                    "benchmark": benchmark,
                    "scale": EXPECTED_SCALES[benchmark],
                    "repetitions": len(samples),
                    "median_total_ms": total_median,
                    "speedup_vs_1.0.0": baseline[benchmark] / total_median if total_median else None,
                    "median_power_at_size": _median(power_scores),
                    "query_medians_ms": query_medians,
                }
            )

    return {
        "schema_version": "1",
        "source_manifest": manifest_path.name,
        "versions": list(EXPECTED_VERSIONS),
        "benchmarks": list(EXPECTED_BENCHMARKS),
        "repetitions": EXPECTED_REPETITIONS,
        "cells": cells,
    }


def write_outputs(result: dict[str, Any], output_dir: Path) -> None:
    (output_dir / "duckdb-version-matrix-analysis.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (output_dir / "duckdb-version-matrix-analysis.csv").open("w", encoding="utf-8", newline="") as handle:
        fieldnames = (
            "version",
            "benchmark",
            "scale",
            "repetitions",
            "median_total_ms",
            "speedup_vs_1.0.0",
            "median_power_at_size",
        )
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({key: cell.get(key) for key in fieldnames} for cell in result["cells"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="matrix-manifest.json emitted by the runner")
    args = parser.parse_args(argv)
    try:
        result = analyze(args.manifest)
        write_outputs(result, args.manifest.parent)
    except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(f"Analyzed {len(result['cells'])} median cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
