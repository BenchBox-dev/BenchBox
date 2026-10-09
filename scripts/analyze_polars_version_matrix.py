#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.polars_matrix_spec import POLARS, PolarsMatrixSpec

CLI_DESCRIPTION = "Analyze Polars version-matrix manifests against the qualification file."
ACCEPTED_STATUSES = {"SUCCESS", "PASS", "PASSED"}
EVIDENCE_REQUIRED = {"uncertain", "not_run"}
PINNED_KEYS = ("benchbox_commit", "pyarrow", "thread_count", "datagen_manifests")

CellKey = tuple[str, str, str]


def load_qualification(path: Path, spec: PolarsMatrixSpec) -> dict[str, Any]:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != spec.qualification_sha256:
        raise ValueError(f"qualification file hash {digest} differs from the spec hash {spec.qualification_sha256}")
    payload = json.loads(raw)
    clean = {
        (row["version"], row["setup"], row["benchmark"]): bool(row["clean"]) for row in payload.get("eligibility", ())
    }
    reference = payload.get("reference", {}).get("row_counts", {})
    divergences = payload.get("known_divergences", {})
    return {
        "scale_factor": float(payload["scale_factor"]),
        "clean": clean,
        "reference": reference,
        "divergences": divergences,
        "sha256": digest,
    }


def load_manifests(paths: list[Path], spec: PolarsMatrixSpec) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifests = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if not manifests:
        raise ValueError("no manifests given")
    for path, manifest in zip(paths, manifests, strict=True):
        if manifest.get("spec") != spec.snapshot():
            raise ValueError(f"{path} was produced by a different spec")
        if not manifest.get("complete"):
            raise ValueError(f"{path} is incomplete")
        if manifest.get("workload_seed") is not None:
            raise ValueError(f"{path} used a workload seed")
        if any(manifest["pins"].get(key) != manifests[0]["pins"].get(key) for key in PINNED_KEYS):
            raise ValueError(f"{path} has different pinned values from {paths[0]}")
    records = [record for manifest in manifests for record in manifest["records"]]
    return manifests, records


def group_records(records: list[dict[str, Any]], spec: PolarsMatrixSpec) -> dict[CellKey, dict[int, dict[str, Any]]]:
    grouped: dict[CellKey, dict[int, dict[str, Any]]] = {}
    for record in records:
        key = (record["benchmark"], record["version"], record["setup"])
        rounds = grouped.setdefault(key, {})
        if record["round"] in rounds:
            raise ValueError(f"duplicate record for {key} round {record['round']}")
        rounds[record["round"]] = record
    expected_rounds = set(range(1, spec.rounds + 1))
    for cell in spec.cells():
        key = (cell.benchmark, cell.version, cell.setup)
        if set(grouped.get(key, {})) != expected_rounds:
            raise ValueError(f"cell {cell.cell_id} does not have exactly rounds {sorted(expected_rounds)}")
    unexpected = set(grouped) - {(c.benchmark, c.version, c.setup) for c in spec.cells()}
    if unexpected:
        raise ValueError(f"records for cells outside the spec: {sorted(unexpected)}")
    return grouped


def assess_record(spec: PolarsMatrixSpec, qualification: dict[str, Any], record: dict[str, Any]) -> list[str]:
    benchmark, version, setup = record["benchmark"], record["version"], record["setup"]
    if record["outcome"] != "completed":
        return [f"outcome {record['outcome']}"]
    reasons: list[str] = []
    if float(record["scale"]) != qualification["scale_factor"]:
        reasons.append(f"scale {record['scale']} differs from the qualification scale {qualification['scale_factor']}")
    if record.get("rechunk_effective") is not False:
        reasons.append("rechunk_effective is not false")
    if record.get("engine_requested") != record["engine"]:
        reasons.append(f"engine_requested {record.get('engine_requested')} differs from {record['engine']}")
    if record.get("polars_version") != version or record.get("installed", {}).get("polars") != version:
        reasons.append("recorded Polars version differs from the cell version")
    if record.get("polars_runtime_version") not in (version, "absent"):
        reasons.append(f"runtime version {record.get('polars_runtime_version')} differs from {version}")

    validation = record.get("validation")
    if validation in EVIDENCE_REQUIRED:
        if not qualification["clean"].get((version, setup, benchmark), False):
            reasons.append(f"validation {validation} without clean qualification evidence")
    elif validation != "passed":
        reasons.append(f"validation status {validation}")

    queries = record.get("queries", {})
    if any(str(query.get("status", "")).upper() not in ACCEPTED_STATUSES for query in queries.values()):
        reasons.append("a measured query did not succeed")
    reference = qualification["reference"].get(benchmark, {})
    streams = {key.split(":", 1)[0] for key in queries}
    expected_keys = {key for key in reference if key.split(":", 1)[0] in streams}
    if set(queries) != expected_keys:
        reasons.append("measured query set differs from the reference query set")
    divergences = qualification["divergences"].get(benchmark, {})
    differing = []
    for key, query in queries.items():
        accepted = divergences[key]["observed"] if key in divergences else reference.get(key)
        if query.get("rows") != accepted:
            differing.append(key)
    if differing:
        reasons.append(f"row counts differ from the DuckDB reference: {', '.join(sorted(differing)[:5])}")
    return reasons


