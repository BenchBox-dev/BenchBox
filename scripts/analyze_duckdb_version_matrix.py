#!/usr/bin/env python3
"""Compute median DuckDB version-matrix metrics from a run manifest."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
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


def _load_power_payloads(manifest_path: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
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

    grouped: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    root = manifest_path.parent
    for record in records:
        version = str(record["requested_version"])
        benchmark = str(record["benchmark"])
        payload = json.loads(_result_path(root, record).read_text(encoding="utf-8"))
        if payload.get("summary", {}).get("validation") != "passed":
            raise ValueError(f"non-passing validation in {record['path']}")
        grouped[(version, benchmark)].append(payload)
    return grouped


def _median_field(payloads: list[dict[str, Any]], path: tuple[str, ...]) -> float | None:
    values: list[float] = []
    for payload in payloads:
        value: Any = payload
        for key in path:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        if not isinstance(value, (int, float)):
            return None
        values.append(float(value))
    return float(statistics.median(values)) if values else None


def _query_key(query: dict[str, Any]) -> tuple[Any, ...]:
    return (
        query.get("id"),
        query.get("run_type"),
        query.get("stream"),
        query.get("iter"),
        query.get("test_type"),
    )


def aggregate_payloads(payloads: list[dict[str, Any]], *, version: str, benchmark: str) -> dict[str, Any]:
    """Create one Results Explorer bundle from the repetitions of one matrix cell."""
    if len(payloads) != EXPECTED_REPETITIONS:
        raise ValueError(f"expected {EXPECTED_REPETITIONS} repetitions for {version}/{benchmark}")
    if any(payload.get("summary", {}).get("validation") != "passed" for payload in payloads):
        raise ValueError(f"non-passing validation in {version}/{benchmark}")

    aggregate = copy.deepcopy(payloads[0])
    aggregate.setdefault("export", {})["aggregation"] = {
        "method": "median",
        "repetitions": len(payloads),
        "source_run_ids": [str(payload.get("run", {}).get("id")) for payload in payloads],
    }
    source_ids = "|".join([version, benchmark, *aggregate["export"]["aggregation"]["source_run_ids"]])
    aggregate.setdefault("run", {})["id"] = hashlib.sha256(source_ids.encode("utf-8")).hexdigest()[:8]

    timing = aggregate.get("summary", {}).get("timing")
    if isinstance(timing, dict):
        for field in timing:
            median = _median_field(payloads, ("summary", "timing", field))
            if median is not None:
                timing[field] = median

    for path in (("summary", "data", "load_time_ms"), ("summary", "tpc_metrics", "power_at_size")):
        median = _median_field(payloads, path)
        if median is not None:
            target: dict[str, Any] = aggregate
            for key in path[:-1]:
                value = target.get(key)
                if not isinstance(value, dict):
                    value = {}
                    target[key] = value
                target = value
            target[path[-1]] = median

    for field in ("query_time_ms", "total_duration_ms"):
        median = _median_field(payloads, ("run", field))
        if median is not None:
            aggregate["run"][field] = median

    query_maps = [
        {_query_key(query): query for query in payload.get("queries", []) if isinstance(query, dict)}
        for payload in payloads
    ]
    if any(set(query_map) != set(query_maps[0]) for query_map in query_maps[1:]):
        raise ValueError(f"repetitions have different query sets for {version}/{benchmark}")
    for query in aggregate.get("queries", []):
        if not isinstance(query, dict):
            continue
        samples = [query_map[_query_key(query)].get("ms") for query_map in query_maps]
        if all(isinstance(value, (int, float)) for value in samples):
            query["ms"] = float(statistics.median([float(value) for value in samples]))
    return aggregate


def _version_token(version: str) -> str:
    return version.replace(".", "_")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_explorer_bundles(manifest_path: Path, output_dir: Path) -> list[Path]:
    """Write one median bundle per version/benchmark cell for Explorer ingestion."""
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Explorer bundle output directory must be new or empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    grouped = _load_power_payloads(manifest_path)
    paths: list[Path] = []
    for version in EXPECTED_VERSIONS:
        for benchmark in EXPECTED_BENCHMARKS:
            aggregate = aggregate_payloads(grouped[(version, benchmark)], version=version, benchmark=benchmark)
            path = output_dir / f"{benchmark}_sf10_duckdb_v{_version_token(version)}_median.json"
            _write_json(path, aggregate)
            paths.append(path)
    return paths


def analyze(manifest_path: Path) -> dict[str, Any]:
    grouped = _load_power_payloads(manifest_path)
    cells: list[dict[str, Any]] = []

    baseline: dict[str, float] = {}
    for version in EXPECTED_VERSIONS:
        for benchmark in EXPECTED_BENCHMARKS:
            samples = grouped[(version, benchmark)]
            if len(samples) != EXPECTED_REPETITIONS:
                raise ValueError(f"expected {EXPECTED_REPETITIONS} repetitions for {version}/{benchmark}")
            query_medians_by_sample = [_query_medians(payload) for payload in samples]
            query_ids = sorted({query_id for queries in query_medians_by_sample for query_id in queries})
            query_medians = {
                query_id: float(
                    statistics.median([queries[query_id] for queries in query_medians_by_sample if query_id in queries])
                )
                for query_id in query_ids
            }
            total_median = float(statistics.median([_total_ms(payload) for payload in samples]))
            power_scores = [
                float(payload.get("summary", {}).get("tpc_metrics", {}).get("power_at_size"))
                for payload in samples
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
    parser.add_argument(
        "--explorer-bundles-dir",
        type=Path,
        help="also write one median bundle per version/benchmark cell to this directory",
    )
    args = parser.parse_args(argv)
    try:
        result = analyze(args.manifest)
        write_outputs(result, args.manifest.parent)
        explorer_paths = (
            write_explorer_bundles(args.manifest, args.explorer_bundles_dir) if args.explorer_bundles_dir else []
        )
    except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(f"Analyzed {len(result['cells'])} median cells")
    if explorer_paths:
        print(f"Wrote {len(explorer_paths)} median Explorer bundles to {args.explorer_bundles_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
