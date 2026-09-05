#!/usr/bin/env python3
"""Replay Explorer math and privacy evidence without production transformers.

This script deliberately imports only the documented visualization-fixture
helpers and the canonical public-path detector.  It does not import the
Explorer transformer or frontend chart helpers.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
import types
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_MEASUREMENT_SHA = "c44fdfc457886d9340b75d86ecb6e29796fdbb98"
EXPECTED_SNAPSHOT_SHA256 = "3bce914eae9f9bb3dceea490af4f47f8b14ad084cb46aeb7a4f624208b1d5795"
EXPECTED_SNAPSHOT_BYTES = 8663040
SNAPSHOT_RETRIEVAL_LOCATOR = "https://benchbox.dev/results/data/results.duckdb"
sys.path.insert(0, str(REPO_ROOT))

from tests.parity.generate_visualization_fixtures import geomean_ms, platform_percentile_stats


def _load_public_path_detector() -> Any:
    """Load the canonical detector without importing the unrelated CLI package."""
    # BenchBox's package initializer imports optional CLI dependencies that the
    # replay itself does not need.  Supply only anonymization.py's direct
    # sibling dependency, then execute that canonical source file.
    platform_spec = importlib.util.spec_from_file_location(
        "benchbox.core.results.platform_options", REPO_ROOT / "benchbox/core/results/platform_options.py"
    )
    assert platform_spec and platform_spec.loader
    platform_module = importlib.util.module_from_spec(platform_spec)
    platform_spec.loader.exec_module(platform_module)
    for name in ("benchbox", "benchbox.core", "benchbox.core.results"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["benchbox.core.results.platform_options"] = platform_module
    sys.modules["benchbox.core.results"].platform_options = platform_module
    spec = importlib.util.spec_from_file_location(
        "explorer_evidence_anonymization", REPO_ROOT / "benchbox/core/results/anonymization.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.find_public_path_leaks


find_public_path_leaks = _load_public_path_detector()


def _verify_snapshot(snapshot: Path) -> tuple[str, int]:
    """Bind historical replay to the exact snapshot used for certification."""
    size = snapshot.stat().st_size
    digest = hashlib.sha256()
    with snapshot.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_digest = digest.hexdigest()
    if actual_digest != EXPECTED_SNAPSHOT_SHA256 or size != EXPECTED_SNAPSHOT_BYTES:
        raise ValueError(
            "snapshot does not match retained historical evidence: "
            f"expected sha256={EXPECTED_SNAPSHOT_SHA256} bytes={EXPECTED_SNAPSHOT_BYTES}, "
            f"got sha256={actual_digest} bytes={size}"
        )
    return actual_digest, size


def _equal(left: float | None, right: float | None) -> bool:
    return (
        left is None
        and right is None
        or (left is not None and right is not None and math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9))
    )


def _competition_ranks(rows: list[tuple[str, float]]) -> dict[str, int]:
    ranks: dict[str, int] = {}
    previous: float | None = None
    for index, (result_id, value) in enumerate(rows, start=1):
        if previous is None or not math.isclose(value, previous, rel_tol=1e-12, abs_tol=1e-12):
            rank = index
            previous = value
        ranks[result_id] = rank
    return ranks


def _privacy_scan_snapshot(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    fields: list[str] = []
    tables = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' ORDER BY table_name"
    ).fetchall()
    for (table,) in tables:
        columns = con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position",
            [table],
        ).fetchall()
        for column, data_type in columns:
            if not any(token in data_type.upper() for token in ("CHAR", "TEXT", "JSON")):
                continue
            for (value,) in con.execute(f'SELECT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL').fetchall():
                payload: Any = value
                if "JSON" in data_type.upper() and isinstance(value, str):
                    try:
                        payload = json.loads(value)
                    except json.JSONDecodeError:
                        pass
                fields.extend(f"{table}.{column}.{path}" for path in find_public_path_leaks(payload))
    return {"tables_scanned": len(tables), "leak_fields": sorted(set(fields)), "leak_hits": len(fields)}


def _privacy_scan_bundles(bundle_root: Path) -> dict[str, Any]:
    fields: list[str] = []
    unreadable: list[str] = []
    files = sorted(bundle_root.rglob("*.json"))
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            unreadable.append(f"{path.name}: {type(exc).__name__}")
            continue
        # The report intentionally preserves only field paths, never values.
        fields.extend(f"{path.name}.{field}" for field in find_public_path_leaks(payload))
    return {
        "files_scanned": len(files),
        "unreadable": unreadable,
        "leak_fields": sorted(set(fields)),
        "leak_hits": len(fields),
    }


def replay(snapshot: Path, bundle_root: Path) -> dict[str, Any]:
    digest, snapshot_bytes = _verify_snapshot(snapshot)
    con = duckdb.connect(str(snapshot), read_only=True)
    timings = defaultdict(list)
    for result_id, display_ms in con.execute("SELECT result_id, display_ms FROM query_display_timings").fetchall():
        timings[result_id].append(display_ms)

    geomean = {result_id: geomean_ms(values) for result_id, values in timings.items()}
    stored_geomean = dict(con.execute("SELECT result_id, display_geomean_ms FROM results").fetchall())
    geomean_divergences = sorted(
        result_id for result_id, value in stored_geomean.items() if not _equal(value, geomean.get(result_id))
    )

    ranking_rows = con.execute(
        "SELECT benchmark, scale_factor, phase, result_id, is_ranking_eligible, primary_metric, primary_order, "
        "power_score, display_geomean_ms, rank, percentile_p50, percentile_p90, percentile_p95, percentile_p99 "
        "FROM benchmark_rankings"
    ).fetchall()
    percentile_divergences: list[str] = []
    rank_divergences: list[str] = []
    direction_failures: list[str] = []
    cohorts: dict[tuple[str, float, str], list[tuple[Any, ...]]] = defaultdict(list)
    for row in ranking_rows:
        cohorts[(row[0], row[1], row[2])].append(row)
        expected = platform_percentile_stats(timings.get(row[3], []))
        actual = row[10:14]
        expected_values = None if expected is None else tuple(expected[key] for key in ("p50", "p90", "p95", "p99"))
        if expected_values is None:
            if any(value is not None for value in actual):
                percentile_divergences.append(row[3])
        elif any(not _equal(left, right) for left, right in zip(actual, expected_values)):
            percentile_divergences.append(row[3])

    rankable = 0
    unranked = 0
    for cohort, rows in cohorts.items():
        metric = rows[0][5]
        order = rows[0][6]
        candidates = []
        for row in rows:
            value = row[7] if metric == "power_score" else row[8]
            if row[4] and value is not None and math.isfinite(value) and value > 0:
                candidates.append((row[3], value, row[9]))
            elif row[9] is not None:
                rank_divergences.append(row[3])
                unranked += 1
            else:
                unranked += 1
        ordered = sorted(
            ((result_id, value) for result_id, value, _ in candidates),
            key=lambda item: item[1],
            reverse=order == "desc",
        )
        expected_ranks = _competition_ranks(ordered)
        if ordered:
            extreme = min(value for _, value in ordered) if order == "asc" else max(value for _, value in ordered)
            for result_id, value, stored_rank in candidates:
                rankable += 1
                if stored_rank != expected_ranks[result_id]:
                    rank_divergences.append(result_id)
            for row in rows:
                stored_rank = row[9]
                if stored_rank != 1:
                    continue
                value = row[7] if metric == "power_score" else row[8]
                if value is None or not math.isfinite(value) or value <= 0 or not _equal(value, extreme):
                    direction_failures.append(row[3])
        else:
            direction_failures.extend(row[3] for row in rows if row[9] == 1)

    script_path = Path(__file__).resolve()
    result = {
        "evidence_scope": "historical_replay",
        "replay": {
            "script": str(script_path.relative_to(REPO_ROOT)),
            "sha256": hashlib.sha256(script_path.read_bytes()).hexdigest(),
        },
        "measurement_sha": EXPECTED_MEASUREMENT_SHA,
        "snapshot": {
            "retrieval_locator": SNAPSHOT_RETRIEVAL_LOCATOR,
            "sha256": digest,
            "bytes": snapshot_bytes,
        },
        "read_model_version": con.execute("SELECT read_model_version FROM metadata").fetchone()[0],
        "geomean": {
            "results_compared": len(stored_geomean),
            "agree": len(stored_geomean) - len(geomean_divergences),
            "diverge": len(geomean_divergences),
            "divergences": geomean_divergences,
        },
        "percentile": {
            "rows_compared": len(ranking_rows),
            "agree": len(ranking_rows) - len(percentile_divergences),
            "diverge": len(percentile_divergences),
            "divergences": sorted(set(percentile_divergences)),
        },
        "ranking": {
            "cohorts": len(cohorts),
            "rankable_rows": rankable,
            "unranked_rows": unranked,
            "rank_diverge": len(set(rank_divergences)),
            "direction_failures": sorted(set(direction_failures)),
        },
        "privacy": {"snapshot": _privacy_scan_snapshot(con), "bundles": _privacy_scan_bundles(bundle_root)},
    }
    con.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--bundle-root", type=Path, default=REPO_ROOT / "results-data" / "bundles")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary_output.write_text(
        json.dumps(replay(args.snapshot, args.bundle_root), indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_output.replace(args.output)


if __name__ == "__main__":
    main()