def _totals(record: dict[str, Any], excluded: set[str]) -> tuple[float, float]:
    queries = record["queries"]
    full = sum(float(query["ms"]) for query in queries.values())
    common = sum(float(query["ms"]) for key, query in queries.items() if key not in excluded)
    return full, common


def _stats(values: list[float]) -> dict[str, float]:
    return {"median": float(statistics.median(values)), "min": min(values), "max": max(values)}


def timing_stats(records: list[dict[str, Any]], excluded: set[str]) -> dict[str, Any] | None:
    try:
        totals = [_totals(record, excluded) for record in records]
    except (KeyError, TypeError, ValueError):
        return None
    return {"full_ms": _stats([full for full, _ in totals]), "common_ms": _stats([common for _, common in totals])}


def assess_cells(
    spec: PolarsMatrixSpec, qualification: dict[str, Any], grouped: dict[CellKey, dict[int, dict[str, Any]]]
) -> list[dict[str, Any]]:
    cells = []
    for cell in spec.cells():
        key = (cell.benchmark, cell.version, cell.setup)
        records = [grouped[key][index] for index in sorted(grouped[key])]
        reasons = [
            f"round {record['round']}: {reason}"
            for record in records
            for reason in assess_record(spec, qualification, record)
        ]
        excluded = set(qualification["divergences"].get(cell.benchmark, {}))
        stats = timing_stats(records, excluded)
        completed = all(record["outcome"] == "completed" for record in records)
        if stats is None and not reasons:
            reasons.append("measured queries have no timing")
        qualified = not reasons
        cells.append(
            {
                "benchmark": cell.benchmark,
                "version": cell.version,
                "setup": cell.setup,
                "engine": cell.engine,
                "scale": spec.scales[cell.benchmark],
                "rounds": len(records),
                "outcomes": [record["outcome"] for record in records],
                "qualified": qualified,
                "reasons": reasons,
                "common_query_exclusions": sorted(excluded),
                "peak_rss_gib": max(record["peak_rss_gib"] for record in records),
                "swap_out_growth_gib": max(record["swap_out_growth_gib"] for record in records),
                "headline": stats if qualified else None,
                "reported_separately": stats if completed and not qualified else None,
            }
        )
    return cells


def compare(spec: PolarsMatrixSpec, cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index = {(cell["benchmark"], cell["version"], cell["setup"]): cell for cell in cells}
    comparisons = []
    frames = (("oldest", spec.baseline_version), ("reference", spec.reference_version))
    for cell in cells:
        if not cell["qualified"]:
            continue
        for frame, frame_version in frames:
            for baseline_setup in dict.fromkeys((cell["setup"], "A")):
                base = index.get((cell["benchmark"], frame_version, baseline_setup))
                if base is not None and base["qualified"]:
                    break
            else:
                continue
            if base is cell:
                continue
            value = cell["headline"]["common_ms"]
            reference = base["headline"]["common_ms"]
            change = value["median"] / reference["median"] - 1
            overlapping = not (value["max"] < reference["min"] or value["min"] > reference["max"])
            comparisons.append(
                {
                    "benchmark": cell["benchmark"],
                    "version": cell["version"],
                    "setup": cell["setup"],
                    "baseline_frame": frame,
                    "baseline_version": frame_version,
                    "baseline_setup": baseline_setup,
                    "median_ms": value["median"],
                    "baseline_median_ms": reference["median"],
                    "speedup": reference["median"] / value["median"],
                    "median_change": change,
                    "ranges_overlap": overlapping,
                    "candidate_mover": (not overlapping) and abs(change) >= spec.mover_effect,
                }
            )
    return comparisons


def analyze(spec: PolarsMatrixSpec, manifest_paths: list[Path], qualification_path: Path) -> dict[str, Any]:
    qualification = load_qualification(qualification_path, spec)
    manifests, records = load_manifests(manifest_paths, spec)
    cells = assess_cells(spec, qualification, group_records(records, spec))
    comparisons = compare(spec, cells)
    return {
        "schema_version": "1",
        "source_manifests": [path.name for path in manifest_paths],
        "shuffle_seeds": [manifest["shuffle_seed"] for manifest in manifests],
        "qualification_sha256": qualification["sha256"],
        "rounds": spec.rounds,
        "cells": cells,
        "comparison_count": len(comparisons),
        "comparisons": comparisons,
        "candidate_movers": [item for item in comparisons if item["candidate_mover"]],
    }


def write_outputs(result: dict[str, Any], output_dir: Path) -> None:
    (output_dir / "polars-version-matrix-analysis.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    fields = (
        "benchmark",
        "version",
        "setup",
        "baseline_frame",
        "baseline_version",
        "baseline_setup",
        "median_ms",
        "baseline_median_ms",
        "speedup",
        "median_change",
        "ranges_overlap",
        "candidate_mover",
    )
    with (output_dir / "polars-version-matrix-comparisons.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result["comparisons"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=CLI_DESCRIPTION)
    parser.add_argument("manifests", type=Path, nargs="+", help="matrix-manifest.json files, one per run directory")
    parser.add_argument("--qualification", type=Path, required=True, help="Qualification file named by the spec")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for the analysis JSON and CSV")
    args = parser.parse_args(argv)
    try:
        result = analyze(POLARS, args.manifests, args.qualification)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        write_outputs(result, args.output_dir)
    except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    qualified = sum(1 for cell in result["cells"] if cell["qualified"])
    print(f"Analyzed {len(result['cells'])} cells ({qualified} qualified); {result['comparison_count']} comparisons")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
